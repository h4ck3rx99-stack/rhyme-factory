// BUILD RENDER JOB — converts the approved package into the helper's job.json (VIDEO schema).
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const cfg = pkg.cfg;
const song = pkg.song;
const fnv1a = (s) => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; } return h; };

pkg.retry_count = Math.max(0, (pkg.llm_log || []).length - 5); // 5 = one call per stage when nothing fails
const job = {
  video_id: pkg.video_id,
  channel_name: cfg.channel_name,
  title: song.title || pkg.idea.title,
  style_bible: cfg.style_bible,
  characters: song.characters.map((c) => ({
    char_id: c.char_id, name: c.name, species: c.species, short_tag: c.short_tag,
    visual_prompt: c.visual_prompt, seed: fnv1a(c.char_id) % 2147483647,
  })),
  song: {
    sections: song.sections.map((s) => ({ section_id: s.section_id, type: s.type, lines: s.lines })),
    music: {
      caption: song.music.caption, bpm: song.music.bpm, key: song.music.key || 'C Major',
      time_signature: String(song.music.time_signature || '4'), target_duration_s: cfg.target_duration_s,
    },
  },
  voice: { hook_text: song.voice.hook_text, outro_text: song.voice.outro_text, voice: cfg.voice },
  scenes: pkg.render_scenes.map((s) => ({
    scene_id: s.scene_id, lines: s.lines, char_ids: s.char_ids, camera: s.camera,
    transition: s.transition, sfx: s.sfx, prompt: s.prompt,
  })),
  title_card: pkg.cards.title_card,
  outro_card: pkg.cards.outro_card,
  thumbnail: pkg.cards.thumbnail,
  render: { width: 1920, height: 1080, fps: 30, transition_s: 0.5, title_card_s: cfg.title_card_s ?? 3.0, outro_s: 5.0, min_duration_s: cfg.min_duration_s, max_duration_s: cfg.max_duration_s },
  qc: { min_intelligibility: cfg.min_intelligibility, max_song_attempts: 3, max_image_attempts: 2 },
};
return [{ json: { pkg, job } }];
