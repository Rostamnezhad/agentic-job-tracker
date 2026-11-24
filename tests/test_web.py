"""Behavioral coverage of the web API, account isolation, and reviewed intake."""

from pathlib import Path
from html.parser import HTMLParser
import json
import tempfile
import unittest

from werkzeug.security import check_password_hash

from job_tracker.intake import assess, extract_description, validate_job, validate_preferences
from job_tracker.web import create_app


PASSWORD = 'fictional-test-password-only'
JOB = {'company': 'Example Labs', 'role': 'Python Developer',
       'url': 'https://example.com/jobs/python'}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'web.sqlite3'
        self.app = create_app(self.path, {'TESTING': True, 'AUTH_RATE_LIMIT': 100})
        self.store = self.app.extensions['workspace']
        self.client = self.app.test_client()
        self.register(self.client, 'alice')

    def send(self, client, method, path, data=None, **kwargs):
        token = client.get('/api/session').json['csrf']
        return client.open('/api' + path, method=method, json=data or {},
                           headers={'X-CSRF-Token': token}, **kwargs)

    def register(self, client, name):
        response = self.send(client, 'POST', '/register', {'username': name, 'password': PASSWORD})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['user']

    def add(self, client=None, **changes):
        response = self.send(client or self.client, 'POST', '/jobs', {**JOB, **changes})
        self.assertEqual(response.status_code, 201, response.json)
        return response.json['id']

    def test_signup_hashes_password_and_never_exposes_it(self):
        stored = self.store.user_by_name('alice')
        self.assertNotEqual(stored['password_hash'], PASSWORD)
        self.assertTrue(check_password_hash(stored['password_hash'], PASSWORD))
        session = self.client.get('/api/session')
        self.assertNotIn('password', json.dumps(session.json))
        self.assertEqual(session.headers['Cache-Control'], 'no-store')
        guest = self.app.test_client()
        cookie = guest.get('/api/session').headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        with self.store.connection() as db:
            tokens = [r[0] for r in db.execute('SELECT token_hash FROM sessions')]
        self.assertNotIn(self.client.get_cookie('job_session').value, tokens)

    def test_registration_and_login_validation(self):
        other = self.app.test_client()
        for payload in [{'username': 'ab', 'password': PASSWORD},
                        {'username': 'other', 'password': 'short'},
                        {'username': 'other', 'password': ['bad']}]:
            with self.subTest(payload=payload):
                self.assertEqual(self.send(other, 'POST', '/register', payload).status_code, 400)
        self.assertEqual(self.send(other, 'POST', '/register',
                         {'username': 'ALICE', 'password': PASSWORD}).status_code, 409)
        for username in ['alice', 'unknown']:
            result = self.send(other, 'POST', '/login', {'username': username, 'password': 'wrong'})
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json['error'], 'Username or password is incorrect.')

    def test_guest_cannot_read_or_write_jobs(self):
        guest = self.app.test_client()
        for path in ['/jobs', '/jobs/1', '/export']:
            self.assertEqual(guest.get('/api' + path).status_code, 401)
        self.assertEqual(self.send(guest, 'POST', '/jobs', JOB).status_code, 401)
        self.assertEqual(self.send(guest, 'POST', '/parse',
                                  {'description': 'Some sufficiently long job description'}).status_code, 401)

    def test_csrf_and_cross_origin_writes_are_rejected(self):
        token = self.client.get('/api/session').json['csrf']
        self.assertEqual(self.client.post('/api/jobs', json=JOB).status_code, 403)
        self.assertEqual(self.client.post('/api/jobs', json=JOB,
                         headers={'X-CSRF-Token': 'invalid-\u00e9'}).status_code, 403)
        result = self.client.post('/api/jobs', json=JOB,
                                 headers={'X-CSRF-Token': token, 'Origin': 'https://evil.example'})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.client.get('/api/jobs').json['jobs'], [])

    def test_logout_invalidates_old_session_and_login_rotates_cookie(self):
        old_token = self.client.get_cookie('job_session').value
        old_csrf = self.client.get('/api/session').json['csrf']
        self.assertEqual(self.send(self.client, 'POST', '/logout').status_code, 200)
        replay = self.app.test_client()
        replay.set_cookie('job_session', old_token)
        self.assertEqual(replay.get('/api/jobs').status_code, 401)
        guest_token = self.client.get_cookie('job_session').value
        result = self.send(self.client, 'POST', '/login', {'username': 'ALICE', 'password': PASSWORD})
        self.assertEqual(result.status_code, 200)
        self.assertNotEqual(old_csrf, result.json['csrf'])
        self.assertNotEqual(guest_token, self.client.get_cookie('job_session').value)

    def test_expired_session_is_not_authorized(self):
        with self.store.connection() as db:
            db.execute('UPDATE sessions SET expires=0')
        self.assertEqual(self.client.get('/api/jobs').status_code, 401)
        self.assertIsNone(self.client.get('/api/session').json['user'])

    def test_account_isolation_for_every_job_operation(self):
        job_id = self.add(notes='Private to Alice')
        bob = self.app.test_client()
        self.register(bob, 'bob')
        self.assertEqual(bob.get('/api/jobs').json['jobs'], [])
        self.assertEqual(bob.get('/api/export').json, [])
        self.assertEqual(bob.get(f'/api/jobs/{job_id}').status_code, 404)
        for method, path, payload in [
            ('PUT', f'/jobs/{job_id}', {**JOB, 'version': 1}),
            ('DELETE', f'/jobs/{job_id}', {'version': 1}),
            ('POST', f'/jobs/{job_id}/restore', {}),
        ]:
            self.assertEqual(self.send(bob, method, path, payload).status_code, 404)
        self.add(bob)  # The same URL is allowed in different accounts.
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}').json['job']['notes'], 'Private to Alice')

    def test_edit_history_conflict_and_reopen_persistence(self):
        job_id = self.add()
        payload = {**JOB, 'version': 1, 'status': 'applied', 'applied_date': '2026-11-23',
                   'notes': 'Follow up next week', 'location': 'Karlsruhe'}
        self.assertEqual(self.send(self.client, 'PUT', f'/jobs/{job_id}', payload).status_code, 200)
        self.assertEqual(self.send(self.client, 'PUT', f'/jobs/{job_id}', payload).status_code, 409)
        self.assertEqual(self.send(self.client, 'DELETE', f'/jobs/{job_id}', {'version': 1}).status_code, 409)
        payload.update(version=2, status='interview')
        self.assertEqual(self.send(self.client, 'PUT', f'/jobs/{job_id}', payload).status_code, 200)
        reopened = create_app(self.path, {'TESTING': True}).test_client()
        reopened.set_cookie('job_session', self.client.get_cookie('job_session').value)
        result = reopened.get(f'/api/jobs/{job_id}').json
        self.assertEqual(result['job']['applied_date'], '2026-11-23')
        self.assertEqual(result['job']['notes'], 'Follow up next week')
        self.assertEqual(result['job']['version'], 3)
        self.assertEqual([event['status'] for event in result['history']], ['saved', 'applied', 'interview'])

    def test_delete_and_undo_preserve_details(self):
        job_id = self.add(notes='Keep this on undo')
        self.assertEqual(self.send(self.client, 'DELETE', f'/jobs/{job_id}', {'version': 1}).status_code, 200)
        self.assertEqual(self.client.get('/api/jobs').json['jobs'], [])
        self.assertEqual(self.client.get(f'/api/jobs/{job_id}').status_code, 404)
        self.assertEqual(self.send(self.client, 'POST', f'/jobs/{job_id}/restore').status_code, 200)
        restored = self.client.get(f'/api/jobs/{job_id}').json['job']
        self.assertEqual(restored['notes'], 'Keep this on undo')
        self.assertEqual(restored['version'], 3)

    def test_restore_cannot_overwrite_an_existing_url(self):
        job_id = self.add()
        self.send(self.client, 'DELETE', f'/jobs/{job_id}', {'version': 1})
        replacement = self.add(notes='Replacement')
        self.assertEqual(self.send(self.client, 'POST', f'/jobs/{job_id}/restore').status_code, 409)
        self.assertEqual(self.client.get('/api/jobs').json['jobs'][0]['id'], replacement)

    def test_validation_and_duplicates_never_damage_saved_jobs(self):
        first = self.add()
        second = self.add(url='https://example.com/jobs/second')
        for changes in [{'url': 'javascript:alert(1)'}, {'company': ''}, {'office_days': True},
                        {'commute_minutes': -1}, {'status': 'interview'},
                        {'status': 'applied', 'applied_date': '2026-02-30'}, {'work_mode': 'maybe'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.send(self.client, 'POST', '/jobs', {**JOB, **changes}).status_code, 400)
        self.assertEqual(self.send(self.client, 'POST', '/jobs', JOB).status_code, 409)
        self.assertEqual(self.send(self.client, 'PUT', f'/jobs/{second}', {**JOB, 'version': 1}).status_code, 409)
        self.assertEqual(len(self.client.get('/api/jobs').json['jobs']), 2)
        self.assertEqual(self.client.get(f'/api/jobs/{first}').json['job']['version'], 1)

    def test_batch_import_is_atomic_and_ignores_foreign_ownership(self):
        self.add()
        fresh = {**JOB, 'url': 'https://example.com/new', 'user_id': 999, 'id': 999}
        self.assertEqual(self.send(self.client, 'POST', '/import', {'jobs': [fresh, JOB]}).status_code, 409)
        self.assertEqual(len(self.client.get('/api/jobs').json['jobs']), 1)
        self.assertEqual(self.send(self.client, 'POST', '/import',
                                  {'jobs': [fresh, {**JOB, 'company': ''}]}).status_code, 400)
        self.assertEqual(len(self.client.get('/api/jobs').json['jobs']), 1)
        self.assertEqual(self.send(self.client, 'POST', '/import', {'jobs': [fresh]}).status_code, 201)
        self.assertEqual(len(self.client.get('/api/jobs').json['jobs']), 2)

    def test_export_can_be_imported_into_another_workspace(self):
        self.add(description='<script>alert(1)</script>', notes="O'Reilly; DROP TABLE users;")
        exported = self.client.get('/api/export')
        self.assertIn('attachment;', exported.headers['Content-Disposition'])
        bob = self.app.test_client()
        self.register(bob, 'bob')
        result = self.send(bob, 'POST', '/import', {'jobs': exported.json})
        self.assertEqual(result.status_code, 201)
        imported = bob.get('/api/jobs').json['jobs'][0]
        self.assertEqual(imported['notes'], "O'Reilly; DROP TABLE users;")
        self.assertEqual(imported['description'], '<script>alert(1)</script>')
        self.assertNotIn('user_id', imported)

    def test_preferences_persist_and_are_private(self):
        preferences = {'employment_type': 'working_student', 'language': 'english',
                       'german_level': 'A2', 'office_days': 1, 'commute_minutes': 120, 'skills': 'Python'}
        self.assertEqual(self.send(self.client, 'PUT', '/preferences', preferences).status_code, 200)
        self.add(employment_type='working_student', language='english', office_days=2)
        fit = self.client.get('/api/jobs').json['jobs'][0]['fit']
        self.assertTrue(any('Job type' in item for item in fit['matches']))
        self.assertTrue(any('Office attendance' in item for item in fit['gaps']))
        self.assertTrue(any('German' in item for item in fit['unknowns']))
        bob = self.app.test_client()
        self.assertEqual(self.register(bob, 'bob')['preferences'], {})
        self.assertEqual(self.client.get('/api/session').json['user']['preferences']['office_days'], 1)

    def test_parser_only_returns_draft_and_samples_are_explicit(self):
        result = self.send(self.client, 'POST', '/parse',
                           {'description': 'Company: Example\nRole: Python Developer\nURL: https://example.com/job'})
        self.assertEqual(result.json['draft']['company'], 'Example')
        self.assertEqual(self.client.get('/api/jobs').json['jobs'], [])
        self.assertEqual(self.send(self.client, 'POST', '/samples').json['count'], 3)
        self.assertEqual(self.send(self.client, 'POST', '/samples').json['count'], 0)
        self.assertTrue(all('FICTIONAL DEMO JOB' in job['description']
                            for job in self.client.get('/api/jobs').json['jobs']))

    def test_auth_throttle_and_json_errors(self):
        self.app.config['AUTH_RATE_LIMIT'] = 1  # The registration already consumed one attempt.
        result = self.send(self.client, 'POST', '/login', {'username': 'alice', 'password': PASSWORD})
        self.assertEqual(result.status_code, 429)
        token = self.client.get('/api/session').json['csrf']
        result = self.client.post('/api/jobs', data='{bad json', content_type='application/json',
                                  headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, 400)
        result = self.client.post('/api/jobs', data='x' * 1_000_001, content_type='application/json',
                                  headers={'X-CSRF-Token': token})
        self.assertEqual(result.status_code, 413)

    def test_page_and_static_security_headers(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Create my workspace', page.data)
        self.assertIn("script-src 'self'", page.headers['Content-Security-Policy'])
        self.assertEqual(page.headers['X-Frame-Options'], 'DENY')
        for path in ['/static/app.js', '/static/app.css', '/static/icon.svg', '/health']:
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200)

    def test_every_stage_is_a_selectable_filter_option(self):
        class StageOptions(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_filter = False
                self.values = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'select':
                    self.in_filter = attrs.get('id') == 'status-filter'
                elif tag == 'option' and self.in_filter:
                    self.values.append(attrs.get('value'))

            def handle_endtag(self, tag):
                if tag == 'select':
                    self.in_filter = False

        parsed = StageOptions()
        parsed.feed(self.client.get('/').get_data(as_text=True))
        self.assertEqual(parsed.values, ['', 'saved', 'applied', 'interview', 'offer', 'rejected', 'withdrawn'])


class IntakeTests(unittest.TestCase):
    def test_labelled_intake_extracts_fields_but_leaves_uncertainty(self):
        draft = extract_description('Company: Example\nRole: Python Engineer\n'
                                    'URL: https://example.com/job\nWork arrangement: Hybrid\n'
                                    'Job type: Working student\nWorking language: English\nGerman: A2')
        self.assertEqual(draft['employment_type'], 'working_student')
        self.assertEqual(draft['german_level'], 'A2')
        self.assertEqual(validate_job(draft)['office_days'], None)
        vague = extract_description('Join our team! Remote work might be possible; German is a plus.')
        self.assertNotIn('work_mode', vague)
        self.assertNotIn('german_level', vague)

    def test_fit_checks_report_unknowns_without_inventing_requirements(self):
        preferences = validate_preferences({'language': 'english', 'work_mode': 'hybrid',
                                           'german_level': 'A2', 'office_days': 1,
                                           'commute_minutes': 120, 'skills': 'Java, Python'})
        job = validate_job({**JOB, 'description': 'Build JavaScript tools, not a confirmed language requirement.'})
        result = assess(job, preferences)
        self.assertTrue(any('Python' in item for item in result['matches']))
        self.assertFalse(any('Java,' in item for item in result['matches']))
        self.assertEqual(len(result['unknowns']), 5)
        self.assertEqual(result['gaps'], [])

    def test_german_commute_and_location_gaps_are_explained(self):
        preferences = validate_preferences({'locations': 'Kaiserslautern, Karlsruhe', 'german_level': 'A2',
                                           'commute_minutes': 120, 'office_days': 1})
        job = validate_job({**JOB, 'location': 'Berlin', 'german_level': 'B2',
                            'commute_minutes': 240, 'office_days': 2})
        result = assess(job, preferences)
        self.assertEqual(len(result['gaps']), 4)
        self.assertEqual(result['unknowns'], [])
        self.assertIn('German B2 requested; your level is A2.', result['gaps'])
        job['work_mode'] = 'remote'
        self.assertFalse(any('Location' in item for item in assess(job, preferences)['gaps']))


if __name__ == '__main__':
    unittest.main()
