"""Linux process-tree tests for the container runtime; no network requests."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'requires the Linux container runtime')
class SignalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'WORKSPACE': str(self.root / 'workspace'), 'PATH': f'{self.bin}:/usr/bin:/bin'}
        self.tool('sherlock', 'print("[+] Example: https://example.org/alice")')
        self.tool('maigret', 'import subprocess,sys,time,os\n'
                  'from pathlib import Path\n'
                  'child=subprocess.Popen([sys.executable,"-c","import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"])\n'
                  'Path(os.environ["WORKSPACE"]).joinpath("child.pid").write_text(str(child.pid))\n'
                  'print("partial", flush=True)\ntime.sleep(30)')

    def tool(self, name, code):
        path = self.bin / name
        path.write_text(f'#!{sys.executable}\n{code}\n')
        path.chmod(0o755)

    def launch(self, *args):
        process = subprocess.Popen([sys.executable, str(ROOT / 'scripts/osint_cli.py'), *args], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        return process

    def started(self):
        end = time.monotonic() + 10
        while time.monotonic() < end:
            paths = list((self.root / 'workspace').glob('osint-*/case.json'))
            if paths and (self.root / 'workspace/child.pid').exists():
                data = json.loads(paths[0].read_text())
                if data['scans'][0]['status'] == 'running':
                    return paths[0]
            time.sleep(0.05)
        self.fail('scan did not start')

    def assert_child_stopped(self):
        pid = int((self.root / 'workspace/child.pid').read_text())
        state = Path(f'/proc/{pid}/stat')
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if not state.exists() or state.read_text().split(') ', 1)[1].startswith('Z'):
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        self.fail('descendant process survived cancellation')

    def test_sigterm_preserves_partial_output_and_resume_runs_pending_tasks(self):
        process = self.launch('alice', '--batch')
        path = self.started()
        process.terminate()
        self.assertEqual(process.wait(timeout=8), 130)
        data = json.loads(path.read_text())
        self.assertEqual([s['status'] for s in data['scans']], ['interrupted', 'pending'])
        self.assertIn('partial', (path.parent / data['scans'][0]['output']).read_text())
        self.assert_child_stopped()
        self.tool('maigret', 'print("finished")')
        resumed = self.launch('--resume', str(path.parent), '--batch')
        self.assertEqual(resumed.wait(timeout=10), 0)
        self.assertEqual([s['status'] for s in json.loads(path.read_text())['scans']],
                         ['interrupted', 'completed', 'completed'])

    def test_timeout_stops_descendants_and_continues(self):
        process = self.launch('alice', '--batch', '--timeout', '1')
        path = self.started()
        self.assertEqual(process.wait(timeout=8), 0)
        self.assertEqual([s['status'] for s in json.loads(path.read_text())['scans']], ['timed_out', 'completed'])
        self.assert_child_stopped()

    def test_completed_tool_does_not_leave_background_children(self):
        path = self.bin / 'maigret'
        path.write_text(path.read_text().replace('\ntime.sleep(30)\n', '\n'))
        process = self.launch('alice', '--batch')
        self.assertEqual(process.wait(timeout=10), 0)
        self.assert_child_stopped()

    def test_resume_stops_processes_left_by_killed_runner(self):
        process = self.launch('alice', '--batch')
        path = self.started()
        process.kill()
        process.wait(timeout=5)
        self.tool('maigret', 'print("finished")')
        resumed = self.launch('--resume', str(path.parent), '--batch')
        self.assertEqual(resumed.wait(timeout=10), 0)
        self.assert_child_stopped()
        self.assertEqual([s['status'] for s in json.loads(path.read_text())['scans']],
                         ['interrupted', 'completed', 'completed'])


if __name__ == '__main__':
    unittest.main()
