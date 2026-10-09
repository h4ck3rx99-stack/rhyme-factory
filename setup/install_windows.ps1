# Rhyme Factory one-time installer for Windows 11
# Run in PowerShell as your normal user (NOT admin):
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#   .\install_windows.ps1
# Re-running is safe; finished steps are skipped.

$ErrorActionPreference = "Stop"
$Root = "C:\RhymeFactory"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Repo = Split-Path -Parent $Here

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Have($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function WingetInstall($id) {
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements
}

Step "1/9 System tools (winget)"
if (-not (Have "py"))     { WingetInstall "Python.Python.3.11" }
if (-not (Have "node"))   { WingetInstall "OpenJS.NodeJS.LTS" }     # n8n 2.x needs Node.js >= 24
if (-not (Have "git"))    { WingetInstall "Git.Git" }
if (-not (Have "ffmpeg")) { WingetInstall "Gyan.FFmpeg" }
if (-not (Have "uv"))     { WingetInstall "astral-sh.uv" }
if (-not (Have "ollama")) { WingetInstall "Ollama.Ollama" }          # optional local LLM fallback
Write-Host "If any command above was just installed, close and reopen PowerShell, then re-run this script." -ForegroundColor Yellow
Write-Host "eSpeak NG (Kokoro fallback phonemizer): install the .msi from https://github.com/espeak-ng/espeak-ng/releases" -ForegroundColor Yellow

Step "2/9 Folders"
foreach ($d in "helper","data","outbox","assets\sfx","assets\fonts","assets\audio","logs") {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}
Copy-Item "$Repo\helper\*" "$Root\helper\" -Recurse -Force
Copy-Item "$Repo\setup\start_all.bat","$Repo\setup\restart_helper.bat","$Repo\setup\stop_all.bat" "$Root\" -Force
Copy-Item "$Repo\assets\sfx\README.txt" "$Root\assets\sfx\" -Force -ErrorAction SilentlyContinue
Copy-Item "$Repo\assets\fonts\README.txt" "$Root\assets\fonts\" -Force -ErrorAction SilentlyContinue

Step "3/9 Helper .env with a random API key"
$EnvFile = "$Root\helper\.env"
if (-not (Test-Path $EnvFile)) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $key = [Convert]::ToBase64String($bytes).Replace("+","A").Replace("/","B").Replace("=","")
    (Get-Content "$Root\helper\.env.example") -replace "CHANGE_ME_TO_A_LONG_RANDOM_STRING", $key | Set-Content $EnvFile
    Write-Host "Your HELPER_API_KEY (paste into the n8n credential 'Rhyme Helper Key'):" -ForegroundColor Green
    Write-Host $key -ForegroundColor Green
} else { Write-Host ".env already exists; key unchanged." }

Step "4/9 n8n (self-hosted Community Edition, free)"
if (-not (Have "n8n")) { npm install -g n8n }
n8n --version

Step "5/9 Python venv + PyTorch (CUDA 12.8 for RTX 50-series) + helper libraries"
if (-not (Test-Path "$Root\venv")) { py -3.11 -m venv "$Root\venv" }
& "$Root\venv\Scripts\python.exe" -m pip install --upgrade pip wheel
& "$Root\venv\Scripts\pip.exe" install torch torchvision --index-url https://download.pytorch.org/whl/cu128
& "$Root\venv\Scripts\pip.exe" install -r "$Root\helper\requirements.txt"
& "$Root\venv\Scripts\python.exe" -c "import torch; print('CUDA:', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"

Step "6/9 Pre-download image models (~10 GB, one time)"
$dl = @"
from huggingface_hub import snapshot_download, hf_hub_download
snapshot_download('stabilityai/stable-diffusion-xl-base-1.0',
    allow_patterns=['*.json','*.txt','*fp16.safetensors','tokenizer*/*','scheduler/*'])
hf_hub_download('h94/IP-Adapter', 'sdxl_models/ip-adapter_sdxl_vit-h.safetensors')
snapshot_download('h94/IP-Adapter', allow_patterns=['models/image_encoder/*'])
snapshot_download('Falconsai/nsfw_image_detection')
print('image models ready')
"@
& "$Root\venv\Scripts\python.exe" -c $dl

Step "7/9 ACE-Step 1.5 (song generation API on port 8001)"
if (-not (Test-Path "$Root\ACE-Step-1.5")) {
    git clone https://github.com/ace-step/ACE-Step-1.5.git "$Root\ACE-Step-1.5"
}
Push-Location "$Root\ACE-Step-1.5"
uv sync
if (-not (Test-Path ".env")) {
@"
ACESTEP_CONFIG_PATH=acestep-v15-turbo
ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-0.6B
ACESTEP_LM_BACKEND=pt
ACESTEP_OFFLOAD_TO_CPU=true
ACESTEP_LM_OFFLOAD_TO_CPU=true
ACESTEP_OFFLOAD_DIT_TO_CPU=true
ACESTEP_API_HOST=127.0.0.1
ACESTEP_API_PORT=8001
"@ | Set-Content ".env"
}
Pop-Location

Step "8/9 Optional local LLM fallback (used only if Gemini fails or hits its daily limit)"
if (Have "ollama") { ollama pull qwen3:8b }

Step "9/9 Start everything at logon + keep the PC awake on charger"
schtasks /Create /F /TN "RhymeFactory" /TR "`"$Root\start_all.bat`"" /SC ONLOGON /RL LIMITED | Out-Null
powercfg /change standby-timeout-ac 0
Write-Host "`nDone. Next: download the two fonts (assets\fonts\README.txt), the SFX pack (assets\sfx\README.txt)," -ForegroundColor Green
Write-Host "then run $Root\start_all.bat and open http://localhost:5678" -ForegroundColor Green
