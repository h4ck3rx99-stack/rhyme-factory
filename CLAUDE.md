# Rhyme Factory: setup brief for Claude Code

You are setting up this project on the user's Windows 11 laptop (i7-13620H, 24 GB RAM, RTX 5050 Laptop 8 GB VRAM).
It is an automated, original nursery-rhyme YouTube channel, **Puddlehop Lane**: n8n (running locally) writes a
song with Gemini, a local Python helper renders pictures (SDXL), singing (ACE-Step), video (FFmpeg), subtitles and
thumbnail, and the result is logged in Google Sheets and uploaded to YouTube.

- This folder (the one holding this file) is the source folder. Older docs call it `C:\RhymeFactory-src`;
  read that as "this folder".
- The installer puts everything it runs into `C:\RhymeFactory` (helper, venv, ACE-Step, data, outbox, logs).
- Read `README.md` first, then `setup\install_windows.ps1`, `helper\.env.example`, `helper\brand.json`.
- `setup\youtube_texts.md` holds every text the user pastes into YouTube Studio.

## Rules
- Never print, log or commit secrets (Gemini key, OAuth client secret, HELPER_API_KEY). Secrets live only in
  n8n credentials and `C:\RhymeFactory\helper\.env`. Never put them in Config, the Sheet or `my_settings.json`.
- Every video is Made for Kids (`selfDeclaredMadeForKids: true`). Never change that.
- Keep `upload_mode` = `manual_outbox` until the user says YouTube's API audit is approved.
- Do not run anything as Administrator. Ask before deleting files outside `C:\RhymeFactory\data\jobs`.
- Once a real video exists, never regenerate the cast reference sheets in `C:\RhymeFactory\data\library\characters`.
- Disk is tight. Check free space on C: before installing. If under 35 GB free, skip the Ollama model
  (`ollama pull qwen3:8b`): Gemini-only is fine. After the installer finishes, run
  `C:\RhymeFactory\venv\Scripts\pip cache purge` and `uv cache clean`.

## What only the user can do (stop and ask, then continue)
1. Google sign-ins, SMS codes, 2-Step Verification.
2. YouTube: create channel "Puddlehop Lane" (handle `@PuddlehopLane`, fallbacks `@PuddlehopLaneSongs`,
   `@PuddlehopLaneKids`) via youtube.com > Settings > Add or manage your channel(s) > Create a channel; verify
   at youtube.com/verify; Studio settings and 11 playlists from `setup\youtube_texts.md`. If Claude in Chrome
   is connected you may do the clicking, but the user signs in.
3. Google Cloud console: project `rhyme-factory` (no billing); enable YouTube Data API v3, YouTube Analytics
   API, Google Sheets API, Google Drive API; OAuth consent screen External, app name "Rhyme Factory", the six
   scopes listed in `setup\youtube_texts.md`, then **Publish app** (Testing mode expires tokens after 7 days);
   Web OAuth client with redirect URI `http://localhost:5678/rest/oauth2-credential/callback`.
   Gemini key from aistudio.google.com > Get API key.
4. Approving the cast picture `C:\RhymeFactory\data\brand\cast_review.png`.
5. Creating the n8n owner account and clicking "Sign in with Google" in the three Google credentials
   (YouTube ones: pick the **Puddlehop Lane** brand account).

## Setup order (do the machine parts yourself)
1. Check: `nvidia-smi`, free disk on C:, `winget --version`.
2. Run the installer: `powershell -ExecutionPolicy Bypass -File .\setup\install_windows.ps1`.
   It may need to be re-run after winget installs (PATH changes); re-running is safe. Confirm step 5/9 prints
   `CUDA: True`. If it prints False, tell the user to update the NVIDIA driver.
3. Disk cleanup (see Rules). Optional: user installs eSpeak NG .msi.
4. Fonts: `C:\RhymeFactory\assets\fonts\Fredoka-Bold.ttf` (Google Fonts "Fredoka", static folder) and
   `LuckiestGuy-Regular.ttf`. You may download them from the official google/fonts GitHub repo
   (ofl/fredoka, ofl/luckiestguy) if reachable; otherwise ask the user.
   SFX: `assets\sfx\README.txt` lists 21 names; only CC0 sounds (user downloads from freesound.org, or skip).
5. Start services: `C:\RhymeFactory\start_all.bat`. Check `http://127.0.0.1:8765/health` and wait for
   `C:\RhymeFactory\logs\acestep.log` to show the API on 127.0.0.1:8001 (first start downloads models).
6. Brand kit: `C:\RhymeFactory\venv\Scripts\python C:\RhymeFactory\helper\make_channel_art.py`.
   Show the user `data\brand\cast_review.png`; redo a character with `--regen <char_id> --variant N`.
   User uploads `avatar_800.png` and `banner_2560x1440.png` in Studio > Customization > Profile.
7. Sheet: user creates a Google Sheet with tabs `Videos`, `TopicWeights`, `Characters`, `Errors` and imports
   the CSVs from `sheets\` (File > Import > Upload > Replace current sheet, untick "convert text").
8. `n8n\my_settings.json`: put the sheet link and the 11 playlist links (full URLs are fine). Then run
   `C:\RhymeFactory\venv\Scripts\python n8n\build_workflows.py`; it must print
   `sheet_id: set | playlists: 11/11 | upload_mode: manual_outbox`.
9. n8n at http://localhost:5678: five credentials — "Google Sheets account" (Google Sheets OAuth2 API),
   "YouTube account" (YouTube OAuth2 API), "YouTube Analytics" (Google OAuth2 API, scope
   `https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly`),
   "Gemini API Key" (Header Auth, name `x-goog-api-key`), "Rhyme Helper Key" (Header Auth, name
   `X-Helper-Key`, value = HELPER_API_KEY from `C:\RhymeFactory\helper\.env`). Import `n8n\RF-AI-Stage.json`,
   `RF-Main.json`, `RF-Error-Handler.json`, `RF-Analytics.json`; in RF - Main point the five `AI:` nodes at
   "RF - AI Stage"; assign credentials; Settings > Error workflow = RF - Error Handler.
   If the n8n public API is enabled (Settings > n8n API) and the user gives you a key for this session only,
   you may import via `POST /api/v1/workflows`; otherwise guide the user through the UI.
10. Tests: set `MOCK=1` in `C:\RhymeFactory\helper\.env`, run `C:\RhymeFactory\restart_helper.bat`, user
    clicks Execute workflow in RF - Main (~5 min). Then `MOCK=0`, render test:
    POST `helper\sample_job.json` to `http://127.0.0.1:8765/jobs` with header `X-Helper-Key`, poll
    `GET /jobs/NR-20261007-TEST`, check `C:\RhymeFactory\data\jobs\NR-20261007-TEST\final.mp4`.
    Then one full real run. A row stuck at `generating`/`rendering` blocks runs for 6 h: set it to `failed`.
11. Publish RF - Main and RF - Analytics. Runs Mon/Wed/Fri 01:30 IST; outputs land in `C:\RhymeFactory\outbox`.

## Health checks you can run any time
- `GET http://127.0.0.1:8765/health`, `GET /status` (needs the key header), `logs\helper.log`, `logs\acestep.log`,
  `logs\n8n.log`.
