// QC GATE — turns the AI reviewer's scores into a decision.
// Routes: 0 pass, 1 revise song, 2 revise storyboard, 3 revise metadata, 4 fail. Max 3 review rounds.
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const qc = pkg.qc;
const round = $runIndex; // 0-based review round in this execution
const MAX_ROUNDS = 3;

const scores = qc.scores || {};
const values = Object.values(scores).map(Number).filter((n) => !Number.isNaN(n));
const core = Object.entries(scores).filter(([k]) => k !== 'algorithm_fit').map(([, v]) => Number(v)).filter((n) => !Number.isNaN(n));
const min = core.length ? Math.min(...core) : 0;
const algoOk = scores.algorithm_fit === undefined || Number(scores.algorithm_fit) >= 6;
const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0;
const blockers = (qc.issues || []).filter((i) => i.severity === 'blocker');
const passed = qc.verdict === 'pass' && min >= 7 && algoOk && Number(scores.child_safety) >= 9 && blockers.length === 0 && !qc.resembles_existing_work;

let route;
if (passed) route = 'pass';
else if (qc.verdict === 'reject' || round >= MAX_ROUNDS - 1) route = 'fail';
else {
  const rank = { blocker: 3, major: 2, minor: 1 };
  const worst = [...(qc.issues || [])].sort((a, b) => (rank[b.severity] || 0) - (rank[a.severity] || 0))[0];
  route = worst?.component || { revise_song: 'song', revise_storyboard: 'storyboard', revise_metadata: 'metadata' }[qc.verdict] || 'song';
  if (qc.resembles_existing_work) route = 'song';
}
const relevant = (qc.issues || []).filter((i) => route === 'song' || i.component === route);
const feedback = relevant.length
  ? `A reviewer found these problems. Fix ALL of them and keep everything else that works:\n${relevant.map((i) => `- [${i.severity}] ${i.problem} -> fix: ${i.fix}`).join('\n')}`
  : '';
pkg.quality_score = Math.round(avg * 10) / 10;
pkg.checks.qc = { round: round + 1, min_score: min, algorithm_fit: scores.algorithm_fit, verdict: qc.verdict, blockers: blockers.length, summary: qc.summary };
const failText = blockers.concat(qc.issues || []).slice(0, 3).map((i) => i.problem).join('; ');
return [{
  json: {
    pkg, route, feedback,
    route_index: { pass: 0, song: 1, storyboard: 2, metadata: 3, fail: 4 }[route],
    fail_reason: route === 'fail' ? `${pkg.video_id} | content QC failed after ${round + 1} review(s): ${failText || qc.summary}` : '',
  },
}];
