import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from adapters import TOOLS
from case_store import load, parse_scan, save


class ProfileAdapterTests(unittest.TestCase):
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

