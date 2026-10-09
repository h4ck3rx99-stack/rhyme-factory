#!/usr/bin/env python3
"""
Rhyme Factory local helper
==========================
A small HTTP service that runs on YOUR Windows PC and does everything n8n cannot:
  * song with sung vocals  -> ACE-Step 1.5 API (local, MIT licence)
  * spoken hook / outro    -> Kokoro-82M TTS (local, Apache-2.0)
  * lyric timing           -> faster-whisper word timestamps (local, MIT)
  * images                 -> SDXL + IP-Adapter via diffusers (local)
  * video                  -> FFmpeg (pan/zoom, transitions, karaoke subtitles, mix)
  * thumbnail              -> Pillow composite, 1280x720
  * media QC               -> ffprobe / ebur128 / blackdetect checks

n8n talks to it over HTTP:
  GET  /health                         (no auth)  liveness
  GET  /status                         (auth)     dependency report
  POST /jobs                           (auth)     submit a render job (JSON, see sample_job.json)
  GET  /jobs/{video_id}                (auth)     job status + outputs + media QC
  GET  /files/{video_id}/{name}        (auth)     download final.mp4 / thumbnail.jpg / subtitles.srt
  POST /jobs/{video_id}/outbox         (auth)     copy finished files to OUTBOX_DIR for manual upload
  POST /jobs/{video_id}/retry          (auth)     resume a failed job from the stage that failed

Auth: every request except /health must send header  X-Helper-Key: <HELPER_API_KEY>.
Only Python stdlib + numpy + Pillow are required for MOCK=1 (wiring test without GPU models).
"""
from __future__ import annotations

import difflib
import gc
import hashlib
import hmac
import json
import math
import os
import queue
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

# ----------------------------------------------------------------------------
# Configuration (.env next to this file, then real environment variables win)
# ----------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(HERE / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_int(name: str, default: int) -> int:
    try:
        return int(env(name, str(default)))
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        return default


HOST = env("HELPER_HOST", "127.0.0.1")
PORT = env_int("HELPER_PORT", 8765)
API_KEY = env("HELPER_API_KEY", "")
DATA_DIR = Path(env("DATA_DIR", str(HERE.parent / "data"))).resolve()
ASSETS_DIR = Path(env("ASSETS_DIR", str(HERE.parent / "assets"))).resolve()
OUTBOX_DIR = Path(env("OUTBOX_DIR", str(DATA_DIR / "outbox"))).resolve()
FFMPEG = env("FFMPEG", "ffmpeg")
FFPROBE = env("FFPROBE", "ffprobe")
MOCK = env("MOCK", "0") == "1"

ACESTEP_URL = env("ACESTEP_URL", "http://127.0.0.1:8001").rstrip("/")
ACESTEP_API_KEY = env("ACESTEP_API_KEY", "")
ACESTEP_TIMEOUT_S = env_int("ACESTEP_TIMEOUT_S", 900)

SDXL_MODEL = env("SDXL_MODEL", "stabilityai/stable-diffusion-xl-base-1.0")
USE_IP_ADAPTER = env("USE_IP_ADAPTER", "1") == "1"
IP_ADAPTER_SCALE = env_float("IP_ADAPTER_SCALE", 0.55)
SDXL_STEPS = env_int("SDXL_STEPS", 28)
SDXL_GUIDANCE = env_float("SDXL_GUIDANCE", 6.0)
IMG_W = env_int("IMG_W", 1344)
IMG_H = env_int("IMG_H", 768)
NSFW_CHECK = env("NSFW_CHECK", "1") == "1"
NSFW_MODEL = env("NSFW_MODEL", "Falconsai/nsfw_image_detection")

KOKORO_VOICE = env("KOKORO_VOICE", "af_heart")
KOKORO_SPEED = env_float("KOKORO_SPEED", 0.95)
WHISPER_MODEL = env("WHISPER_MODEL", "small.en")
WHISPER_DEVICE = env("WHISPER_DEVICE", "cpu")

VIDEO_ENCODER = env("VIDEO_ENCODER", "libx264")  # or h264_nvenc
SUB_FONT_NAME = env("SUB_FONT_NAME", "Fredoka")
SUB_FONT_SIZE = env_int("SUB_FONT_SIZE", 76)
TITLE_FONT_FILE = env("TITLE_FONT_FILE", "LuckiestGuy-Regular.ttf")
KEEP_INTERMEDIATE_DAYS = env_int("KEEP_INTERMEDIATE_DAYS", 7)
CLIP_WORKERS = env_int("CLIP_WORKERS", 3)

ALLOWED_FILES = {"final.mp4", "thumbnail.jpg", "subtitles.srt", "subs.ass", "song.wav",
                 "mix.wav", "status.json", "job.json", "timeline.json"}
CAMERA_MOVES = {"zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static"}
TRANSITIONS = {"fade", "dissolve", "slideleft", "slideright", "wipeleft", "wiperight",
               "circleopen", "circleclose", "smoothleft", "smoothright", "radial"}
STAGES = ["validate", "song", "voice", "images", "timeline", "subtitles", "mix",
          "clips", "video", "thumbnail", "qc"]

JOBS_DIR = DATA_DIR / "jobs"
LIB_DIR = DATA_DIR / "library" / "characters"
for d in (JOBS_DIR, LIB_DIR, OUTBOX_DIR):
    d.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    print(time.strftime("%H:%M:%S"), msg, flush=True)


# ----------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------
class JobError(Exception):
    """Fails the job with a readable reason (shown in n8n + Google Sheets)."""


def safe_id(video_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", video_id or ""):
        raise JobError(f"invalid video_id: {video_id!r}")
    return video_id


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def stable_seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16) % 2_147_483_647


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 3600) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        raise JobError(f"command failed ({cmd[0]}): {tail}")
    return (proc.stdout or "") + (proc.stderr or "")


def norm_words(text: str) -> list[str]:
    text = text.lower().replace("’", "'")
    return re.findall(r"[a-z0-9']+", text)


def http_json(method: str, url: str, body=None, headers=None, timeout: int = 60):
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_download(url: str, dest: Path, headers=None, timeout: int = 300) -> None:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


# ----------------------------------------------------------------------------
# Audio helpers (everything is converted to 48 kHz stereo float32 for mixing)
# ----------------------------------------------------------------------------
SR = 48000


def load_audio(path: Path) -> np.ndarray:
    out = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "2",
                          "-ar", str(SR), "-"], capture_output=True, timeout=600)
    if out.returncode != 0:
        raise JobError(f"cannot decode audio {path.name}: {out.stderr.decode(errors='ignore')[-400:]}")
    return np.frombuffer(out.stdout, dtype=np.float32).reshape(-1, 2).copy()


def save_wav(path: Path, audio: np.ndarray, sr: int = SR) -> None:
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def audio_duration(path: Path) -> float:
    out = run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of",
               "default=nw=1:nk=1", str(path)])
    try:
        return float(out.strip().splitlines()[0])
    except Exception as exc:
        raise JobError(f"cannot read duration of {path.name}") from exc


def mix_tracks(tracks: list[tuple[np.ndarray, float, float]], total_s: float) -> np.ndarray:
    n = int(total_s * SR) + 1
    bus = np.zeros((n, 2), dtype=np.float32)
    for audio, offset, gain in tracks:
        start = max(0, int(offset * SR))
        if start >= n or audio.size == 0:
            continue
        end = min(n, start + audio.shape[0])
        bus[start:end] += audio[: end - start] * gain
    peak = float(np.max(np.abs(bus))) if bus.size else 0.0
    if peak > 0.98:
        bus *= 0.98 / peak
    return bus


def atempo(src: Path, dst: Path, factor: float) -> None:
    factor = max(0.5, min(2.0, factor))
    run([FFMPEG, "-y", "-v", "error", "-i", str(src), "-filter:a", f"atempo={factor:.4f}", str(dst)])


# ----------------------------------------------------------------------------
# Procedural music + mock voice (used for MOCK=1 and as last-resort fallback)
# ----------------------------------------------------------------------------
NOTE = {"C": 261.63, "D": 293.66, "E": 329.63, "F": 349.23, "G": 392.0, "A": 440.0, "B": 493.88}


def procedural_backing(bpm: int, seconds: float, seed: int = 1) -> np.ndarray:
    """Original, licence-free toy-piano + soft beat backing track (I-V-vi-IV)."""
    rng = random.Random(seed)
    beat = 60.0 / max(60, min(160, bpm))
    t_total = int(seconds * SR)
    out = np.zeros(t_total, dtype=np.float32)
    chords = [("C", "E", "G"), ("G", "B", "D"), ("A", "C", "E"), ("F", "A", "C")]
    order = rng.choice([[0, 1, 2, 3], [0, 3, 1, 0], [0, 2, 3, 1]])

    def tone(freq: float, dur: float, vol: float) -> np.ndarray:
        n = int(dur * SR)
        t = np.arange(n) / SR
        wave_ = 2 * np.abs(2 * ((t * freq) % 1) - 1) - 1  # triangle
        env = np.exp(-3.5 * t / max(dur, 1e-3))
        return (wave_ * env * vol).astype(np.float32)

    step = beat / 2
    i = 0
    t = 0.0
    while t < seconds:
        bar = int(t / (4 * beat))
        chord = chords[order[bar % 4]]
        note = chord[[0, 1, 2, 1][i % 4]]
        freq = NOTE[note] * (2 if i % 8 in (5, 6) else 1)
        seg = tone(freq, step * 1.6, 0.18)
        s = int(t * SR)
        e = min(t_total, s + seg.size)
        out[s:e] += seg[: e - s]
        if i % 2 == 0:  # soft kick on each beat
            kn = int(0.12 * SR)
            kt = np.arange(kn) / SR
            kick = np.sin(2 * np.pi * (90 - 40 * kt / 0.12) * kt) * np.exp(-25 * kt) * 0.35
            e2 = min(t_total, s + kn)
            out[s:e2] += kick[: e2 - s].astype(np.float32)
        if i % 8 == 0:  # bass note per bar
            bass = tone(NOTE[chord[0]] / 2, 4 * beat, 0.16)
            e3 = min(t_total, s + bass.size)
            out[s:e3] += bass[: e3 - s]
        t += step
        i += 1
    fade = int(1.5 * SR)
    if t_total > 2 * fade:
        out[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
    return np.stack([out, out], axis=1)


def mock_voice(text: str) -> np.ndarray:
    """Placeholder 'voice': one soft blip per word so timing can be checked by ear."""
    words = norm_words(text) or ["hi"]
    per = 0.32
    n = int(len(words) * per * SR) + int(0.2 * SR)
    out = np.zeros(n, dtype=np.float32)
    for i, w in enumerate(words):
        f = 330 + 40 * (len(w) % 5)
        m = int(0.22 * SR)
        t = np.arange(m) / SR
        blip = np.sin(2 * np.pi * f * t) * np.hanning(m) * 0.3
        s = int(i * per * SR)
        out[s:s + m] += blip.astype(np.float32)
    return np.stack([out, out], axis=1)


# ----------------------------------------------------------------------------
# Model wrappers (lazy-loaded, released after use so 8 GB VRAM is enough)
# ----------------------------------------------------------------------------
class Kokoro:
    _pipe = None

    @classmethod
    def say(cls, text: str, dest: Path, voice: str | None = None, speed: float | None = None) -> Path:
        if MOCK:
            save_wav(dest, mock_voice(text))
            return dest
        if cls._pipe is None:
            from kokoro import KPipeline  # pip install kokoro
            try:  # CPU keeps the GPU free for SDXL; Kokoro is fast enough on an i7
                cls._pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", device="cpu")
            except TypeError:
                cls._pipe = KPipeline(lang_code="a")
        chunks = []
        for _gs, _ps, audio in cls._pipe(text, voice=voice or KOKORO_VOICE, speed=speed or KOKORO_SPEED):
            if audio is None:
                continue
            a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(a.astype(np.float32).reshape(-1))
        if not chunks:
            raise JobError(f"Kokoro produced no audio for: {text[:60]}")
        save_wav(dest, np.concatenate(chunks), sr=24000)
        return dest


class Whisper:
    _model = None

    @classmethod
    def words(cls, path: Path) -> list[dict]:
        if cls._model is None:
            from faster_whisper import WhisperModel  # pip install faster-whisper
            compute = "int8" if WHISPER_DEVICE == "cpu" else "float16"
            cls._model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=compute)
        segments, _info = cls._model.transcribe(str(path), language="en", word_timestamps=True,
                                                vad_filter=False, beam_size=5)
        out = []
        for seg in segments:
            for w in seg.words or []:
                for tok in norm_words(w.word):
                    out.append({"w": tok, "start": float(w.start), "end": float(w.end)})
        return out


class Painter:
    """SDXL (+ optional IP-Adapter) image generation with explicit VRAM release."""

    def __init__(self) -> None:
        self.pipe = None
        self.ip_loaded = False
        self.nsfw = None

    def _load(self) -> None:
        import torch
        from diffusers import StableDiffusionXLPipeline
        kwargs = {"torch_dtype": torch.float16, "use_safetensors": True}
        if not Path(SDXL_MODEL).exists():
            kwargs["variant"] = "fp16"
        self.pipe = StableDiffusionXLPipeline.from_pretrained(SDXL_MODEL, **kwargs)
        self.pipe.enable_model_cpu_offload()
        self.pipe.vae.enable_tiling()  # pipeline-level enable_vae_tiling() was removed in diffusers 0.41

    def _ensure_ip(self) -> None:
        if self.ip_loaded or not USE_IP_ADAPTER:
            return
        self.pipe.load_ip_adapter("h94/IP-Adapter", subfolder="sdxl_models",
                                  weight_name="ip-adapter_sdxl_vit-h.safetensors",
                                  image_encoder_folder="models/image_encoder")
        self.pipe.enable_model_cpu_offload()  # re-register offload hooks so the image encoder is managed too
        self.ip_loaded = True

    def _nsfw_score(self, img: Image.Image) -> float:
        if not NSFW_CHECK or MOCK:
            return 0.0
        if self.nsfw is None:
            from transformers import pipeline
            self.nsfw = pipeline("image-classification", model=NSFW_MODEL, device=-1)
        for r in self.nsfw(img):
            if r["label"].lower() in ("nsfw", "porn", "sexy", "hentai"):
                return float(r["score"])
        return 0.0

    @staticmethod
    def _looks_ok(img: Image.Image) -> tuple[bool, str]:
        arr = np.asarray(img.convert("L"), dtype=np.float32)
        mean, std = float(arr.mean()), float(arr.std())
        if std < 14:
            return False, f"image nearly flat (std {std:.1f})"
        if mean < 35:
            return False, f"image too dark (mean {mean:.0f})"
        if mean > 240:
            return False, f"image washed out (mean {mean:.0f})"
        return True, "ok"

    def generate(self, prompt: str, negative: str, seed: int, dest: Path, ref: Path | None,
                 ref_scale: float, width: int, height: int, attempts: int = 2, label: str = "") -> Path:
        if MOCK:
            mock_image(prompt, dest, width, height, seed, label)
            return dest
        import torch
        if self.pipe is None:
            self._load()
        last_reason = ""
        for k in range(attempts + 1):
            kwargs = dict(prompt=prompt, negative_prompt=negative, width=width, height=height,
                          num_inference_steps=SDXL_STEPS, guidance_scale=SDXL_GUIDANCE,
                          generator=torch.Generator("cpu").manual_seed(seed + 1009 * k))
            if self.ip_loaded:
                if ref is not None and ref.exists():
                    self.pipe.set_ip_adapter_scale(ref_scale)
                    kwargs["ip_adapter_image"] = Image.open(ref).convert("RGB")
                else:  # IP-Adapter loaded but no character: neutral reference at scale 0
                    self.pipe.set_ip_adapter_scale(0.0)
                    kwargs["ip_adapter_image"] = Image.new("RGB", (224, 224), "white")
            img = self.pipe(**kwargs).images[0]
            ok, reason = self._looks_ok(img)
            score = self._nsfw_score(img)
            if ok and score < 0.2:
                img.save(dest)
                return dest
            last_reason = reason if not ok else f"safety classifier score {score:.2f}"
            log(f"   image retry {k + 1} for {dest.name}: {last_reason}")
        raise JobError(f"image generation failed for {dest.name} after {attempts + 1} tries: {last_reason}")

    def release(self) -> None:
        self.pipe = None
        self.ip_loaded = False
        self.nsfw = None
        gc.collect()
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass


def mock_image(prompt: str, dest: Path, width: int, height: int, seed: int, label: str) -> None:
    rng = random.Random(seed)
    base = [rng.randint(120, 230) for _ in range(3)]
    img = Image.new("RGB", (width, height), tuple(base))
    draw = ImageDraw.Draw(img)
    for _ in range(14):
        r = rng.randint(40, 200)
        x, y = rng.randint(0, width), rng.randint(0, height)
        col = tuple(rng.randint(60, 255) for _ in range(3))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
    font = load_font(None, 40)
    draw.rectangle([0, height - 120, width, height], fill=(255, 255, 255))
    draw.text((30, height - 105), (label or "scene")[:60], fill=(40, 40, 60), font=font)
    draw.text((30, height - 55), prompt[:110], fill=(90, 90, 110), font=load_font(None, 20))
    img.save(dest)


# ----------------------------------------------------------------------------
# Fonts / text drawing
# ----------------------------------------------------------------------------
FONT_FALLBACKS = ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf",
                  "/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def load_font(file_name: str | None, size: int) -> ImageFont.FreeTypeFont:
    candidates = []
    if file_name:
        candidates += [str(ASSETS_DIR / "fonts" / file_name), file_name]
    candidates += FONT_FALLBACKS
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def fit_text(draw: ImageDraw.ImageDraw, text: str, font_file: str | None, max_w: int,
             max_h: int, start: int = 150) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    words = text.split()
    size = start
    while size > 24:
        font = load_font(font_file, size)
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        line_h = font.size * 1.12
        widest = max((draw.textlength(l, font=font) for l in lines), default=0)
        if len(lines) * line_h <= max_h and widest <= max_w:
            return font, lines
        size -= 6
    return load_font(font_file, 24), [text]


def draw_outlined(img: Image.Image, lines: list[str], font, x: int, y: int, fill=(255, 230, 0),
                  stroke=(60, 20, 90), stroke_w: int = 10, align: str = "left") -> None:
    draw = ImageDraw.Draw(img)
    line_h = int(font.size * 1.12)
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        lx = x - w / 2 if align == "center" else x
        # soft drop shadow
        draw.text((lx + 6, y + i * line_h + 8), line, font=font, fill=(0, 0, 0),
                  stroke_width=stroke_w, stroke_fill=(0, 0, 0))
        draw.text((lx, y + i * line_h), line, font=font, fill=fill,
                  stroke_width=stroke_w, stroke_fill=stroke)


def cover_resize(img: Image.Image, w: int, h: int) -> Image.Image:
    scale = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


# ----------------------------------------------------------------------------
# Lyric alignment
# ----------------------------------------------------------------------------
def align_lines(lines: list[str], words: list[dict], song_len: float) -> tuple[list[dict], float]:
    """Map known lyric lines onto whisper word timestamps. Returns (timings, recall)."""
    lyric_tokens, owner = [], []
    for li, line in enumerate(lines):
        for tok in norm_words(line):
            lyric_tokens.append(tok)
            owner.append(li)
    heard = [w["w"] for w in words]
    sm = difflib.SequenceMatcher(None, lyric_tokens, heard, autojunk=False)
    tok_time: dict[int, tuple[float, float]] = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            tok_time[a + k] = (words[b + k]["start"], words[b + k]["end"])
    recall = len(tok_time) / max(1, len(lyric_tokens))

    per_line: list[dict] = []
    for li, line in enumerate(lines):
        idx = [i for i, o in enumerate(owner) if o == li]
        times = [tok_time[i] for i in idx if i in tok_time]
        per_line.append({"idx": li, "text": line,
                         "start": min(t[0] for t in times) if times else None,
                         "end": max(t[1] for t in times) if times else None,
                         "words": [{"w": lyric_tokens[i], "start": tok_time[i][0], "end": tok_time[i][1]}
                                   for i in idx if i in tok_time]})
    # interpolate unmatched lines between known neighbours (proportional to word count)
    n = len(per_line)
    i = 0
    while i < n:
        if per_line[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < n and per_line[j]["start"] is None:
            j += 1
        t0 = per_line[i - 1]["end"] if i > 0 else 0.5
        t1 = per_line[j]["start"] if j < n else song_len - 1.0
        if t1 <= t0:
            t1 = t0 + 2.5 * (j - i)
        weights = [max(1, len(norm_words(per_line[k]["text"]))) for k in range(i, j)]
        total_w = sum(weights)
        cur = t0
        for k, wgt in zip(range(i, j), weights):
            span = (t1 - t0) * wgt / total_w
            per_line[k]["start"], per_line[k]["end"] = cur + 0.05, cur + span - 0.05
            per_line[k]["words"] = []
            cur += span
        i = j
    # monotonic clean-up
    for k in range(1, n):
        if per_line[k]["start"] < per_line[k - 1]["start"]:
            per_line[k]["start"] = per_line[k - 1]["end"]
        if per_line[k]["end"] <= per_line[k]["start"]:
            per_line[k]["end"] = per_line[k]["start"] + 1.0
    return per_line, recall


# ----------------------------------------------------------------------------
# The render pipeline
# ----------------------------------------------------------------------------
class Job:
    def __init__(self, video_id: str):
        self.id = safe_id(video_id)
        self.dir = JOBS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("images", "audio", "clips", "fonts"):
            (self.dir / sub).mkdir(exist_ok=True)
        self.spec = read_json(self.dir / "job.json", {})
        self.status_path = self.dir / "status.json"

    # -- status ---------------------------------------------------------------
    def status(self) -> dict:
        return read_json(self.status_path, {"video_id": self.id, "status": "unknown"})

    def set_status(self, **kw) -> dict:
        st = self.status()
        st.update(kw)
        st["video_id"] = self.id
        st["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        write_json(self.status_path, st)
        return st

    def stage_done(self, stage: str) -> bool:
        return (self.dir / f".done_{stage}").exists()

    def mark_done(self, stage: str, seconds: float) -> None:
        (self.dir / f".done_{stage}").write_text(str(seconds))
        st = self.status()
        timings = st.get("timings", {})
        timings[stage] = round(seconds, 1)
        self.set_status(timings=timings)

    # -- driver ---------------------------------------------------------------
    def run(self) -> None:
        self.set_status(status="running", started_at=self.status().get("started_at") or
                        time.strftime("%Y-%m-%dT%H:%M:%S%z"), error=None)
        for i, stage in enumerate(STAGES):
            if self.stage_done(stage):
                continue
            self.set_status(stage=stage, progress=int(100 * i / len(STAGES)), message="")
            log(f"[{self.id}] stage {stage}")
            t0 = time.time()
            getattr(self, f"stage_{stage}")()
            self.mark_done(stage, time.time() - t0)
        qc = read_json(self.dir / "media_qc.json", {})
        final = "done" if qc.get("pass") else "failed"
        self.set_status(status=final, stage="finished", progress=100,
                        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                        error=None if final == "done" else "media QC failed: " +
                        "; ".join(k for k, v in qc.get("checks", {}).items() if not v.get("ok")))

    # -- helpers --------------------------------------------------------------
    def all_lines(self) -> list[dict]:
        out = []
        for sec in self.spec["song"]["sections"]:
            for li, text in enumerate(sec.get("lines", [])):
                out.append({"gi": len(out), "section_id": sec["section_id"],
                            "type": sec.get("type", "verse"), "li": li, "text": text})
        return out

    # -- stages ---------------------------------------------------------------
    def stage_validate(self) -> None:
        s = self.spec
        for key in ("video_id", "title", "song", "scenes", "characters", "style_bible"):
            if key not in s:
                raise JobError(f"job.json missing '{key}'")
        if not s["song"].get("sections"):
            raise JobError("song.sections is empty")
        lines = self.all_lines()
        if len(lines) < 8:
            raise JobError(f"only {len(lines)} lyric lines; need at least 8")
        if not 4 <= len(s["scenes"]) <= 60:
            raise JobError(f"scene count {len(s['scenes'])} outside 4..60")
        for sc in s["scenes"]:
            if not sc.get("prompt"):
                raise JobError(f"scene {sc.get('scene_id')} has no prompt")
            bad = [g for g in sc.get("lines", []) if not 0 <= int(g) < len(lines)]
            if bad:
                raise JobError(f"scene {sc.get('scene_id')} references unknown lines {bad}")
        fonts = ASSETS_DIR / "fonts"
        if fonts.exists():
            for f in fonts.glob("*.[ot]tf"):
                shutil.copy2(f, self.dir / "fonts" / f.name)

    def _ace_lyrics(self) -> str:
        parts, verse_n = [], 0
        for sec in self.spec["song"]["sections"]:
            typ = sec.get("type", "verse")
            if typ == "verse":
                verse_n += 1
                tag = f"[Verse {verse_n}]"
            else:
                tag = {"chorus": "[Chorus]", "bridge": "[Bridge]", "intro": "[Intro]",
                       "outro": "[Outro]", "pre_chorus": "[Pre-Chorus]"}.get(typ, "[Verse]")
            parts.append(tag + "\n" + "\n".join(sec.get("lines", [])))
        return "\n\n".join(parts)

    def _ace_generate(self, lyrics: str, caption: str, duration: float, seed: int, dest: Path) -> Path:
        m = self.spec["song"].get("music", {})
        headers = {"Authorization": f"Bearer {ACESTEP_API_KEY}"} if ACESTEP_API_KEY else {}
        body = {"prompt": caption, "lyrics": lyrics, "audio_duration": round(duration, 1),
                "bpm": int(m.get("bpm", 110)), "key_scale": m.get("key", "C Major"),
                "time_signature": str(m.get("time_signature", "4")), "vocal_language": "en",
                "thinking": True, "batch_size": 1, "inference_steps": 8, "audio_format": "wav",
                "use_random_seed": False, "seed": seed}
        resp = http_json("POST", f"{ACESTEP_URL}/release_task", body, headers, timeout=60)
        task_id = (resp.get("data") or {}).get("task_id")
        if not task_id:
            raise JobError(f"ACE-Step did not return a task_id: {str(resp)[:300]}")
        deadline = time.time() + ACESTEP_TIMEOUT_S
        while time.time() < deadline:
            time.sleep(4)
            q = http_json("POST", f"{ACESTEP_URL}/query_result", {"task_id_list": [task_id]},
                          headers, timeout=60)
            rows = q.get("data") or []
            if not rows:
                continue
            row = rows[0]
            if row.get("status") == 2:
                raise JobError(f"ACE-Step task failed: {str(row)[:300]}")
            if row.get("status") == 1:
                result = row.get("result")
                items = json.loads(result) if isinstance(result, str) else result
                file_url = items[0]["file"]
                if file_url.startswith("/"):
                    file_url = ACESTEP_URL + file_url
                http_download(file_url, dest, headers)
                return dest
        raise JobError("ACE-Step timed out")

    def stage_song(self) -> None:
        """Sung version via ACE-Step; falls back to spoken 'chant' over an instrumental."""
        song = self.spec["song"]
        music = song.get("music", {})
        qc = self.spec.get("qc", {})
        lines = [l["text"] for l in self.all_lines()]
        target = float(music.get("target_duration_s", 150))
        threshold = float(qc.get("min_intelligibility", 0.55))
        max_tries = int(qc.get("max_song_attempts", 3))
        caption = music.get("caption") or "cheerful children's nursery rhyme, bright female vocal, ukulele, glockenspiel"
        base_seed = stable_seed(self.id + "song")
        best = None
        if not MOCK and env("SONG_MODE", "sung") == "sung":
            for k in range(max_tries):
                dest = self.dir / "audio" / f"song_try{k}.wav"
                try:
                    self._ace_generate(self._ace_lyrics(), caption, target, base_seed + k, dest)
                    dur = audio_duration(dest)
                    timings, recall = align_lines(lines, Whisper.words(dest), dur)
                    log(f"   song try {k + 1}: intelligibility {recall:.2f}")
                    if best is None or recall > best["intelligibility"]:
                        best = {"path": dest, "duration": dur, "lines": timings,
                                "intelligibility": recall, "attempts": k + 1}
                    if recall >= threshold:
                        break
                except (JobError, urllib.error.URLError, OSError) as exc:
                    log(f"   song try {k + 1} failed: {exc}")
        if best and best["intelligibility"] >= threshold:
            lines_t, dur, trimmed = best["lines"], best["duration"], 0.0
            first = lines_t[0]["start"] if lines_t else 0.0
            if first > float(qc.get("max_intro_s", 4.0)):  # long instrumental intro loses young viewers
                trimmed = round(first - 1.5, 3)
                run([FFMPEG, "-y", "-v", "error", "-ss", f"{trimmed:.3f}", "-i", str(best["path"]),
                     "-af", "afade=t=in:st=0:d=0.4", str(self.dir / "song.wav")])
                for ln in lines_t:
                    ln["start"] -= trimmed
                    ln["end"] -= trimmed
                    for w in ln.get("words", []):
                        w["start"] -= trimmed
                        w["end"] -= trimmed
                dur = audio_duration(self.dir / "song.wav")
            else:
                shutil.copy2(best["path"], self.dir / "song.wav")
            out = {"mode": "sung", "duration": dur, "lines": lines_t, "intro_trimmed_s": trimmed,
                   "intelligibility": round(best["intelligibility"], 3), "attempts": best["attempts"]}
        else:
            reason = (f"best sung take intelligibility {best['intelligibility']:.2f} < {threshold}"
                      if best else "sung mode unavailable")
            log(f"   falling back to chant mode ({reason})")
            out = self._chant(lines, music, caption, base_seed)
            out["fallback_reason"] = reason
        write_json(self.dir / "song.json", out)

    def _chant(self, lines: list[str], music: dict, caption: str, seed: int) -> dict:
        bpm = int(music.get("bpm", 108))
        bar = 4 * 60.0 / bpm
        cursor = 1 * bar  # one-bar intro: the hook starts fast
        timings = []
        sections = self.spec["song"]["sections"]
        gi = 0
        for sec in sections:
            for text in sec.get("lines", []):
                raw = self.dir / "audio" / f"chant_{gi:03d}.wav"
                Kokoro.say(text, raw)
                d = audio_duration(raw)
                # smallest slot (2, 3 or 4 bars) the line fits into with at most x1.3 speed-up
                slot_bars = next((b for b in (2, 3, 4) if d <= b * bar * 0.92 * 1.3), 4)
                slot = slot_bars * bar
                if d > slot * 0.92:
                    fitted = raw.with_name(raw.stem + "_fit.wav")
                    atempo(raw, fitted, min(1.3, d / (slot * 0.9)))
                    raw, d = fitted, audio_duration(fitted)
                timings.append({"idx": gi, "text": text, "start": cursor + 0.1,
                                "end": cursor + 0.1 + d, "words": [], "file": raw.name})
                cursor += slot
                gi += 1
            cursor += bar  # breath between sections
        total = cursor + 2 * bar
        inst = self.dir / "audio" / "instrumental.wav"
        got_inst = False
        if not MOCK:
            try:
                self._ace_generate("[Instrumental]", caption + ", instrumental, no vocals", total, seed, inst)
                got_inst = True
            except (JobError, urllib.error.URLError, OSError) as exc:
                log(f"   ACE-Step instrumental failed ({exc}); using procedural backing")
        backing = load_audio(inst) if got_inst else procedural_backing(bpm, total, seed)
        tracks = [(backing, 0.0, 0.55 if got_inst else 0.7)]
        for t in timings:
            tracks.append((load_audio(self.dir / "audio" / t.pop("file")), t["start"], 1.0))
        save_wav(self.dir / "song.wav", mix_tracks(tracks, total))
        return {"mode": "chant", "duration": total, "lines": timings, "intelligibility": 1.0,
                "attempts": 1, "backing": "ace-step" if got_inst else "procedural"}

    def stage_voice(self) -> None:
        v = self.spec.get("voice", {})
        hook = v.get("hook_text") or f"Hello friends! Let's sing {self.spec['title']}!"
        outro = v.get("outro_text") or "Bye-bye, friends! See you next time!"
        Kokoro.say(hook, self.dir / "audio" / "hook.wav", v.get("voice"))
        Kokoro.say(outro, self.dir / "audio" / "outro.wav", v.get("voice"))

    def stage_images(self) -> None:
        s = self.spec
        style = s["style_bible"]
        neg = style.get("negative", "")
        if not MOCK:
            # SDXL needs ~6 GB; if another process (e.g. ACE-Step without ACESTEP_OFFLOAD_DIT_TO_CPU=true)
            # still holds VRAM, Windows spills into shared memory and images get ~50x slower.
            import torch
            if torch.cuda.is_available():
                free_gb = torch.cuda.mem_get_info()[0] / 2**30
                if free_gb < 6.0:
                    log(f"[{self.id}] WARNING: only {free_gb:.1f} GB VRAM free before images; "
                        "check ACE-Step offload settings in ACE-Step-1.5\\.env")
        painter = Painter()
        refs: dict[str, Path] = {}
        try:
            # 1) character reference sheets (reused across videos => consistent recurring stars)
            for ch in s["characters"]:
                cid = re.sub(r"[^a-z0-9_-]", "", ch["char_id"].lower()) or "char"
                ref = LIB_DIR / f"{cid}.png"
                if not ref.exists():
                    prompt = (f"{style.get('positive', '')}, character reference sheet, one character only, "
                              f"full body, front view, standing, {ch['visual_prompt']}, plain white background")
                    painter.generate(prompt, neg, int(ch.get("seed") or stable_seed(cid)), ref, None, 0.0,
                                     1024, 1024, label=f"ref {ch.get('name', cid)}")
                refs[ch["char_id"]] = ref
            if not MOCK and USE_IP_ADAPTER and painter.pipe is not None:
                painter._ensure_ip()
            elif not MOCK and USE_IP_ADAPTER:
                painter._load()
                painter._ensure_ip()
            # 2) scenes, cards and thumbnail
            base_seed = stable_seed(self.id + "img")
            jobs = [(f"scene_{int(sc['scene_id']):03d}.png", sc["prompt"], sc.get("char_ids", []),
                     IP_ADAPTER_SCALE, f"scene {sc['scene_id']}") for sc in s["scenes"]]
            for key, scale in (("title_card", 0.6), ("outro_card", 0.6), ("thumbnail", 0.65)):
                card = s.get(key) or {}
                if card.get("prompt"):
                    jobs.append((f"{key}.png", card["prompt"], card.get("char_ids", []), scale, key))
            for n, (name, prompt, cids, scale, label) in enumerate(jobs):
                dest = self.dir / "images" / name
                self.set_status(message=f"image {n + 1}/{len(jobs)}",
                                progress=int(100 * (3 + n / max(1, len(jobs))) / len(STAGES)))
                if dest.exists():
                    continue
                ref = refs.get(cids[0]) if cids else None
                painter.generate(prompt, neg, base_seed + n * 7, dest, ref, scale, IMG_W, IMG_H,
                                 attempts=int(s.get("qc", {}).get("max_image_attempts", 2)), label=label)
        finally:
            painter.release()
        # cards fall back to the first/last scene image if no dedicated prompt was given
        imgs = self.dir / "images"
        first = imgs / f"scene_{int(s['scenes'][0]['scene_id']):03d}.png"
        last = imgs / f"scene_{int(s['scenes'][-1]['scene_id']):03d}.png"
        for name, src in (("title_card.png", first), ("outro_card.png", last), ("thumbnail.png", first)):
            if not (imgs / name).exists():
                shutil.copy2(src, imgs / name)

    def stage_timeline(self) -> None:
        s = self.spec
        r = s.get("render", {})
        song = read_json(self.dir / "song.json")
        lines = song["lines"]
        T = float(r.get("transition_s", 0.5))
        hook_len = audio_duration(self.dir / "audio" / "hook.wav")
        outro_len = audio_duration(self.dir / "audio" / "outro.wav")
        title_dur = max(float(r.get("title_card_s", 3.0)), hook_len + 0.6)
        song_off = title_dur
        song_end = song_off + float(song["duration"])
        outro_dur = max(float(r.get("outro_s", 5.0)), outro_len + 1.5)

        # scene starts follow the first lyric line each scene covers
        scenes = sorted(s["scenes"], key=lambda sc: min(sc.get("lines") or [10 ** 6]))
        starts = []
        for k, sc in enumerate(scenes):
            ln = sc.get("lines") or []
            if k == 0 or not ln:
                t = song_off if k == 0 else None
            else:
                t = song_off + lines[min(ln)]["start"] - 0.15
            starts.append(t)
        for k in range(len(starts)):  # scenes without lines: midpoint between neighbours
            if starts[k] is None:
                prev = starts[k - 1]
                nxt = next((x for x in starts[k + 1:] if x is not None), song_end)
                starts[k] = (prev + nxt) / 2
        segs = [{"image": "images/title_card.png", "start": 0.0, "end": song_off,
                 "camera": "zoom_in", "transition": "fade", "kind": "title"}]
        for k, sc in enumerate(scenes):
            end = starts[k + 1] if k + 1 < len(scenes) else song_end
            segs.append({"image": f"images/scene_{int(sc['scene_id']):03d}.png", "start": starts[k],
                         "end": end, "camera": sc.get("camera", "zoom_in"),
                         "transition": sc.get("transition", "fade"), "kind": "scene",
                         "scene_id": sc["scene_id"], "sfx": sc.get("sfx", [])})
        segs.append({"image": "images/outro_card.png", "start": song_end, "end": song_end + outro_dur,
                     "camera": "zoom_out", "transition": "fade", "kind": "outro"})
        # merge too-short scenes into the previous one; split very long ones
        merged = []
        for sg in segs:
            if merged and sg["kind"] == "scene" and sg["end"] - sg["start"] < 1.6:
                merged[-1]["end"] = sg["end"]
                continue
            merged.append(sg)
        final = []
        for sg in merged:
            length = sg["end"] - sg["start"]
            if sg["kind"] == "scene" and length > 9.0:
                half = sg["start"] + length / 2
                a = dict(sg, end=half)
                b = dict(sg, start=half, transition="dissolve", sfx=[],
                         camera={"zoom_in": "pan_right", "zoom_out": "pan_left"}.get(sg["camera"], "zoom_out"))
                final += [a, b]
            else:
                final.append(sg)
        for sg in final:
            if sg["camera"] not in CAMERA_MOVES:
                sg["camera"] = "zoom_in"
            if sg["transition"] not in TRANSITIONS:
                sg["transition"] = "fade"
            sg["dur"] = round(sg["end"] - sg["start"], 3)
        total = final[-1]["end"]

        # subtitles (absolute times)
        subs = []
        for k, ln in enumerate(lines):
            st = song_off + ln["start"]
            nxt = song_off + lines[k + 1]["start"] if k + 1 < len(lines) else song_end
            en = min(song_off + ln["end"] + 0.6, nxt - 0.05)
            subs.append({"start": round(st, 3), "end": round(max(en, st + 0.8), 3), "text": ln["text"],
                         "words": [{"w": w["w"], "start": song_off + w["start"], "end": song_off + w["end"]}
                                   for w in ln.get("words", [])]})
        # sound effects
        sfx = [{"name": "sparkle", "t": 0.2}]
        for sg in final:
            for fx in sg.get("sfx", []) or []:
                at = sg["start"] + (0.3 if fx.get("at", "start") == "start" else sg["dur"] / 2)
                sfx.append({"name": fx.get("name", ""), "t": round(at, 2)})
        sfx.append({"name": "sparkle", "t": round(song_end + 0.2, 2)})
        # chapters: first line of each section (YouTube needs 0:00 first, >=3, each >=10 s)
        chapters = [{"t": 0, "label": "Intro"}]
        seen = set()
        all_lines = self.all_lines()
        verse_no = 0
        for k, ln in enumerate(lines):
            meta = all_lines[k]
            if meta["section_id"] in seen:
                continue
            seen.add(meta["section_id"])
            if meta["type"] == "verse":
                verse_no += 1
                label = f"Verse {verse_no}"
            else:
                label = {"chorus": "Chorus", "bridge": "Bridge", "outro": "Ending", "intro": "Intro",
                         "pre_chorus": "Pre-chorus"}.get(meta["type"], meta["type"].title())
            t = int(song_off + ln["start"])
            if t - chapters[-1]["t"] >= 10:
                chapters.append({"t": t, "label": label})
        if total - chapters[-1]["t"] > 15:
            chapters.append({"t": int(song_end), "label": "Goodbye"})
        write_json(self.dir / "timeline.json", {
            "total": round(total, 3), "song_offset": song_off, "song_end": song_end, "transition": T,
            "segments": final, "subs": subs, "sfx": sfx,
            "chapters": chapters if len(chapters) >= 3 else [],
            "hook_at": 0.35, "outro_at": round(song_end + 0.3, 2)})

    def stage_subtitles(self) -> None:
        tl = read_json(self.dir / "timeline.json")

        def ts_ass(t: float) -> str:
            cs = int(round(t * 100))
            return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"

        def ts_srt(t: float) -> str:
            ms = int(round(t * 1000))
            return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

        header = (
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Lyric,{SUB_FONT_NAME},{SUB_FONT_SIZE},&H0000E6FF,&H00FFFFFF,&H00781E5A,&H96000000,-1,0,0,0,"
            "100,100,1,0,1,6,3,2,90,90,64,1\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        events, srt = [], []
        for n, sub in enumerate(tl["subs"], 1):
            words = sub["text"].split()
            dur_cs = max(1, int((sub["end"] - sub["start"]) * 100))
            sung_cs = int(dur_cs * 0.85)
            weights = [len(re.sub(r"[^A-Za-z0-9]", "", w)) + 2 for w in words]
            total_w = sum(weights) or 1
            parts = [f"{{\\kf{max(1, int(sung_cs * w / total_w))}}}{word}" for w, word in zip(weights, words)]
            text = " ".join(parts).replace("\n", " ")
            events.append(f"Dialogue: 0,{ts_ass(sub['start'])},{ts_ass(sub['end'])},Lyric,,0,0,0,,"
                          f"{{\\fad(120,120)}}{text}")
            srt.append(f"{n}\n{ts_srt(sub['start'])} --> {ts_srt(sub['end'])}\n{sub['text']}\n")
        (self.dir / "subs.ass").write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        (self.dir / "subtitles.srt").write_text("\n".join(srt), encoding="utf-8")

    def stage_mix(self) -> None:
        tl = read_json(self.dir / "timeline.json")
        total = tl["total"]
        tracks = [(load_audio(self.dir / "song.wav"), tl["song_offset"], 0.95),
                  (load_audio(self.dir / "audio" / "hook.wav"), tl["hook_at"], 1.0),
                  (load_audio(self.dir / "audio" / "outro.wav"), tl["outro_at"], 1.0)]
        jingle = ASSETS_DIR / "audio" / "jingle.wav"
        if jingle.exists():
            tracks.append((load_audio(jingle), 0.0, 0.45))
        bed = ASSETS_DIR / "audio" / "outro_bed.wav"
        if bed.exists():
            tracks.append((load_audio(bed), tl["song_end"], 0.4))
        missing = set()
        for fx in tl["sfx"]:
            path = ASSETS_DIR / "sfx" / f"{fx['name']}.wav"
            if path.exists():
                tracks.append((load_audio(path), fx["t"], 0.32))
            elif fx["name"]:
                missing.add(fx["name"])
        if missing:
            log(f"   sfx files not found (skipped): {sorted(missing)}")
        save_wav(self.dir / "mix.wav", mix_tracks(tracks, total))

    @staticmethod
    def _zoompan(camera: str, frames: int) -> str:
        p = f"(on/{frames})"
        e = f"({p}*{p}*(3-2*{p}))"  # smoothstep easing
        cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        moves = {
            "zoom_in": (f"1+0.14*{e}", cx, cy),
            "zoom_out": (f"1.14-0.14*{e}", cx, cy),
            "pan_right": ("1.16", f"(iw-iw/zoom)*{e}", cy),
            "pan_left": ("1.16", f"(iw-iw/zoom)*(1-{e})", cy),
            "pan_up": ("1.16", cx, f"(ih-ih/zoom)*(1-{e})"),
            "pan_down": ("1.16", cx, f"(ih-ih/zoom)*{e}"),
            "static": (f"1.04+0.02*sin({p}*PI)", cx, cy),
        }
        z, x, y = moves.get(camera, moves["zoom_in"])
        return f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s=1920x1080:fps=30"

    def _card(self, kind: str, src: Path, dest: Path) -> None:
        img = cover_resize(Image.open(src).convert("RGB"), 1920, 1080)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(480):  # top gradient for legibility
            od.line([(0, y), (1920, y)], fill=(20, 10, 40, int(170 * (1 - y / 480))))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)
        channel = self.spec.get("channel_name", "")
        if kind == "title":
            font, lines = fit_text(draw, self.spec["title"], TITLE_FONT_FILE, 1640, 300, 130)
            draw_outlined(img, lines, font, 960, 70, align="center")
            sub_font = load_font(TITLE_FONT_FILE, 54)
            draw_outlined(img, [f"Sing along{(' with ' + channel) if channel else ''}!"], sub_font, 960,
                          70 + len(lines) * int(font.size * 1.12) + 20, fill=(255, 255, 255),
                          stroke_w=7, align="center")
        else:
            font, lines = fit_text(draw, "Bye-bye, friends!", TITLE_FONT_FILE, 1600, 200, 130)
            draw_outlined(img, lines, font, 960, 80, align="center")
            draw_outlined(img, ["See you next time!"], load_font(TITLE_FONT_FILE, 60), 960, 260,
                          fill=(255, 255, 255), stroke_w=7, align="center")
        img.save(dest, quality=95)

    def stage_clips(self) -> None:
        tl = read_json(self.dir / "timeline.json")
        T = tl["transition"]
        segs = tl["segments"]
        self._card("title", self.dir / "images" / "title_card.png", self.dir / "images" / "title_comp.png")
        self._card("outro", self.dir / "images" / "outro_card.png", self.dir / "images" / "outro_comp.png")

        def render(i: int) -> None:
            sg = segs[i]
            dest = self.dir / "clips" / f"seg_{i:03d}.mp4"
            if dest.exists() and dest.stat().st_size > 1000:
                return
            img = {"title": "images/title_comp.png", "outro": "images/outro_comp.png"}.get(sg["kind"], sg["image"])
            length = sg["dur"] + (T if i < len(segs) - 1 else 0)  # extra T is eaten by the xfade
            frames = max(2, int(round(length * 30)))
            vf = ("scale=3840:2160:force_original_aspect_ratio=increase:flags=lanczos,crop=3840:2160,"
                  + self._zoompan(sg["camera"], frames) + ",format=yuv420p")
            tmp = dest.with_suffix(".tmp.mp4")
            run([FFMPEG, "-y", "-v", "error", "-i", img, "-vf", vf, "-frames:v", str(frames),
                 "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", str(tmp)],
                cwd=self.dir, timeout=900)
            os.replace(tmp, dest)

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max(1, CLIP_WORKERS)) as pool:
            for k, fut in enumerate([pool.submit(render, i) for i in range(len(segs))]):
                fut.result()
                self.set_status(message=f"clip {k + 1}/{len(segs)}")

    def stage_video(self) -> None:
        tl = read_json(self.dir / "timeline.json")
        segs, T = tl["segments"], tl["transition"]
        n = len(segs)
        inputs = []
        for i in range(n):
            inputs += ["-i", f"clips/seg_{i:03d}.mp4"]
        inputs += ["-i", "mix.wav"]
        graph, prev, offset = [], "0:v", 0.0
        for i in range(1, n):
            offset += segs[i - 1]["dur"]  # transition i starts exactly when segment i is due
            out = f"x{i}"
            graph.append(f"[{prev}][{i}:v]xfade=transition={segs[i]['transition']}:duration={T}:"
                         f"offset={offset:.3f}[{out}]")
            prev = out
        graph.append(f"[{prev}]subtitles=subs.ass:fontsdir=fonts,format=yuv420p[vout]")
        graph.append(f"[{n}:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
        (self.dir / "graph.txt").write_text(";\n".join(graph), encoding="utf-8")
        enc = ["-c:v", VIDEO_ENCODER]
        enc += (["-preset", "p5", "-cq", "21", "-b:v", "0"] if "nvenc" in VIDEO_ENCODER
                else ["-preset", "medium", "-crf", "20"])
        tmp = self.dir / "final.tmp.mp4"

        def encode(enc_args: list[str]) -> None:
            run([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex_script", "graph.txt",
                 "-map", "[vout]", "-map", "[aout]", *enc_args, "-profile:v", "high", "-pix_fmt", "yuv420p",
                 "-r", "30", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{tl['total']:.3f}",
                 "-movflags", "+faststart", tmp.name], cwd=self.dir, timeout=7200)

        try:
            encode(enc)
        except JobError as exc:
            if "nvenc" not in VIDEO_ENCODER:
                raise
            log(f"   NVENC failed ({str(exc)[:120]}); retrying with libx264")
            encode(["-c:v", "libx264", "-preset", "medium", "-crf", "20"])
        os.replace(tmp, self.dir / "final.mp4")

    def stage_thumbnail(self) -> None:
        th = self.spec.get("thumbnail", {})
        text = (th.get("text") or self.spec["title"]).upper()
        text = " ".join(text.split()[:4])
        img = cover_resize(Image.open(self.dir / "images" / "thumbnail.png").convert("RGB"), 1280, 720)
        img = ImageEnhance.Color(img).enhance(1.18)
        img = ImageEnhance.Contrast(img).enhance(1.08)
        draw = ImageDraw.Draw(img)
        side = th.get("text_side", "left")
        box_w = 560
        font, lines = fit_text(draw, text, TITLE_FONT_FILE, box_w, 420, 140)
        block_h = len(lines) * int(font.size * 1.12)
        x = 48 if side == "left" else 1280 - 48 - box_w
        y = max(30, (720 - block_h) // 2 - 40)
        draw_outlined(img, lines, font, x, y, fill=(255, 235, 30), stroke=(70, 20, 110), stroke_w=12)
        channel = self.spec.get("channel_name", "")
        if channel and env("THUMB_BADGE", "1") == "1":  # small consistent brand mark
            bf = load_font(TITLE_FONT_FILE, 30)
            tw = int(draw.textlength(channel, font=bf))
            bx, by = 1280 - tw - 52, 720 - 66
            draw.rounded_rectangle([bx, by, bx + tw + 32, by + 46], radius=23, fill=(255, 255, 255))
            draw.text((bx + 16, by + 7), channel, font=bf, fill=(70, 20, 110))
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
        dest = self.dir / "thumbnail.jpg"
        for q in (92, 85, 78, 70):
            img.save(dest, "JPEG", quality=q, optimize=True)
            if dest.stat().st_size < 2 * 1024 * 1024:
                break

    def stage_qc(self) -> None:
        tl = read_json(self.dir / "timeline.json")
        song = read_json(self.dir / "song.json")
        r = self.spec.get("render", {})
        q = self.spec.get("qc", {})
        final = self.dir / "final.mp4"
        checks = {}

        def check(name, ok, value, expected):
            checks[name] = {"ok": bool(ok), "value": value, "expected": expected}

        check("video_exists", final.exists() and final.stat().st_size > 1_000_000,
              final.stat().st_size if final.exists() else 0, "> 1 MB")
        info = json.loads(run([FFPROBE, "-v", "error", "-print_format", "json", "-show_streams",
                               "-show_format", str(final)])) if final.exists() else {}
        streams = info.get("streams", [])
        v = next((s for s in streams if s.get("codec_type") == "video"), {})
        a = next((s for s in streams if s.get("codec_type") == "audio"), {})
        dur = float(info.get("format", {}).get("duration", 0) or 0)
        check("duration", r.get("min_duration_s", 90) <= dur <= r.get("max_duration_s", 330), round(dur, 1),
              f"{r.get('min_duration_s', 90)}-{r.get('max_duration_s', 330)} s")
        check("resolution", v.get("width") == 1920 and v.get("height") == 1080,
              f"{v.get('width')}x{v.get('height')}", "1920x1080")
        check("video_codec", v.get("codec_name") == "h264", v.get("codec_name"), "h264")
        check("audio_exists", bool(a) and a.get("codec_name") == "aac", a.get("codec_name"), "aac stream")
        loud = None
        if final.exists():
            out = run([FFMPEG, "-nostats", "-i", str(final), "-filter_complex", "ebur128", "-f", "null", "-"])
            m = re.findall(r"I:\s+(-?[\d.]+) LUFS", out)
            loud = float(m[-1]) if m else None
        check("loudness", loud is not None and -18.0 <= loud <= -10.0, loud, "-18..-10 LUFS (target -14)")
        black = []
        if final.exists():
            out = run([FFMPEG, "-nostats", "-i", str(final), "-vf", "blackdetect=d=1.0:pix_th=0.08",
                       "-an", "-f", "null", "-"])
            black = re.findall(r"black_start:([\d.]+)", out)
        check("no_black_gaps", len(black) == 0, len(black), "0 black intervals >= 1 s")
        thumb = self.dir / "thumbnail.jpg"
        tw = th = 0
        if thumb.exists():
            with Image.open(thumb) as im:
                tw, th = im.size
        check("thumbnail", thumb.exists() and (tw, th) == (1280, 720) and thumb.stat().st_size < 2 * 1024 * 1024,
              f"{tw}x{th}, {thumb.stat().st_size if thumb.exists() else 0} bytes", "1280x720 JPEG < 2 MB")
        check("subtitles", len(tl["subs"]) >= max(1, int(0.8 * len(self.all_lines()))), len(tl["subs"]),
              ">= 80% of lyric lines")
        check("vocal_intelligibility",
              song["mode"] == "chant" or song["intelligibility"] >= float(q.get("min_intelligibility", 0.55)),
              song["intelligibility"], f">= {q.get('min_intelligibility', 0.55)} or chant mode")
        passed = all(c["ok"] for c in checks.values())
        result = {"pass": passed, "checks": checks}
        write_json(self.dir / "media_qc.json", result)
        self.set_status(media_qc=result, song={k: song.get(k) for k in
                                               ("mode", "intelligibility", "attempts", "fallback_reason", "backing")},
                        timeline={"duration_s": round(dur, 1), "chapters": tl["chapters"],
                                  "segments": len(tl["segments"])},
                        outputs={"video": "final.mp4", "thumbnail": "thumbnail.jpg", "srt": "subtitles.srt"},
                        paths={"job_dir": str(self.dir), "video": str(final), "thumbnail": str(thumb)})


# ----------------------------------------------------------------------------
# Worker + housekeeping
# ----------------------------------------------------------------------------
JOB_QUEUE: "queue.Queue[str]" = queue.Queue()
QUEUED: set[str] = set()
LOCK = threading.Lock()


def worker() -> None:
    while True:
        vid = JOB_QUEUE.get()
        job = Job(vid)
        try:
            job.run()
            log(f"[{vid}] finished: {job.status().get('status')}")
        except JobError as exc:
            job.set_status(status="failed", error=str(exc))
            log(f"[{vid}] FAILED: {exc}")
        except Exception as exc:  # unexpected bug: keep the traceback for troubleshooting
            job.set_status(status="failed", error=f"{type(exc).__name__}: {exc}")
            (job.dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            log(f"[{vid}] CRASHED: {exc}")
        finally:
            with LOCK:
                QUEUED.discard(vid)
            JOB_QUEUE.task_done()


def enqueue(vid: str) -> None:
    with LOCK:
        if vid in QUEUED:
            return
        QUEUED.add(vid)
    JOB_QUEUE.put(vid)


def housekeeping() -> None:
    while True:
        cutoff = time.time() - KEEP_INTERMEDIATE_DAYS * 86400
        for d in JOBS_DIR.iterdir() if JOBS_DIR.exists() else []:
            st = read_json(d / "status.json", {})
            if st.get("status") in ("done", "failed") and d.stat().st_mtime < cutoff:
                for sub in ("clips", "images", "audio"):
                    shutil.rmtree(d / sub, ignore_errors=True)
        time.sleep(6 * 3600)


def resume_unfinished() -> None:
    for d in sorted(JOBS_DIR.iterdir()):
        st = read_json(d / "status.json", {})
        if st.get("status") in ("queued", "running"):
            log(f"resuming {d.name} after restart")
            enqueue(d.name)


def dependency_report() -> dict:
    rep = {"mock": MOCK, "ffmpeg": shutil.which(FFMPEG) is not None or Path(FFMPEG).exists(),
           "data_dir": str(DATA_DIR), "queue": sorted(QUEUED)}
    try:
        rep["acestep"] = http_json("GET", f"{ACESTEP_URL}/health", timeout=5).get("data", {}).get("status")
    except Exception as exc:
        rep["acestep"] = f"unreachable: {exc.__class__.__name__}"
    for mod in ("torch", "diffusers", "kokoro", "faster_whisper", "transformers"):
        try:
            __import__(mod)
            rep[mod] = True
        except Exception:
            rep[mod] = False
    try:
        import torch
        rep["cuda"] = torch.cuda.is_available()
        rep["gpu"] = torch.cuda.get_device_name(0) if rep["cuda"] else None
    except Exception:
        pass
    return rep


# ----------------------------------------------------------------------------
# HTTP API
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "RhymeHelper/1.0"

    def log_message(self, fmt, *args):  # quieter console
        if "/health" not in (args[0] if args else ""):
            log("http " + fmt % args)

    def _send(self, code: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        if not API_KEY:
            self._send(500, {"error": "HELPER_API_KEY is not set in helper/.env"})
            return False
        given = self.headers.get("X-Helper-Key", "")
        if not hmac.compare_digest(given.encode(), API_KEY.encode()):
            self._send(401, {"error": "missing or wrong X-Helper-Key header"})
            return False
        return True

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20 * 1024 * 1024:
            raise JobError("request body too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def do_GET(self):  # noqa: N802
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if path == "/health":
            return self._send(200, {"ok": True, "mock": MOCK})
        if not self._authed():
            return
        try:
            parts = path.strip("/").split("/")
            if path == "/status":
                return self._send(200, dependency_report())
            if len(parts) == 2 and parts[0] == "jobs":
                job_dir = JOBS_DIR / safe_id(parts[1])
                if not (job_dir / "status.json").exists():
                    return self._send(404, {"video_id": parts[1], "status": "not_found"})
                return self._send(200, Job(parts[1]).status())
            if len(parts) == 3 and parts[0] == "files":
                vid, name = safe_id(parts[1]), parts[2]
                if name not in ALLOWED_FILES:
                    return self._send(400, {"error": f"file not allowed: {name}"})
                fpath = JOBS_DIR / vid / name
                if not fpath.exists():
                    return self._send(404, {"error": f"{name} not found for {vid}"})
                ctype = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".srt": "application/x-subrip",
                         ".wav": "audio/wav", ".json": "application/json"}.get(fpath.suffix, "text/plain")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(fpath.stat().st_size))
                self.send_header("Content-Disposition", f'attachment; filename="{vid}_{name}"')
                self.end_headers()
                with open(fpath, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, length=1024 * 1024)
                return
            return self._send(404, {"error": "unknown route"})
        except JobError as exc:
            return self._send(400, {"error": str(exc)})

    def do_POST(self):  # noqa: N802
        if not self._authed():
            return
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        parts = path.strip("/").split("/")
        try:
            if path == "/jobs":
                spec = self._body()
                vid = safe_id(str(spec.get("video_id", "")))
                job = Job(vid)
                st = job.status()
                if st.get("status") in ("queued", "running", "done"):
                    return self._send(200, st)  # idempotent: never renders the same video twice
                write_json(job.dir / "job.json", spec)
                submits = int(st.get("submits", 0)) + 1
                if submits > 3:
                    return self._send(409, {"video_id": vid, "status": "failed",
                                            "error": "job already resubmitted 3 times; create a new video_id"})
                job.set_status(status="queued", stage="queued", progress=0, submits=submits,
                               queued_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                enqueue(vid)
                return self._send(202, job.status())
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "retry":
                job = Job(parts[1])
                if job.status().get("status") != "failed":
                    return self._send(409, {"error": "only failed jobs can be retried", **job.status()})
                job.set_status(status="queued", error=None)
                enqueue(job.id)
                return self._send(202, job.status())
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "outbox":
                job = Job(parts[1])
                if job.status().get("status") != "done":
                    return self._send(409, {"error": "job is not done", **job.status()})
                meta = self._body()
                dest = OUTBOX_DIR / job.id
                dest.mkdir(parents=True, exist_ok=True)
                safe_title = re.sub(r"[^A-Za-z0-9 _-]", "", meta.get("title", job.id))[:80].strip() or job.id
                shutil.copy2(job.dir / "final.mp4", dest / f"{safe_title}.mp4")
                shutil.copy2(job.dir / "thumbnail.jpg", dest / "thumbnail.jpg")
                shutil.copy2(job.dir / "subtitles.srt", dest / "subtitles.srt")
                when = meta.get("publish_suggestion", "")
                try:  # show the slot in IST too, since Studio's scheduler uses your local time
                    import datetime as _dt
                    t = _dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                    ist = t.astimezone(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
                    when = f"{when} (UTC) = {ist.strftime('%a %d %b %Y, %H:%M')} IST"
                except Exception:
                    pass
                txt = (f"TITLE:\n{meta.get('title', '')}\n\nDESCRIPTION:\n{meta.get('description', '')}\n\n"
                       f"TAGS:\n{meta.get('tags', '')}\n\nPLAYLIST: {meta.get('playlist', '')}\n"
                       f"AUDIENCE: Yes, it's made for kids\nCATEGORY: Education    LANGUAGE: English\n"
                       f"SCHEDULE FOR: {when}\n")
                (dest / "metadata.txt").write_text(txt, encoding="utf-8")
                return self._send(200, {"outbox": str(dest), "files": sorted(p.name for p in dest.iterdir())})
            return self._send(404, {"error": "unknown route"})
        except (JobError, json.JSONDecodeError) as exc:
            return self._send(400, {"error": str(exc)})


def main() -> None:
    if not API_KEY:
        log("WARNING: HELPER_API_KEY is empty; all authenticated routes will refuse requests.")
    if not (shutil.which(FFMPEG) or Path(FFMPEG).exists()):
        log("WARNING: ffmpeg not found; set FFMPEG in helper/.env")
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=housekeeping, daemon=True).start()
    resume_unfinished()
    log(f"Rhyme helper listening on http://{HOST}:{PORT}  (mock={MOCK}, data={DATA_DIR})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
