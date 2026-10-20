#!/usr/bin/env python3
"""Export your Nintendo Account play history directly to a Gravk CSV."""

import argparse
import base64
from decimal import Decimal, InvalidOperation
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import webbrowser

from export import FIELDS, write_csv

CLIENT = '5c38e31cd085304b'
ACCOUNTS = 'https://accounts.nintendo.com'
HISTORY = 'https://app-api.znej.nintendo.com/api/v2.0/users/me/play_histories'
CALLBACK = f'npf{CLIENT}://auth'
USER_AGENT = 'com.nintendo.znej/3.0.3 (iOS/26.0.1)'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_json(url, payload=None, form=False, bearer=None, locale='en-US'):
    # Never send credentials to a user-supplied endpoint or a redirected host.
    allowed = {ACCOUNTS + '/connect/1.0.0/api/session_token',
               ACCOUNTS + '/connect/1.0.0/api/token', HISTORY}
    if url not in allowed:
        raise ValueError('Unexpected Nintendo endpoint.')
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'gentry-locale': locale}
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
        body = (urlencode(payload) if form else json.dumps(payload)).encode('utf-8')
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    try:
        with build_opener(NoRedirect()).open(Request(url, data=body, headers=headers), timeout=30) as response:
            data = json.load(response)
    except HTTPError as exc:
        # Do not print server bodies, headers, callback codes, or tokens.
        auth_error = exc.code in (401, 403)
        if exc.code == 400:
            try:
                detail = json.loads(exc.read())
                auth_error = detail.get('error') in ('invalid_grant', 'invalid_token')
            except (ValueError, AttributeError):
                pass
        if auth_error:
            raise ValueError('Nintendo rejected the authorization. Run: bash nintendo.sh login') from None
        raise ValueError(f'Nintendo returned HTTP {exc.code}. The undocumented API or app version may have changed; '
                         'for rate limits, wait and retry.') from None
    except (URLError, TimeoutError, OSError):
        raise ValueError('Could not connect to Nintendo. Check your connection and retry.') from None
    except (ValueError, UnicodeError):
        raise ValueError('Nintendo returned an invalid JSON response.') from None
    if not isinstance(data, dict):
        raise ValueError('Unexpected Nintendo response: expected an object.')
    return data


def default_session():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/nintendo-to-gravk/session.json'
    base = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config')
    return base / 'nintendo-to-gravk/session.json'


def save_private(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name  # NamedTemporaryFile is owner-only (0600).
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_session(path):
    path = Path(path)
    if not path.exists():
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
        raise ValueError('Session must be an owner-only regular file (chmod 600), owned by your user.')
    data = json.loads(path.read_text(encoding='utf-8'))
    token = data.get('session_token') if isinstance(data, dict) else None
    if not isinstance(token, str) or not token:
        raise ValueError('Session file is invalid. Run: bash nintendo.sh login')
    return token


def login_request():
    state = secrets.token_urlsafe(36)
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    url = ACCOUNTS + '/connect/1.0.0/authorize?' + urlencode({
        'client_id': CLIENT, 'redirect_uri': CALLBACK, 'response_type': 'session_token_code',
        'scope': 'openid user user.mii user.email user.links[].id',
        'state': state, 'session_token_code_challenge': challenge,
        'session_token_code_challenge_method': 'S256', 'theme': 'login_form',
    })
    return url, state, verifier


def callback_code(value, expected_state):
    parsed = urlparse(value.strip())
    if (parsed.scheme != f'npf{CLIENT}' or parsed.netloc != 'auth'
            or parsed.path or parsed.query):
        raise ValueError('Expected the copied npf…://auth#… link from the account-selection button.')
    params = parse_qs(parsed.fragment)
    state_values = params.get('state', [])
    codes = params.get('session_token_code', [])
    if len(state_values) != 1 or not secrets.compare_digest(state_values[0], expected_state):
        raise ValueError('Sign-in state mismatch. Run login again and use the new sign-in link.')
    if len(codes) != 1 or not codes[0]:
        raise ValueError('The callback does not contain one authorization code.')
    return codes[0]


def login(path, no_browser=False):
    if not sys.stdin.isatty():
        raise ValueError('Login needs an interactive terminal. Run bash nintendo.sh login locally.')
    url, state, verifier = login_request()
    print('Open this Nintendo sign-in link:\n\n' + url + '\n')
    print('Sign in, then right-click “Select this person” and copy its link address.\n'
          'Do not click that button or open the copied npf… link in your browser.\n'
          'Paste that entire link below; input is hidden. Do not paste it into chat.\n'
          'If Safari says the address is invalid after account selection, dismiss\n'
          'the alert, return to that page, and copy the button link instead.')
    if not no_browser:
        try:
            webbrowser.open(url)
        except webbrowser.Error:
            pass  # The printed link is also usable manually.
    code = callback_code(getpass.getpass('Nintendo callback link: '), state)
    response = request_json(ACCOUNTS + '/connect/1.0.0/api/session_token', {
        'client_id': CLIENT, 'session_token_code': code, 'session_token_code_verifier': verifier,
    }, form=True)
    token = response.get('session_token')
    if not isinstance(token, str) or not token:
        raise ValueError('Nintendo returned no session token. Repeat login with a fresh sign-in link.')
    save_private(path, {'session_token': token})
    print('Signed in. Session saved locally with owner-only permissions.')
    return token


def get_history(session, locale):
    response = request_json(ACCOUNTS + '/connect/1.0.0/api/token', {
        'client_id': CLIENT, 'session_token': session,
        'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer-session-token',
    })
    token = response.get('access_token')
    if not isinstance(token, str) or not token:
        raise ValueError('Nintendo returned no access token. Run: bash nintendo.sh login')
    return request_json(HISTORY, bearer=token, locale=locale)


def convert(history, mappings):
    if not isinstance(history, dict) or not isinstance(history.get('playHistories'), list):
        raise ValueError('Expected a Nintendo playHistories array.')
    # Observed API codes match Nintendo's HAC (Switch) and BEE (Switch 2) families.
    # Other unverified hardware codes still require an explicit user mapping.
    platforms = {'nintendo switch': 'Nintendo Switch', 'switch': 'Nintendo Switch',
                 'nintendo switch 2': 'Nintendo Switch 2', 'switch 2': 'Nintendo Switch 2',
                 'hac': 'Nintendo Switch', 'bee': 'Nintendo Switch 2'}
    for mapping in mappings:
        source, separator, target = mapping.partition('=')
        if not separator or not source.strip() or not target.strip():
            raise ValueError('--platform-map must be SOURCE=GRAVK_LABEL.')
        platforms[source.strip().casefold()] = target.strip()
    records = []
    seen = {}
    for game in history['playHistories']:
        if not isinstance(game, dict):
            raise ValueError('Unexpected game record.')
        title = game.get('titleName')
        identifier = game.get('titleId')
        source = game.get('platform') or game.get('deviceType')
        if not isinstance(title, str) or not title.strip() or not isinstance(identifier, str) or not identifier:
            raise ValueError('Game record is missing titleId or titleName.')
        if not isinstance(source, str) or source.strip().casefold() not in platforms:
            raise ValueError(f'Unmapped Nintendo platform {source!r}. Use --save-json to keep the response, '
                             'then --platform-map SOURCE=GRAVK_LABEL after verifying the platform.')
        minutes = game.get('totalPlayedMinutes')
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0:
            raise ValueError(f'Missing or invalid totalPlayedMinutes for {title!r}.')
        key = (identifier, source.strip().casefold())
        if key in seen:
            if seen[key] != minutes:
                raise ValueError(f'Conflicting duplicate playtime for {title!r}; refusing to guess.')
            continue
        seen[key] = minutes
        total = Decimal(minutes) / 60
        hours = format(total.quantize(Decimal('0.0001')), 'f').rstrip('0').rstrip('.') or '0'
        records.append(dict(zip(FIELDS, [title.strip(), hours, '', platforms[key[1]], 'played', '',
                                         'false', 'false', 'false'])))
    if not records:
        raise ValueError('Nintendo returned no play history. Check your account in the Store app and allow time to sync.')
    # Recent daily records are subsets of these totals, so they are deliberately not added.
    return sorted(records, key=lambda row: (row['platform'], row['title'].casefold()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-file', type=Path, default=default_session(), help='Private session location')
    commands = parser.add_subparsers(dest='command', required=True)
    signin = commands.add_parser('login', help='Sign in through Nintendo in your browser')
    signin.add_argument('--no-browser', action='store_true', help='Print the link without opening the browser')
    commands.add_parser('logout', help='Delete the local session (does not revoke it at Nintendo)')
    export = commands.add_parser('export', help='Fetch your history and create a Gravk CSV')
    export.add_argument('-o', '--output', type=Path, default=Path('gravk-nintendo.csv'))
    export.add_argument('--force', action='store_true', help='Replace an existing CSV')
    export.add_argument('--locale', default='en-US')
    export.add_argument('--input-json', type=Path, help='Convert a previously saved Nintendo response offline')
    export.add_argument('--save-json', type=Path, help='Save the raw response locally, even if conversion fails')
    export.add_argument('--platform-map', action='append', default=[], metavar='SOURCE=GRAVK_LABEL')
    args = parser.parse_args(argv)
    try:
        if args.command == 'login':
            login(args.session_file, args.no_browser)
        elif args.command == 'logout':
            args.session_file.unlink(missing_ok=True)
            print('Local session deleted. This does not revoke Nintendo authorization.')
        else:
            if args.output.exists() and not args.force:
                raise ValueError('Output exists; choose another name or use --force.')
            if args.output.resolve() == args.session_file.resolve():
                raise ValueError('CSV output cannot replace the session file.')
            if args.input_json and args.output.resolve() == args.input_json.resolve():
                raise ValueError('CSV output cannot replace its JSON input.')
            if args.save_json:
                reserved = [args.output, args.session_file] + ([args.input_json] if args.input_json else [])
                if args.save_json.exists() or any(args.save_json.resolve() == path.resolve() for path in reserved):
                    raise ValueError('Choose a new --save-json path separate from input, CSV, and session files.')
            if args.input_json:
                history = json.loads(args.input_json.read_text(encoding='utf-8'))
            else:
                session = load_session(args.session_file) or login(args.session_file)
                print('Fetching play history from Nintendo...', file=sys.stderr)
                history = get_history(session, args.locale)
            if args.save_json:
                save_private(args.save_json, history)
                print(f'Saved Nintendo response to {args.save_json}', file=sys.stderr)
            records = convert(history, args.platform_map)
            write_csv(args.output, records, args.force)
            print(f'Exported {len(records)} games to {args.output}')
        return 0
    except (ValueError, OSError, InvalidOperation) as exc:
        # JSON decoder diagnostics can contain source data; show a generic error for those.
        message = 'Invalid JSON file.' if isinstance(exc, json.JSONDecodeError) else str(exc)
        print('Error: ' + message, file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print('\nCancelled.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
