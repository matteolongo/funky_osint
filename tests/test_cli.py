import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name)

    def cli(self, *args, input=''):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/osint_cli.py'), *args],
                              input=input, capture_output=True, text=True,
                              env={**os.environ, 'WORKSPACE': str(self.workspace), 'PATH': ''}, timeout=15)

    def test_batch_exits_without_prompt_and_records_missing_tools(self):
        result = self.cli('alice', '--batch')
        self.assertEqual(result.returncode, 0, result.stderr)
        case = next(self.workspace.glob('osint-*/case.json'))
        data = json.loads(case.read_text())
        self.assertEqual([s['status'] for s in data['scans']], ['unavailable', 'unavailable'])
        self.assertEqual((case.parent / 'target_username.txt').read_text().strip(), 'alice')

    def test_reparse_never_runs_tools_or_creates_new_case(self):
        self.assertEqual(self.cli('alice', '--batch').returncode, 0)
        case = next(self.workspace.glob('osint-*/case.json'))
        before = json.loads(case.read_text())
        result = self.cli('--reparse', str(case.parent))
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads(case.read_text())
        self.assertEqual([s['id'] for s in after['scans']], [s['id'] for s in before['scans']])
        self.assertEqual(len(list(self.workspace.glob('osint-*'))), 1)

    def test_resume_keeps_supplied_people(self):
        intake = self.workspace / 'intake.json'
        intake.write_text(json.dumps({'people': [{'name': 'Alice', 'inputs': [{'type': 'username', 'value': 'alice'}]}]}))
        self.assertEqual(self.cli('--case', str(intake), '--batch').returncode, 0)
        case = next(self.workspace.glob('osint-*/case.json'))
        before = json.loads(case.read_text())
        result = self.cli('--resume', str(case.parent), '--batch')
        self.assertEqual(result.returncode, 0, result.stderr)
        after = json.loads(case.read_text())
        self.assertEqual(after['people'], before['people'])
        self.assertEqual(len(after['scans']), 4)

    def test_invalid_input_does_not_create_case(self):
        result = self.cli('invalid name', '--batch')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(self.workspace.glob('osint-*')), [])

    def test_review_requires_key_before_creating_case(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            result = self.cli('alice', '--review', '--batch')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('OPENAI_API_KEY', result.stderr)
        self.assertEqual(list(self.workspace.glob('osint-*')), [])


if __name__ == '__main__':
    unittest.main()
