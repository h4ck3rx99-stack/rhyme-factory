# Rhyme Factory

Automated, original nursery-rhyme videos: idea -> song -> storyboard -> pictures -> singing -> video ->
subtitles -> thumbnail -> QC -> YouTube -> Google Sheets log. The full explanation is in the build guide doc;
this file is the short version.

## What is in this folder

| Path | What it is |
| --- | --- |
| `n8n/RF-Main.json` | Main pipeline (45 nodes). Import into n8n. |
| `n8n/RF-AI-Stage.json` | Sub-workflow: one AI call with Gemini -> Ollama fallback, JSON validation, 3 attempts. |
| `n8n/RF-Error-Handler.json` | Marks failed runs in Google Sheets. |
| `n8n/RF-Analytics.json` | Weekly stats + topic weights. |
| `n8n/src/*.js` | Readable source of every Code node (already embedded in the JSON). |
| `n8n/my_settings.json` | Your sheet ID, playlist IDs and upload mode. Fill it, then run the build script. |
| `n8n/build_workflows.py` | Regenerates the JSON from `src/`, `helper/brand.json` and `my_settings.json`. |
| `helper/rhyme_helper.py` | Local render service n8n calls (images, singing, video, thumbnail, media QC). |
| `helper/sample_job.json` | Example render job; also the job schema reference. |
| `helper/brand.json` | The channel brand: Puddlehop Lane, cast bibles, world, style, playlists, art prompts. Single source of truth. |
| `helper/make_channel_art.py` | Generates cast reference sheets, profile picture, banner, jingle and outro music. |
| `sheets/*.csv` | Header rows for the four Google Sheets tabs. |
| `setup/install_windows.ps1` | One-time installer for Windows 11. |
| `setup/start_all.bat` | Starts ACE-Step, the helper and n8n (Task Scheduler runs it at logon). |
| `assets/` | Put fonts, sound effects and optional jingles here (see the README in each folder). |

## Quick start

The detailed, click-by-click version is the "Setup walkthrough" tab of the build guide.

1. Create the YouTube channel "Puddlehop Lane" and its 11 playlists; paste each playlist link into
   `n8n\my_settings.json`.
2. Copy this folder to `C:\RhymeFactory-src`, open PowerShell there, run `setup\install_windows.ps1`.
   It prints your `HELPER_API_KEY`.
3. Download the two fonts and the SFX pack (`assets\fonts\README.txt`, `assets\sfx\README.txt`).
4. Run `C:\RhymeFactory\start_all.bat`, then
   `C:\RhymeFactory\venv\Scripts\python C:\RhymeFactory\helper\make_channel_art.py` and approve the cast in
   `data\brand\cast_review.png`. Upload `avatar_800.png` and `banner_2560x1440.png` to the channel.
5. Google Cloud: one project, 4 APIs, OAuth consent screen *published*, one Web OAuth client.
6. Create one Google Sheet with tabs `Videos`, `TopicWeights`, `Characters`, `Errors`; import each CSV
   from `sheets\` into its tab (File -> Import -> Upload -> Replace current sheet). Paste the sheet link
   into `my_settings.json`, then run `C:\RhymeFactory\venv\Scripts\python C:\RhymeFactory-src\n8n\build_workflows.py`.
7. http://localhost:5678: owner account, five credentials, import the four JSON files, pick
   "RF - AI Stage" in the five AI nodes, assign credentials, Settings -> Error workflow = "RF - Error Handler".
8. Test with `MOCK=1` in `C:\RhymeFactory\helper\.env` first (no GPU models, about 4 minutes), then
   `MOCK=0`. Publish RF - Main and RF - Analytics.

## Test the helper without n8n

```
curl -X POST -H "X-Helper-Key: YOUR_KEY" -H "Content-Type: application/json" ^
     --data @helper\sample_job.json http://127.0.0.1:8765/jobs
curl -H "X-Helper-Key: YOUR_KEY" http://127.0.0.1:8765/jobs/NR-20261007-TEST
```
