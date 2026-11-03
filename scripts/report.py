"""Export a local, printable snapshot without running tools or model reviews."""
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path, PureWindowsPath
from urllib.parse import quote

from case_store import case_lock


def text(value):
    return escape(str(value), quote=True)


def items(rows):
    return '<ul>' + ''.join(f'<li>{row}</li>' for row in rows) + '</ul>'


def fields(entry, keys):
    return ' · '.join(f'{text(key.replace("_", " ").capitalize())} {text(entry[key])}'
                      for key in keys if entry.get(key) is not None)


def artifact_hash(case, name):
    # Reject Windows drive paths and separators even when exporting on Linux.
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or '\x00' in name or any(part in ('', '.', '..') for part in name.split('/'))
            or PureWindowsPath(name).drive):
        return 'Unsafe path', None
    path = case / name
    if path.suffix.lower() not in ('.txt', '.json') or name == 'case.json':
        return 'Unsafe path', None
    try:
        if path.resolve() != path:
            return 'Unsafe path', None
        if not path.is_file():
            return 'Missing', None
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                digest.update(chunk)
        return 'Available', digest.hexdigest()
    except (OSError, RuntimeError, ValueError):
        return 'Unavailable', None


def artifact_records(case, data):
    expected = {}
    scans = {scan['id']: scan for scan in data.get('scans', [])}
    for scan in scans.values():
        review = latest(scan.get('reviews', []))
        for key in ('output', 'structured_output'):
            if name := scan.get(key):
                expected.setdefault(name, set())
        for name, checksum in review_artifacts(review, scan, scans):
            if name:
                expected.setdefault(name, set()).add(checksum)
    for evidence in data.get('evidence', []):
        if name := evidence.get('filename'):
            hashes = expected.setdefault(name, set())
            if checksum := evidence.get('artifact_sha256'):
                hashes.add(checksum)
    cluster = latest(data.get('cluster_reviews', []))
    for name, checksum in cluster.get('manifest', {}).get('file_hashes', {}).items():
        expected.setdefault(name, set()).add(checksum)
    return {name: (*artifact_hash(case, name), hashes) for name, hashes in expected.items()}


def latest(entries):
    return entries[-1] if entries else {}


def review_artifacts(review, scan, scans):
    for key, checksum in review.get('file_hashes', {}).items():
        scan_id, separator, role = key.partition(':')
        source = scans.get(scan_id, {}) if separator else scan
        yield source.get(role if separator else key), checksum


def references(ids, prefix, known):
    return ', '.join(f'<a href="#{prefix}-{known[value]}">{text(value)}</a>'
                     if value in known else text(value) for value in ids) or 'None recorded'


def citation_links(ids, targets):
    return ', '.join(f'<a href="#{targets[value]}">{text(value)}</a>'
                     if value in targets else text(value) for value in ids) or 'None recorded'


def review_result(review):
    if 'result' in review:
        return review['result']
    batches = [batch['result'] for batch in review.get('batches', [])]
    return {
        'summary': ' '.join(batch.get('summary', '') for batch in batches),
        'decision': 'pause' if any(batch.get('decision') == 'pause' for batch in batches) else '',
        **{key: [item for batch in batches for item in batch.get(key, [])]
           for key in ('triage', 'findings', 'suggested_checks')},
    }


def render(data, generated, snapshot_hash, artifacts, stale_reviews=()):
    scans = data.get('scans', [])
    evidence = data.get('evidence', [])
    accounts = data.get('accounts', [])
    identifiers = {item['id']: item for item in data.get('identifiers', [])}
    evidence_ids = {item['id']: index for index, item in enumerate(evidence)}
    account_ids = {item['id']: index for index, item in enumerate(accounts)}
    scan_ids = {item['id']: index for index, item in enumerate(scans)}
    identifier_ids = {value: index for index, value in enumerate(identifiers)}
    citation_targets = {value: f'{kind}-{index}'
                        for kind, ids in (('identifier', identifier_ids), ('scan', scan_ids),
                                          ('account', account_ids), ('evidence', evidence_ids))
                        for value, index in ids.items()}
    scan_by_id = {scan['id']: scan for scan in scans}
    reviewed_ids = set()
    assessments = []
    completed_reviews = 0
    for scan in scans:
        review = latest(scan.get('reviews', []))
        result = review_result(review)
        status = review.get('status', 'unreviewed')
        if scan['id'] in stale_reviews:
            status = 'stale'
        if any(
            artifacts.get(name, (None, None))[1] != checksum
            for name, checksum in review_artifacts(review, scan, scan_by_id)
        ):
            status = 'stale'
        coverage = review.get('coverage', {})
        if status == 'completed' and coverage.get('reviewed', 0) < coverage.get('total', 0):
            status = 'partial'
        if status == 'completed':
            completed_reviews += 1
        if status != 'stale':
            reviewed_ids.update(item.get('evidence_id') for item in result.get('triage', []))
        triage = []
        for item in result.get('triage', []):
            source = citation_links([item.get('evidence_id', '')], citation_targets)
            cited = citation_links(item.get('evidence_ids', []), citation_targets)
            triage.append(f'{source} · {fields(item, ("label", "rationale"))} · Sources {cited}')
        for item in result.get('findings', []):
            cited = citation_links(item.get('evidence_ids', []), citation_targets)
            triage.append(f'{fields(item, ("severity", "description"))} · Sources {cited}')
        decision = ''
        if result.get('decision') == 'pause':
            approval = review.get('approval')
            decision = f'<p>Paused. Manual approval {fields(approval, ("created_at", "note"))}.</p>' if approval else '<p>Paused pending manual approval.</p>'
        checks = result.get('suggested_checks', [])
        coverage_text = 'Review coverage details unavailable.'
        if 'total' in coverage:
            coverage_text = f'{text(coverage.get("reviewed", 0))} of {text(coverage["total"])} triage items. '
            if coverage.get('reviewed', 0) < coverage['total']:
                coverage_text += 'Partial review. '
            coverage_text += text(coverage.get('note', ''))
        elif coverage:
            coverage_text = fields(coverage, ('included_accounts', 'reported_accounts', 'note'))
        assessments.append(
            f'<h3>{text(scan.get("tool", ""))} · {text(scan["id"])} · {text(status.replace("_", " ").capitalize())}</h3>'
            f'<p>{fields(review, ("created_at", "input_hash", "error"))}</p>'
            f'{decision}<p>{text(result.get("summary", ""))}</p>'
            f'<p>{coverage_text}</p>'
            f'{items(triage)}<h4>Suggested manual checks</h4>{items(map(text, checks))}'
        )
    reviewed_count = len(reviewed_ids & evidence_ids.keys())
    cluster = latest(data.get('cluster_reviews', []))
    cluster_status = cluster.get('status', 'unreviewed')
    cluster_result = cluster.get('result', {
        'groups': [group for batch in cluster.get('batches', []) for group in batch['result'].get('groups', [])],
    })
    cluster_manifest = cluster.get('manifest', {})
    if cluster_manifest:
        cluster_inputs = {'accounts': accounts, 'evidence': evidence, 'policy': data.get('review_policy')}
        cluster_files = {name for scan in scans if scan.get('status') not in ('pending', 'running')
                         and not scan.get('parent_scan') for name in (scan.get('output'), scan.get('structured_output'))
                         if name}
        if (any(key in cluster_manifest and cluster_manifest[key] != value for key, value in cluster_inputs.items())
                or ('file_hashes' in cluster_manifest and cluster_files != cluster_manifest['file_hashes'].keys())
                or any(artifacts[name][1] != checksum for name, checksum in cluster_manifest.get('file_hashes', {}).items())):
            cluster_status = 'stale'
    groups = []
    for group in cluster_result.get('groups', []):
        members = references(group.get('member_ids', []), 'account', account_ids)
        supporting = citation_links(group.get('supporting_evidence_ids', []), citation_targets)
        conflicting = citation_links(group.get('contradicting_evidence_ids', []), citation_targets)
        groups.append(f'Candidate accounts {members}<p>{text(group.get("rationale", ""))}</p>'
                      f'<p>Supporting evidence {supporting}</p><p>Conflicting evidence {conflicting}</p>')
    manifest = []
    for index, (name, (status, checksum, expected)) in enumerate(artifacts.items()):
        source = text(name)
        if checksum:
            source = f'<a href="./{quote(name)}">{source}</a>'
            if expected and expected != {checksum}:
                status = 'Changed'
        recorded = ', '.join(sorted(expected)) or 'Unavailable'
        manifest.append(f'<li id="artifact-{index}">{source} · {status} · '
                        f'Export SHA-256 {checksum or "Unavailable"} · Recorded SHA-256 {text(recorded)}</li>')
    artifact_ids = {name: index for index, name in enumerate(artifacts)}

    def source_files(names):
        return references((name for name in names if name), 'artifact', artifact_ids)

    people = [f'{text(person.get("name", ""))} · {text(person.get("id", ""))}'
              + items(fields(entry, ('type', 'value', 'source', 'notes', 'country_code'))
                      for entry in person.get('inputs', [])) for person in data.get('people', [])]
    supplied = items(fields(item, ('id', 'type', 'value')) for item in identifiers.values() if item.get('supplied'))
    identifiers_html = ''.join(
        f'<li id="identifier-{index}">{fields(item, ("id", "type", "value"))}</li>'
        for index, item in enumerate(identifiers.values())
    )
    relationships = items(fields(item, ('from', 'to', 'label', 'source')) for item in data.get('person_relationships', []))
    scans_html = ''.join(
        f'<li id="scan-{index}">'
        + fields(scan, ('id', 'tool', 'status', 'parse_status', 'error', 'parse_error', 'parent_scan'))
        + f' · Input {fields(scan.get("input", identifiers.get(scan.get("target"), {})), ("type", "value"))}'
        + f' · Sources {source_files((scan.get("output"), scan.get("structured_output")))}'
        + (items(fields(check, ('site', 'status')) for check in scan['checks']) if scan.get('checks') else '')
        + '</li>'
        for index, scan in enumerate(scans)
    )
    evidence_html = ''.join(
        f'<li id="evidence-{index}">{fields(item, ("id", "kind", "value", "line", "end_line", "field", "scan_id"))}'
        f' · Source {source_files((item.get("filename"),))}</li>'
        for index, item in enumerate(evidence)
    )
    accounts_html = ''.join(
        f'<li id="account-{index}">{fields(item, ("id", "site", "url"))}'
        + items(references([observation['scan_id']], 'scan', scan_ids) + ' · ' + fields(observation, ('fields',))
                for observation in item.get('observations', []))
        + '</li>' for index, item in enumerate(accounts)
    )
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><title>Investigation brief</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 70rem; margin: 2rem auto; padding: 0 1rem; overflow-wrap: anywhere; }}
@media print {{ body {{ max-width: none; margin: 0; padding: 0; }} h2, h3 {{ break-after: avoid; }} }}
</style>
<h1>Investigation brief</h1>
<p>Case {text(data.get("id", ""))} · Exported {text(generated)}</p>
<h2>Supplied people and inputs</h2>{items(people)}{supplied}{relationships}
<h2>Tool execution coverage</h2><p>{len(scans)} recorded scans.</p><ul>{scans_html}</ul>
<h2>Saved observations</h2>
<p>These extracted observations are unverified leads.</p><ul>{evidence_html}</ul><ul>{accounts_html}</ul>
<h3>Recorded identifiers</h3><ul>{identifiers_html}</ul>
<h2>Model assessments</h2>
<p>{completed_reviews} scans with completed review. Evidence triage coverage: {reviewed_count} reviewed,
{len(evidence_ids) - reviewed_count} unreviewed. Stale assessments are historical. Review may cover only part of the saved evidence.</p>
{''.join(assessments)}
<h2>Candidate groups and conflicting evidence</h2>
<p>{text(cluster_status.replace("_", " ").capitalize())}. Groups are hypotheses for manual verification.</p>
<p>{fields(cluster, ("created_at", "input_hash", "error"))}</p>
<p>{fields(cluster.get("coverage", {}), ("reviewed", "total"))}</p>
<p>{'Comparison coverage limited: additional candidate pairs were not examined.' if cluster.get('coverage', {}).get('selection_limited') else ''}</p>
{items(groups)}
<p>Unassigned accounts {references(cluster_result.get("unassigned_ids", []), "account", account_ids)}</p>
<h2>Snapshot manifest</h2>
<p>case.json SHA-256 {snapshot_hash}</p>
<p>Hashes help detect changes to saved files. They cannot establish the truth of source claims.
Links open the saved artifacts beside this report.</p>
<ul>{''.join(manifest)}</ul>
<p>Clustering manifest {fields(cluster_manifest, ("version",))} ·
{len(cluster_manifest.get("accounts", []))} accounts · {len(cluster_manifest.get("evidence", []))} evidence records.</p>
</html>
'''


def export_report(case: Path) -> Path:
    case = case.resolve()
    snapshot = case / 'case.json'
    if not snapshot.is_file() or snapshot.resolve() != snapshot:
        raise ValueError('Expected a saved case.json in the case directory')
    with case_lock(case):
        raw = snapshot.read_bytes()
        data = json.loads(raw)
        stale_reviews = set()
        if data.get('review_policy'):
            # Fingerprinting is local and never calls the API or requires credentials.
            from llm_review import review_input
            for scan in data.get('scans', []):
                review = latest(scan.get('reviews', []))
                if not review.get('input_hash'):
                    continue
                try:
                    _, fingerprint, _, _ = review_input(case, data, scan)
                    if review['input_hash'] != fingerprint:
                        stale_reviews.add(scan['id'])
                except (OSError, ValueError, KeyError, StopIteration):
                    stale_reviews.add(scan['id'])
        generated = datetime.now(timezone.utc)
        output = case / f'report-{generated:%Y%m%dT%H%M%S%fZ}.html'
        document = render(data, generated.isoformat(), hashlib.sha256(raw).hexdigest(), artifact_records(case, data), stale_reviews)
        with tempfile.NamedTemporaryFile(dir=case, prefix='.report-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
        try:
            temporary.write_text(document, encoding='utf-8')
            temporary.replace(output)
        finally:
            temporary.unlink(missing_ok=True)
    return output
