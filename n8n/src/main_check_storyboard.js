// CHECK STORYBOARD — maps scenes to global lyric lines, enforces coverage + enums, and BUILDS every
// image prompt from the shared style bible + character bible (deterministic consistency).
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const sb = pkg.storyboard;
const song = pkg.song;
const cfg = pkg.cfg;
const attempt = $runIndex;
const MAX_RUNS = 4;
const CAMERA = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down', 'static'];
const TRANS = ['fade', 'dissolve', 'slideleft', 'slideright', 'wipeleft', 'wiperight', 'circleopen', 'smoothleft', 'smoothright', 'radial'];
const SFX = ['splash', 'pop', 'boing', 'chime', 'whoosh', 'giggle', 'clap', 'bell', 'footsteps', 'bird_chirp', 'rain_light', 'wind_soft', 'car_horn_toy', 'train_toot', 'animal_moo', 'animal_quack', 'animal_roar_cute', 'drum_roll', 'ding', 'snore'];
const problems = [];
const fixes = [];
const clean = (s, max = 30) => String(s || '').replace(/[\r\n"]+/g, ' ').replace(/\s+/g, ' ').trim().split(' ').slice(0, max).join(' ');

// global line index
const flat = [];
const secIndex = {};
for (const s of song.sections) {
  secIndex[s.section_id] = { start: flat.length, len: s.lines.length };
  s.lines.forEach((t, li) => flat.push({ gi: flat.length, section_id: s.section_id, li, text: t }));
}
const bible = Object.fromEntries(song.characters.map((c) => [c.char_id, c]));
const mainId = (song.characters.find((c) => c.role === 'main') || song.characters[0]).char_id;

let scenes = [];
for (const sc of sb.scenes || []) {
  const key = Object.keys(secIndex).find((k) => k === sc.section_id) ||
    Object.keys(secIndex).find((k) => k.replace(/_/g, '') === String(sc.section_id).toLowerCase().replace(/[^a-z0-9]/g, ''));
  if (!key) { fixes.push('dropped scenes with unknown section ids'); continue; }
  const sec = secIndex[key];
  const gl = [...new Set((sc.line_indices || []).map(Number).filter((n) => Number.isInteger(n) && n >= 0 && n < sec.len))]
    .sort((a, b) => a - b).map((n) => sec.start + n);
  if (!gl.length) { fixes.push('dropped scenes without valid lines'); continue; }
  const ids = (sc.char_ids || []).filter((id) => bible[id]).slice(0, 2);
  if (ids.length !== (sc.char_ids || []).length) fixes.push('removed unknown character ids');
  scenes.push({
    lines: gl, char_ids: ids, setting: clean(sc.setting, 18), action: clean(sc.action, 22), expression: clean(sc.expression, 8),
    framing: ['wide shot', 'medium shot', 'close-up'].includes(sc.framing) ? sc.framing : 'medium shot',
    camera: CAMERA.includes(sc.camera) ? sc.camera : 'zoom_in',
    transition: TRANS.includes(sc.transition) ? sc.transition : 'fade',
    sfx: (sc.sfx || []).filter((f) => SFX.includes(f.name)).slice(0, 1).map((f) => ({ name: f.name, at: f.at === 'middle' ? 'middle' : 'start' })),
  });
}
scenes.sort((a, b) => a.lines[0] - b.lines[0]);

// coverage: every lyric line must be inside some scene
const covered = new Set(scenes.flatMap((s) => s.lines));
const missing = flat.filter((l) => !covered.has(l.gi)).map((l) => l.gi);
if (missing.length > Math.max(3, Math.floor(flat.length * 0.2))) {
  problems.push(`scenes leave ${missing.length} lyric lines uncovered (e.g. section ${flat[missing[0]].section_id} line ${flat[missing[0]].li})`);
} else if (missing.length && scenes.length) {
  for (const gi of missing) {
    const host = [...scenes].reverse().find((s) => s.lines[0] <= gi) || scenes[0];
    host.lines = [...host.lines, gi].sort((a, b) => a - b);
  }
  fixes.push(`attached ${missing.length} uncovered lines to neighbouring scenes`);
}
if (scenes.length < 10) problems.push(`only ${scenes.length} usable scenes; make 14-32`);
if (scenes.length > 40) problems.push(`${scenes.length} scenes is too many; make 14-32`);
const withMain = scenes.filter((s) => s.char_ids.includes(mainId)).length;
if (scenes.length && withMain / scenes.length < 0.4) problems.push('the main character should appear in most scenes');

// prompts: style bible + character short tags + scene description
const style = cfg.style_bible.positive;
const tags = (ids) => ids.map((id) => bible[id].short_tag).join(' and ');
const build = (...parts) => parts.filter((p) => p && String(p).trim()).join(', ').replace(/\s+/g, ' ');
scenes = scenes.map((s, i) => ({
  ...s, scene_id: i + 1,
  prompt: build(style, s.framing, tags(s.char_ids), s.action, s.expression && `${s.expression} expression`, s.setting),
}));
const card = (c, fallbackAction, extra) => {
  const ids = ((c && c.char_ids) || []).filter((id) => bible[id]).slice(0, 2);
  const useIds = ids.length ? ids : [mainId];
  return { char_ids: useIds, prompt: build(style, 'wide shot', tags(useIds), clean(c?.action, 20) || fallbackAction, clean(c?.setting, 16), extra) };
};
const th = sb.thumbnail || {};
const side = th.text_side === 'right' ? 'right' : 'left';
const thumbText = clean(String(th.text || song.title).replace(/[^\p{L}\p{N}!?' ]/gu, ''), 4);
pkg.render_scenes = scenes;
pkg.cards = {
  title_card: card(sb.title_card, 'waving hello happily at the viewer', 'empty space at the top of the picture'),
  outro_card: card(sb.outro_card, 'waving goodbye happily', 'empty space at the top of the picture'),
  thumbnail: {
    char_ids: [mainId], text: thumbText, text_side: side,
    prompt: build(style, 'close-up', tags([mainId]), clean(th.action, 16), `${clean(th.expression, 6) || 'big happy'} expression`,
      clean(th.background, 10) || 'plain bright sky blue background', `character placed on the ${side === 'left' ? 'right' : 'left'} side`, 'simple composition'),
  },
};
const list = [...new Set(problems)].slice(0, 6);
const route = list.length === 0 ? 'ok' : (attempt < MAX_RUNS - 1 ? 'retry' : 'fail');
pkg.checks.storyboard = { attempt: attempt + 1, problems: list, fixes: [...new Set(fixes)], scenes: scenes.length };
return [{
  json: {
    pkg, route, route_index: { ok: 0, retry: 1, fail: 2 }[route],
    fail_reason: route === 'fail' ? `${pkg.video_id} | storyboard rejected after ${attempt + 1} checks: ${list.join('; ')}` : '',
    feedback: list.length ? `Your previous storyboard was rejected. Fix ALL of these:\n- ${list.join('\n- ')}` : '',
  },
}];
