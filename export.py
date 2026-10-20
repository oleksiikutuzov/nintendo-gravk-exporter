#!/usr/bin/env python3
"""Export public Exophase Nintendo playtime to the Gravk CSV template."""

import argparse
import csv
from decimal import Decimal, InvalidOperation
import html
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

FIELDS = ['title', 'hours', 'completedAt', 'platform', 'status', 'userScore',
          'platinum', 'steamDeck', 'favorite']
PLATFORMS = {'switch': 'Nintendo Switch', 'switch-2': 'Nintendo Switch 2'}


def fetch(url):
    request = Request(url, headers={
        'User-Agent': 'exophase-to-gravk/1.0',
        'Accept': 'application/json,text/html;q=0.9',
    })
    try:
        with urlopen(request, timeout=30) as response:
            return response.read().decode('utf-8')
    except HTTPError as exc:
        if exc.code in (403, 429, 503):
            raise ValueError(
                f'Exophase returned HTTP {exc.code}. Open the URL in your browser. '
                'For a blocked profile, use --profile-html or --player-id. '
                'For a blocked games API, save its JSON pages and use --input-json. '
                'For rate limits, wait before trying again.'
            ) from exc
        raise ValueError(f'HTTP {exc.code} fetching {url}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError(f'Could not fetch {url}: {exc}') from exc


def profile_url(value):
    if re.fullmatch(r'[A-Za-z0-9_-]+', value):
        return f'https://www.exophase.com/user/{value}/'
    parsed = urlparse(value)
    if (parsed.scheme == 'https' and parsed.netloc in ('www.exophase.com', 'exophase.com')
            and re.fullmatch(r'/user/[A-Za-z0-9_-]+/?', parsed.path)
            and not parsed.query and not parsed.fragment):
        return value
    raise ValueError('Expected an Exophase username or https://www.exophase.com/user/USERNAME/.')


def player_id(source):
    match = re.search(r'\bplayerProfileId\s*[=:]\s*[\'\"]?([A-Za-z0-9_]+)', source)
    if not match:
        raise ValueError('No playerProfileId found. Save the actual public profile HTML '
                         '(not a browser challenge), or supply --player-id.')
    return match.group(1)


def parse_page(source, allow_end=False):
    try:
        page = json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError('Expected a games API JSON response; received invalid JSON or HTML.') from exc
    # Exophase returns this exact sentinel after the last populated page.
    if allow_end and page == {'success': False}:
        return []
    if not isinstance(page, dict) or page.get('success') is not True or not isinstance(page.get('games'), list):
        raise ValueError('Unexpected API response: expected success=true and a games array.')
    return page['games']


def api_pages(identifier, max_pages):
    previous = set()
    for number in range(1, max_pages + 1):
        url = f'https://api.exophase.com/public/player/{identifier}/games?' + urlencode({
            'page': number, 'environment': '', 'sort': 1, 'showHidden': 0,
        })
        print(f'Reading games page {number}...', file=sys.stderr)
        games = parse_page(fetch(url), allow_end=number > 1)
        if not games:
            return
        fingerprint = json.dumps(games, sort_keys=True)
        if fingerprint in previous:
            raise ValueError('API repeated a page; refusing to export an incomplete list.')
        previous.add(fingerprint)
        yield games
        time.sleep(0.3)
    raise ValueError('Page limit reached before an empty page. Increase --max-pages.')


def nonnegative(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'Invalid playtime number: {value!r}') from exc
    if not number.is_finite() or number < 0:
        raise ValueError(f'Invalid playtime number: {value!r}')
    return number


def hours(game):
    units = game.get('playtimeUnits')
    if isinstance(units, dict) and any(units.get(k) is not None for k in ('hours', 'minutes')):
        total = nonnegative(units.get('hours') or 0) + nonnegative(units.get('minutes') or 0) / 60
    else:
        value = game.get('playtime')
        if value is None or value == '':
            return ''  # Unknown time must not become a fabricated zero.
        match = re.fullmatch(r'\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?\s*', str(value))
        if not match or not any(match.groups()):
            raise ValueError(f'Unrecognized playtime: {value!r}')
        total = Decimal(match.group(1) or 0) + Decimal(match.group(2) or 0) / 60
    return format(total.quantize(Decimal('0.0001')), 'f').rstrip('0').rstrip('.') or '0'


def rows(pages, switch_name, switch2_name):
    result = []
    seen = set()
    names = {'switch': switch_name, 'switch-2': switch2_name}
    for games in pages:
        for game in games:
            if not isinstance(game, dict):
                raise ValueError('Unexpected non-object game record.')
            meta = game.get('meta') or {}
            platforms = meta.get('platforms') or []
            selected = set()
            for platform in platforms:
                slug = platform.get('slug', '')
                name = str(platform.get('name', '')).lower().strip()
                if slug in PLATFORMS:
                    selected.add(slug)
                elif name in ('switch', 'nintendo switch'):
                    selected.add('switch')
                elif name in ('switch 2', 'nintendo switch 2'):
                    selected.add('switch-2')
            if not selected:
                continue
            if len(selected) > 1:
                print(f'Warning: {meta.get("title")}: shared Switch/Switch 2 record; '
                      f'exporting once as {switch_name}. Console-specific time is unavailable.', file=sys.stderr)
                slug = 'switch'
            else:
                slug = selected.pop()
            title = html.unescape(str(meta.get('title') or '')).strip()
            if not title:
                raise ValueError('Nintendo game record has no title.')
            key = (str(game.get('master_id') or title), slug)
            if key in seen:
                continue
            seen.add(key)
            result.append(dict(zip(FIELDS, [title, hours(game), '', names[slug], 'played', '',
                                             'false', 'false', 'false'])))
    if not result:
        raise ValueError('No Nintendo Switch games found. Check public visibility and run an Exophase sync.')
    return sorted(result, key=lambda row: (row['platform'], row['title'].casefold()))


def write_csv(destination, records, force):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                         dir=destination.parent, delete=False) as output:
            temp_name = output.name
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(records)
        if force:
            os.replace(temp_name, destination)
        else:
            # Publish a complete file without a race that could overwrite another export.
            os.link(temp_name, destination)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', nargs='?', help='Public Exophase username or profile URL')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--player-id', help='playerProfileId from your public profile HTML')
    source.add_argument('--profile-html', type=Path, help='Saved public profile HTML')
    source.add_argument('--input-json', type=Path, nargs='+', help='Saved games API JSON pages (offline)')
    parser.add_argument('-o', '--output', default='gravk-nintendo.csv')
    parser.add_argument('--force', action='store_true', help='Replace an existing output file')
    parser.add_argument('--max-pages', type=int, default=200)
    parser.add_argument('--switch-platform', default='Nintendo Switch', help='Gravk platform label')
    parser.add_argument('--switch2-platform', default='Nintendo Switch 2', help='Gravk platform label')
    args = parser.parse_args(argv)
    try:
        if args.max_pages < 1:
            raise ValueError('--max-pages must be positive.')
        if Path(args.output).exists() and not args.force:
            raise ValueError('Output already exists. Choose another filename or use --force.')
        if args.input_json:
            pages = [parse_page(path.read_text(encoding='utf-8')) for path in args.input_json]
        else:
            identifier = args.player_id
            if not identifier:
                if args.profile_html:
                    page = args.profile_html.read_text(encoding='utf-8')
                elif args.profile:
                    page = fetch(profile_url(args.profile))
                else:
                    raise ValueError('Supply a profile, --player-id, --profile-html, or --input-json.')
                identifier = player_id(page)
            if not re.fullmatch(r'[A-Za-z0-9_]+', identifier):
                raise ValueError('Invalid player ID.')
            pages = api_pages(identifier, args.max_pages)
        records = rows(pages, args.switch_platform, args.switch2_platform)
        write_csv(args.output, records, args.force)
        print(f'Exported {len(records)} Nintendo games to {args.output}', file=sys.stderr)
        unknown = sum(row['hours'] == '' for row in records)
        if unknown:
            print(f'Warning: {unknown} games have unknown playtime (blank hours). Review before importing.', file=sys.stderr)
        return 0
    except (ValueError, OSError, TypeError, AttributeError, InvalidOperation) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
