// BUILD BATCHES — YouTube IDs from the Videos sheet, 50 per videos.list call (1 quota unit each).
const cfg = $('Analytics Config').first().json.cfg;
const rows = $('Read Videos').all().map((i) => i.json).filter((r) => r.youtube_id && r.status !== 'failed');
const ids = [...new Set(rows.map((r) => String(r.youtube_id).trim()).filter((id) => /^[A-Za-z0-9_-]{11}$/.test(id)))];
if (!ids.length) return []; // nothing published yet
const today = new Date().toISOString().slice(0, 10);
const out = [];
for (let i = 0; i < ids.length; i += 50) {
  out.push({ json: { ids: ids.slice(i, i + 50).join(','), all_ids: ids.slice(-200).join(','), start_date: cfg.channel_start_date, end_date: today } });
}
return out;
