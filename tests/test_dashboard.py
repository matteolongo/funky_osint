import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.case = self.workspace / 'osint-example'
        self.case.mkdir()
        self.store = module('case_store', ROOT / 'scripts' / 'case_store.py')
        self.store.add_identifier(self.case, 'username', 'alice')

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_records_evidence_and_only_positive_accounts(self):
        output = self.case / 'sherlock_1.txt'
        output.write_text('[+] Example: https://example.org/alice\nusername: bob\nContact: @carol and hi@example.org\n[-] Missing: https://missing.org/alice\n', encoding='utf-8')
        self.store.add_scan(self.case, 'username', 'alice', 'sherlock', output.name, 0)
        data = json.loads((self.case / 'case.json').read_text(encoding='utf-8'))
        self.assertEqual([a['url'] for a in data['accounts']], ['https://example.org/alice'])
        self.assertEqual(data['scans'][0]['output'], 'sherlock_1.txt')
        self.assertEqual(data['relationships'][0]['source'], data['scans'][0]['id'])
        self.assertIn('bob', [i['value'] for i in data['identifiers']])
        self.assertIn('carol', [i['value'] for i in data['identifiers']])
        self.assertNotIn('example.org', [i['value'] for i in data['identifiers']])
        self.assertTrue(any(r['label'] == 'mentioned in output' for r in data['relationships']))
        self.assertNotIn('missing.org', json.dumps(data))

    def test_http_serves_cases_and_evidence_but_rejects_unlisted_files(self):
        output = self.case / 'scan.txt'
        output.write_text('evidence', encoding='utf-8')
        (self.case / 'private.txt').write_text('private', encoding='utf-8')
        self.store.add_scan(self.case, 'username', 'alice', 'sherlock', output.name, 0)
        server_module = module('dashboard_server', ROOT / 'dashboard' / 'server.py')
        server = server_module.make_server(self.workspace, '127.0.0.1', 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(base + '/api/cases') as response:
            self.assertEqual(json.load(response)[0]['id'], 'osint-example')
        with urllib.request.urlopen(base + '/api/cases/osint-example/evidence/scan.txt') as response:
            self.assertEqual(response.read(), b'evidence')
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + '/api/cases/osint-example/evidence/private.txt')
        self.assertEqual(error.exception.code, 404)

    def test_maigret_preserves_recursive_search_and_account_details(self):
        output = self.case / 'maigret.txt'
        output.write_text(
            '[*] Checking username alice on:\n'
            '[+] Example: https://example.org/alice\n'
            ' ├─fullname: Alice Smith\n'
            ' ├─image: https://images.example.org/alice.jpg\n'
            ' └─follower_count: 42\n'
            '[+] Example: https://example.org/alice\n'
            ' └─bio: Writer\n'
            '[+] Blog: https://alice.wordpress.com/\n'
            '[+] Generic site: https://generic.example.org\n'
            '[+] Broken: https://[invalid\n'
            '[*] Checking username bob on:\n'
            '[+] Other: https://example.org/bob\n'
            ' └─fullname: Bob Jones\n', encoding='utf-8')
        self.store.add_scan(self.case, 'username', 'alice', 'maigret', output.name, 0)
        data = json.loads((self.case / 'case.json').read_text(encoding='utf-8'))
        direct = next(a for a in data['accounts'] if a['site'] == 'Example')
        recursive = next(a for a in data['accounts'] if a['site'] == 'Other')
        self.assertNotIn('Generic site', [a['site'] for a in data['accounts']])
        self.assertIn('Blog', [a['site'] for a in data['accounts']])
        observation = direct['observations'][0]
        self.assertEqual(observation['fields']['fullname'], 'Alice Smith')
        self.assertEqual(observation['fields']['image'], 'https://images.example.org/alice.jpg')
        self.assertEqual(observation['fields']['follower_count'], '42')
        self.assertEqual(observation['fields']['bio'], 'Writer')
        self.assertEqual(len(direct['observations']), 1)
        self.assertEqual(sum(r['target'] == direct['id'] for r in data['relationships']), 1)
        recursive_source = next(r['source'] for r in data['relationships'] if r['target'] == recursive['id'])
        recursive_scan = next(s for s in data['scans'] if s['id'] == recursive_source)
        self.assertEqual(recursive_scan['scope'], 'recursive')
        self.assertEqual(recursive_scan['output'], 'maigret.txt')
        self.assertEqual(next(i['value'] for i in data['identifiers'] if i['id'] == recursive_scan['target']), 'bob')
        self.assertEqual(recursive_scan['parent_scan'], data['scans'][0]['id'])

    def test_holehe_statuses_preserve_rate_limits_and_errors(self):
        output = self.case / 'holehe.txt'
        output.write_text('[+] example.org\n[-] absent.org\n[x] limited.org\n[!] error.org\n', encoding='utf-8')
        self.store.add_scan(self.case, 'email', 'alice@example.org', 'holehe', output.name, 0)
        data = json.loads((self.case / 'case.json').read_text(encoding='utf-8'))
        self.assertEqual(data['scans'][0]['checks'], [
            {'site': 'example.org', 'status': 'reported'},
            {'site': 'absent.org', 'status': 'not reported'},
            {'site': 'limited.org', 'status': 'rate limited'},
            {'site': 'error.org', 'status': 'error'},
        ])
        self.assertEqual(data['accounts'], [])


if __name__ == '__main__':
    unittest.main()
