// UPLOAD RESULT — normalises the YouTube response from either upload node.
const yt = $input.first().json;
const prev = $('Media QC Gate').first().json;
if (!yt.id) throw new Error(`${prev.pkg.video_id} | YouTube upload returned no video id: ${JSON.stringify(yt).slice(0, 300)}`);
return [{
  json: {
    ...prev,
    youtube: {
      id: yt.id,
      url: `https://www.youtube.com/watch?v=${yt.id}`,
      privacy: yt.status?.privacyStatus || '',
      publish_at: yt.status?.publishAt || '',
      made_for_kids: yt.status?.selfDeclaredMadeForKids ?? true,
      uploaded_at: new Date().toISOString(),
    },
  },
}];
