// CHECK METADATA — enforces YouTube limits and honesty rules. Always auto-fixes; never fails.
const pkg = JSON.parse(JSON.stringify($input.first().json.pkg));
const md = pkg.metadata;
const strip = (s) => String(s || '').replace(/[<>]/g, '').replace(/\s+/g, ' ').trim();
const BRANDS = ['cocomelon', 'pinkfong', 'baby shark', 'bluey', 'peppa', 'disney', 'pixar', 'paw patrol', 'super simple', 'little baby bum', 'blippi', 'sesame', 'mickey', 'frozen', 'pokemon', 'chuchu', 'bebefinn', 'masha'];

let title = strip(md.title);
// de-shout: words of 4+ letters in ALL CAPS read as clickbait
title = title.split(' ').map((w) => (w.length > 3 && /[A-Z]/.test(w) && w === w.toUpperCase() ? w[0] + w.slice(1).toLowerCase() : w)).join(' ');
title = title.replace(/[!?]{2,}/g, '!');
if (BRANDS.some((b) => title.toLowerCase().includes(b))) title = pkg.song.title; // never borrow other brands
const phrase = String(pkg.idea?.search_phrase || '').trim();
const words = (s) => String(s).toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter((w) => w.length > 2);
const pw = words(phrase);
const covered = pw.filter((w) => words(title).includes(w)).length;
if (pw.length && covered / pw.length < 0.6) { // add the searchable phrase if the AI left it out
  const titleCase = phrase.replace(/\b\w/g, (c) => c.toUpperCase());
  const base = title.split(' | ')[0];
  if ((base + ' | ' + titleCase).length <= 90) title = `${base} | ${titleCase}`;
}
if (title.length > 100) title = title.slice(0, 97).replace(/\s+\S*$/, '') + '...';

let description = String(md.description || '').replace(/[<>]/g, '').replace(/https?:\/\/\S+/g, '').replace(/#\w+/g, '').trim();
if (description.length > 2500) description = description.slice(0, 2500).replace(/\s+\S*$/, '') + '...';

const tags = [];
let budget = 0; // YouTube: 500 characters for all tags; multi-word tags count their quotes
for (const raw of md.tags || []) {
  const t = strip(raw).toLowerCase().replace(/[,#"]/g, '');
  if (!t || t.length > 30 || tags.includes(t) || BRANDS.some((b) => t.includes(b))) continue;
  const cost = t.length + (t.includes(' ') ? 2 : 0) + 1;
  if (budget + cost > 450) break;
  tags.push(t);
  budget += cost;
}
const hashtags = (md.hashtags || []).map((h) => String(h).replace(/[^A-Za-z0-9]/g, '')).filter((h) => h && !BRANDS.some((b) => h.toLowerCase().includes(b.replace(/ /g, '')))).slice(0, 3);
pkg.metadata_final = { title, description, tags, hashtags };
return [{ json: { pkg, feedback: '' } }];
