"""Execution tests use local Python programs, never external OSINT services."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import case_runner as runner
import case_store as store


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.case = Path(self.tmp.name) / 'osint-test'
        self.case.mkdir()

    def fake_tool(self, name, code):
        from adapters import Tool
        return Tool(name, 'username', lambda item: ['-u', '-c', code],
                    lambda data, scan, content: store.parse_accounts(data, scan, 'username', 'alice', content))

    def run_tools(self, tools, **options):
        with patch.dict(runner.TOOLS, {t.name: t for t in tools}, clear=True), \
             patch.object(runner.shutil, 'which', return_value=sys.executable):
            runner.run_targets(self.case, [{'type': 'username', 'value': 'alice'}], **options)
        return store.load(self.case)

    def test_scan_is_running_and_all_tasks_exist_before_tool_starts(self):
        code = "import json,pathlib,os; d=json.loads((pathlib.Path(os.environ['OSINT_CASE_DIR'])/'case.json').read_text()); print(','.join(s['status'] for s in d['scans']))"
        data = self.run_tools([self.fake_tool('first', code), self.fake_tool('second', 'print("ok")')])
        self.assertEqual((self.case / data['scans'][0]['output']).read_text().strip(), 'running,pending')
        self.assertEqual([s['status'] for s in data['scans']], ['completed', 'completed'])
        self.assertIn('finished_at', data['scans'][0])
        self.assertEqual(data['scans'][0]['exit_code'], 0)

    def test_timeout_keeps_partial_evidence_and_continues(self):
        data = self.run_tools([self.fake_tool('slow', 'import time; print("partial", flush=True); time.sleep(30)'),
                               self.fake_tool('next', 'print("ok")')], timeout=0.3)
        self.assertEqual([s['status'] for s in data['scans']], ['timed_out', 'completed'])
        self.assertIn('partial', (self.case / data['scans'][0]['output']).read_text())

    def test_resume_skips_completed_and_rerun_retains_attempts(self):
        tool = self.fake_tool('example', 'print("[+] Example: https://example.org/alice")')
        first = self.run_tools([tool])
        resumed = self.run_tools([tool])
        self.assertEqual(len(resumed['scans']), 1)
        rerun = self.run_tools([tool], rerun=True)
        self.assertEqual(len(rerun['scans']), 2)
        self.assertEqual(rerun['scans'][1]['previous_attempt'], first['scans'][0]['id'])
        self.assertEqual(len(rerun['accounts']), 1)
        self.assertEqual(len(rerun['accounts'][0]['observations']), 2)
        self.assertTrue(all((self.case / s['output']).is_file() for s in rerun['scans']))

    def test_parse_failure_preserves_execution_then_reparse_is_idempotent(self):
        tool = self.fake_tool('example', 'print("[+] Example: https://example.org/alice")')
        from dataclasses import replace
        def broken(data, scan, content):
            raise ValueError('unsupported output')
        data = self.run_tools([replace(tool, parse=broken)])
        self.assertEqual(data['scans'][0]['status'], 'completed')
        self.assertEqual(data['scans'][0]['parse_status'], 'failed')
        self.assertIn('unsupported output', data['scans'][0]['parse_error'])
        with patch.dict(runner.TOOLS, {'example': tool}, clear=True):
            runner.reparse_case(self.case)
            runner.reparse_case(self.case)
        parsed = store.load(self.case)
        self.assertEqual(parsed['scans'][0]['parse_status'], 'completed')
        self.assertEqual(len(parsed['accounts']), 1)
        self.assertEqual(len(parsed['accounts'][0]['observations']), 1)
        self.assertEqual(len(parsed['relationships']), 1)

    def test_restart_records_interrupted_attempt_and_retries(self):
        tool = self.fake_tool('example', 'print("ok")')
        data = self.run_tools([tool])
        data['scans'][0]['status'] = 'running'
        store.save(self.case, data)
        with patch.dict(runner.TOOLS, {'example': tool}, clear=True), \
             patch.object(runner.shutil, 'which', return_value=sys.executable):
            runner.resume_case(self.case)
        scans = store.load(self.case)['scans']
        self.assertEqual([s['status'] for s in scans], ['interrupted', 'completed'])
        self.assertEqual(scans[1]['previous_attempt'], scans[0]['id'])

    def test_second_writer_is_rejected(self):
        with store.case_lock(self.case):
            program = "import sys; from pathlib import Path; import case_store;\nwith case_store.case_lock(Path(sys.argv[1])): print('acquired')"
            result = subprocess.run([sys.executable, '-c', program, str(self.case)],
                                    env={**os.environ, 'PYTHONPATH': str(ROOT / 'scripts')}, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already being modified', result.stderr)
        with store.case_lock(self.case):
            pass

    def test_legacy_store_command_obeys_writer_lock(self):
        with store.case_lock(self.case):
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/case_store.py'), 'identifier',
                                     str(self.case), 'username', 'bob'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.case / 'case.json').exists())

    def test_missing_tool_does_not_block_other_tools(self):
        tools = [self.fake_tool('missing', 'print("bad")'), self.fake_tool('working', 'print("ok")')]
        with patch.dict(runner.TOOLS, {t.name: t for t in tools}, clear=True), \
             patch.object(runner.shutil, 'which', side_effect=lambda name: None if name == 'missing' else sys.executable):
            runner.run_targets(self.case, [{'type': 'username', 'value': 'alice'}])
        self.assertEqual([s['status'] for s in store.load(self.case)['scans']], ['unavailable', 'completed'])

    def test_invalid_target_creates_no_scans(self):
        for value in ('--help', '', 'name\nother'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.run_targets(self.case, [{'type': 'username', 'value': value}])
        self.assertFalse((self.case / 'case.json').exists())

    def test_each_attempt_keeps_its_own_side_files(self):
        tool = self.fake_tool('example', "from pathlib import Path; Path('side.txt').write_text('saved')")
        self.run_tools([tool])
        data = self.run_tools([tool], rerun=True)
        self.assertNotEqual(data['scans'][0].get('artifact_dir'), data['scans'][1].get('artifact_dir'))
        for scan in data['scans']:
            self.assertEqual((self.case / scan['artifact_dir'] / 'side.txt').read_text(), 'saved')

    def test_maigret_structured_report_retains_profile_fields(self):
        report = {'Example': {'status': {'status': 'Claimed', 'url': 'https://example.org/alice',
                  'ids': {'fullname': 'Alice Example', 'image': 'https://images.example.org/a.jpg', 'email': 'contact@example.org'}}},
                  'Absent': {'status': {'status': 'Available', 'url': 'https://absent.org/alice', 'ids': {}}}}
        code = f"import pathlib,json; pathlib.Path('report_alice_simple.json').write_text({json.dumps(json.dumps(report))}); print('no terminal account lines')"
        from dataclasses import replace
        tool = replace(runner.TOOLS['maigret'], arguments=lambda item: ['-u', '-c', code])
        data = self.run_tools([tool])
        self.assertEqual([a['url'] for a in data['accounts']], ['https://example.org/alice'])
        fields = data['accounts'][0]['observations'][0]['fields']
        self.assertEqual(fields['fullname'], 'Alice Example')
        self.assertEqual(fields['image'], 'https://images.example.org/a.jpg')
        self.assertIn('contact@example.org', [i['value'] for i in data['identifiers']])
        self.assertTrue((self.case / data['scans'][0]['structured_output']).is_file())

    def test_resume_finishes_pending_parse_without_repeating_execution(self):
        tool = self.fake_tool('example', 'print("[+] Example: https://example.org/alice")')
        data = self.run_tools([tool])
        data['scans'][0]['parse_status'] = 'pending'
        data['accounts'] = []
        data['relationships'] = []
        store.save(self.case, data)
        with patch.dict(runner.TOOLS, {'example': tool}, clear=True):
            runner.resume_case(self.case)
        resumed = store.load(self.case)
        self.assertEqual(len(resumed['scans']), 1)
        self.assertEqual(resumed['scans'][0]['parse_status'], 'completed')
        self.assertEqual(resumed['accounts'][0]['url'], 'https://example.org/alice')

    def test_reparse_removes_obsolete_derived_leads_but_keeps_supplied_inputs(self):
        tool = self.fake_tool('example', 'print("[+] Example: https://example.org/alice\\nusername: oldlead\\nusername: both")')
        self.run_tools([tool])
        store.add_identifier(self.case, 'username', 'supplied')
        store.add_identifier(self.case, 'username', 'both')
        from dataclasses import replace
        with patch.dict(runner.TOOLS, {'example': replace(tool, parse=lambda data, scan, content: None)}, clear=True):
            runner.reparse_case(self.case)
        data = store.load(self.case)
        self.assertEqual({i['value'] for i in data['identifiers']}, {'alice', 'supplied', 'both'})
        self.assertEqual(data['accounts'], [])

    def test_resume_rejects_scan_id_path_traversal(self):
        tool = self.fake_tool('example', 'print("ok")')
        data = self.run_tools([tool])
        data['scans'][0].update(id='../../outside', status='pending', output='new.txt')
        store.save(self.case, data)
        with patch.dict(runner.TOOLS, {'example': tool}, clear=True), self.assertRaises(ValueError):
            runner.resume_case(self.case)
        self.assertFalse((self.case.parent / 'outside').exists())

    def test_resume_recovers_unregistered_report_copy_from_original(self):
        report = {'Example': {'status': {'status': 'Claimed', 'url': 'https://example.org/alice', 'ids': {}}}}
        from dataclasses import replace
        code = f"import pathlib; pathlib.Path('report_alice_simple.json').write_text({json.dumps(json.dumps(report))})"
        tool = replace(runner.TOOLS['maigret'], arguments=lambda item: ['-u', '-c', code])
        data = self.run_tools([tool])
        scan = data['scans'][0]
        (self.case / scan.pop('structured_output')).write_text('{')
        scan['parse_status'] = 'pending'
        data['accounts'] = []
        data['relationships'] = []
        store.save(self.case, data)
        with patch.dict(runner.TOOLS, {'maigret': tool}, clear=True):
            runner.resume_case(self.case)
        recovered = store.load(self.case)
        self.assertEqual(recovered['scans'][0]['parse_status'], 'completed')
        self.assertEqual(recovered['accounts'][0]['url'], 'https://example.org/alice')


if __name__ == '__main__':
    unittest.main()
