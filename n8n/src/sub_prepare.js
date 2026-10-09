// PREPARE — builds prompts, JSON schema and request bodies for ONE AI stage.
// First run: input comes from "When Executed by Another Workflow" = { stage, pkg, feedback }.
// Retry runs: input comes from "Route" output 1 = { ctx, error } of the failed attempt.
const input = $input.first().json;
const base = input.ctx ?? { stage: input.stage, pkg: input.pkg ?? {}, feedback: input.feedback ?? '' };
const stage = base.stage;
const pkg = base.pkg;
const cfg = pkg.cfg ?? {};
const attempt = $runIndex; // 0, 1, 2 — this node runs again on every retry
let feedback = base.feedback || '';
if (input.error) {
  feedback += `\nYour previous answer was rejected by the validator: ${input.error}\nReturn ONLY valid JSON that matches the schema exactly.`;
}

// ---------- schema helpers (Gemini responseSchema dialect) ----------
const STR = (extra = {}) => ({ type: 'STRING', ...extra });
const INT = (extra = {}) => ({ type: 'INTEGER', ...extra });
const BOOL = () => ({ type: 'BOOLEAN' });
const ARR = (items, extra = {}) => ({ type: 'ARRAY', items, ...extra });
const OBJ = (properties, required = Object.keys(properties)) => ({ type: 'OBJECT', properties, required });

const CAMERA = ['zoom_in', 'zoom_out', 'pan_left', 'pan_right', 'pan_up', 'pan_down', 'static'];
const TRANSITION = ['fade', 'dissolve', 'slideleft', 'slideright', 'wipeleft', 'wiperight', 'circleopen', 'smoothleft', 'smoothright', 'radial'];
const SFX = ['splash', 'pop', 'boing', 'chime', 'whoosh', 'giggle', 'clap', 'bell', 'footsteps', 'bird_chirp', 'rain_light', 'wind_soft', 'car_horn_toy', 'train_toot', 'animal_moo', 'animal_quack', 'animal_roar_cute', 'drum_roll', 'ding', 'snore'];
const categories = cfg.categories ?? ['animals'];

const SCHEMAS = {
  idea: OBJ({
    title: STR(), category: STR({ enum: categories }), search_phrase: STR(), premise: STR(), learning_goal: STR(),
    hook_line: STR(), rewatch_hook: STR(), setting: STR(),
    mood: STR({ enum: ['bouncy', 'gentle', 'silly', 'adventurous', 'cozy', 'energetic'] }),
    repetition_device: STR(),
    main_character: OBJ({ reuse_star: BOOL(), name: STR(), species: STR(), one_line: STR() }),
    supporting_character: OBJ({ name: STR(), species: STR() }),
    concept_keywords: ARR(STR(), { minItems: 3, maxItems: 6 }),
    why_kids_love_it: STR(),
  }, ['title', 'category', 'search_phrase', 'premise', 'learning_goal', 'hook_line', 'rewatch_hook', 'setting', 'mood', 'repetition_device', 'main_character', 'concept_keywords']),

  song: OBJ({
    title: STR(), logline: STR(),
    story_beats: ARR(OBJ({ beat: INT(), summary: STR() }), { minItems: 3, maxItems: 6 }),
    sections: ARR(OBJ({
      section_id: STR(),
      type: STR({ enum: ['intro', 'verse', 'pre_chorus', 'chorus', 'bridge', 'outro'] }),
      lines: ARR(STR(), { minItems: 2, maxItems: 8 }),
      actions: STR(),
    }, ['section_id', 'type', 'lines']), { minItems: 4, maxItems: 10 }),
    characters: ARR(OBJ({
      char_id: STR(), name: STR(), species: STR(), role: STR({ enum: ['main', 'friend'] }),
      personality: STR(), visual_prompt: STR(), short_tag: STR(),
      colors: ARR(STR()), clothing: STR(), distinctive_features: STR(),
    }, ['char_id', 'name', 'species', 'role', 'personality', 'visual_prompt', 'short_tag']), { minItems: 1, maxItems: 3 }),
    music: OBJ({
      caption: STR(), bpm: INT(),
      key: STR({ enum: ['C Major', 'D Major', 'E Major', 'F Major', 'G Major', 'A Major', 'Bb Major'] }),
      time_signature: STR({ enum: ['4', '3'] }), mood: STR(),
    }),
    voice: OBJ({ hook_text: STR(), outro_text: STR() }),
    vocabulary_words: ARR(STR()), moral: STR(),
  }, ['title', 'logline', 'story_beats', 'sections', 'characters', 'music', 'voice']),

  storyboard: OBJ({
    scenes: ARR(OBJ({
      scene_id: INT(), section_id: STR(), line_indices: ARR(INT(), { minItems: 1, maxItems: 3 }),
      char_ids: ARR(STR(), { maxItems: 2 }), setting: STR(), action: STR(), expression: STR(),
      framing: STR({ enum: ['wide shot', 'medium shot', 'close-up'] }),
      camera: STR({ enum: CAMERA }), transition: STR({ enum: TRANSITION }),
      sfx: ARR(OBJ({ name: STR({ enum: SFX }), at: STR({ enum: ['start', 'middle'] }) }), { maxItems: 1 }),
    }, ['scene_id', 'section_id', 'line_indices', 'char_ids', 'setting', 'action', 'expression', 'framing', 'camera', 'transition']),
    { minItems: 10, maxItems: 40 }),
    title_card: OBJ({ setting: STR(), action: STR(), char_ids: ARR(STR()) }),
    outro_card: OBJ({ setting: STR(), action: STR(), char_ids: ARR(STR()) }),
    thumbnail: OBJ({
      action: STR(), expression: STR(), background: STR(), char_ids: ARR(STR()),
      text: STR(), text_side: STR({ enum: ['left', 'right'] }),
    }),
  }),

  metadata: OBJ({
    title: STR(), description: STR(),
    tags: ARR(STR(), { minItems: 8, maxItems: 15 }),
    hashtags: ARR(STR(), { maxItems: 3 }),
  }),

  qc: OBJ({
    scores: OBJ({
      originality: INT(), child_safety: INT(), age_appropriateness: INT(), grammar: INT(),
      rhyme_and_meter: INT(), singability: INT(), story_coherence: INT(),
      character_consistency: INT(), metadata_accuracy: INT(), kids_quality: INT(), algorithm_fit: INT(),
    }),
    issues: ARR(OBJ({
      component: STR({ enum: ['song', 'storyboard', 'metadata'] }),
      severity: STR({ enum: ['minor', 'major', 'blocker'] }),
      problem: STR(), fix: STR(),
    })),
    resembles_existing_work: BOOL(), resembles_note: STR(),
    verdict: STR({ enum: ['pass', 'revise_song', 'revise_storyboard', 'revise_metadata', 'reject'] }),
    summary: STR(),
  }, ['scores', 'issues', 'resembles_existing_work', 'verdict', 'summary']),
};

// ---------- prompts ----------
const channel = cfg.channel_name || 'our channel';
const world = cfg.world || '';
const cast = cfg.cast || [];
const YT = `HOW YOUTUBE TREATS KIDS' VIDEOS (apply this honestly; never game it)
- Recommendations follow what viewers actually watch and enjoy: watch time, re-watches, likes and dislikes, satisfaction surveys, and the channel's reputation for quality. Made for Kids videos have no comments and no notification bell, so almost every view comes from recommendations beside other kids' videos, YouTube Kids, playlists and search.
- YouTube's quality principles for kids' content reward videos that are age-appropriate, enriching, engaging and inspiring: kindness, friendship, self-care routines, curiosity and learning, creativity and imagination, a clear story with a resolution, and a wide range of people and places. They punish (limited ads or removal from the Partner Program) heavily promotional content, dangerous or unkind behaviour, titles or thumbnails that trick kids, jumbled stories or unclear audio, sensational or bizarre content, and familiar characters in odd or risky situations. Spam rules also forbid keyword stuffing in titles, descriptions and tags.
- The Partner Program does not pay for mass-produced, templated or repetitive videos (the inauthentic content policy), including AI-made videos built from a generic template and picture slideshows with little story. Every video must be materially different from the channel's earlier ones: a new story, a new learning goal, new places and new things to watch. A shared intro and outro is fine.
- Search ranks by relevance, engagement and quality. Parents search plain phrases such as "counting song", "bath time song" or "animal sounds for toddlers".
- Attention is won in the first seconds: the hook comes immediately, the chorus arrives early, and something new happens on screen every few seconds.
- Children re-watch songs they can join in with: repetition, simple actions, call-and-response, sound words and characters they already know.`;
const SYSTEM = {
  idea: `You are the head writer of "${channel}", a YouTube channel of ORIGINAL sing-along songs for children aged 2-6. You invent fresh song concepts that parents are happy to play and toddlers want to repeat.
Rules:
- Every concept is original. Never base an idea on an existing nursery rhyme, children's song, book, TV show, film, game or YouTube channel (for example: no "Twinkle Twinkle", "Wheels on the Bus", "Baby Shark", "Old MacDonald", CoComelon, Bluey, Peppa Pig, Disney, Pixar, Pokemon).
- Never use a trademarked or copyrighted character, brand or catchphrase.
- One clear, age-appropriate learning goal (counting, colours, shapes, opposites, animal sounds, feelings, kindness, routines, nature, first words).
- Child safety first: nothing scary, violent, sad-ending, gross-out or romantic; no dangerous behaviour a toddler could copy (fire, knives, medicine, electricity, roads, water without a grown-up, climbing high places); no sweets as rewards; no gender or cultural stereotypes; never mock anyone.
- A strong repetition device makes it memorable (counting up or down, call-and-response, cumulative list, an action repeated every chorus).
- Characters are friendly animals, vehicles, foods with faces or invented creatures - never real people.
- Title: max 60 characters, descriptive and honest. No clickbait, no ALL CAPS, no emojis.
- search_phrase: the short phrase (2-5 words) a parent would really type into YouTube to find this song, e.g. "counting song for toddlers", "brush teeth song", "farm animal sounds song". It must honestly describe the song and appear naturally in the title.
- rewatch_hook: one sentence on why a 3-year-old will want to watch it again (the action, the call-and-response, the funny sound).
- The channel's world is ${world}. Most stories happen there; short trips (seaside, farm, space) are fine.
${YT}
Return JSON only.`,

  song: `You are an award-winning children's songwriter and picture-book author writing an ORIGINAL nursery rhyme for ages 2-6 for "${channel}".
LYRICS
- Brand-new lyrics only. Never copy, quote or closely paraphrase any existing song, rhyme or poem - not even one line. Avoid famous lines such as "twinkle twinkle", "up above the world so high", "the wheels on the bus", "E-I-E-I-O", "row, row, row your boat", "if you're happy and you know it", "baby shark doo doo".
- Very simple words a 3-year-old knows. Present tense. 3-9 words per line, steady bouncy meter, lines of similar length.
- Rhyme scheme AABB or ABCB with true rhymes (not near-rhymes).
- Default structure (adapt only if it clearly serves the song): verse1, chorus, verse2, chorus, verse3, chorus, optional bridge, outro. 4 lines per verse and chorus; 2-4 lines for bridge and outro. section_id values are unique, e.g. verse1, chorus1, verse2, chorus2.
- The chorus is identical every time (same lines, same order) and carries the hook and the repetition device.
- Each verse moves the story on: beginning, small problem or discovery, happy resolution.
- Include sound words (splash, boing, moo) and one simple action kids can do (clap, jump, wave) - describe it in "actions".
- 18-36 lines in total; every line singable in about two bars; the whole song lasts about 2-3 minutes.
- Win the first seconds: the very first sung line already contains the hook; no intro section, or an intro of at most 2 lines; the first chorus starts no later than the 5th line.
STORY
- 3-6 story beats the verses follow. Warm, gentle humour, happy ending.
CHARACTERS (the "character bible" used for EVERY picture - be precise, never vague)
- 1-3 characters. char_id is lowercase_snake_case and unique.
- visual_prompt: max 30 words of concrete visual facts: species, body shape, main colour, eyes, clothing with colours, one distinctive accessory. Example: "small round golden lion cub, fluffy orange mane, big brown eyes, red scarf with white stars, tiny green backpack".
- short_tag: max 8 words with the most recognisable features. Example: "golden lion cub in a red star scarf".
- No real people, no trademarked characters, no logos or text on clothing.
- If a recurring star is provided, copy its name, species, visual_prompt and short_tag EXACTLY. You may add ONE friend from the recurring cast list (copy that bible exactly too) or invent a new friend.
MUSIC (for an AI singer)
- caption: comma-separated style tags, max 30 words, e.g. "cheerful children's song, bright friendly female vocal, ukulele, glockenspiel, hand claps, bouncy, short intro". Always include "short intro". Never name an existing artist or song.
- bpm 90-126, a major key, time_signature "4" ("3" only for a lullaby waltz).
VOICE
- hook_text: what the narrator says over the 3-second title card, max 12 words, inviting kids to sing along.
- outro_text: a warm goodbye, max 14 words, may recap the learning goal.
${YT}
Return JSON only.`,

  storyboard: `You are the storyboard artist of a children's animated sing-along. You turn lyrics into picture-book illustrations that will be animated with gentle camera moves.
Rules
- Each scene illustrates 1-2 consecutive lyric lines of ONE section; line_indices are 0-based within that section. Cover every line of every section, in order.
- Repeated choruses get NEW pictures (different angle, prop or action) so the video never feels like a looping slideshow.
- 14-32 scenes in total. scene_id counts from 1.
- char_ids: only ids from the character bible, at most 2 per scene; the main character appears in most scenes.
- Do NOT describe what characters look like - their appearance is added automatically from the bible. Describe only: setting (max 15 words), action and pose (max 18 words), facial expression (max 6 words).
- Keep locations consistent within the story, colourful, simple and uncluttered. No text, letters, signs or numerals in pictures - show counting with objects.
- Visuals are safe and gentle: no danger, no scary shadows, no injuries, no long crying.
- framing: vary wide shot / medium shot / close-up. camera: vary moves; pan_left or pan_right for movement, zoom_in for emotional moments, static rarely.
- transition: mostly fade or dissolve; playful ones (slideleft, slideright, circleopen, wipeleft, radial) at section changes.
- sfx: only from the allowed enum, max one per scene, only where the lyrics show that sound or action, in roughly one third of scenes; otherwise an empty array.
- The first three scenes decide whether a child keeps watching: make them the most colourful, close and lively (big expressions, movement, a camera move on every one).
- Home scenes use the channel's world: ${world}.
- title_card: the main character greeting the viewer in the story's setting. outro_card: the characters waving goodbye.
- thumbnail: ONE big, expressive main character (close-up, big happy emotion), plain bright background, no clutter, readable at phone size. text: 1-3 words (max 4), the honest hook of the song, no clickbait; it must show something that really happens in the video. The character goes on the side opposite text_side.
${YT}
Return JSON only.`,

  metadata: `You write YouTube metadata for "${channel}", a children's channel. Every video is Made for Kids. Be accurate, warm and useful to parents, and help the right parents find the song in search.
- title: max 70 characters, format "<Song name> | <search phrase in Title Case>", e.g. "Pip Counts the Puddles | Counting Song for Kids". Put the words parents search for in the title naturally. No clickbait, no ALL CAPS words, no emojis, no misleading claims, no other channels' or brands' names.
- description: 3 short paragraphs, 600-1400 characters in total. The first sentence (shown in search results) names the song, the search phrase and "${channel}" naturally. Then: (1) what happens in the song, (2) what children practise or learn, (3) a sing-along or movement tip for parents and carers. Plain text, no links, no hashtags, no timestamps (added automatically), no promises, no keyword lists.
- tags: 10-15 short relevant phrases, max 30 characters each, lowercase; the search phrase first, then honest variations (topic, learning goal, character species, "nursery rhymes", "kids songs"). No brand or other channel names, nothing unrelated - keyword stuffing counts as low quality.
- hashtags: max 3, without the # sign: one for the topic plus "nurseryrhymes" and "kidssongs".
${YT}
Return JSON only.`,

  qc: `You are a strict quality and safety reviewer for a children's YouTube channel (ages 2-6). You protect children, parents and the channel. Score each dimension 1-10 (10 = excellent).
- originality: lyrics, title and concept are not copied or closely paraphrased from any existing song, rhyme, book or show. If you recognise any line from an existing work set resembles_existing_work=true and add a blocker issue.
- child_safety: no danger a toddler could imitate; nothing scary, violent, sad, gross, romantic or rude; no stereotypes; no brand or copyrighted character. Anything unsafe is a blocker.
- age_appropriateness: vocabulary and ideas suit ages 2-6.
- grammar: correct English (sound words and playful repetition are fine).
- rhyme_and_meter: true rhymes, even line lengths, singable.
- singability: catchy chorus, repeated identically, easy to remember.
- story_coherence: clear beginning, middle and end; storyboard matches lyrics.
- character_consistency: storyboard uses the defined characters sensibly; no unknown characters.
- metadata_accuracy: title, description and tags honestly match the content; no clickbait.
- kids_quality: how well the package meets YouTube's quality principles for kids' content (enriching, positive behaviour, clear story, creativity, no sensational or bizarre elements, no keyword stuffing).
- algorithm_fit: hook in the first sung line, chorus by line 5, lively first scenes, an honest searchable title built on the search phrase, a thumbnail readable at phone size, and a real reason to re-watch. Judge it as a viewer would, never by tricks.
${YT}
Verdict: "pass" only if every score >= 7 (algorithm_fit >= 6 is enough), child_safety >= 9 and there is no blocker. Otherwise choose the component whose fix matters most: revise_song (lyrics, characters, music), revise_storyboard (scenes, thumbnail), revise_metadata (title, description, tags). Use "reject" only if the concept itself is unsafe or unoriginal. Every issue needs a concrete, actionable fix.
Return JSON only.`,
};

const list = (arr) => (arr && arr.length ? arr.map((x) => `- ${x}`).join('\n') : '- (none yet)');
const plan = pkg.plan ?? {};
const star = plan.star;
const song = pkg.song ?? {};
const sectionsText = (song.sections ?? []).map((s) => `${s.section_id} (${s.type}):\n` + s.lines.map((l, i) => `  ${i}: ${l}`).join('\n')).join('\n');

const USER = {
  idea: () => `Category for this video: ${plan.category}
Month: ${plan.month} (${plan.season})
Main character: ${star
    ? `REUSE our recurring star ${star.name} the ${star.species} (${star.short_tag}). Set main_character.reuse_star=true and keep the name and species exactly.`
    : `create a NEW main character (main_character.reuse_star=false). Do not use these species, they appeared too often recently: ${(plan.banned_species ?? []).join(', ') || 'none'}.`}
Titles we already published - do not repeat or closely paraphrase any of them:
${list(plan.avoid_titles)}
Concept keywords we already used:
${list(plan.avoid_concepts)}
Topic performance on our channel (higher = viewers watched more; prefer strong topics but keep variety): ${plan.weights_note || 'not enough data yet'}
${feedback}
Give one concept.`,

  song: () => `Write the song for this approved concept:
${JSON.stringify(pkg.idea, null, 1)}
${star && pkg.idea?.main_character?.reuse_star ? `Recurring star - copy exactly into characters: ${JSON.stringify(star)}` : ''}
Recurring cast you may add ONE friend from (copy the bible exactly):
${cast.filter((c) => !star || c.char_id !== star.char_id).map((c) => `- ${c.name} the ${c.species} (char_id ${c.char_id}): ${c.personality}. visual_prompt: ${c.visual_prompt}. short_tag: ${c.short_tag}`).join('\n') || '- (none)'}
Search phrase to serve: ${pkg.idea?.search_phrase}
Target song length: about ${plan.target_duration_s ?? 150} seconds.
${feedback}`,

  storyboard: () => `Character bible (ids you may use):
${(song.characters ?? []).map((c) => `- ${c.char_id}: ${c.name}, ${c.short_tag} (${c.role})`).join('\n')}
Story beats:
${(song.story_beats ?? []).map((b) => `${b.beat}. ${b.summary}`).join('\n')}
Song sections (line_indices refer to the numbers shown):
${sectionsText}
${feedback}`,

  metadata: () => `Channel: ${channel}
Song title: ${song.title}
Search phrase: ${pkg.idea?.search_phrase}
Logline: ${song.logline}
Learning goal: ${pkg.idea?.learning_goal}
Why kids re-watch: ${pkg.idea?.rewatch_hook}
Thumbnail text: ${pkg.cards?.thumbnail?.text ?? ''}
Lyrics:
${(song.sections ?? []).map((s) => s.lines.join('\n')).join('\n\n')}
${feedback}`,

  qc: () => `Package to review:
${JSON.stringify({
    concept: { title: pkg.idea?.title, search_phrase: pkg.idea?.search_phrase, premise: pkg.idea?.premise, learning_goal: pkg.idea?.learning_goal, rewatch_hook: pkg.idea?.rewatch_hook },
    song: { title: song.title, sections: song.sections, characters: song.characters, music_caption: song.music?.caption, voice: song.voice },
    storyboard: (pkg.render_scenes ?? []).map((s) => ({ id: s.scene_id, lines: s.lines, chars: s.char_ids, action: s.action, setting: s.setting })),
    thumbnail: pkg.cards?.thumbnail ? { text: pkg.cards.thumbnail.text, prompt: pkg.cards.thumbnail.prompt } : null,
    metadata: pkg.metadata_final ?? pkg.metadata,
  })}
${feedback}`,
};

if (!SCHEMAS[stage]) throw new Error(`Unknown stage "${stage}"`);
const TEMPERATURE = { idea: 1.0, song: 0.9, storyboard: 0.7, metadata: 0.5, qc: 0.2 };
const system = SYSTEM[stage];
const user = USER[stage]().trim();
const schema = SCHEMAS[stage];

// Ollama wants standard JSON Schema (lower-case types)
const toJsonSchema = (s) => JSON.parse(JSON.stringify(s).replace(/"type":"([A-Z]+)"/g, (_, t) => `"type":"${t.toLowerCase()}"`));

return [{
  json: {
    ctx: { stage, pkg, feedback: base.feedback || '', attempt, model: cfg.gemini_model || 'gemini-2.5-flash', ollama_url: cfg.ollama_url || 'http://127.0.0.1:11434' },
    schema,
    gemini_body: {
      systemInstruction: { parts: [{ text: system }] },
      contents: [{ role: 'user', parts: [{ text: user }] }],
      generationConfig: { temperature: TEMPERATURE[stage], maxOutputTokens: 16384, responseMimeType: 'application/json', responseSchema: schema },
    },
    ollama_body: {
      model: cfg.ollama_model || 'qwen3:8b', stream: false, format: toJsonSchema(schema),
      options: { temperature: TEMPERATURE[stage], num_ctx: 16384 },
      messages: [{ role: 'system', content: system }, { role: 'user', content: user }],
    },
  },
}];
