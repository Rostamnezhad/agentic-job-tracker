"""Bounded, user-triggered public-web discovery. No scraping or LLM calls."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html import unescape
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .intake import text, number, choice, JOB_TYPES, LABELS, split_items, mention
from .models import JobEntry
from .workspace import ConflictError

SOURCES = [
    {'id': 'linkedin', 'name': 'LinkedIn', 'domain': 'linkedin.com'},
    {'id': 'indeed', 'name': 'Indeed', 'domain': 'indeed.com'},
    {'id': 'stepstone', 'name': 'StepStone', 'domain': 'stepstone.de'},
    {'id': 'arbeitsagentur', 'name': 'Bundesagentur für Arbeit', 'domain': 'arbeitsagentur.de'},
    {'id': 'arbeitnow', 'name': 'Arbeitnow', 'domain': 'arbeitnow.com'},
    {'id': 'jobicy', 'name': 'Jobicy', 'domain': 'jobicy.com'},
    {'id': 'rptu', 'name': 'RPTU / university HiWi', 'domain': 'rptu.de'},
    {'id': 'studierendenwerk', 'name': 'Studierendenwerk Kaiserslautern', 'domain': 'studierendenwerk-kaiserslautern.de'},
    {'id': 'academics', 'name': 'academics', 'domain': 'academics.de'},
    {'id': 'jobmensa', 'name': 'Jobmensa', 'domain': 'jobmensa.de'},
]
SOURCE_IDS = {s['id'] for s in SOURCES}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS discovery_profiles (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), profile TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_runs (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
 fingerprint TEXT NOT NULL, created INTEGER NOT NULL, month TEXT NOT NULL,
 credits INTEGER NOT NULL, result TEXT);
CREATE INDEX IF NOT EXISTS discovery_owner ON discovery_runs(user_id,created);
'''


class ProviderError(Exception):
    """Safe, curated message: never include a provider body or credential."""


def validate_profile(data):
    result = {key: text(data, key, limit) for key, limit in
              [('skills', 400), ('interests', 400), ('languages', 200), ('city', 120), ('country', 80)]}
    if not all(result[k] for k in ('skills', 'interests', 'languages', 'city', 'country')):
        raise ValueError('Enter skills, interests, languages, town, and country.')
    result['radius_km'] = number(data, 'radius_km', 1000)
    if not result['radius_km'] or result['radius_km'] < 1:
        raise ValueError('Maximum distance must be 1–1000 km.')
    result['employment_type'] = choice(data, 'employment_type', JOB_TYPES)
    sources = data.get('sources', [s['id'] for s in SOURCES])
    if (not isinstance(sources, list) or not sources or len(sources) > 10
            or not all(isinstance(s, str) and s in SOURCE_IDS for s in sources)):
        raise ValueError('Choose 1–10 supported sources.')
    result['sources'] = sorted(set(sources))
    return result


def query_for(profile):
    kind = ('Werkstudent working student HiWi' if profile['employment_type'] == 'working_student'
            else LABELS.get(profile['employment_type'], 'job vacancy'))
    # A radius in search text is a request, not a verified geographic filter.
    return ' '.join([kind[:40], ', '.join(split_items(profile['interests'])[:3])[:90],
                     ', '.join(split_items(profile['skills'])[:4])[:70], profile['city'][:60], profile['country'][:35],
                     f"within {profile['radius_km']} km", profile['languages'][:45], 'job application'])[:400]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a credential to another host.


def tavily_search(source, query, key):
    payload = {'query': query, 'include_domains': [source['domain']], 'search_depth': 'basic',
               'max_results': 8, 'include_answer': False, 'include_raw_content': False,
               'auto_parameters': False, 'topic': 'general', 'include_usage': True}
    req = Request('https://api.tavily.com/search', data=json.dumps(payload).encode(),
                  headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(req, timeout=15) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ProviderError('Provider response was too large.')
        body = json.loads(raw)
        if not isinstance(body, dict) or not isinstance(body.get('results'), list):
            raise ProviderError('Provider returned an unexpected response.')
        return body['results'][:8]
    except HTTPError as exc:
        messages = {401: 'API key rejected. Check your local Tavily configuration.',
                    403: 'Provider denied access.', 429: 'Provider rate limit reached. Try later.',
                    432: 'Tavily credits exhausted. Wait for the free allowance to reset.',
                    433: 'Tavily allowance exceeded. No automatic upgrade was attempted.'}
        raise ProviderError(messages.get(exc.code, 'Search provider could not complete this request.')) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise ProviderError('Search provider is unavailable or returned invalid data.') from None


def clean(value, limit):
    return unescape(re.sub(r'<[^>]*>', ' ', value))[:limit].strip() if isinstance(value, str) else ''


def normalize(item, source, profile):
    if not isinstance(item, dict):
        return None
    title, url = clean(item.get('title'), 180), item.get('url')
    if not title or not isinstance(url, str) or len(url) > 2000:
        return None
    try:
        url = JobEntry(company='Review required', role=title, url=url).url
        parts = urlsplit(url)
        host = parts.hostname.lower()
        if not (host == source['domain'] or host.endswith('.' + source['domain'])):
            return None
        params = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith('utm_')
                  and k.lower() not in ('trk', 'trackingid', 'refid')]
        url = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(params), ''))
    except ValueError:
        return None
    snippet = clean(item.get('content'), 6000)
    combined = title + '\n' + snippet
    matches = []
    score = 0
    for field, weight in [('skills', 3), ('interests', 4)]:
        found = [term for term in split_items(profile[field])[:12] if mention(term, combined)]
        if found:
            matches.append(field.capitalize() + ' mentioned: ' + ', '.join(found))
            score += len(found) * weight
    if mention(profile['city'], combined):
        matches.append('Your town is mentioned; confirm the office address.')
        score += 2
    kinds = {'working_student': r'werkstudent|working student|hiwi|studentische hilfskraft',
             'internship': r'internship|praktikum', 'part_time': r'part.time|teilzeit',
             'full_time': r'full.time|vollzeit', 'contract': r'freelance|contractor'}
    if profile['employment_type'] in kinds and re.search(kinds[profile['employment_type']], combined, re.I):
        score += 3
        matches.append('Requested job type is mentioned.')
    languages = [term for term in split_items(profile['languages']) if mention(term, combined)]
    if languages:
        matches.append('Language text mentioned: ' + ', '.join(languages) + '; required level needs review.')
    gaps = []
    if profile['employment_type'] == 'working_student' and re.search(r'\b(senior|principal|director)\b', title, re.I):
        gaps.append('Title may require more experience than a working-student role.')
        score -= 5
    if re.search(r'no longer available|position (?:is )?filled|job (?:is )?closed|stelle besetzt', combined, re.I):
        gaps.append('Search text suggests this vacancy may be closed.')
        score -= 20
    return {'title': title, 'url': url, 'snippet': snippet, 'sources': [source['name']],
            'relevance': max(0, score), 'matches': matches, 'gaps': gaps,
            'unknowns': [f"Distance within {profile['radius_km']} km is not verified.",
                         'Working language and required proficiency need checking.',
                         'Live availability and whether this is an individual vacancy need checking.']}


class Discovery:
    def __init__(self, store, search=None):
        self.store, self.search = store, search or tavily_search
        with store.connection() as db:
            db.executescript(SCHEMA)

    def profile(self, user_id):
        with self.store.connection() as db:
            row = db.execute('SELECT profile FROM discovery_profiles WHERE user_id=?', (user_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_profile(self, user_id, data):
        profile = validate_profile(data)
        with self.store.connection() as db:
            db.execute('INSERT INTO discovery_profiles VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET profile=excluded.profile',
                       (user_id, json.dumps(profile)))
        return profile

    def status(self, user_id):
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        with self.store.connection() as db:
            used = db.execute('SELECT COALESCE(SUM(credits),0) FROM discovery_runs WHERE month=?', (month,)).fetchone()[0]
            latest = db.execute('SELECT result FROM discovery_runs WHERE user_id=? AND result IS NOT NULL ORDER BY id DESC LIMIT 1',
                                (user_id,)).fetchone()
        return {'configured': bool(os.getenv('TAVILY_API_KEY', '').strip()), 'profile': self.profile(user_id),
                'sources': SOURCES, 'reserved_credits': used, 'monthly_limit': 1000,
                'latest': json.loads(latest[0]) if latest else None}

    def run(self, user_id):
        profile = self.profile(user_id)
        if not profile:
            raise ValueError('Save your search profile first.')
        key = os.getenv('TAVILY_API_KEY', '').strip()
        if not key:
            raise ValueError('Set TAVILY_API_KEY on the server, then restart it. See README → Search setup.')
        fingerprint = hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()
        now = int(time.time())
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        selected = [s for s in SOURCES if s['id'] in profile['sources']]
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            cached = db.execute('SELECT result FROM discovery_runs WHERE user_id=? AND fingerprint=? AND created>? AND result IS NOT NULL ORDER BY id DESC LIMIT 1',
                                (user_id, fingerprint, now - 86400)).fetchone()
            if cached:
                result = json.loads(cached[0])
                if any(source['state'] != 'failed' for source in result['coverage']):
                    result['cached'] = True
                    return result
            active = db.execute('SELECT id FROM discovery_runs WHERE user_id=? AND result IS NULL AND created>?',
                                (user_id, now - 180)).fetchone()
            if active:
                raise ConflictError('A search is already running. Wait before trying again.')
            used = db.execute('SELECT COALESCE(SUM(credits),0) FROM discovery_runs WHERE month=?', (month,)).fetchone()[0]
            daily = db.execute('SELECT COALESCE(SUM(credits),0) FROM discovery_runs WHERE user_id=? AND created>?',
                               (user_id, now - 86400)).fetchone()[0]
            if used + len(selected) > 1000 or daily + len(selected) > 40:
                raise ConflictError('Usage limit reached: 1,000 requests/month per installation or 40/day per user. No paid fallback.')
            run_id = db.execute('INSERT INTO discovery_runs(user_id,fingerprint,created,month,credits) VALUES (?,?,?,?,?)',
                                (user_id, fingerprint, now, month, len(selected))).lastrowid
        query = query_for(profile)
        def fetch(source):
            try:
                return source, self.search(source, query, key), None
            except ProviderError as exc:
                return source, [], str(exc)
            except Exception:
                return source, [], 'Search failed. No retry or paid fallback was attempted.'
        coverage, dedup = [], {}
        with ThreadPoolExecutor(max_workers=3) as pool:
            for source, raw, failure in pool.map(fetch, selected):
                count = 0
                for item in raw:
                    candidate = normalize(item, source, profile)
                    if not candidate:
                        continue
                    count += 1
                    if candidate['url'] not in dedup:
                        dedup[candidate['url']] = candidate
                coverage.append({'name': source['name'], 'domain': source['domain'], 'count': count,
                                 'state': 'failed' if failure else 'results' if count else 'no_results', 'error': failure})
        result = {'created_at': now, 'profile': profile, 'query': query, 'coverage': coverage,
                  'results': sorted(dedup.values(), key=lambda j: (-j['relevance'], j['title']))[:80],
                  'reserved_credits': len(selected), 'cached': False}
        with self.store.connection() as db:
            db.execute('UPDATE discovery_runs SET result=? WHERE id=? AND user_id=?', (json.dumps(result), run_id, user_id))
        return result
