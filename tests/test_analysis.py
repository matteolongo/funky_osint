"""Synthetic candidate evidence only; executed by CI."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import analysis
import case_store as store
import llm_review


def account(id, **fields):
    return {'id': id, 'url': f'https://{id}.example/alice', 'site': id,
            'observations': [{'scan_id': 'scan', 'fields': fields}]}


class AnalysisTests(unittest.TestCase):
    def fixture(self, accounts):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        case = Path(temporary.name)
        (case / 'scan.txt').write_text('synthetic evidence', encoding='utf-8')
        data = {'accounts': accounts, 'identifiers': [], 'relationships': [],
                'scans': [{'id': 'scan', 'status': 'completed', 'output': 'scan.txt'}],
                'review_policy': {'provider': 'openai', 'model': 'test', 'timeout': 2}}
        store.save(case, data)
        return case

    def test_reused_handle_alone_does_not_generate_candidate(self):
        self.assertEqual(analysis.candidates([account('a', username='alice'), account('b', username='alice')]), [])

    def test_explicit_profile_link_and_shared_email_are_candidates(self):
        accounts = [account('a', website='https://b.example/alice'), account('b'),
                    account('c', email='Team@EXAMPLE.org'), account('d', email='Team@example.org')]
        pairs = analysis.candidates(accounts)
        self.assertEqual({tuple(p['member_ids']) for p in pairs}, {('a', 'b'), ('c', 'd')})

    def test_unknown_members_and_uncited_groups_rejected(self):
        for result in ({'groups': [{'member_ids': ['a', 'x'], 'supporting_evidence_ids': ['a'],
                                    'contradicting_evidence_ids': [], 'rationale': 'link'}], 'unassigned_ids': []},
                       {'groups': [{'member_ids': ['a', 'b'], 'supporting_evidence_ids': [],
                                    'contradicting_evidence_ids': [], 'rationale': 'link'}], 'unassigned_ids': []}):
            with self.assertRaises(ValueError):
                analysis.validate_result(result, {'a', 'b'}, {'a', 'b'})

    def test_budget_resume_caches_completed_pairs_and_does_not_change_accounts(self):
        accounts = [account(x, email='shared@example.org') for x in ('a', 'b', 'c')]
        case = self.fixture(accounts)

        def reply(payload, policy, ids, **kwargs):
            members = payload['candidate']['member_ids']
            result = {'groups': [], 'unassigned_ids': members}
            return kwargs['validator'](result, ids), 'synthetic', {}

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'fake', 'OPENAI_REVIEW_MAX_REQUESTS': '1'}), \
             patch.object(llm_review, 'request_review', side_effect=reply) as request:
            for _ in range(2):
                with self.assertRaises(llm_review.ReviewBlocked):
                    analysis.review_clusters(case)
            analysis.review_clusters(case)
            analysis.review_clusters(case)
        data = store.load(case)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(data['accounts'], accounts)
        self.assertEqual(data['cluster_reviews'][-1]['status'], 'completed')
        self.assertEqual(data['cluster_reviews'][-1]['result']['unassigned_ids'], ['a', 'b', 'c'])

    def test_changed_artifact_invalidates_cluster_offline(self):
        case = self.fixture([account('a')])
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'}):
            analysis.review_clusters(case)
        (case / 'scan.txt').write_text('changed', encoding='utf-8')
        with patch.object(llm_review, 'request_review', side_effect=AssertionError('must remain offline')):
            analysis.invalidate_clusters(case)
        self.assertEqual(store.load(case)['cluster_reviews'][-1]['status'], 'stale')

    def test_duplicate_reports_do_not_create_extra_candidate_votes(self):
        a = account('a', website='https://b.example/alice')
        a['observations'].append({'scan_id': 'other-tool', 'fields': dict(a['observations'][0]['fields'])})
        pairs = analysis.candidates([a, account('b')])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(pairs[0]['signals']), 1)

    def test_common_location_limits_comparisons_without_losing_accounts(self):
        accounts = [account(str(i), location='Example City') for i in range(70)]
        coverage = {}
        with patch.object(analysis, 'MAX_PAIRS', 3):
            pairs = analysis.candidates(accounts, coverage)
        self.assertEqual(len(pairs), 3)
        self.assertTrue(coverage['selection_limited'])
        self.assertEqual(len(accounts), 70)

    def test_large_candidate_context_is_bounded_and_cites_actual_records(self):
        accounts = [account(x, **{f'field{i}': 'x' * 5000 for i in range(40)}) for x in ('a', 'b')]
        records = [{'id': f'{a}-{i}', 'account_id': a, 'value': 'x' * 5000} for a in ('a', 'b') for i in range(40)]
        payload, ids = analysis.comparison_input({'accounts': accounts, 'evidence': records},
                                                {'member_ids': ['a', 'b'], 'signals': []})
        self.assertLessEqual(llm_review.input_size(payload), llm_review.MAX_INPUT_BYTES)
        self.assertNotIn('a', ids)
        self.assertNotIn('b', ids)
        self.assertEqual({e['account_id'] for e in payload['evidence']}, {'a', 'b'})

    def test_parse_marks_previous_clusters_stale_in_saved_snapshot(self):
        from adapters import TOOLS
        case = self.fixture([])
        data = store.load(case)
        data['identifiers'] = [{'id': 'target', 'type': 'username', 'value': 'alice'}]
        data['scans'][0].update(tool='sherlock', target='target')
        data['cluster_reviews'] = [{'status': 'completed', 'result': {'groups': []}}]
        store.save(case, data)
        (case / 'scan.txt').write_text('[+] Example: https://example.org/alice', encoding='utf-8')
        store.parse_scan(case, 'scan', TOOLS['sherlock'])
        self.assertEqual(store.load(case)['cluster_reviews'][-1]['status'], 'stale')

    def test_cluster_failure_blocks_next_tool_and_resume_keeps_completed_scan(self):
        import case_runner as runner
        from adapters import Tool
        case = self.fixture([])
        data = store.load(case)
        data['scans'] = []
        store.save(case, data)

        def parse(data, scan, content):
            data['accounts'] = [account('a', email='shared@example.org'), account('b', email='shared@example.org')]
            for item in data['accounts']:
                item['observations'][0]['scan_id'] = scan['id']

        tools = {'first': Tool('first', 'username', lambda item: ['-c', 'print("synthetic")'], parse),
                 'second': Tool('second', 'username', lambda item: ['-c', 'print("synthetic")'], lambda *args: None)}
        fail = True

        def reply(payload, policy, ids, **kwargs):
            if 'candidate' in payload:
                if fail:
                    raise ValueError('synthetic unavailable API')
                return {'groups': [], 'unassigned_ids': payload['candidate']['member_ids']}, 'test', {}
            return {'decision': 'continue', 'summary': 'Synthetic review', 'findings': [], 'suggested_checks': [],
                    'triage': [{'evidence_id': item['id'], 'label': 'uncertain', 'rationale': 'Synthetic',
                                'evidence_ids': [item['id']]} for item in payload['triage_items']]}, 'test', {}

        with patch.dict('os.environ', {'OPENAI_API_KEY': 'fake'}), patch.dict(runner.TOOLS, tools, clear=True), \
             patch.object(runner.shutil, 'which', return_value=sys.executable), \
             patch.object(llm_review, 'request_review', side_effect=reply):
            with self.assertRaises(llm_review.ReviewBlocked):
                runner.run_targets(case, [{'type': 'username', 'value': 'alice'}])
            before = store.load(case)
            self.assertEqual([s['status'] for s in before['scans']], ['completed', 'pending'])
            fail = False
            runner.resume_case(case)
        after = store.load(case)
        self.assertEqual([s['id'] for s in after['scans']], [s['id'] for s in before['scans']])
        self.assertEqual([s['status'] for s in after['scans']], ['completed', 'completed'])


if __name__ == '__main__':
    unittest.main()
