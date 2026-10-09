#!/usr/bin/env python3
"""Generates the four importable n8n workflow JSON files from the Code-node sources in src/."""
import json
import re
import uuid
from pathlib import Path

HERE = Path(__file__).parent
SRC = HERE / "src"
CFG = json.loads((SRC / "config.json").read_text(encoding="utf-8"))
BRAND = json.loads((HERE.parent / "helper" / "brand.json").read_text(encoding="utf-8"))
# brand.json is the single source of truth for name, world, look, cast and playlists
CFG["cfg"].update({
    "channel_name": BRAND["channel_name"],
    "channel_handle": BRAND["handle"],
    "world": BRAND["world"],
    "style_bible": BRAND["style_bible"],
    "cast": [{k: c[k] for k in ("char_id", "name", "species", "short_tag", "visual_prompt", "personality")}
             for c in BRAND["cast"]],
    "category_playlist": BRAND["playlists"],
    "playlist_ids": {name: CFG["cfg"].get("playlist_ids", {}).get(name, "")
                     for name in dict.fromkeys(BRAND["playlists"].values())},
    "title_card_s": 3.0,
})
CFG["cfg"]["categories"] = list(BRAND["playlists"].keys())
(SRC / "config.json").write_text(json.dumps(CFG, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
SHEET_PLACEHOLDER = "PASTE_YOUR_GOOGLE_SHEET_ID_HERE"

# Your own values (sheet ID, playlist IDs) live in my_settings.json next to this script, so you never
# edit JSON inside n8n. Full URLs are accepted; the IDs are pulled out of them.
MY_FILE = HERE / "my_settings.json"
if not MY_FILE.exists():
    MY_FILE.write_text(json.dumps({
        "sheet_id": "",
        "upload_mode": "manual_outbox",
        "playlist_ids": {name: "" for name in CFG["cfg"]["playlist_ids"]},
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
MY = json.loads(MY_FILE.read_text(encoding="utf-8-sig"))


def _sheet_id(v):
    m = re.search(r"/d/([A-Za-z0-9_-]{20,})", v or "")
    return m.group(1) if m else (v or "").strip()


def _playlist_id(v):
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", v or "")
    return m.group(1) if m else (v or "").strip()


SHEET_ID = _sheet_id(MY.get("sheet_id")) or SHEET_PLACEHOLDER
CFG["cfg"]["sheet_id"] = SHEET_ID
for _name, _val in (MY.get("playlist_ids") or {}).items():
    if _name in CFG["cfg"]["playlist_ids"] and _playlist_id(_val):
        CFG["cfg"]["playlist_ids"][_name] = _playlist_id(_val)
    elif _playlist_id(_val):
        print(f"WARNING: playlist name not in brand.json, ignored: {_name}")
if MY.get("upload_mode") in ("manual_outbox", "api_private", "api_scheduled"):
    CFG["cfg"]["upload_mode"] = MY["upload_mode"]

VIDEOS_COLS = ["video_id", "exec_id", "status", "created_at", "category", "title", "topic", "learning_goal",
               "main_characters", "main_species", "char_ids", "concept_keywords", "concept_hash", "title_norm",
               "lyrics", "lyrics_hash", "quality_score", "qc_notes", "retry_count", "llm_providers", "song_mode",
               "intelligibility", "duration_s", "generation_time_min", "render_path", "thumbnail_path",
               "youtube_id", "youtube_url", "privacy", "publish_at", "upload_date", "thumbnail_status",
               "playlist_status", "error", "failed_node", "views", "likes", "comments", "watch_time_min",
               "avg_view_duration_s", "avg_view_pct", "subs_gained", "impressions", "ctr", "analytics_updated_at"]
TOPIC_COLS = ["category", "weight", "videos", "median_views", "note", "updated_at"]
CHAR_COLS = ["char_id", "name", "species", "short_tag", "visual_prompt", "personality", "recurring",
             "first_video", "last_video", "appearances"]
ERR_COLS = ["at", "workflow", "exec_id", "video_id", "failed_node", "error", "execution_url"]


def code(name):
    return (SRC / name).read_text(encoding="utf-8")


class WF:
    def __init__(self, name, settings=None):
        self.name = name
        self.nodes = []
        self.conns = {}
        self.settings = {"executionOrder": "v1", "timezone": "Asia/Kolkata", "saveManualExecutions": True,
                         "callerPolicy": "workflowsFromSameOwner", **(settings or {})}

    def add(self, name, ntype, version, params, pos, **extra):
        node = {"id": str(uuid.uuid4()), "name": name, "type": ntype, "typeVersion": version,
                "position": list(pos), "parameters": params}
        node.update(extra)
        self.nodes.append(node)
        return name

    def link(self, src, dst, out=0):
        outs = self.conns.setdefault(src, {"main": []})["main"]
        while len(outs) <= out:
            outs.append([])
        outs[out].append({"node": dst, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def note(self, text, pos, w=520, h=260, color=7):
        self.add(f"Note {len(self.nodes)}", "n8n-nodes-base.stickyNote", 1,
                 {"content": text, "height": h, "width": w, "color": color}, pos)

    def dump(self, path):
        names = {n["name"] for n in self.nodes}
        for src, v in self.conns.items():
            assert src in names, f"unknown source {src}"
            for outs in v["main"]:
                for c in outs:
                    assert c["node"] in names, f"unknown target {c['node']}"
        data = {"name": self.name, "nodes": self.nodes, "connections": self.conns, "settings": self.settings,
                "pinData": {}, "meta": {"templateCredsSetupCompleted": False}, "active": False}
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {path.name}: {len(self.nodes)} nodes")


# ---------- node factories ----------
def schema(cols, types=None):
    types = types or {}
    return [{"id": c, "displayName": c, "required": False, "defaultMatch": False, "display": True,
             "type": types.get(c, "string"), "canBeUsedToMatch": True} for c in cols]


def sheet_ref(doc_expr, tab):
    return ({"__rl": True, "value": doc_expr, "mode": "id"},
            {"__rl": True, "value": tab, "mode": "name"})


def sheets_read(doc_expr, tab):
    d, s = sheet_ref(doc_expr, tab)
    return {"operation": "read", "documentId": d, "sheetName": s, "options": {}}


def sheets_write(op, doc_expr, tab, values, match=None):
    d, s = sheet_ref(doc_expr, tab)
    cols = list(values.keys())
    return {"operation": op, "documentId": d, "sheetName": s,
            "columns": {"mappingMode": "defineBelow", "value": values, "matchingColumns": [match] if match else [],
                        "schema": schema(cols), "attemptToConvertTypes": False, "convertFieldsToString": False},
            "options": {}}


def switch(expr, outputs):
    return {"mode": "expression", "numberOutputs": outputs, "output": expr}


def http(method, url, **kw):
    p = {"method": method, "url": url, "options": kw.pop("options", {})}
    p.update(kw)
    return p


def ai_call(stage, pkg_expr, feedback_expr):
    vals = {"stage": stage, "pkg": pkg_expr, "feedback": feedback_expr}
    return {"workflowId": {"__rl": True, "value": "", "mode": "list", "cachedResultName": "RF - AI Stage"},
            "workflowInputs": {"mappingMode": "defineBelow", "value": vals, "matchingColumns": [],
                               "schema": schema(["stage", "pkg", "feedback"], {"pkg": "object"}),
                               "attemptToConvertTypes": False, "convertFieldsToString": False},
            "options": {"waitForSubWorkflow": True}}


RETRY = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 5000}
HEADER_AUTH = {"authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth"}
CFG_DOC = "={{ $('Config').first().json.cfg.sheet_id }}"
H = "$('Build Render Job').first().json.pkg"   # package after content approval
M = "$('Media QC Gate').first().json"          # upload metadata
U = "$('Upload Result').first().json"          # youtube result

# =====================================================================================
# 1) Sub-workflow: RF - AI Stage
# =====================================================================================
sub = WF("RF - AI Stage")
sub.note("## RF - AI Stage\nCalled by the main workflow once per stage (idea, song, storyboard, metadata, qc).\n"
         "Gemini (free tier) first; if it errors after 3 tries -> local Ollama.\n"
         "Invalid JSON -> up to 3 attempts with the validator's error fed back. Prompts + JSON schemas live in **Prepare**.",
         (-40, -260), 620, 200)
sub.add("When Executed by Another Workflow", "n8n-nodes-base.executeWorkflowTrigger", 1.1,
        {"workflowInputs": {"values": [{"name": "stage"}, {"name": "pkg", "type": "object"}, {"name": "feedback"}]}},
        (0, 0))
sub.add("Prepare", "n8n-nodes-base.code", 2, {"jsCode": code("sub_prepare.js")}, (240, 0))
sub.add("Gemini", "n8n-nodes-base.httpRequest", 4.2, http(
    "POST", "=https://generativelanguage.googleapis.com/v1beta/models/{{ $json.ctx.model }}:generateContent",
    **HEADER_AUTH, sendBody=True, specifyBody="json", jsonBody="={{ JSON.stringify($json.gemini_body) }}",
    options={"timeout": 180000}), (480, 0), onError="continueErrorOutput", **RETRY)
sub.add("Ollama Fallback", "n8n-nodes-base.httpRequest", 4.2, http(
    "POST", "={{ $('Prepare').last().json.ctx.ollama_url }}/api/chat", sendBody=True, specifyBody="json",
    jsonBody="={{ JSON.stringify($('Prepare').last().json.ollama_body) }}", options={"timeout": 600000}),
    (720, 160), onError="continueRegularOutput")
sub.add("Parse & Validate", "n8n-nodes-base.code", 2, {"jsCode": code("sub_parse.js")}, (960, 0))
sub.add("Route", "n8n-nodes-base.switch", 3.2, switch("={{ $json.route_index }}", 3), (1200, 0))
sub.add("Return", "n8n-nodes-base.code", 2, {"jsCode": code("sub_return.js")}, (1440, -120))
sub.add("Stop: AI Output Invalid", "n8n-nodes-base.stopAndError", 1, {
    "errorMessage": "={{ ($json.ctx.pkg.video_id || 'no-id') + ' | ' + $json.ctx.stage + ' stage: AI output invalid after ' + ($json.attempt + 1) + ' attempts: ' + $json.error }}"},
    (1440, 160))
sub.chain("When Executed by Another Workflow", "Prepare", "Gemini", "Parse & Validate", "Route")
sub.link("Gemini", "Ollama Fallback", 1)
sub.link("Ollama Fallback", "Parse & Validate")
sub.link("Route", "Return", 0)
sub.link("Route", "Prepare", 1)
sub.link("Route", "Stop: AI Output Invalid", 2)

# =====================================================================================
# 2) Main workflow
# =====================================================================================
main = WF("RF - Main (Idea to YouTube)")
main.note("## Rhyme Factory - main pipeline\n1. Set **Config** (sheet id, upload_mode...).\n"
          "2. In the five **AI:** nodes pick the workflow *RF - AI Stage*.\n"
          "3. Assign credentials (Google Sheets, Rhyme Helper Key, YouTube).\n"
          "4. Workflow Settings -> Error workflow = *RF - Error Handler*.\n"
          "Every loop has a hard cap; failures stop at **Stop: Failed** and are logged by the error workflow.",
          (-400, -340), 560, 250)
y0, y1, y2 = 0, 300, 600
main.add("Schedule", "n8n-nodes-base.scheduleTrigger", 1.2,
         {"rule": {"interval": [{"field": "cronExpression", "expression": "30 1 * * 1,3,5"}]}}, (-400, -40))
main.add("Manual Run", "n8n-nodes-base.manualTrigger", 1, {}, (-400, 140))
main.add("Config", "n8n-nodes-base.set", 3.4, {"mode": "raw", "jsonOutput": json.dumps(CFG, indent=2), "options": {}}, (-160, 40))
main.add("Read History", "n8n-nodes-base.googleSheets", 4.5, sheets_read(CFG_DOC, "Videos"), (60, 40),
         executeOnce=True, alwaysOutputData=True, **RETRY)
main.add("Read Topic Weights", "n8n-nodes-base.googleSheets", 4.5, sheets_read(CFG_DOC, "TopicWeights"), (280, 40),
         executeOnce=True, alwaysOutputData=True, **RETRY)
main.add("Read Characters", "n8n-nodes-base.googleSheets", 4.5, sheets_read(CFG_DOC, "Characters"), (500, 40),
         executeOnce=True, alwaysOutputData=True, **RETRY)
main.add("Plan Run", "n8n-nodes-base.code", 2, {"jsCode": code("main_plan_run.js")}, (720, 40))
main.add("Log Start", "n8n-nodes-base.googleSheets", 4.5, sheets_write("append", CFG_DOC, "Videos", {
    "video_id": "={{ $json.pkg.video_id }}", "exec_id": "={{ $json.pkg.exec_id }}", "status": "generating",
    "created_at": "={{ $json.pkg.started_at }}", "category": "={{ $json.pkg.plan.category }}"}), (940, 40), **RETRY)
main.add("AI: Idea", "n8n-nodes-base.executeWorkflow", 1.2,
         ai_call("idea", "={{ $json.pkg ?? $('Plan Run').first().json.pkg }}", "={{ $json.feedback ?? '' }}"), (1160, 40))
main.add("Check Idea", "n8n-nodes-base.code", 2, {"jsCode": code("main_check_idea.js")}, (1380, 40))
main.add("Idea Route", "n8n-nodes-base.switch", 3.2, switch("={{ $json.route_index }}", 3), (1600, 40))

main.add("AI: Song", "n8n-nodes-base.executeWorkflow", 1.2, ai_call("song", "={{ $json.pkg }}", "={{ $json.feedback ?? '' }}"), (60, y1))
main.add("Check Song", "n8n-nodes-base.code", 2, {"jsCode": code("main_check_song.js")}, (280, y1))
main.add("Song Route", "n8n-nodes-base.switch", 3.2, switch("={{ $json.route_index }}", 3), (500, y1))
main.add("AI: Storyboard", "n8n-nodes-base.executeWorkflow", 1.2, ai_call("storyboard", "={{ $json.pkg }}", "={{ $json.feedback ?? '' }}"), (720, y1))
main.add("Check Storyboard", "n8n-nodes-base.code", 2, {"jsCode": code("main_check_storyboard.js")}, (940, y1))
main.add("Storyboard Route", "n8n-nodes-base.switch", 3.2, switch("={{ $json.route_index }}", 3), (1160, y1))
main.add("AI: Metadata", "n8n-nodes-base.executeWorkflow", 1.2, ai_call("metadata", "={{ $json.pkg }}", "={{ $json.feedback ?? '' }}"), (1380, y1))
main.add("Check Metadata", "n8n-nodes-base.code", 2, {"jsCode": code("main_check_metadata.js")}, (1600, y1))
main.add("AI: QC Review", "n8n-nodes-base.executeWorkflow", 1.2, ai_call("qc", "={{ $json.pkg }}", "={{ '' }}"), (1820, y1))
main.add("QC Gate", "n8n-nodes-base.code", 2, {"jsCode": code("main_qc_gate.js")}, (2040, y1))
main.add("QC Route", "n8n-nodes-base.switch", 3.2, switch("={{ $json.route_index }}", 5), (2260, y1))

main.add("Build Render Job", "n8n-nodes-base.code", 2, {"jsCode": code("main_build_render_job.js")}, (60, y2))
main.add("Character Rows", "n8n-nodes-base.code", 2, {"jsCode": code("main_character_rows.js")}, (280, y2 - 160))
main.add("Save Characters", "n8n-nodes-base.googleSheets", 4.5, sheets_write("appendOrUpdate", CFG_DOC, "Characters", {
    c: f"={{{{ $json.{c} }}}}" for c in CHAR_COLS}, match="char_id"), (500, y2 - 160), onError="continueRegularOutput")
main.add("Start Render", "n8n-nodes-base.httpRequest", 4.2, http(
    "POST", "={{ $json.pkg.cfg.helper_url }}/jobs", **HEADER_AUTH, sendBody=True, specifyBody="json",
    jsonBody="={{ JSON.stringify($json.job) }}", options={"timeout": 30000}), (280, y2), **RETRY)
main.add("Log Rendering", "n8n-nodes-base.googleSheets", 4.5, sheets_write("update", CFG_DOC, "Videos", {
    "video_id": f"={{{{ {H}.video_id }}}}",
    "status": "rendering",
    "title": f"={{{{ {H}.metadata_final.title }}}}",
    "topic": f"={{{{ {H}.idea.premise }}}}",
    "category": f"={{{{ {H}.idea.category }}}}",
    "learning_goal": f"={{{{ {H}.idea.learning_goal }}}}",
    "main_characters": f"={{{{ {H}.song.characters.map(c => c.name + ' the ' + c.species).join(', ') }}}}",
    "main_species": f"={{{{ ({H}.song.characters.find(c => c.role === 'main') || {H}.song.characters[0]).species }}}}",
    "char_ids": f"={{{{ {H}.song.characters.map(c => c.char_id).join(',') }}}}",
    "concept_keywords": f"={{{{ {H}.idea.concept_keywords.join(',') }}}}",
    "concept_hash": f"={{{{ {H}.hash.concept_hash }}}}",
    "title_norm": f"={{{{ {H}.hash.title_norm }}}}",
    "lyrics": f"={{{{ {H}.lyrics_text }}}}",
    "lyrics_hash": f"={{{{ {H}.hash.lyrics_hash }}}}",
    "quality_score": f"={{{{ {H}.quality_score }}}}",
    "qc_notes": f"={{{{ {H}.checks.qc.summary }}}}",
    "retry_count": f"={{{{ {H}.retry_count }}}}",
    "llm_providers": f"={{{{ [...new Set({H}.llm_log.map(l => l.provider))].join(',') }}}}",
}, match="video_id"), (500, y2), **RETRY)
main.add("Wait 2 min", "n8n-nodes-base.wait", 1.1, {"amount": 2, "unit": "minutes"}, (720, y2), webhookId=str(uuid.uuid4()))
main.add("Check Render", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", f"={{{{ {H}.cfg.helper_url }}}}/jobs/{{{{ {H}.video_id }}}}", **HEADER_AUTH, options={"timeout": 30000}),
    (940, y2), **RETRY)
main.add("Render Route", "n8n-nodes-base.switch", 3.2, switch(
    f"={{{{ $json.status === 'done' ? 0 : ($json.status === 'failed' || $runIndex >= {H}.cfg.max_poll) ? 1 : 2 }}}}", 3),
    (1160, y2))
main.add("Media QC Gate", "n8n-nodes-base.code", 2, {"jsCode": code("main_media_qc_gate.js")}, (1380, y2))
main.add("Upload Mode", "n8n-nodes-base.switch", 3.2, switch("={{ $json.upload.mode === 'manual_outbox' ? 0 : 1 }}", 2), (1600, y2))
main.add("Send to Outbox", "n8n-nodes-base.httpRequest", 4.2, http(
    "POST", "={{ $json.pkg.cfg.helper_url }}/jobs/{{ $json.pkg.video_id }}/outbox", **HEADER_AUTH, sendBody=True,
    specifyBody="json",
    jsonBody="={{ JSON.stringify({ title: $json.upload.title, description: $json.upload.description, tags: $json.upload.tags, publish_suggestion: $json.upload.publish_at, playlist: $json.upload.playlist_name }) }}",
    options={"timeout": 120000}), (1820, y2 - 160), **RETRY)
main.add("Log Ready", "n8n-nodes-base.googleSheets", 4.5, sheets_write("update", CFG_DOC, "Videos", {
    "video_id": f"={{{{ {M}.pkg.video_id }}}}",
    "status": "ready_for_manual_upload",
    "render_path": "={{ $json.outbox }}",
    "thumbnail_path": f"={{{{ {M}.render.thumbnail_path }}}}",
    "duration_s": f"={{{{ {M}.render.duration_s }}}}",
    "song_mode": f"={{{{ {M}.render.song_mode }}}}",
    "intelligibility": f"={{{{ {M}.render.intelligibility }}}}",
    "publish_at": f"={{{{ {M}.upload.publish_at }}}}",
    "generation_time_min": f"={{{{ Math.round((Date.now() - new Date({M}.pkg.started_at).getTime()) / 60000) }}}}",
}, match="video_id"), (2040, y2 - 160), **RETRY)
main.add("Download Video", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", "={{ $json.pkg.cfg.helper_url }}/files/{{ $json.pkg.video_id }}/final.mp4", **HEADER_AUTH,
    options={"timeout": 600000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}),
    (1820, y2 + 60), **RETRY)
main.add("Privacy Route", "n8n-nodes-base.switch", 3.2, switch(f"={{{{ {M}.upload.mode === 'api_scheduled' ? 1 : 0 }}}}", 2), (2040, y2 + 60))
yt_opts = {
    "description": f"={{{{ {M}.upload.description }}}}",
    "tags": f"={{{{ {M}.upload.tags }}}}",
    "privacyStatus": "private",
    "selfDeclaredMadeForKids": True,
    "notifySubscribers": False,
    "defaultLanguage": f"={{{{ {M}.upload.language }}}}",
    "embeddable": True,
    "license": "youtube",
    "publicStatsViewable": True,
}
yt_base = {"resource": "video", "operation": "upload", "title": f"={{{{ {M}.upload.title }}}}",
           "regionCode": f"={{{{ {M}.upload.region_code }}}}", "categoryId": f"={{{{ {M}.upload.category_id }}}}",
           "binaryProperty": "data"}
main.add("Upload (Private)", "n8n-nodes-base.youTube", 1, {**yt_base, "options": dict(yt_opts)}, (2260, y2 - 20))
main.add("Upload (Scheduled)", "n8n-nodes-base.youTube", 1,
         {**yt_base, "options": {**yt_opts, "publishAt": f"={{{{ {M}.upload.publish_at }}}}"}}, (2260, y2 + 140))
main.add("Upload Result", "n8n-nodes-base.code", 2, {"jsCode": code("main_upload_result.js")}, (2480, y2 + 60))
main.add("Download Thumbnail", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", "={{ $json.pkg.cfg.helper_url }}/files/{{ $json.pkg.video_id }}/thumbnail.jpg", **HEADER_AUTH,
    options={"timeout": 60000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "thumb"}}}),
    (2700, y2 + 60), **RETRY)
main.add("Set Thumbnail", "n8n-nodes-base.httpRequest", 4.2, http(
    "POST", "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
    authentication="predefinedCredentialType", nodeCredentialType="youTubeOAuth2Api",
    sendQuery=True, queryParameters={"parameters": [
        {"name": "videoId", "value": f"={{{{ {U}.youtube.id }}}}"}, {"name": "uploadType", "value": "media"}]},
    sendHeaders=True, headerParameters={"parameters": [{"name": "Content-Type", "value": "image/jpeg"}]},
    sendBody=True, contentType="binaryData", inputDataFieldName="thumb", options={"timeout": 60000}),
    (2920, y2 + 60), onError="continueRegularOutput", retryOnFail=True, maxTries=2, waitBetweenTries=5000)
main.add("Add to Playlist", "n8n-nodes-base.youTube", 1, {
    "resource": "playlistItem", "operation": "add", "playlistId": f"={{{{ {U}.upload.playlist_id }}}}",
    "videoId": f"={{{{ {U}.youtube.id }}}}", "options": {}}, (3140, y2 + 60), onError="continueRegularOutput")
main.add("Log Uploaded", "n8n-nodes-base.googleSheets", 4.5, sheets_write("update", CFG_DOC, "Videos", {
    "video_id": f"={{{{ {U}.pkg.video_id }}}}",
    "status": f"={{{{ {U}.upload.mode === 'api_scheduled' ? 'scheduled' : 'uploaded_private' }}}}",
    "youtube_id": f"={{{{ {U}.youtube.id }}}}",
    "youtube_url": f"={{{{ {U}.youtube.url }}}}",
    "privacy": f"={{{{ {U}.youtube.privacy }}}}",
    "publish_at": f"={{{{ {U}.upload.mode === 'api_scheduled' ? {U}.upload.publish_at : '' }}}}",
    "upload_date": f"={{{{ {U}.youtube.uploaded_at }}}}",
    "thumbnail_status": "={{ $('Set Thumbnail').first().json.error ? 'failed: ' + String($('Set Thumbnail').first().json.error.message ?? $('Set Thumbnail').first().json.error).slice(0, 150) : 'ok' }}",
    "playlist_status": f"={{{{ !{U}.upload.playlist_id ? 'skipped' : ($json.error ? 'failed' : 'added') }}}}",
    "render_path": f"={{{{ {U}.render.video_path }}}}",
    "thumbnail_path": f"={{{{ {U}.render.thumbnail_path }}}}",
    "duration_s": f"={{{{ {U}.render.duration_s }}}}",
    "song_mode": f"={{{{ {U}.render.song_mode }}}}",
    "intelligibility": f"={{{{ {U}.render.intelligibility }}}}",
    "generation_time_min": f"={{{{ Math.round((Date.now() - new Date({U}.pkg.started_at).getTime()) / 60000) }}}}",
}, match="video_id"), (3360, y2 + 60), **RETRY)
main.add("Stop: Failed", "n8n-nodes-base.stopAndError", 1, {
    "errorMessage": "={{ $json.fail_reason || ($('Build Render Job').isExecuted ? $('Build Render Job').first().json.pkg.video_id + ' | render failed or timed out: ' + ($json.error || $json.status) : 'pipeline stopped') }}"},
    (1380, 820))

main.chain("Schedule", "Config")
main.chain("Manual Run", "Config", "Read History", "Read Topic Weights", "Read Characters", "Plan Run", "Log Start",
           "AI: Idea", "Check Idea", "Idea Route")
main.link("Idea Route", "AI: Song", 0)
main.link("Idea Route", "AI: Idea", 1)
main.link("Idea Route", "Stop: Failed", 2)
main.chain("AI: Song", "Check Song", "Song Route")
main.link("Song Route", "AI: Storyboard", 0)
main.link("Song Route", "AI: Song", 1)
main.link("Song Route", "Stop: Failed", 2)
main.chain("AI: Storyboard", "Check Storyboard", "Storyboard Route")
main.link("Storyboard Route", "AI: Metadata", 0)
main.link("Storyboard Route", "AI: Storyboard", 1)
main.link("Storyboard Route", "Stop: Failed", 2)
main.chain("AI: Metadata", "Check Metadata", "AI: QC Review", "QC Gate", "QC Route")
main.link("QC Route", "Build Render Job", 0)
main.link("QC Route", "AI: Song", 1)
main.link("QC Route", "AI: Storyboard", 2)
main.link("QC Route", "AI: Metadata", 3)
main.link("QC Route", "Stop: Failed", 4)
main.link("Build Render Job", "Character Rows")
main.link("Character Rows", "Save Characters")
main.link("Build Render Job", "Start Render")
main.chain("Start Render", "Log Rendering", "Wait 2 min", "Check Render", "Render Route")
main.link("Render Route", "Media QC Gate", 0)
main.link("Render Route", "Stop: Failed", 1)
main.link("Render Route", "Wait 2 min", 2)
main.link("Media QC Gate", "Upload Mode")
main.link("Upload Mode", "Send to Outbox", 0)
main.link("Upload Mode", "Download Video", 1)
main.link("Send to Outbox", "Log Ready")
main.link("Download Video", "Privacy Route")
main.link("Privacy Route", "Upload (Private)", 0)
main.link("Privacy Route", "Upload (Scheduled)", 1)
main.link("Upload (Private)", "Upload Result")
main.link("Upload (Scheduled)", "Upload Result")
main.chain("Upload Result", "Download Thumbnail", "Set Thumbnail", "Add to Playlist", "Log Uploaded")

# =====================================================================================
# 3) Error handler
# =====================================================================================
err = WF("RF - Error Handler")
err.note("## RF - Error Handler\nSet this as the *Error workflow* of RF - Main (Workflow -> Settings).\n"
         "Marks the video row as failed (matched by execution id) and appends to the Errors tab.\n"
         "Runs only for production (scheduled/active) executions, not for manual test runs.", (-40, -240), 560, 180)
err.add("Error Trigger", "n8n-nodes-base.errorTrigger", 1, {}, (0, 0))
err.add("Format Error", "n8n-nodes-base.code", 2, {"jsCode": code("err_format.js")}, (240, 0))
err.add("Mark Video Failed", "n8n-nodes-base.googleSheets", 4.5, sheets_write("update", SHEET_ID, "Videos", {
    "exec_id": "={{ $json.exec_id }}", "status": "failed", "error": "={{ $json.error }}",
    "failed_node": "={{ $json.failed_node }}"}, match="exec_id"), (480, 0), onError="continueRegularOutput")
err.add("Log Error", "n8n-nodes-base.googleSheets", 4.5, sheets_write("append", SHEET_ID, "Errors", {
    c: f"={{{{ $('Format Error').first().json.{c} }}}}" for c in ERR_COLS}), (720, 0), onError="continueRegularOutput")
err.chain("Error Trigger", "Format Error", "Mark Video Failed", "Log Error")

# =====================================================================================
# 4) Analytics (weekly)
# =====================================================================================
an = WF("RF - Analytics (weekly)")
an.note("## RF - Analytics\nEvery Monday: pulls views/likes/comments (YouTube Data API, 1 unit per 50 videos) and\n"
        "watch time / retention / subs (YouTube Analytics API), writes them to Videos, and recomputes\n"
        "TopicWeights, which Plan Run uses to pick categories. Keep the category list identical to RF - Main.",
        (-40, -260), 640, 190)
ACFG = {"cfg": {"sheet_id": SHEET_ID, "channel_start_date": "2026-10-01", "categories": CFG["cfg"]["categories"]}}
A_DOC = "={{ $('Analytics Config').first().json.cfg.sheet_id }}"
B = "$('Build Batches').first().json"
an.add("Weekly", "n8n-nodes-base.scheduleTrigger", 1.2,
       {"rule": {"interval": [{"field": "cronExpression", "expression": "0 7 * * 1"}]}}, (0, -60))
an.add("Manual Run", "n8n-nodes-base.manualTrigger", 1, {}, (0, 120))
an.add("Analytics Config", "n8n-nodes-base.set", 3.4, {"mode": "raw", "jsonOutput": json.dumps(ACFG, indent=2), "options": {}}, (220, 40))
an.add("Read Videos", "n8n-nodes-base.googleSheets", 4.5, sheets_read(A_DOC, "Videos"), (440, 40), executeOnce=True, alwaysOutputData=True)
an.add("Read Weights", "n8n-nodes-base.googleSheets", 4.5, sheets_read(A_DOC, "TopicWeights"), (660, 40), executeOnce=True, alwaysOutputData=True)
an.add("Build Batches", "n8n-nodes-base.code", 2, {"jsCode": code("an_build_batches.js")}, (880, 40))
GAUTH = {"authentication": "predefinedCredentialType", "nodeCredentialType": "googleOAuth2Api"}
an.add("Video Stats", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", "https://www.googleapis.com/youtube/v3/videos", **GAUTH, sendQuery=True,
    queryParameters={"parameters": [{"name": "part", "value": "statistics"}, {"name": "id", "value": "={{ $json.ids }}"},
                                    {"name": "maxResults", "value": "50"}]}), (1100, 40), **RETRY)
rep_q = lambda metrics: {"parameters": [
    {"name": "ids", "value": "channel==MINE"}, {"name": "startDate", "value": f"={{{{ {B}.start_date }}}}"},
    {"name": "endDate", "value": f"={{{{ {B}.end_date }}}}"}, {"name": "metrics", "value": metrics},
    {"name": "dimensions", "value": "video"}, {"name": "filters", "value": f"=video=={{{{ {B}.all_ids }}}}"},
    {"name": "sort", "value": "-" + metrics.split(",")[0]}, {"name": "maxResults", "value": "200"}]}
an.add("Analytics Report", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", "https://youtubeanalytics.googleapis.com/v2/reports", **GAUTH, sendQuery=True,
    queryParameters=rep_q("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained")),
    (1320, 40), executeOnce=True, onError="continueRegularOutput")
an.add("CTR Report", "n8n-nodes-base.httpRequest", 4.2, http(
    "GET", "https://youtubeanalytics.googleapis.com/v2/reports", **GAUTH, sendQuery=True,
    queryParameters=rep_q("videoThumbnailImpressions,videoThumbnailImpressionsClickRate")),
    (1540, 40), executeOnce=True, onError="continueRegularOutput")
an.add("Merge & Score", "n8n-nodes-base.code", 2, {"jsCode": code("an_merge_score.js")}, (1760, 40))
an.add("Route Rows", "n8n-nodes-base.switch", 3.2, switch("={{ $json.kind === 'video' ? 0 : 1 }}", 2), (1980, 40))
an.add("Update Video Stats", "n8n-nodes-base.googleSheets", 4.5, sheets_write("update", A_DOC, "Videos", {
    c: f"={{{{ $json.{c} }}}}" for c in ["video_id", "views", "likes", "comments", "watch_time_min", "avg_view_duration_s",
                                          "avg_view_pct", "subs_gained", "impressions", "ctr", "analytics_updated_at"]},
    match="video_id"), (2200, -60), **RETRY)
an.add("Upsert Topic Weights", "n8n-nodes-base.googleSheets", 4.5, sheets_write("appendOrUpdate", A_DOC, "TopicWeights", {
    c: f"={{{{ $json.{c} }}}}" for c in TOPIC_COLS}, match="category"), (2200, 140), **RETRY)
an.chain("Weekly", "Analytics Config")
an.chain("Manual Run", "Analytics Config", "Read Videos", "Read Weights", "Build Batches", "Video Stats",
         "Analytics Report", "CTR Report", "Merge & Score", "Route Rows")
an.link("Route Rows", "Update Video Stats", 0)
an.link("Route Rows", "Upsert Topic Weights", 1)

OUT = HERE
sub.dump(OUT / "RF-AI-Stage.json")
main.dump(OUT / "RF-Main.json")
err.dump(OUT / "RF-Error-Handler.json")
an.dump(OUT / "RF-Analytics.json")

# Google Sheets header files (import each as a tab of ONE spreadsheet)
sheets = HERE.parent / "sheets"
sheets.mkdir(exist_ok=True)
for name, cols in (("Videos", VIDEOS_COLS), ("TopicWeights", TOPIC_COLS), ("Errors", ERR_COLS)):
    (sheets / f"{name}.csv").write_text(",".join(cols) + "\n", encoding="utf-8")
import csv  # Characters tab is pre-seeded with the recurring cast so the first videos already use it
with open(sheets / "Characters.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(CHAR_COLS)
    for c in BRAND["cast"]:
        w.writerow([c["char_id"], c["name"], c["species"], c["short_tag"], c["visual_prompt"], c["personality"],
                    "yes", "", "", 0])
print("wrote sheet headers")
_filled = sum(1 for v in CFG["cfg"]["playlist_ids"].values() if v)
print(f"sheet_id: {'set' if SHEET_ID != SHEET_PLACEHOLDER else 'NOT SET (edit my_settings.json)'} | "
      f"playlists: {_filled}/{len(CFG['cfg']['playlist_ids'])} | upload_mode: {CFG['cfg']['upload_mode']}")
print(f"Import the RF-*.json files from {OUT}")
