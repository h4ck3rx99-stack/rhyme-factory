// CHARACTER ROWS — one item per character for the Characters sheet (recurring cast memory).
const { pkg } = $input.first().json;
const existing = {};
try { for (const i of $('Read Characters').all()) if (i.json.char_id) existing[i.json.char_id] = i.json; } catch (e) { /* empty sheet */ }
return pkg.song.characters.map((c) => {
  const old = existing[c.char_id] || {};
  return {
    json: {
      char_id: c.char_id, name: c.name, species: c.species, short_tag: c.short_tag,
      visual_prompt: c.visual_prompt, personality: c.personality || '',
      recurring: old.recurring || (c.role === 'main' ? 'yes' : 'no'),
      first_video: old.first_video || pkg.video_id, last_video: pkg.video_id,
      appearances: Number(old.appearances || 0) + 1,
    },
  };
});
