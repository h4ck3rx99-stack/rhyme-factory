// CHECK SONG — structure, safety words, copying from famous rhymes, near-duplicates of our own songs,
// character bible clean-up. Auto-fixes small things; routes 0 ok, 1 retry, 2 fail.
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const song = pkg.song;
const attempt = $runIndex; // counts every song check in this execution (incl. QC revisions)
const MAX_RUNS = 4;

const norm = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[’']/g, '').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
const ngrams = (s, n) => { const w = norm(s).split(' ').filter(Boolean); const out = new Set(); for (let i = 0; i + n <= w.length; i++) out.add(w.slice(i, i + n).join(' ')); return out; };
const jaccard = (a, b) => { if (!a.size || !b.size) return 0; let n = 0; for (const x of a) if (b.has(x)) n++; return n / (a.size + b.size - n); };
const fnv1a = (s) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h.toString(16).padStart(8, '0'); };
const slug = (s) => norm(s).replace(/ /g, '_').slice(0, 40);
const problems = [];
const fixes = [];

// --- structure -------------------------------------------------------------
const secs = (song.sections || []).filter((s) => Array.isArray(s.lines) && s.lines.some((l) => String(l).trim()));
const seenIds = {};
secs.forEach((s, i) => {
  s.lines = s.lines.map((l) => String(l).replace(/\s+/g, ' ').trim()).filter(Boolean);
  let id = slug(s.section_id) || `section_${i + 1}`;
  if (seenIds[id]) { seenIds[id] += 1; id = `${id}_${seenIds[id]}`; fixes.push('renamed duplicate section ids'); } else seenIds[id] = 1;
  s.section_id = id;
});
const choruses = secs.filter((s) => s.type === 'chorus');
if (choruses.length < 2) problems.push('the chorus must appear at least twice, identical each time');
else {
  for (const c of choruses.slice(1)) {
    if (JSON.stringify(c.lines) !== JSON.stringify(choruses[0].lines)) { c.lines = [...choruses[0].lines]; fixes.push('made every chorus identical'); }
  }
}
const lines = secs.flatMap((s) => s.lines);
if (lines.length < 16 || lines.length > 40) problems.push(`the song has ${lines.length} lines; write 18-36`);
const tooLong = lines.filter((l) => l.split(' ').length > 11);
if (tooLong.length) problems.push(`these lines are too long to sing (max 9-10 words): ${tooLong.slice(0, 3).map((l) => `"${l}"`).join(', ')}`);

// --- toddler-safety vocabulary ------------------------------------------------
const BANNED = ['kill', 'killed', 'kills', 'die', 'dies', 'died', 'dead', 'death', 'blood', 'bloody', 'gun', 'guns', 'knife', 'knives', 'sword', 'hate', 'stupid', 'idiot', 'dumb', 'shut up', 'ugly', 'fat', 'beer', 'wine', 'cigarette', 'drunk', 'sexy', 'scary', 'monster', 'ghost', 'devil', 'hell', 'poop', 'fart', 'vomit', 'candy reward'];
const hay = ` ${norm(lines.join(' '))} `;
const hits = BANNED.filter((w) => hay.includes(` ${w} `));
if (hits.length) problems.push(`remove words unsuitable for toddlers: ${hits.join(', ')}`);

// --- copying from well-known rhymes (any 4 consecutive words) --------------------
const FAMOUS_LINES = ['twinkle twinkle little star how i wonder what you are', 'up above the world so high like a diamond in the sky', 'the wheels on the bus go round and round', 'old macdonald had a farm e i e i o', 'row row row your boat gently down the stream', 'merrily merrily merrily merrily life is but a dream', 'mary had a little lamb its fleece was white as snow', 'humpty dumpty sat on a wall humpty dumpty had a great fall', 'the itsy bitsy spider climbed up the water spout', 'jack and jill went up the hill to fetch a pail of water', 'hickory dickory dock the mouse ran up the clock', 'london bridge is falling down my fair lady', 'baa baa black sheep have you any wool', 'five little monkeys jumping on the bed', 'head shoulders knees and toes', 'if youre happy and you know it clap your hands', 'johny johny yes papa eating sugar no papa', 'rain rain go away come again another day', 'hey diddle diddle the cat and the fiddle the cow jumped over the moon', 'baby shark doo doo doo doo doo doo', 'im a little teapot short and stout', 'the ants go marching one by one hurrah hurrah', 'this old man he played one he played knick knack on my thumb', 'pat a cake pat a cake bakers man', 'ring around the rosie a pocket full of posies', 'three blind mice see how they run', 'hot cross buns one a penny two a penny', 'little bo peep has lost her sheep', 'the farmer in the dell', 'pop goes the weasel', 'do your ears hang low', 'five little ducks went out one day over the hill and far away', 'there were ten in the bed and the little one said roll over', 'do you know the muffin man who lives on drury lane', 'you are my sunshine my only sunshine', 'happy birthday to you', 'the more we get together together together', 'this is the way we wash our hands', 'where is thumbkin where is thumbkin', 'are you sleeping are you sleeping brother john morning bells are ringing', 'one two buckle my shoe three four shut the door', 'the grand old duke of york he had ten thousand men', 'sing a song of sixpence a pocket full of rye', 'polly put the kettle on', 'it is raining it is pouring the old man is snoring', 'teddy bear teddy bear turn around', 'the bear went over the mountain to see what he could see', 'down by the bay where the watermelons grow', 'skinnamarink a dink a dink skinnamarink a doo'];
const famous4 = new Set();
FAMOUS_LINES.forEach((l) => ngrams(l, 4).forEach((g) => famous4.add(g)));
const copied = lines.filter((l) => [...ngrams(l, 4)].some((g) => famous4.has(g)));
if (copied.length) problems.push(`these lines are too close to existing nursery rhymes - rewrite them: ${copied.slice(0, 3).map((l) => `"${l}"`).join(', ')}`);

// --- near-identical to our own earlier songs -------------------------------------
let hist = [];
try { hist = $('Read History').all().map((i) => i.json).filter((r) => r.video_id && r.lyrics && r.status !== 'failed'); } catch (e) { hist = []; }
const mine = ngrams(lines.join(' '), 3);
let worst = { sim: 0, title: '' };
for (const r of hist) {
  const sim = jaccard(mine, ngrams(String(r.lyrics).replace(/\[[^\]]*\]/g, ' '), 3));
  if (sim > worst.sim) worst = { sim, title: r.title };
}
if (worst.sim >= 0.25) problems.push(`the lyrics are ${Math.round(worst.sim * 100)}% similar to our earlier song "${worst.title}" - write new lines`);

// --- character bible -------------------------------------------------------------
const FRANCHISE = ['mickey', 'minnie', 'elsa', 'olaf', 'simba', 'nemo', 'dory', 'pooh', 'tigger', 'peppa', 'bluey', 'bingo heeler', 'chase', 'marshall', 'pikachu', 'elmo', 'barney', 'spongebob', 'thomas', 'cocomelon', 'blippi', 'hello kitty', 'paddington', 'shrek', 'minion', 'stitch', 'moana', 'baby shark'];
let chars = (song.characters || []).slice(0, 3);
if (!chars.length) problems.push('define at least one character in the character bible');
const usedIds = new Set();
chars.forEach((c, i) => {
  let id = slug(c.char_id || c.name) || `char_${i + 1}`;
  while (usedIds.has(id)) id = `${id}_${i + 1}`;
  usedIds.add(id);
  c.char_id = id;
  if (FRANCHISE.includes(norm(c.name))) problems.push(`the character name "${c.name}" belongs to an existing franchise`);
  const words = String(c.visual_prompt || '').split(/\s+/);
  if (words.length > 40) { c.visual_prompt = words.slice(0, 40).join(' '); fixes.push('shortened a visual_prompt'); }
  if (!c.short_tag) c.short_tag = `${c.species}`;
  if (!['main', 'friend'].includes(c.role)) c.role = i === 0 ? 'main' : 'friend';
});
if (chars.length && !chars.some((c) => c.role === 'main')) chars[0].role = 'main';
const star = pkg.plan.star;
if (star && pkg.idea?.main_character?.reuse_star) { // recurring star: stored bible always wins
  const idx = chars.findIndex((c) => norm(c.name) === norm(star.name));
  const fixed = { ...(chars[idx] || {}), char_id: star.char_id, name: star.name, species: star.species, visual_prompt: star.visual_prompt, short_tag: star.short_tag, personality: star.personality || chars[idx]?.personality || '', role: 'main' };
  if (idx >= 0) chars[idx] = fixed; else chars = [fixed, ...chars].slice(0, 3);
  chars.forEach((c) => { if (c.char_id !== star.char_id) c.role = 'friend'; });
  fixes.push('applied the recurring star bible');
}
for (const member of pkg.cfg.cast || []) { // recurring friends also keep their stored bible
  const idx = chars.findIndex((c) => norm(c.name) === norm(member.name) || c.char_id === member.char_id);
  if (idx >= 0 && chars[idx].char_id !== star?.char_id) {
    chars[idx] = { ...chars[idx], char_id: member.char_id, name: member.name, species: member.species, visual_prompt: member.visual_prompt, short_tag: member.short_tag, personality: chars[idx].personality || member.personality };
    fixes.push(`applied the stored bible for ${member.name}`);
  }
}
song.sections = secs;
song.characters = chars;

// --- music + voice sanity ------------------------------------------------------
song.music = song.music || {};
song.music.bpm = Math.min(126, Math.max(90, parseInt(song.music.bpm, 10) || 108));
if (!['3', '4'].includes(String(song.music.time_signature))) song.music.time_signature = '4';
song.music.caption = String(song.music.caption || 'cheerful children\'s song, bright friendly female vocal, ukulele, glockenspiel, hand claps').slice(0, 300);
song.voice = song.voice || {};

pkg.lyrics_text = secs.map((s) => `[${s.section_id}]\n${s.lines.join('\n')}`).join('\n\n');
pkg.hash.lyrics_hash = fnv1a(norm(lines.join(' ')));
const list = [...new Set(problems)].slice(0, 6);
const route = list.length === 0 ? 'ok' : (attempt < MAX_RUNS - 1 ? 'retry' : 'fail');
pkg.checks.song = { attempt: attempt + 1, problems: list, fixes: [...new Set(fixes)], similarity_to_own: Math.round(worst.sim * 100) / 100 };
return [{
  json: {
    pkg, route, route_index: { ok: 0, retry: 1, fail: 2 }[route],
    fail_reason: route === 'fail' ? `${pkg.video_id} | song rejected after ${attempt + 1} checks: ${list.join('; ')}` : '',
    feedback: list.length ? `Your previous song was rejected. Fix ALL of these and keep everything else that worked:\n- ${list.join('\n- ')}` : '',
  },
}];
