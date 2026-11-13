import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from adapters import TOOLS
from evidence import parse_output_mentions


class PhoneLeadTests(unittest.TestCase):
    def test_international_phone_numbers_become_leads_unless_masked(self):
        data = {'identifiers': [{'id': 'target', 'type': 'phone', 'value': '+34600000001'}],
                'accounts': [], 'scans': [], 'relationships': []}
        scan = {'id': 'scan', 'target': 'target',
                'artifact': {'filename': 'output.txt', 'artifact_sha256': 'hash'}}
        parse_output_mentions(data, scan, 'E164: +34600000001\nContact: +34 (600) 000-002\n'
                              'Recovery: +34 600 000 ***\nShort: +3460\nid 1+34600000003\n', handles=False)
        self.assertEqual([(i['type'], i['value']) for i in data['identifiers']],
                         [('phone', '+34600000001'), ('phone', '+34600000002')])
        mention, = data['evidence']
        self.assertEqual((mention['kind'], mention['value'], mention['line']), ('phone', '+34600000002', 2))

    def test_ignorant_records_site_checks_and_plain_calling_code(self):
        self.assertEqual(TOOLS['ignorant'].arguments(
            {'type': 'phone', 'value': '+34600000001', 'country_code': '+34'}), ['34', '600000001'])
        self.assertIsNone(TOOLS['ignorant'].arguments({'type': 'phone', 'value': '+34600000001'}))
        data = {'identifiers': [{'id': 'target', 'type': 'phone', 'value': '+34600000001'}],
                'accounts': [], 'scans': [], 'relationships': []}
        scan = {'id': 'scan', 'target': 'target',
                'artifact': {'filename': 'output.txt', 'artifact_sha256': 'hash'}}
        TOOLS['ignorant'].parse(data, scan, '   34600000001\n[+] amazon.com\n[-] instagram.com\n'
                                '[x] snapchat.com\n[+] Phone number used, [-] Phone number not used\n')
        self.assertEqual(scan['checks'], [{'site': 'amazon.com', 'status': 'reported'},
                                          {'site': 'instagram.com', 'status': 'not reported'},
                                          {'site': 'snapchat.com', 'status': 'rate limited'}])
        self.assertEqual([e['line'] for e in data['evidence']], [2, 3, 4])

