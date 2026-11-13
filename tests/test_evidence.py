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

    def profile_case(self, case, url, output):
        (case / 'output.txt').write_text(output, encoding='utf-8')
        data = load(case)
        data['identifiers'].append({'id': 'target', 'type': 'profile', 'value': url, 'supplied': True})
        data['scans'].append({'id': 'scan', 'target': 'target', 'tool': 'socid-extractor', 'output': 'output.txt'})
        save(case, data)
        parse_scan(case, 'scan', TOOLS['socid-extractor'])
        return load(case)

    def test_profile_page_fields_and_url_handle_become_leads(self):
        tool = TOOLS['socid-extractor']
        self.assertEqual((tool.kind, tool.arguments({'type': 'profile', 'value': 'https://example.org/alice'})),
                         ('profile', ['--url', 'https://example.org/alice', '--json']))
        output = 'warning: slow response\n' + json.dumps([{'url': 'https://example.org/in/alice/', 'info': {
            'fullname': 'Alice Example', 'example_username': 'alice_alt',
            'bio': 'Write to Local@EXAMPLE.org', 'links': ['mail other@example.org', 3]}}])
        with tempfile.TemporaryDirectory() as directory:
            case = Path(directory)
            parsed = self.profile_case(case, 'https://example.org/in/alice/', output)
            self.assertEqual(parsed['scans'][0]['parse_status'], 'completed')
            account, = parsed['accounts']
            self.assertEqual(account['url'], 'https://example.org/in/alice/')
            self.assertEqual(account['observations'][0]['fields']['fullname'], 'Alice Example')
            leads = {(i['type'], i['value']) for i in parsed['identifiers'] if i['id'] != 'target'}
            self.assertEqual(leads, {('username', 'alice_alt'), ('username', 'alice'),
                                     ('email', 'Local@EXAMPLE.org'), ('email', 'other@example.org')})
            located = {e['value']: e['field'] for e in parsed['evidence'] if e['kind'] in ('username', 'email')}
            self.assertEqual(located, {'alice_alt': '/0/info/example_username', 'Local@EXAMPLE.org': '/0/info/bio',
                                       'other@example.org': '/0/info/links/0'})
            self.assertTrue(all(e['account_id'] == account['id'] for e in parsed['evidence']))
            labels = {r['label'] for r in parsed['relationships']}
            self.assertIn('handle in supplied profile URL', labels)
            parse_scan(case, 'scan', tool)
            self.assertEqual(parsed['evidence'], load(case)['evidence'])
            self.assertEqual(len(load(case)['identifiers']), len(parsed['identifiers']))

    def test_profile_without_extracted_data_keeps_only_the_url_handle(self):
        for url, output, expected in [
                ('https://example.org/@alice', '[]', ['alice']),
                ('https://example.org/alice', 'Tool is not installed or has no adapter\n', ['alice']),
                ('https://example.org/posts/123/comments', '[]', []),
                ('https://example.org/channel/UC123', '[]', [])]:
            with tempfile.TemporaryDirectory() as directory:
                parsed = self.profile_case(Path(directory), url, output)
                self.assertEqual(parsed['accounts'], [])
                self.assertEqual(parsed.get('evidence', []), [])
                self.assertEqual([i['value'] for i in parsed['identifiers'] if i['type'] == 'username'], expected)

