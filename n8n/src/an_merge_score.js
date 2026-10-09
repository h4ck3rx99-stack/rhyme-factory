// MERGE & SCORE — per-video stats rows + new category weights for topic selection.
// Weight = 0.6 x (median views vs channel median) + 0.4 x (retention vs channel average),
// smoothed 50/50 with the old weight, clamped to 0.5..2.5. Categories with < 2 mature videos get 1.2
// (exploration bonus) so the channel keeps trying new things instead of collapsing onto one topic.
const cfg = $('Analytics Config').first().json.cfg;
const stats = {};
for (const it of $('Video Stats').all()) for (const v of it.json.items || []) stats[v.id] = v.statistics || {};
const table = (item) => {
  const j = item?.json || {};
  if (!j.columnHeaders) return {};
  const names = j.columnHeaders.map((c) => c.name);
  const out = {};
  for (const row of j.rows || []) { const o = {}; names.forEach((n, i) => { o[n] = row[i]; }); out[o.video] = o; }
  return out;
};
let an = {};
let ctr = {};
try { an = table($('Analytics Report').first()); } catch (e) { an = {}; }
try { ctr = table($('CTR Report').first()); } catch (e) { ctr = {}; }

const rows = $('Read Videos').all().map((i) => i.json).filter((r) => r.youtube_id && stats[r.youtube_id]);
const now = new Date().toISOString();
const items = [];
const perVideo = {};
for (const r of rows) {
  const s = stats[r.youtube_id];
  const a = an[r.youtube_id] || {};
  const c = ctr[r.youtube_id] || {};
  const v = {
    kind: 'video', video_id: r.video_id,
    views: Number(s.viewCount || 0), likes: Number(s.likeCount || 0), comments: Number(s.commentCount || 0),
    watch_time_min: a.estimatedMinutesWatched ?? '', avg_view_duration_s: a.averageViewDuration ?? '',
    avg_view_pct: a.averageViewPercentage ?? '', subs_gained: a.subscribersGained ?? '',
    impressions: c.videoThumbnailImpressions ?? '', ctr: c.videoThumbnailImpressionsClickRate ?? '',
    analytics_updated_at: now,
  };
  perVideo[r.video_id] = v;
  items.push({ json: v });
}

const median = (arr) => { const s = [...arr].sort((x, y) => x - y); if (!s.length) return 0; const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const mature = rows.filter((r) => Date.now() - new Date(r.publish_at || r.upload_date || r.created_at).getTime() > 7 * 86400000);
const byCat = {};
for (const r of mature) (byCat[r.category] ||= []).push(perVideo[r.video_id]);
const all = Object.values(byCat).flat();
const medViews = Math.max(1, median(all.map((v) => v.views)));
const pcts = all.map((v) => Number(v.avg_view_pct)).filter((n) => n > 0);
const avgPct = pcts.length ? pcts.reduce((x, y) => x + y, 0) / pcts.length : 0;
const oldW = {};
try { for (const i of $('Read Weights').all()) if (i.json.category) oldW[i.json.category] = Number(i.json.weight) || 1; } catch (e) { /* first run */ }

for (const cat of cfg.categories) {
  const vids = byCat[cat] || [];
  let computed = 1.2;
  let note = 'exploring: fewer than 2 videos older than 7 days';
  if (vids.length >= 2) {
    const viewRatio = median(vids.map((v) => v.views)) / medViews;
    const catPct = vids.map((v) => Number(v.avg_view_pct) || 0).reduce((x, y) => x + y, 0) / vids.length;
    const retRatio = avgPct ? catPct / avgPct : 1;
    computed = 0.6 * viewRatio + 0.4 * retRatio;
    note = `views x${viewRatio.toFixed(2)} vs channel median, retention x${retRatio.toFixed(2)} vs channel average`;
  }
  const weight = Math.min(2.5, Math.max(0.5, 0.5 * (oldW[cat] ?? 1) + 0.5 * computed));
  items.push({ json: { kind: 'weight', category: cat, weight: Math.round(weight * 100) / 100, videos: vids.length, median_views: median(vids.map((v) => v.views)), note, updated_at: now } });
}
return items;
