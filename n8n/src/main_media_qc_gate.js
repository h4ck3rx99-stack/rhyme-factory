// MEDIA QC GATE — stops the run if the helper's file checks failed, then prepares upload metadata
// (description + chapters + lyrics + disclosure) and the publish slot. Routes: 0 outbox, 1 private, 2 scheduled.
const st = $input.first().json; // helper job status
const pkg = JSON.parse(JSON.stringify($('Build Render Job').first().json.pkg));
const cfg = pkg.cfg;
if (!st.media_qc || !st.media_qc.pass) {
  const bad = Object.entries(st.media_qc?.checks || {}).filter(([, v]) => !v.ok).map(([k, v]) => `${k}=${v.value} (expected ${v.expected})`);
  throw new Error(`${pkg.video_id} | media QC failed: ${bad.join('; ') || st.error || 'no QC result'}`);
}
const md = pkg.metadata_final;
const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const chapters = (st.timeline?.chapters || []).map((c) => `${mmss(c.t)} ${c.label}`).join('\n');
const seenChorus = new Set();
const lyrics = pkg.song.sections.map((s) => {
  if (s.type === 'chorus') {
    const key = s.lines.join('|');
    if (seenChorus.has(key)) return '(Chorus)';
    seenChorus.add(key);
  }
  return s.lines.join('\n');
}).join('\n\n');
const disclosure = `${cfg.channel_name} makes original sing-along songs for little ones. The song, lyrics and artwork were created for this channel with the help of AI tools.`;
let description = [md.description, chapters && `Chapters:\n${chapters}`, `Lyrics:\n${lyrics}`, disclosure, md.hashtags.map((h) => `#${h}`).join(' ')]
  .filter(Boolean).join('\n\n');
if (description.length > 4500) description = description.slice(0, 4500);

// next publish slot: configured weekday + UTC time, at least 2 hours ahead
const [hh, mi] = String(cfg.publish_time_utc || '12:00').split(':').map(Number);
const slot = new Date();
slot.setUTCHours(hh, mi, 0, 0);
while (slot.getTime() < Date.now() + 2 * 3600 * 1000 || !(cfg.publish_days_utc || [1, 3, 5]).includes(slot.getUTCDay())) {
  slot.setUTCDate(slot.getUTCDate() + 1);
}
const mode = ['manual_outbox', 'api_private', 'api_scheduled'].includes(cfg.upload_mode) ? cfg.upload_mode : 'manual_outbox';
const upload = {
  mode, title: md.title, description, tags: md.tags.join(','),
  category_id: String(cfg.category_id || '27'), region_code: cfg.region_code || 'IN', language: cfg.language || 'en',
  publish_at: slot.toISOString(),
  playlist_id: (cfg.playlist_ids || {})[(cfg.category_playlist || {})[pkg.idea.category]] || cfg.playlist_id || '',
  playlist_name: (cfg.category_playlist || {})[pkg.idea.category] || '',
};
return [{
  json: {
    pkg, upload,
    render: {
      duration_s: st.timeline?.duration_s, video_path: st.paths?.video, thumbnail_path: st.paths?.thumbnail,
      song_mode: st.song?.mode, intelligibility: st.song?.intelligibility,
    },
    route_index: { manual_outbox: 0, api_private: 1, api_scheduled: 2 }[mode],
  },
}];
