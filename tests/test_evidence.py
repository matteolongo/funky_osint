import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from adapters import TOOLS
from case_store import load, parse_scan, save
from evidence import comparison_key, parse_output_mentions


class EvidenceTests(unittest.TestCase):
    def test_output_username_can_span_lines(self):
        data = {'identifiers': [], 'relationships': []}
        scan = {'id': 'scan', 'target': 'target',
                'artifact': {'filename': 'output.txt', 'artifact_sha256': 'hash'}}
        parse_output_mentions(data, scan, 'header\nusername:\nalice\n', handles=False)
        mention, = data['evidence']
        self.assertEqual((mention['value'], mention['line'], mention['end_line']),
                         ('alice', 2, 3))

    def test_text_mentions_are_scoped_to_profile_block(self):
        data = {'identifiers': [{'id': 'target', 'type': 'username', 'value': 'A'}],
                'accounts': [], 'scans': [], 'relationships': []}
        scan = {'id': 'scan', 'target': 'target',
                'artifact': {'filename': 'output.txt', 'artifact_sha256': 'hash'}}
        TOOLS['sherlock'].parse(data, scan, 'Support: help@vendor.example\n'
                               '[+] Site: https://example.org/A\n'
                               '└─username:\nalice\n[-] Other site\n'
                               'Support: help@vendor.example')
        mention, = [item for item in data['evidence'] if item['kind'] in ('username', 'email')]
        self.assertEqual((mention['value'], mention['line'], mention['end_line']),
                         ('alice', 3, 4))
        self.assertEqual(mention['account_id'], data['accounts'][0]['id'])
        self.assertEqual(mention['field'], 'username')

    def test_comparison_preserves_case_sensitive_parts(self):
        self.assertEqual(comparison_key('account', 'https://EXAMPLE.org/A?q=Y'),
                         'https://example.org/A?q=Y')
        self.assertNotEqual(comparison_key('account', 'https://EXAMPLE.org/A'),
                            comparison_key('account', 'https://example.org/a'))
        self.assertEqual(comparison_key('email', 'Local@EXAMPLE.org'), 'Local@example.org')
        self.assertEqual(comparison_key('username', 'MixedCase'), 'MixedCase')

    def test_profile_mention_has_stable_raw_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            artifact = json.dumps({'Site/Name': {'status': {
                'status': 'claimed', 'url': 'https://example.org/A',
                'ids': {'bio': 'Contact Local@EXAMPLE.org'},
            }}}).encode()
            (case / 'report.json').write_bytes(artifact)
            data = load(case)
            data['identifiers'].append({'id': 'target', 'type': 'username', 'value': 'A'})
            data['scans'].append({'id': 'scan', 'target': 'target', 'tool': 'maigret',
                                  'output': 'output.txt', 'structured_output': 'report.json'})
            save(case, data)
            parse_scan(case, 'scan', TOOLS['maigret'])
            first = load(case)
            mention = next(item for item in first['evidence'] if item['kind'] == 'email')
            self.assertEqual(mention['account_id'], first['accounts'][0]['id'])
            self.assertEqual(mention['field'], '/Site~1Name/status/ids/bio')
            self.assertEqual(mention['filename'], 'report.json')
            self.assertEqual(mention['artifact_sha256'], hashlib.sha256(artifact).hexdigest())
            parse_scan(case, 'scan', TOOLS['maigret'])
            self.assertEqual(first['evidence'], load(case)['evidence'])

    def test_text_reports_keep_separate_locations_for_same_account(self):
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            data = load(case)
            data['identifiers'].append({'id': 'target', 'type': 'username', 'value': 'A'})
            for scan_id, host in [('one', 'EXAMPLE.org'), ('two', 'example.org')]:
                filename = scan_id + '.txt'
                (case / filename).write_bytes(
                    f'header\r\n[+] Site: https://{host}/A\r\n'.encode())
                data['scans'].append({'id': scan_id, 'target': 'target', 'tool': 'sherlock',
                                      'output': filename})
            save(case, data)
            for scan_id in ['one', 'two']:
                parse_scan(case, scan_id, TOOLS['sherlock'])
            parsed = load(case)
            self.assertEqual(len(parsed['accounts']), 1)
            self.assertEqual(len(parsed['accounts'][0]['observations']), 2)
            self.assertEqual([(e['filename'], e['line']) for e in parsed['evidence']],
                             [('one.txt', 2), ('two.txt', 2)])
            self.assertEqual(parsed['evidence'][0]['value'], 'https://EXAMPLE.org/A')
            self.assertNotEqual(parsed['evidence'][0]['id'], parsed['evidence'][1]['id'])
