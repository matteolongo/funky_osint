/* Model assessments are a view over evidence, never mutations of evidence. */
function triageIndex(c) {
  const index = new Map();
  for (const scan of c.scans) {
    const review = scan.reviews?.at(-1);
    if (!review || review.status === 'stale') continue;
    const entries = review.result?.triage || (review.batches || []).flatMap(b => b.result.triage || []);
    for (const entry of entries) index.set(entry.evidence_id, entry);
  }
  return index;
}
function itemAssessment(c, item, index) {
  const records = (c.evidence || []).filter(e => e.account_id === item.id || e.identifier_id === item.id);
  const labels = records.length ? records.map(e => index.get(e.id)?.label || 'unreviewed') : [index.get(item.id)?.label || 'unreviewed'];
  for (const label of ['relevant', 'unreviewed', 'uncertain', 'likely_noise']) if (labels.includes(label)) return label;
  return 'unreviewed';
}
if (typeof module !== 'undefined') module.exports = {triageIndex, itemAssessment};
