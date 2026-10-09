// PLAN RUN — decides what to make: category (learned weights), recurring star or new character,
// and what must not be repeated. Returns NO items (= quiet stop) if another video is still in progress.
const cfg = $('Config').first().json.cfg;
const rows = (node) => {
  try { return $(node).all().map((i) => i.json).filter((r) => r && Object.keys(r).length); } catch (e) { return []; }
};
const history = rows('Read History').filter((r) => r.video_id);
const weightRows = rows('Read Topic Weights').filter((r) => r.category);
const stars = rows('Read Characters').filter((r) => r.char_id && String(r.recurring).toLowerCase() === 'yes');
const now = new Date();

// 1) Guard against overlapping runs (manual run + schedule, or a slow render)
const busy = history.find((r) => ['generating', 'rendering', 'uploading'].includes(r.status) &&
  now - new Date(r.created_at) < 6 * 3600 * 1000);
if (busy) return [];

// 2) Category: weighted random using weights written by the Analytics workflow
const weights = Object.fromEntries(cfg.categories.map((c) => [c, 1]));
for (const r of weightRows) {
  const w = Number(r.weight);
  if (r.category in weights && w > 0) weights[r.category] = Math.min(3, Math.max(0.4, w));
}
for (const c of history.slice(-3).map((r) => r.category)) if (c in weights) weights[c] *= 0.35; // variety
const learned = weightRows.length > 0;
const weightsNote = learned
  ? Object.entries(weights).sort((a, b) => b[1] - a[1]).map(([c, w]) => `${c} ${w.toFixed(2)}`).join(', ')
  : '';
let roll = Math.random() * Object.values(weights).reduce((a, b) => a + b, 0);
let category = cfg.categories[0];
for (const [c, w] of Object.entries(weights)) { roll -= w; if (roll <= 0) { category = c; break; } }

// 3) Recurring star (builds a recognisable cast) vs new character; block over-used species
const speciesCount = {};
for (const r of history.slice(-10)) {
  const s = String(r.main_species || '').toLowerCase().trim();
  if (s) speciesCount[s] = (speciesCount[s] || 0) + 1;
}
const bannedSpecies = Object.entries(speciesCount).filter(([, n]) => n >= 3).map(([s]) => s);
const recentIds = history.slice(-2).flatMap((r) => String(r.char_ids || '').split(',').map((s) => s.trim()));
const eligible = stars.filter((s) => !recentIds.includes(s.char_id));
let star = null;
if (eligible.length && Math.random() < Number(cfg.recurring_star_probability ?? 0.5)) {
  eligible.sort((a, b) => Number(a.appearances || 0) - Number(b.appearances || 0));
  const s = eligible[0];
  star = { char_id: s.char_id, name: s.name, species: s.species, short_tag: s.short_tag, visual_prompt: s.visual_prompt, personality: s.personality || '' };
}

// 4) Soft avoid-lists for the prompt (hard duplicate checks run after generation)
const done = history.filter((r) => r.status !== 'failed');
const month = now.toLocaleString('en-US', { month: 'long', timeZone: 'Asia/Kolkata' });
const season = ['winter', 'winter', 'spring', 'spring', 'spring', 'summer', 'summer', 'summer', 'autumn', 'autumn', 'autumn', 'winter'][now.getUTCMonth()];
const stamp = now.toISOString().slice(0, 10).replace(/-/g, '');
const rand = Array.from({ length: 4 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');

const pkg = {
  video_id: `NR-${stamp}-${rand}`,
  exec_id: String($execution.id),
  started_at: now.toISOString(),
  cfg,
  plan: {
    category, month, season, star,
    banned_species: bannedSpecies,
    avoid_titles: done.slice(-60).map((r) => r.title).filter(Boolean),
    avoid_concepts: done.slice(-40).map((r) => r.concept_keywords).filter(Boolean),
    target_duration_s: cfg.target_duration_s,
    weights_note: weightsNote,
  },
  hash: {},
  checks: {},
  llm_log: [],
};
return [{ json: { pkg, feedback: '' } }];
