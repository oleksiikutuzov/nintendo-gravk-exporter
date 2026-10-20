import csv
import hashlib
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import nintendo


def title(platform='Nintendo Switch', minutes=91):
    return {'titleId': 'synthetic-id', 'titleName': 'Pokémon, "Example"',
            'platform': platform, 'totalPlayedMinutes': minutes}


class NintendoTests(unittest.TestCase):
    def test_login_challenge_and_callback_validation(self):
        url, state, verifier = nintendo.login_request()
        params = parse_qs(urlparse(url).query)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(params['session_token_code_challenge'], [challenge])
        self.assertEqual(params['state'], [state])
        self.assertNotEqual(state, nintendo.login_request()[1])
        callback = nintendo.CALLBACK + f'#state={state}&session_token_code=synthetic-code'
        self.assertEqual(nintendo.callback_code(callback, state), 'synthetic-code')
        for invalid in (callback.replace('://auth', '://other'), callback.replace(state, 'wrong'),
                        callback + '&state=second', callback + '&session_token_code=second',
                        'https://example.org/#state=' + state):
            with self.assertRaises(ValueError):
                nintendo.callback_code(invalid, state)

    def test_login_and_session_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / 'config/session.json'
            with patch.object(nintendo.sys.stdin, 'isatty', return_value=True), \
                    patch.object(nintendo, 'login_request', return_value=('https://accounts.nintendo.com/test', 'state', 'verifier')), \
                    patch.object(nintendo.getpass, 'getpass', return_value=nintendo.CALLBACK + '#state=state&session_token_code=code'), \
                    patch.object(nintendo, 'request_json', return_value={'session_token': 'synthetic-secret'}) as request, \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                nintendo.login(session, no_browser=True)
            self.assertEqual(request.call_args.kwargs, {'form': True})
            self.assertEqual(request.call_args.args[1]['session_token_code_verifier'], 'verifier')
            self.assertNotIn('synthetic-secret', output.getvalue())
            self.assertEqual(nintendo.load_session(session), 'synthetic-secret')
            self.assertEqual(session.stat().st_mode & 0o777, 0o600)
            os.chmod(session, 0o644)
            with self.assertRaises(ValueError):
                nintendo.load_session(session)
            self.assertEqual(nintendo.main(['--session-file', str(session), 'logout']), 0)
            self.assertFalse(session.exists())

    def test_invalid_callback_makes_no_network_request(self):
        with patch.object(nintendo.sys.stdin, 'isatty', return_value=True), \
                patch.object(nintendo.getpass, 'getpass', return_value='https://example.org/'), \
                patch.object(nintendo, 'request_json') as request, patch('sys.stdout', new_callable=io.StringIO):
            with self.assertRaises(ValueError):
                nintendo.login(Path('/unused'), no_browser=True)
            request.assert_not_called()

    def test_convert_totals_without_adding_daily_history(self):
        record = title()
        history = {'playHistories': [record, record, title('Nintendo Switch 2', 60)],
                   'recentPlayHistories': [{'totalPlayedMinutes': 300}]}
        rows = nintendo.convert(history, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['hours'] for r in rows], ['1.5167', '1'])
        self.assertTrue(all(r['completedAt'] == '' for r in rows))
        self.assertEqual(nintendo.convert({'playHistories': [title(minutes=0)]}, [])[0]['hours'], '0')

    def test_unverified_platform_and_conflicts_fail(self):
        history = {'playHistories': [title('UNVERIFIED')]}
        with self.assertRaisesRegex(ValueError, 'Unmapped'):
            nintendo.convert(history, [])
        self.assertEqual(nintendo.convert(history, ['UNVERIFIED=Nintendo Switch'])[0]['platform'], 'Nintendo Switch')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            nintendo.convert({'playHistories': [title(minutes=10), title(minutes=20)]}, [])
        for minutes in (None, -1, True, '10', 1.5):
            with self.assertRaises(ValueError):
                nintendo.convert({'playHistories': [title(minutes=minutes)]}, [])

    def test_hardware_codes_and_legacy_device_type(self):
        legacy = title('HAC', 30)
        legacy['deviceType'] = legacy.pop('platform')
        history = {'playHistories': [legacy, title('bee', 91)],
                   'recentPlayHistories': [{'totalPlayedMinutes': 999}]}
        rows = nintendo.convert(history, [])
        self.assertEqual([(r['platform'], r['hours']) for r in rows],
                         [('Nintendo Switch', '0.5'), ('Nintendo Switch 2', '1.5167')])
        overridden = nintendo.convert({'playHistories': [title('BEE')]}, ['BEE=Switch 2'])
        self.assertEqual(overridden[0]['platform'], 'Switch 2')

    def test_auth_exchange_and_history_headers(self):
        responses = [io.BytesIO(b'{"access_token":"synthetic-access"}'),
                     io.BytesIO(json.dumps({'playHistories': [title()]}).encode())]
        with patch.object(nintendo, 'build_opener') as build:
            build.return_value.open.side_effect = responses
            history = nintendo.get_history('synthetic-session', 'en-GB')
        self.assertEqual(len(history['playHistories']), 1)
        calls = build.return_value.open.call_args_list
        self.assertEqual(json.loads(calls[0].args[0].data)['session_token'], 'synthetic-session')
        req = calls[1].args[0]
        self.assertEqual(req.full_url, nintendo.HISTORY)
        self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-access')
        self.assertEqual(req.get_header('Gentry-locale'), 'en-GB')
        self.assertIsNone(nintendo.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))

    def test_errors_never_echo_response_secrets(self):
        error = HTTPError(nintendo.HISTORY, 400, 'bad', {}, io.BytesIO(
            b'{"error":"invalid_grant","error_description":"secret-value"}'))
        with patch.object(nintendo, 'build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaises(ValueError) as caught:
                nintendo.request_json(nintendo.HISTORY)
        self.assertNotIn('secret-value', str(caught.exception))
        self.assertIn('login', str(caught.exception))
        with self.assertRaises(ValueError):
            nintendo.request_json('https://example.org/', bearer='synthetic-secret')

    def test_shell_offline_export_and_no_partial_output(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.json'
            output = Path(directory) / 'result.csv'
            source.write_text(json.dumps({'playHistories': [title()]}))
            command = ['bash', str(root / 'nintendo.sh'), 'export', '--input-json', str(source), '-o', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with output.open(newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]['title'], title()['titleName'])
            original = output.read_bytes()
            source.write_text(json.dumps({'playHistories': [title('UNKNOWN')]}))
            result = subprocess.run(command + ['--force'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(output.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
