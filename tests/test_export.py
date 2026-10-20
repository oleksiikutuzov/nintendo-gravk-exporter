import csv
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('exporter', ROOT / 'export.py')
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def game(identifier=1, slug='switch', title='Synthetic game', **extra):
    return {'master_id': identifier, 'meta': {'title': title, 'platforms': [{'slug': slug}]},
            'playtimeUnits': {'hours': 1, 'minutes': 30}, **extra}


def page(games):
    return json.dumps({'success': True, 'games': games})


class ExportTests(unittest.TestCase):
    def test_pagination_filters_deduplicates_and_preserves_unknown(self):
        sources = [page([game(), game(2, 'ps5')]),
                   page([game(), game(3, 'switch-2', playtimeUnits=None, playtime='')]),
                   page([])]
        with patch.object(exporter, 'fetch', side_effect=sources) as fetch, patch.object(exporter.time, 'sleep'):
            records = exporter.rows(exporter.api_pages('123', 10), 'Switch', 'Switch 2')
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['hours'], '1.5')
        self.assertEqual(records[1]['hours'], '')
        self.assertIn('page=3', fetch.call_args.args[0])
        self.assertTrue(all(row['completedAt'] == '' for row in records))

    def test_time_formats(self):
        self.assertEqual(exporter.hours({'playtime': '7m'}), '0.1167')
        self.assertEqual(exporter.hours({'playtime': '117h 55m'}), '117.9167')
        self.assertEqual(exporter.hours({'playtimeUnits': {'hours': 0, 'minutes': 0}}), '0')
        for bad in ('a while', '-1h'):
            with self.assertRaises(ValueError):
                exporter.hours({'playtime': bad})
        for bad in (-1, 'NaN', 'Infinity'):
            with self.assertRaises(ValueError):
                exporter.hours({'playtimeUnits': {'hours': bad}})

    def test_bad_and_repeated_pages_fail(self):
        for bad in ('<html>challenge</html>', '{}', '{"success":false,"games":[]}'):
            with self.assertRaises(ValueError):
                exporter.parse_page(bad)
        with patch.object(exporter, 'fetch', return_value=page([game()])), patch.object(exporter.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'repeated'):
                list(exporter.api_pages('123', 3))
        with patch.object(exporter, 'fetch', return_value=page([game()])), patch.object(exporter.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, 'limit'):
                list(exporter.api_pages('123', 1))

    def test_failure_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'existing.csv'
            destination.write_text('original')
            with patch.object(exporter, 'fetch', side_effect=[page([game()]), ValueError('network failure')]), \
                    patch.object(exporter.time, 'sleep'), patch('sys.stderr', new_callable=io.StringIO):
                result = exporter.main(['--player-id', '123', '-o', str(destination), '--force'])
            self.assertEqual(result, 1)
            self.assertEqual(destination.read_text(), 'original')

    def test_shared_platform_exports_once(self):
        record = game()
        record['meta']['platforms'].append({'slug': 'switch-2'})
        with patch('sys.stderr', new_callable=io.StringIO) as stderr:
            records = exporter.rows([[record]], 'Switch', 'Switch 2')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['platform'], 'Switch')
        self.assertEqual(records[0]['hours'], '1.5')
        self.assertIn('shared', stderr.getvalue())

    def test_live_end_of_list_sentinel(self):
        with patch.object(exporter, 'fetch', side_effect=[page([game()]), '{"success":false}']), \
                patch.object(exporter.time, 'sleep'):
            self.assertEqual(len(list(exporter.api_pages('123', 10))), 1)
        with self.assertRaises(ValueError):
            exporter.parse_page('{"success":false}')
        with self.assertRaises(ValueError):
            exporter.parse_page('{"success":false,"error":"failed"}', allow_end=True)

    def test_profile_sources(self):
        self.assertEqual(exporter.player_id('window.playerProfileId = "1234";'), '1234')
        self.assertEqual(exporter.profile_url('example'), 'https://www.exophase.com/user/example/')
        with self.assertRaises(ValueError):
            exporter.profile_url('https://example.org/user/example/')

    def test_shell_offline_csv_and_overwrite(self):
        with tempfile.TemporaryDirectory(prefix='gravk test ') as directory:
            source = Path(directory) / 'page.json'
            destination = Path(directory) / 'result.csv'
            title = 'Pokémon, "Example"\nEdition'
            source.write_text(page([game(title=title), game(2, 'ps5')]), encoding='utf-8')
            command = ['bash', str(ROOT / 'export.sh'), '--input-json', str(source), '-o', str(destination)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            with destination.open(newline='', encoding='utf-8') as stream:
                reader = csv.DictReader(stream)
                self.assertEqual(reader.fieldnames, exporter.FIELDS)
                records = list(reader)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['title'], title)
            self.assertEqual(records[0]['hours'], '1.5')
            self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)
            self.assertEqual(subprocess.run(command + ['--force'], capture_output=True).returncode, 0)


if __name__ == '__main__':
    unittest.main()
