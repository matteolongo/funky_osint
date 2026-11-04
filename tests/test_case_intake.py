import importlib.util
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('case_store', ROOT / 'scripts/case_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)
sys.path.insert(0, str(ROOT / 'scripts'))


class CaseIntakeTests(unittest.TestCase):
    def test_intake_preserves_people_and_supplied_relationships(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            store.add_intake(case, {'people': [
                {'name': 'Ana', 'inputs': [{'type': 'username', 'value': 'ana'}]},
                {'name': 'Carlos', 'inputs': [{'type': 'phone', 'value': '+34123456789'}]},
            ], 'relationships': [{'from': 0, 'to': 1, 'label': 'partner'}]})
            data = json.loads((case / 'case.json').read_text(encoding='utf-8'))
            self.assertEqual([p['name'] for p in data['people']], ['Ana', 'Carlos'])
            self.assertEqual(data['people'][0]['inputs'][0]['value'], 'ana')
            self.assertEqual(data['people'][1]['inputs'][0]['value'], '+34123456789')
            self.assertEqual(data['person_relationships'][0]['source'], 'user supplied')

    def test_invalid_intake_does_not_write_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            with self.assertRaises(ValueError):
                store.add_intake(case, {'people': [{'name': 'A', 'inputs': [{'type': 'phone', 'value': ''}]}]})
            self.assertFalse((case / 'case.json').exists())

    def test_mentions_matching_other_input_are_evidence_backed_leads(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            store.add_intake(case, {'people': [
                {'name': 'A', 'inputs': [{'type': 'username', 'value': 'alice'}]},
                {'name': 'B', 'inputs': [{'type': 'email', 'value': 'bob@example.com'}]},
            ]})
            (case / 'scan.txt').write_text('[+] Example: https://example.com/alice\nContact bob@example.com\n', encoding='utf-8')
            store.add_scan(case, 'username', 'alice', 'sherlock', 'scan.txt', 0)
            data = json.loads((case / 'case.json').read_text(encoding='utf-8'))
            self.assertTrue(any(r['label'] == 'mentioned in output' and r['certainty'] == 'lead'
                                and r['target'] == data['people'][1]['inputs'][0]['identifier_id']
                                and r['source'] == data['scans'][0]['id'] for r in data['relationships']))

    def test_runner_continues_after_tool_failure(self):
        runner_spec = importlib.util.spec_from_file_location('case_runner', ROOT / 'scripts/case_runner.py')
        runner = importlib.util.module_from_spec(runner_spec)
        runner_spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp)
            intake = {'people': [{'name': 'Ana', 'inputs': [{'type': 'username', 'value': 'ana'}]}]}
            with patch.object(runner.shutil, 'which', side_effect=lambda name: name if name in ('maigret', 'sherlock') else None), \
                 patch.object(runner.subprocess, 'run', side_effect=[OSError('unavailable'), unittest.mock.Mock(returncode=0)]) as run:
                runner.run_case(case, intake)
            self.assertIn('--no-recursion', run.call_args_list[0].args[0])
            data = json.loads((case / 'case.json').read_text(encoding='utf-8'))
            self.assertEqual([scan['status'] for scan in data['scans']], ['failed', 'completed'])
            self.assertTrue(all((case / scan['output']).exists() for scan in data['scans']))


if __name__ == '__main__':
    unittest.main()
