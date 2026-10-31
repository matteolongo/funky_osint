"""A local fake API exercises the actual HTTP client; no investigation data is sent."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import case_runner as runner
import case_store as store
from adapters import Tool


class ReviewTests(unittest.TestCase):
    def setUp(self):
        import llm_review
        self.review = llm_review
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.case = Path(self.tmp.name) / 'osint-test'
        self.case.mkdir()
        self.requests = []
        self.responses = []
        test = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                test.requests.append(payload)
                response = test.responses.pop(0) if test.responses else {'decision': 'continue', 'summary': 'Synthetic results only.', 'findings': [], 'suggested_checks': []}
                if isinstance(response, int):
                    self.send_error(response)
                    return
                envelope = response.get('api_response', {'id': 'resp_test', 'status': 'completed', 'model': 'test-model',
                           'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(response)}]}]})
                body = json.dumps(envelope).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(patch.stopall)
        patch.object(llm_review, 'API_URL', f'http://127.0.0.1:{self.server.server_port}/v1/responses').start()
        patch.dict(os.environ, {'OPENAI_API_KEY': 'unit-test-secret'}).start()
        self.policy = {'provider': 'openai', 'model': 'test-model', 'timeout': 2}
        first = Tool('first', 'username', lambda item: ['-c', 'print("[+] Example: https://example.org/alice")'],
                     lambda data, scan, content: store.parse_accounts(data, scan, 'username', 'alice', content))
        second = Tool('second', 'username', lambda item: ['-c',
                      "import os,json,pathlib; d=json.loads((pathlib.Path(os.environ['OSINT_CASE_DIR'])/'case.json').read_text()); print(d['scans'][0]['reviews'][-1]['result']['decision']); print('key_leaked' if 'OPENAI_API_KEY' in os.environ else 'no_key')"],
                      lambda data, scan, content: None)
        patch.dict(runner.TOOLS, {'first': first, 'second': second}, clear=True).start()
        patch.object(runner.shutil, 'which', return_value=sys.executable).start()

    def run_case(self):
        runner.run_targets(self.case, [{'type': 'username', 'value': 'alice'}], review=self.policy)
        return store.load(self.case)

    def test_review_precedes_next_tool_and_key_is_not_in_child_or_case(self):
        data = self.run_case()
        output = (self.case / data['scans'][1]['output']).read_text()
        self.assertIn('continue', output)
        self.assertIn('no_key', output)
        self.assertNotIn('unit-test-secret', (self.case / 'case.json').read_text())
        self.assertEqual(len(self.requests), 2)
        self.assertFalse(self.requests[0]['store'])
        self.assertEqual(self.requests[0]['text']['format']['type'], 'json_schema')
        self.assertNotIn('tools', self.requests[0])

    def test_pause_blocks_resume_until_explicit_approval(self):
        self.responses.append({'decision': 'pause', 'summary': 'Needs manual review.', 'findings': [], 'suggested_checks': ['Check source.']})
        with self.assertRaises(self.review.ReviewBlocked):
            self.run_case()
        data = store.load(self.case)
        self.assertEqual([s['status'] for s in data['scans']], ['completed', 'pending'])
        with self.assertRaises(self.review.ReviewBlocked):
            runner.resume_case(self.case)
        self.assertEqual(len(self.requests), 1)
        self.review.approve_review(self.case, data['scans'][0]['id'], 'Source checked manually')
        runner.resume_case(self.case)
        result = store.load(self.case)
        self.assertEqual([s['status'] for s in result['scans']], ['completed', 'completed'])
        self.assertEqual(result['scans'][0]['reviews'][-1]['approval']['note'], 'Source checked manually')
        self.assertEqual(len(self.requests), 2)

    def test_api_error_preserves_output_and_resume_retries_only_review(self):
        self.responses.append(429)
        with self.assertRaises(self.review.ReviewBlocked):
            self.run_case()
        before = store.load(self.case)
        self.assertEqual(before['scans'][0]['reviews'][-1]['status'], 'failed')
        runner.resume_case(self.case)
        after = store.load(self.case)
        self.assertEqual([s['id'] for s in before['scans']], [s['id'] for s in after['scans']])
        self.assertEqual(len(after['scans'][0]['reviews']), 2)

    def test_invalid_response_cannot_approve_next_step(self):
        self.responses.append({'decision': 'continue', 'summary': 'Invented evidence.',
                               'findings': [{'severity': 'info', 'description': 'Claim', 'evidence_ids': ['invented']}],
                               'suggested_checks': []})
        with self.assertRaises(self.review.ReviewBlocked):
            self.run_case()
        data = store.load(self.case)
        self.assertEqual(data['scans'][1]['status'], 'pending')
        self.assertEqual(data['scans'][0]['reviews'][-1]['status'], 'failed')

    def test_completed_reviews_are_reused_but_changed_evidence_is_reviewed_again(self):
        self.run_case()
        runner.resume_case(self.case)
        self.assertEqual(len(self.requests), 2)
        data = store.load(self.case)
        (self.case / data['scans'][0]['output']).write_text('Changed saved evidence')
        runner.resume_case(self.case)
        self.assertGreater(len(self.requests), 2)

    def test_missing_key_blocks_before_starting_tools(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}), self.assertRaises(ValueError):
            self.run_case()
        self.assertFalse(list(self.case.glob('*.txt')))

    def test_refusal_or_incomplete_response_blocks_progress(self):
        for envelope in ([], {'status': 'completed', 'output': [None]}, {'status': 'incomplete', 'output': []},
                         {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'Cannot review'}]}]}):
            self.responses.append({'api_response': envelope})
            with self.assertRaises(self.review.ReviewBlocked):
                self.run_case()
            self.assertEqual(store.load(self.case)['scans'][1]['status'], 'pending')

    def test_interrupted_review_is_retried_on_resume(self):
        with patch.object(self.review, 'request_review', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.run_case()
        before = store.load(self.case)
        self.assertEqual(before['scans'][0]['reviews'][-1]['status'], 'interrupted')
        runner.resume_case(self.case)
        self.assertEqual(len(store.load(self.case)['scans']), 2)
        self.assertEqual(len(self.requests), 2)

    def test_manual_approval_is_invalid_after_evidence_changes(self):
        self.responses.append({'decision': 'pause', 'summary': 'Check source.', 'findings': [], 'suggested_checks': []})
        with self.assertRaises(self.review.ReviewBlocked):
            self.run_case()
        scan = store.load(self.case)['scans'][0]
        (self.case / scan['output']).write_text('changed')
        with self.assertRaises(ValueError):
            self.review.approve_review(self.case, scan['id'], 'Checked')

    def test_review_context_is_bounded_and_reports_coverage(self):
        self.run_case()
        data = store.load(self.case)
        data['accounts'] = [{'id': f'account-{i}', 'site': 'Example', 'url': f'https://example.org/{i}',
                             'observations': [{'scan_id': data['scans'][0]['id'],
                              'fields': {f'field-{j}': 'x' * 5000 for j in range(30)}}]} for i in range(60)]
        payload, _, ids = self.review.review_input(self.case, data, data['scans'][0])
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), self.review.MAX_INPUT_BYTES)
        self.assertEqual(payload['coverage']['reported_accounts'], 60)
        self.assertLess(payload['coverage']['included_accounts'], 60)
        self.assertTrue(all(a['id'] in ids for a in payload['accounts']))

    def test_offline_reparse_marks_changed_review_stale_without_api_call(self):
        self.run_case()
        data = store.load(self.case)
        (self.case / data['scans'][0]['output']).write_text('[+] Other: https://other.example/alice')
        runner.reparse_case(self.case)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(store.load(self.case)['scans'][0]['reviews'][-1]['status'], 'stale')

    def test_cli_pause_and_explicit_approval_use_saved_policy(self):
        self.responses.append({'decision': 'pause', 'summary': 'Check missing tools.', 'findings': [], 'suggested_checks': []})
        workspace = self.case.parent / 'cli-workspace'
        program = f"import sys; sys.path.insert(0, {str(ROOT / 'scripts')!r}); import llm_review, osint_cli; llm_review.API_URL={self.review.API_URL!r}; raise SystemExit(osint_cli.main(sys.argv[1:]))"
        env = {**os.environ, 'WORKSPACE': str(workspace), 'PATH': '', 'OPENAI_MODEL': 'test-model'}
        paused = subprocess.run([sys.executable, '-c', program, 'alice', '--review', '--batch'], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(paused.returncode, 3, paused.stderr)
        path = next(workspace.glob('osint-*/case.json'))
        data = json.loads(path.read_text())
        self.assertEqual(data['scans'][1]['status'], 'pending')
        resumed = subprocess.run([sys.executable, '-c', program, '--resume', str(path.parent), '--batch',
                                  '--approve-review', data['scans'][0]['id'], '--review-note', 'Checked tool availability'],
                                 env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        # Both CLI tools are unavailable in this fixture; resume also retries the first.
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(json.loads(path.read_text())['scans']), 3)


if __name__ == '__main__':
    unittest.main()
