"""No real credentials or network calls: deterministic provider boundary tests."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from job_tracker.discovery import SOURCES, ProviderError, normalize, query_for, tavily_search, validate_profile
from job_tracker.web import create_app

PROFILE = {'skills':'Python, SQL', 'interests':'AI, automation', 'languages':'English, German A2',
           'city':'Kaiserslautern', 'country':'Germany', 'radius_km':100, 'employment_type':'working_student'}


def fixture_search(source, query, key):
    return [{'title':'Working student Python AI', 'url':f"https://{source['domain']}/jobs/student?utm_source=test",
             'content':'Python and SQL automation in Kaiserslautern. English. Job location requires confirmation.'},
            {'title':'Duplicate', 'url':f"https://{source['domain']}/jobs/student", 'content':'same vacancy'},
            {'title':'Wrong source', 'url':'https://evil.example/job', 'content':'Python'}]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {'TAVILY_API_KEY':'fictional-test-key'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.calls = []
        def provider(source, query, key):
            self.calls.append(source['id'])
            return fixture_search(source, query, key)
        self.app = create_app(Path(self.temp.name)/'web.sqlite3', {'TESTING':True,'DISCOVERY_SEARCH':provider})
        self.client = self.app.test_client()
        result = self.send('/register', {'username':'alice','password':'fictional-password-for-test'})
        self.uid = result.json['user']['id']
        self.send('/discovery/profile', PROFILE, 'PUT')

    def send(self, path, data=None, method='POST', client=None):
        client = client or self.client
        csrf = client.get('/api/session').json['csrf']
        return client.open('/api'+path, method=method, json=data or {}, headers={'X-CSRF-Token':csrf})

    def test_full_workflow_ten_sources_dedup_cache_and_save(self):
        response = self.send('/discovery/search')
        self.assertEqual(response.status_code, 200)
        report = response.json
        self.assertEqual(len(report['coverage']), 10)
        self.assertEqual(len(report['results']), 10)
        self.assertEqual(len(self.calls), 10)
        candidate = report['results'][0]
        self.assertNotIn('utm_', candidate['url'])
        self.assertTrue(candidate['matches'])
        self.assertTrue(any('not verified' in x for x in candidate['unknowns']))
        self.assertTrue(self.send('/discovery/search').json['cached'])
        self.assertEqual(len(self.calls), 10)
        self.assertEqual(self.client.get('/api/discovery').json['reserved_credits'], 10)
        self.assertEqual(self.client.get('/api/jobs').json['jobs'], [])
        result = self.send('/jobs', {'company':'User verified employer','role':candidate['title'],
                                   'url':candidate['url'],'description':candidate['snippet']})
        self.assertEqual(result.status_code, 201)

    def test_profile_and_results_private_and_persistent(self):
        self.send('/discovery/search')
        bob = self.app.test_client()
        self.send('/register', {'username':'bob','password':'fictional-password-for-test'}, client=bob)
        state = bob.get('/api/discovery').json
        self.assertIsNone(state['profile']); self.assertIsNone(state['latest'])
        guest = self.app.test_client()
        self.assertEqual(guest.get('/api/discovery').status_code, 401)
        self.assertEqual(self.send('/discovery/search', client=guest).status_code, 401)
        reopened = create_app(self.app.extensions['workspace'].path, {'TESTING':True}).test_client()
        reopened.set_cookie('job_session', self.client.get_cookie('job_session').value)
        self.assertEqual(reopened.get('/api/discovery').json['profile']['city'], 'Kaiserslautern')
        self.assertEqual(len(reopened.get('/api/discovery').json['latest']['results']), 10)

    def test_missing_key_never_spends_and_no_key_returned(self):
        with patch.dict(os.environ, {'TAVILY_API_KEY':''}):
            self.assertEqual(self.send('/discovery/search').status_code, 400)
            self.assertFalse(self.client.get('/api/discovery').json['configured'])
        self.assertEqual(self.calls, [])
        self.assertNotIn('fictional-test-key', self.client.get('/api/discovery').get_data(as_text=True))

    def test_validation_and_source_allowlist(self):
        for change in [{'radius_km':0}, {'radius_km':True}, {'sources':['evil.example']},
                       {'sources':[]}, {'city':''}, {'skills':['Python']}, {'radius_km':1001}]:
            with self.subTest(change=change):
                self.assertEqual(self.send('/discovery/profile', {**PROFILE,**change}, 'PUT').status_code, 400)
        self.assertEqual(self.client.put('/api/discovery/profile', json=PROFILE).status_code, 403)

    def test_global_monthly_limit_reserved_before_network(self):
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.app.extensions['workspace'].connection() as db:
            db.execute('INSERT INTO discovery_runs(user_id,fingerprint,created,month,credits,result) VALUES (?,?,?,?,?,?)',
                       (self.uid,'older',int(time.time())-90000,month,995,'{}'))
        self.assertEqual(self.send('/discovery/search').status_code, 409)
        self.assertEqual(self.calls, [])

    def test_daily_limit_and_inflight_lock(self):
        store = self.app.extensions['workspace']
        with store.connection() as db:
            db.execute('INSERT INTO discovery_runs(user_id,fingerprint,created,month,credits) VALUES (?,?,?,?,?)',
                       (self.uid,'inflight',int(time.time()),datetime.now(timezone.utc).strftime('%Y-%m'),10))
        self.assertEqual(self.send('/discovery/search').status_code, 409)
        with store.connection() as db:
            db.execute("UPDATE discovery_runs SET created=created-200,credits=40,result='{}'")
        self.assertEqual(self.send('/discovery/search').status_code, 409)
        self.assertEqual(self.calls, [])

    def test_partial_failure_preserves_other_sources(self):
        def partial(source, query, key):
            if source['id'] == 'linkedin':
                raise ProviderError('Provider rate limit reached. Try later.')
            return fixture_search(source, query, key)
        self.app.extensions['discovery'].search = partial
        result = self.send('/discovery/search').json
        self.assertEqual(len(result['results']), 9)
        self.assertEqual(result['coverage'][0]['state'], 'failed')
        self.assertEqual(result['reserved_credits'], 10)

    def test_all_failed_can_retry_after_key_correction(self):
        def fail(*args):
            raise RuntimeError('credential-like-private-value')
        self.app.extensions['discovery'].search = fail
        result = self.send('/discovery/search').json
        self.assertEqual(result['results'], [])
        self.assertNotIn('credential-like-private-value', json.dumps(result))
        self.app.extensions['discovery'].search = fixture_search
        self.assertEqual(len(self.send('/discovery/search').json['results']), 10)

    def test_profile_changes_do_not_reuse_old_cache(self):
        self.send('/discovery/search')
        self.send('/discovery/profile', {**PROFILE,'city':'Mannheim','sources':['arbeitnow']}, 'PUT')
        result = self.send('/discovery/search').json
        self.assertFalse(result['cached']); self.assertEqual(result['reserved_credits'], 1)
        self.assertIn('Mannheim', result['query'])

    def test_untrusted_results_and_honest_ranking(self):
        source=SOURCES[0]; profile=validate_profile(PROFILE)
        for url in ['javascript:alert(1)','https://linkedin.com.evil.example/job','https://x:y@linkedin.com/job']:
            self.assertIsNone(normalize({'title':'Python','url':url},source,profile))
        senior=normalize({'title':'Senior Director Python AI','url':'https://linkedin.com/jobs/view/1','content':'Job closed'},source,profile)
        self.assertEqual(len(senior['gaps']),2)
        self.assertIn('100 km', query_for(profile))
        self.assertNotIn('probability', json.dumps(senior))
        spaced = normalize({'title':'Python', 'url':' https://linkedin.com/jobs/view/2 '}, source, profile)
        self.assertEqual(spaced['url'], 'https://linkedin.com/jobs/view/2')

    def test_provider_request_has_fixed_cost_and_no_extra_tools(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,limit): return b'{"results":[]}'
        with patch('job_tracker.discovery.build_opener') as opener:
            opener.return_value.open.return_value = Response()
            self.assertEqual(tavily_search(SOURCES[0],'Python jobs','dummy-key'), [])
            request=opener.return_value.open.call_args.args[0]
            payload=json.loads(request.data)
            self.assertEqual(request.full_url,'https://api.tavily.com/search')
            self.assertEqual(payload['search_depth'],'basic')
            self.assertFalse(payload['auto_parameters'])
            self.assertFalse(payload['include_raw_content'])
            self.assertEqual(payload['include_domains'],['linkedin.com'])
            self.assertNotIn('api_key',payload)
            opener.return_value.open.side_effect = HTTPError(request.full_url,401,'private body',{},None)
            with self.assertRaisesRegex(ProviderError,'API key rejected'):
                tavily_search(SOURCES[0],'Python','dummy-key')


if __name__ == '__main__':
    unittest.main()
