"""Offline report regressions using synthetic case snapshots."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import case_store as store
from report import export_report


class ReportTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.case = Path(tmp.name) / 'case'
        self.case.mkdir()
        self.data = store.load(self.case)

    def report(self):
        store.save(self.case, self.data)
        with patch('socket.getaddrinfo', side_effect=AssertionError('network forbidden')), \
                patch('socket.create_connection', side_effect=AssertionError('network forbidden')), \
                patch('subprocess.Popen', side_effect=AssertionError('subprocess forbidden')):
            path = export_report(self.case)
        self.assertEqual(path.parent, self.case.resolve())
        self.assertRegex(path.name, r'^report-.*\.html$')
        return path.read_text(encoding='utf-8')

    def test_report_escapes_input_and_preserves_manifest(self):
        raw = self.case / 'raw #.txt'
        raw.write_bytes(b'evidence')
        self.data['people'] = [{'name': '<script>unsafe()</script>', 'inputs': []}]
        self.data['scans'] = [{'id': 'scan1', 'tool': 'tool', 'status': 'completed', 'output': raw.name}]
        html = self.report()
        self.assertIn('&lt;script&gt;unsafe()', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertIn('href="./raw%20%23.txt"', html)
        self.assertIn(hashlib.sha256(b'evidence').hexdigest(), html)
        self.assertIn(hashlib.sha256((self.case / 'case.json').read_bytes()).hexdigest(), html)
        self.assertIn('@media print', html)

    def test_unsafe_missing_and_changed_artifacts(self):
        outside = self.case.parent / 'private.txt'
        outside.write_bytes(b'private')
        alias = self.case / 'alias.txt'
        try:
            alias.symlink_to(outside)
        except OSError:
            self.skipTest('symlinks unavailable')
        (self.case / 'changed.txt').write_bytes(b'new')
        self.data['scans'] = [
            {'id': str(i), 'tool': 'tool', 'status': 'completed', 'output': name}
            for i, name in enumerate(('alias.txt', '../private.txt', 'missing.txt', 'changed.txt'))
        ]
        self.data['scans'][-1]['reviews'] = [{
            'status': 'completed', 'file_hashes': {'output': hashlib.sha256(b'old').hexdigest()},
            'result': {'summary': 'Old analysis'},
        }]
        html = self.report()
        self.assertNotIn('href="./alias.txt"', html)
        self.assertNotIn('href="./../private.txt"', html)
        self.assertNotIn('href="./missing.txt"', html)
        self.assertNotIn(hashlib.sha256(b'private').hexdigest(), html)
        self.assertIn('Missing', html)
        self.assertIn('Changed', html)
        self.assertIn('Stale', html)

    def test_coverage_and_historical_assessments(self):
        self.data['evidence'] = [{'id': key, 'kind': 'account', 'value': key} for key in ('e1', 'e2')]
        self.data['scans'] = [
            {'id': 'first', 'tool': 'one', 'status': 'completed', 'reviews': [{
                'status': 'completed', 'result': {'decision': 'pause', 'triage': [
                    {'evidence_id': 'e1', 'label': 'uncertain', 'rationale': 'Reason', 'evidence_ids': ['e1']},
                ], 'suggested_checks': ['Compare archived profiles']},
            }]},
            {'id': 'second', 'tool': 'two', 'status': 'failed', 'reviews': [
                {'status': 'failed', 'error': 'Review unavailable'},
            ]},
        ]
        self.data['cluster_reviews'] = [{'status': 'stale', 'result': {'groups': [{
            'member_ids': ['candidate'], 'supporting_evidence_ids': ['e1'],
            'contradicting_evidence_ids': ['e2'], 'rationale': 'Possible match',
        }]}}]
        html = self.report()
        for phrase in ('1 reviewed', '1 unreviewed', 'Reason', 'Compare archived profiles', 'Paused',
                       'Review unavailable', 'Stale', 'Possible match', 'Conflicting evidence'):
            self.assertIn(phrase, html)

    def test_partial_batch_is_visible_and_new_account_makes_cluster_stale(self):
        self.data['accounts'] = [{'id': 'new-account', 'site': 'new site'}]
        self.data['scans'] = [{
            'id': 'partial', 'tool': 'tool', 'status': 'completed', 'reviews': [{
                'status': 'budget_limited', 'coverage': {'reviewed': 1, 'total': 2},
                'batches': [{'result': {'summary': 'Only the first batch was reviewed'}}],
            }],
        }]
        self.data['cluster_reviews'] = [{
            'status': 'completed', 'manifest': {'accounts': [], 'evidence': [], 'file_hashes': {}},
            'result': {'groups': [], 'unassigned_ids': []},
        }]
        html = self.report()
        self.assertIn('Partial review', html)
        self.assertIn('Only the first batch was reviewed', html)
        self.assertIn('1 of 2 triage items', html)
        self.assertIn('Stale. Groups', html)

    def test_honors_case_writer_lock(self):
        store.save(self.case, self.data)
        with store.case_lock(self.case), self.assertRaisesRegex(ValueError, 'already being modified'):
            export_report(self.case)
        self.assertEqual(list(self.case.glob('report-*.html')), [])

    def test_account_scan_and_identifier_citations_are_links(self):
        self.data['identifiers'] = [{'id': 'target', 'type': 'username', 'value': 'alice'}]
        self.data['accounts'] = [{'id': 'account', 'site': 'Example', 'url': 'https://example.org/alice'}]
        self.data['scans'] = [{'id': 'scan', 'tool': 'example', 'status': 'completed', 'reviews': [{
            'status': 'completed', 'result': {'findings': [{'severity': 'info', 'description': 'Synthetic',
                                                          'evidence_ids': ['account', 'scan', 'target']}]}}]}]
        html = self.report()
        for kind in ('account', 'scan', 'identifier'):
            self.assertIn(f'href="#{kind}-0"', html)
            self.assertIn(f'id="{kind}-0"', html)

    def test_changed_case_context_marks_review_stale_without_network(self):
        import llm_review
        self.data['identifiers'] = [{'id': 'target', 'type': 'username', 'value': 'alice'}]
        self.data['review_policy'] = {'provider': 'openai', 'model': 'test', 'timeout': 2}
        (self.case / 'raw.txt').write_text('Synthetic', encoding='utf-8')
        scan = {'id': 'scan', 'target': 'target', 'tool': 'example', 'status': 'completed', 'output': 'raw.txt'}
        self.data['scans'] = [scan]
        _, fingerprint, _, hashes = llm_review.review_input(self.case, self.data, scan)
        scan['reviews'] = [{'status': 'completed', 'input_hash': fingerprint, 'file_hashes': hashes,
                            'result': {'summary': 'Old interpretation'}}]
        self.data['people'] = [{'name': 'Updated context', 'inputs': []}]
        html = self.report()
        self.assertIn('Stale', html)
        self.assertIn('0 scans with completed review', html)


if __name__ == '__main__':
    unittest.main()
