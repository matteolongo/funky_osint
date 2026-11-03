const test = require('node:test');
const assert = require('node:assert/strict');
const {triageIndex, itemAssessment} = require('../dashboard/static/assessments.js');

test('stale assessment cannot filter current evidence as noise', () => {
  const c = {scans:[{reviews:[{status:'stale',result:{triage:[{evidence_id:'e',label:'likely_noise'}]}}]}]};
  assert.equal(triageIndex(c).has('e'), false);
});
test('validated partial batches are visible, omitted evidence stays unreviewed', () => {
  const c = {scans:[{reviews:[{status:'budget_limited',batches:[{result:{triage:[{evidence_id:'e',label:'relevant',rationale:'Explicit source'}]}}]}]}],
             evidence:[{id:'e',account_id:'a'},{id:'other',account_id:'b'}]};
  const index = triageIndex(c);
  assert.equal(itemAssessment(c,{id:'a'},index), 'relevant');
  assert.equal(itemAssessment(c,{id:'b'},index), 'unreviewed');
});
test('a partly unreviewed account is never hidden as likely noise', () => {
  const c = {scans:[], evidence:[{id:'e',account_id:'a'},{id:'pending',account_id:'a'}]};
  const index = new Map([['e',{label:'likely_noise'}]]);
  assert.equal(itemAssessment(c,{id:'a'},index), 'unreviewed');
});
