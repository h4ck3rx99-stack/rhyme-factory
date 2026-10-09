// CHECK IDEA — duplicate + originality gate for the concept. Routes: 0 ok, 1 retry, 2 fail.
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const idea = pkg.idea;
const attempt = $runIndex; // how many ideas were already checked in this execution
const MAX_RETRIES = 2;

const STOP = new Set(['the', 'a', 'an', 'and', 'of', 'for', 'to', 'in', 'on', 'with', 'song', 'rhyme', 'nursery', 'kids', 'little', 'my', 'our', 'is', 'are', 'at', 'by']);
const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
const normTitle = (s) => norm(s).split(' ').filter((w) => w && !STOP.has(w)).join(' ');
const grams = (s, n = 3) => { const t = ` ${s} `; const out = new Set(); for (let i = 0; i + n <= t.length; i++) out.add(t.slice(i, i + n)); return out; };
const jaccard = (a, b) => { if (!a.size || !b.size) return 0; let n = 0; for (const x of a) if (b.has(x)) n++; return n / (a.size + b.size - n); };
const fnv1a = (s) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16).padStart(8, '0'); };
const kw = (arr) => new Set((arr || []).map((x) => norm(x)).filter(Boolean));
const FAMOUS = ['twinkle twinkle', 'wheels on the bus', 'baby shark', 'old macdonald', 'mary had a little lamb', 'humpty dumpty', 'itsy bitsy spider', 'incy wincy', 'row row row your boat', 'jack and jill', 'hickory dickory', 'london bridge', 'baa baa black sheep', 'five little monkeys', 'head shoulders knees', 'happy and you know it', 'johny johny', 'rain rain go away', 'hey diddle diddle', 'little miss muffet', 'pat a cake', 'ring around the rosie', 'this old man', 'farmer in the dell', 'old king cole', 'little bo peep', 'three blind mice', 'hot cross buns', 'ten in the bed', 'five little ducks', 'ants go marching', 'little teapot', 'muffin man', 'pop goes the weasel', 'bluey', 'peppa', 'cocomelon', 'paw patrol', 'pinkfong', 'super simple songs', 'little baby bum', 'blippi', 'disney', 'pixar', 'frozen', 'mickey', 'minnie', 'elsa', 'pokemon', 'pikachu', 'sesame street', 'elmo', 'barney', 'teletubbies', 'spongebob', 'winnie the pooh', 'paddington', 'thomas the tank', 'hello kitty', 'minions', 'gabby'];

let hist = [];
try { hist = $('Read History').all().map((i) => i.json).filter((r) => r.video_id && r.status !== 'failed'); } catch (e) { hist = []; }
const problems = [];
const tNorm = normTitle(idea.title);
const tGrams = grams(tNorm);
const kwSet = kw(idea.concept_keywords);
const species = norm(idea.main_character?.species);
const conceptHash = fnv1a([norm(idea.category), ...[...kwSet].sort(), species].join('|'));

for (const r of hist) {
  const rt = String(r.title_norm || normTitle(r.title));
  if (rt && (rt === tNorm || jaccard(grams(rt), tGrams) >= 0.6)) problems.push(`the title is too similar to our existing video "${r.title}"`);
  if (r.concept_hash && r.concept_hash === conceptHash) problems.push(`the concept is identical to "${r.title}"`);
  const rk = kw(String(r.concept_keywords || '').split(','));
  if (rk.size >= 3 && norm(r.category) === norm(idea.category) && jaccard(rk, kwSet) >= 0.6) problems.push(`the concept keywords overlap heavily with "${r.title}"`);
}
const text = ` ${norm(`${idea.title} ${idea.premise} ${idea.main_character?.name} ${idea.search_phrase}`)} `;
const phraseWords = norm(idea.search_phrase).split(' ').filter(Boolean);
if (phraseWords.length < 2 || phraseWords.length > 6) problems.push('search_phrase must be a real 2-5 word phrase a parent would type');
for (const f of FAMOUS) if (text.includes(` ${f} `)) problems.push(`it refers to an existing song or brand ("${f}")`);
if (!idea.main_character?.reuse_star && (pkg.plan.banned_species ?? []).includes(species)) problems.push(`the species "${species}" was used too often recently`);
if (pkg.plan.star && idea.main_character?.reuse_star && norm(idea.main_character.name) !== norm(pkg.plan.star.name)) problems.push(`reuse_star is true but the name is not "${pkg.plan.star.name}"`);
if (!pkg.cfg.categories.includes(idea.category)) idea.category = pkg.plan.category; // auto-fix

const list = [...new Set(problems)].slice(0, 6);
const route = list.length === 0 ? 'ok' : (attempt < MAX_RETRIES ? 'retry' : 'fail');
pkg.hash = { ...pkg.hash, title_norm: tNorm, concept_hash: conceptHash };
pkg.checks.idea = { attempt: attempt + 1, problems: list };
return [{
  json: {
    pkg, route, route_index: { ok: 0, retry: 1, fail: 2 }[route],
    fail_reason: route === 'fail' ? `${pkg.video_id} | idea rejected after ${attempt + 1} attempts: ${list.join('; ')}` : '',
    feedback: list.length ? `The previous idea "${idea.title}" was rejected because ${list.join('; ')}. Propose a clearly different idea.` : '',
  },
}];
