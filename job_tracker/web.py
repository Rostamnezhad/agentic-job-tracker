"""Flask web application with server-side sessions and account-scoped records."""

from pathlib import Path
import json
import os
import re
import secrets
import sqlite3

from flask import Flask, g, jsonify, make_response, render_template, request
from werkzeug.exceptions import HTTPException, Unauthorized, Forbidden, TooManyRequests
from werkzeug.security import check_password_hash, generate_password_hash

from .intake import assess, extract_description, validate_job, validate_preferences
from .workspace import Workspace, ConflictError, MissingError
from .discovery import Discovery


def create_app(database=None, test_config=None):
    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=1_000_000,
        COOKIE_SECURE=os.getenv('JOB_TRACKER_HTTPS') == '1',
        AUTH_RATE_LIMIT=10,
    )
    if test_config:
        app.config.update(test_config)
    hosts = os.getenv('JOB_TRACKER_ALLOWED_HOSTS')
    if hosts:
        app.config['TRUSTED_HOSTS'] = [host.strip() for host in hosts.split(',') if host.strip()]
    path = database or os.getenv('JOB_TRACKER_WEB_DB') or Path.home() / '.agentic-job-tracker' / 'web.sqlite3'
    store = Workspace(path)
    app.extensions['workspace'] = store
    discovery = Discovery(store, app.config.get('DISCOVERY_SEARCH'))
    app.extensions['discovery'] = discovery
    dummy_hash = generate_password_hash(secrets.token_urlsafe(32))
    app.json.ensure_ascii = False

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError('Send a JSON object.')
        return value

    def uid():
        if not g.web_session or not g.web_session['user_id']:
            raise Unauthorized('Please sign in to continue.')
        return g.web_session['user_id']

    def rotate(user_id=None, status=200):
        token, csrf = store.new_session(user_id, request.cookies.get('job_session'))
        response = make_response(jsonify(user=store.user(user_id) if user_id else None, csrf=csrf), status)
        response.set_cookie('job_session', token, max_age=604800, httponly=True,
                            secure=app.config['COOKIE_SECURE'], samesite='Lax', path='/')
        return response

    @app.before_request
    def protect_request():
        if not request.path.startswith('/api/'):
            return
        g.web_session = store.session(request.cookies.get('job_session'))
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not g.web_session or not secrets.compare_digest(
                request.headers.get('X-CSRF-Token', '').encode(), g.web_session['csrf'].encode()
            ):
                raise Forbidden('Your session expired. Refresh the page and try again.')
            if request.headers.get('Origin') and request.headers['Origin'] != request.host_url.rstrip('/'):
                raise Forbidden('Request origin does not match this application.')
            if not request.is_json:
                raise ValueError('Send JSON with Content-Type application/json.')

    @app.after_request
    def security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if app.config['COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(ValueError)
    def input_error(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(ConflictError)
    def conflict(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(MissingError)
    def missing(error):
        return jsonify(error=str(error)), 404

    @app.errorhandler(sqlite3.Error)
    def storage_error(error):
        app.logger.error('Database operation failed: %s', type(error).__name__)
        return jsonify(error='The database is unavailable. Please try again.'), 503

    @app.get('/')
    def index():
        return render_template('index.html')

    @app.get('/health')
    def health():
        return jsonify(status='ok')

    @app.get('/api/session')
    def get_session():
        if not g.web_session:
            return rotate()
        user_id = g.web_session['user_id']
        return jsonify(user=store.user(user_id) if user_id else None, csrf=g.web_session['csrf'])

    @app.post('/api/<action>')
    def authenticate(action):
        if action not in ('login', 'register', 'logout'):
            raise MissingError('Route not found.')
        if action == 'logout':
            uid()
            return rotate()
        data = body()
        username, password = data.get('username', ''), data.get('password', '')
        if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username):
            raise ValueError('Use a username of 3–32 letters, numbers, dots, hyphens or underscores.')
        username = username.lower()
        if not isinstance(password, str) or len(password) > 256:
            raise ValueError('Password must be at most 256 characters.')
        if not store.allow_auth_attempt(request.remote_addr or '', username, app.config['AUTH_RATE_LIMIT']):
            raise TooManyRequests('Too many sign-in attempts. Please wait 15 minutes.')
        if action == 'register':
            if len(password) < 12:
                raise ValueError('Choose a password with at least 12 characters.')
            return rotate(store.register(username, generate_password_hash(password)), 201)
        user = store.user_by_name(username)
        valid = check_password_hash(user['password_hash'] if user else dummy_hash, password)
        if not user or not valid:
            raise Unauthorized('Username or password is incorrect.')
        return rotate(user['id'])

    @app.get('/api/jobs')
    def list_jobs():
        user_id = uid()
        preferences = store.user(user_id)['preferences']
        jobs = store.list_jobs(user_id)
        for job in jobs:
            job['fit'] = assess(job, preferences)
        return jsonify(jobs=jobs)

    @app.get('/api/discovery')
    def discovery_status():
        return jsonify(discovery.status(uid()))

    @app.put('/api/discovery/profile')
    def discovery_profile():
        return jsonify(profile=discovery.save_profile(uid(), body()))

    @app.post('/api/discovery/search')
    def discovery_search():
        return jsonify(discovery.run(uid()))

    @app.post('/api/jobs')
    def add_job():
        job_id = store.add_jobs(uid(), [validate_job(body())])[0]
        return jsonify(id=job_id), 201

    @app.get('/api/jobs/<int:job_id>')
    def get_job(job_id):
        job, history = store.get_job(uid(), job_id)
        return jsonify(job=job, history=history, fit=assess(job, store.user(uid())['preferences']))

    def version(data):
        value = data.get('version')
        if type(value) is not int or value < 1:
            raise ValueError('A valid record version is required. Refresh and try again.')
        return value

    @app.put('/api/jobs/<int:job_id>')
    def update_job(job_id):
        data = body()
        store.update_job(uid(), job_id, validate_job(data), version(data))
        return jsonify(ok=True)

    @app.delete('/api/jobs/<int:job_id>')
    def delete_job(job_id):
        store.delete_job(uid(), job_id, version(body()))
        return jsonify(ok=True)

    @app.post('/api/jobs/<int:job_id>/restore')
    def restore_job(job_id):
        store.restore_job(uid(), job_id)
        return jsonify(ok=True)

    @app.put('/api/preferences')
    def save_preferences():
        store.set_preferences(uid(), validate_preferences(body()))
        return jsonify(user=store.user(uid()))

    @app.post('/api/parse')
    def parse_description():
        uid()
        return jsonify(draft=extract_description(body().get('description')))

    @app.get('/api/export')
    def export_jobs():
        jobs = store.list_jobs(uid())
        response = make_response(json.dumps(jobs, ensure_ascii=False, indent=2))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        response.headers['Content-Disposition'] = 'attachment; filename="my-jobs.json"'
        return response

    @app.post('/api/import')
    def import_jobs():
        user_id = uid()
        jobs = body().get('jobs')
        if not isinstance(jobs, list) or not 1 <= len(jobs) <= 200 or not all(isinstance(x, dict) for x in jobs):
            raise ValueError('Import a JSON array containing 1–200 job objects.')
        # Validate the whole batch before committing any record.
        ids = store.add_jobs(user_id, [validate_job(job) for job in jobs])
        return jsonify(count=len(ids)), 201

    @app.post('/api/samples')
    def load_samples():
        user_id = uid()
        samples = [
            {'company': 'Northstar Labs', 'role': 'Working Student · AI Engineering',
             'url': 'https://example.com/job-tracker-samples/northstar', 'location': 'Karlsruhe',
             'work_mode': 'hybrid', 'employment_type': 'working_student', 'language': 'english',
             'description': 'FICTIONAL DEMO JOB. Build Python tools, evaluate LLM responses and test APIs.',
             'notes': 'Sample entry for exploring the app. This is not a real vacancy.'},
            {'company': 'Orbit Studio', 'role': 'Junior Python Developer',
             'url': 'https://example.com/job-tracker-samples/orbit', 'location': 'Germany',
             'work_mode': 'remote', 'office_days': 0, 'employment_type': 'full_time',
             'language': 'english', 'german_level': 'none',
             'description': 'FICTIONAL DEMO JOB. Develop Python services with SQL and Docker.',
             'notes': 'Sample entry for exploring the app. This is not a real vacancy.'},
            {'company': 'Fieldwork', 'role': 'Machine Learning Intern',
             'url': 'https://example.com/job-tracker-samples/fieldwork', 'location': 'Mannheim',
             'work_mode': 'hybrid', 'office_days': 2, 'employment_type': 'internship',
             'language': 'mixed', 'german_level': 'B2',
             'description': 'FICTIONAL DEMO JOB. Explore datasets using Python and scikit-learn.',
             'notes': 'Sample entry for exploring the app. This is not a real vacancy.'},
        ]
        existing = {job['url'] for job in store.list_jobs(user_id)}
        fresh = [validate_job(job) for job in samples if job['url'] not in existing]
        ids = store.add_jobs(user_id, fresh) if fresh else []
        return jsonify(count=len(ids)), 201

    return app
