"""Exercise the real HTTP server and persistence using disposable, fictional data."""

from contextlib import contextmanager
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def server(database, port):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('JOB_TRACKER_')}
    with tempfile.TemporaryFile(mode='w+') as logs:
        process = subprocess.Popen(
            [sys.executable, '-m', 'job_tracker', 'serve', '--port', str(port), '--web-db', str(database)],
            cwd=ROOT, env=environment, stdout=logs, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    logs.seek(0)
                    raise RuntimeError('Server did not start: ' + logs.read())
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health', timeout=1) as response:
                        if response.status == 200:
                            break
                except (OSError, URLError):
                    time.sleep(.1)
            else:
                raise RuntimeError('Timed out waiting for the demo server.')
            yield
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


class Client:
    def __init__(self, port):
        self.base = f'http://127.0.0.1:{port}'
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, method='GET', data=None, expected=200):
        headers = {}
        if method != 'GET':
            headers = {'Content-Type': 'application/json', 'Origin': self.base,
                       'X-CSRF-Token': self.call('/session')['csrf']}
        request = Request(self.base + '/api' + path, method=method, headers=headers,
                          data=json.dumps(data or {}).encode() if method != 'GET' else None)
        try:
            response = self.opener.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            payload = json.load(response)
            assert response.status == expected, (path, response.status, payload)
            return payload


def main():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory() as folder:
        database = Path(folder) / 'demo.sqlite3'
        alice, bob = Client(port), Client(port)
        with server(database, port):
            alice.call('/register', 'POST', {'username': 'demo_alice', 'password': 'fictional-demo-password'}, 201)
            bob.call('/register', 'POST', {'username': 'demo_bob', 'password': 'another-demo-password'}, 201)
            alice.call('/preferences', 'PUT', {'employment_type': 'working_student', 'skills': 'Python',
                                               'language': 'english', 'office_days': 1, 'german_level': 'A2'})
            draft = alice.call('/parse', 'POST', {'description':
                'Company: Example Labs\nRole: Working Student Python\nURL: https://example.com/fictional/job\n'
                'Job type: Working student\nWorking language: English\nFictional demo posting.'})['draft']
            assert alice.call('/jobs')['jobs'] == [], 'Parsing must not save an unreviewed draft.'
            job_id = alice.call('/jobs', 'POST', draft, 201)['id']
            job = alice.call(f'/jobs/{job_id}')['job']
            alice.call(f'/jobs/{job_id}', 'PUT', {**job, 'status': 'applied', 'applied_date': '2026-11-23'})
            applied = alice.call(f'/jobs/{job_id}')
            assert applied['job']['applied_date'] == '2026-11-23'
            assert [event['status'] for event in applied['history']] == ['saved', 'applied']
            assert applied['fit']['matches'] and applied['fit']['unknowns']
            assert bob.call('/jobs')['jobs'] == []
            bob.call(f'/jobs/{job_id}', expected=404)
            exported = alice.call('/export')
            assert len(exported) == 1
            bob.call('/import', 'POST', {'jobs': exported}, 201)
            alice.call(f'/jobs/{job_id}', 'DELETE', {'version': applied['job']['version']})
            assert alice.call('/jobs')['jobs'] == []
            alice.call(f'/jobs/{job_id}/restore', 'POST')
            print('PASS: register -> preferences -> review import -> save -> apply -> export/import -> delete/undo')
        with server(database, port):
            persisted = alice.call('/jobs')['jobs']
            assert len(persisted) == 1 and persisted[0]['status'] == 'applied'
            assert len(bob.call('/jobs')['jobs']) == 1
            print('PASS: separate accounts and SQLite data survive a server restart')
    print('Demo finished. Temporary accounts and data removed; your normal database was not used.')


if __name__ == '__main__':
    main()
