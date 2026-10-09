#!/usr/bin/env python3
"""
Brand kit for the channel, made with the same local SDXL setup as the videos.

  python make_channel_art.py                  # cast sheets + avatar + banner + review sheet
  python make_channel_art.py --only cast      # just the character reference sheets
  python make_channel_art.py --regen pip_duckling --variant 2   # redo one character with a new seed
  python make_channel_art.py --only avatar --variant 2         # another profile picture (same for banner)
  python make_channel_art.py --only sounds    # 4 s jingle + 6 s outro music (needs ACE-Step running)

Outputs (DATA_DIR = C:\\RhymeFactory\\data by default):
  library\\characters\\<char_id>.png   reference sheets the video pipeline reuses for every video
  brand\\cast_review.png              all characters side by side, to approve the look
  brand\\avatar_800.png               YouTube profile picture (800x800)
  brand\\banner_2560x1440.png         YouTube banner; text sits inside the 1546x423 safe area
  assets\\audio\\jingle.wav, outro_bed.wav   channel sounds under the title card and goodbye card
Delete a reference sheet (or use --regen) BEFORE the first real video if you do not like it:
once videos use a character, keep its sheet so the character never changes.
"""
import argparse
import json
from types import SimpleNamespace
from pathlib import Path

from PIL import Image, ImageDraw

import rhyme_helper as rh

HERE = Path(__file__).resolve().parent
BRAND = json.loads((HERE / "brand.json").read_text(encoding="utf-8"))
OUT = rh.DATA_DIR / "brand"
OUT.mkdir(parents=True, exist_ok=True)


def fnv1a(text: str) -> int:
    """Same seed formula as the n8n 'Build Render Job' node, so sheets match what videos would create."""
    h = 0x811C9DC5
    for ch in text:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h % 2147483647


def cast_sheets(painter, only=None, variant=0):
    style = BRAND["style_bible"]
    for c in BRAND["cast"]:
        if only and c["char_id"] != only:
            continue
        dest = rh.LIB_DIR / f"{c['char_id']}.png"
        if dest.exists() and not only:
            print(f"keep  {dest.name} (delete it or use --regen to redo)")
            continue
        prompt = (f"{style['positive']}, character reference sheet, one character only, full body, front view, "
                  f"standing, {c['visual_prompt']}, plain white background")
        seed = fnv1a(c["char_id"]) + 1009 * variant
        painter.generate(prompt, style["negative"], seed, dest, None, 0.0, 1024, 1024, label=f"ref {c['name']}")
        print(f"made  {dest.name} (seed {seed})")


def review_sheet():
    cast = BRAND["cast"]
    tile = 420
    sheet = Image.new("RGB", (tile * len(cast), tile + 70), "white")
    draw = ImageDraw.Draw(sheet)
    font = rh.load_font(rh.TITLE_FONT_FILE, 34)
    for i, c in enumerate(cast):
        ref = rh.LIB_DIR / f"{c['char_id']}.png"
        if ref.exists():
            sheet.paste(Image.open(ref).convert("RGB").resize((tile, tile)), (i * tile, 0))
        label = f"{c['name']} the {c['species']}"
        w = draw.textlength(label, font=font)
        draw.text((i * tile + (tile - w) / 2, tile + 16), label, font=font, fill=(70, 20, 110))
    sheet.save(OUT / "cast_review.png")
    print(f"made  {OUT / 'cast_review.png'}")


def avatar(painter, variant=1):
    style = BRAND["style_bible"]
    raw = OUT / "avatar_raw.png"
    ref = rh.LIB_DIR / f"{BRAND['cast'][0]['char_id']}.png"
    if not rh.MOCK and rh.USE_IP_ADAPTER:
        if painter.pipe is None:
            painter._load()
        painter._ensure_ip()
    painter.generate(f"{style['positive']}, {BRAND['art']['avatar_prompt']}", style["negative"], 4242 + 1009 * (variant - 1), raw,
                     ref if ref.exists() else None, 0.6, 1024, 1024, label="avatar")
    Image.open(raw).convert("RGB").resize((800, 800), Image.LANCZOS).save(OUT / "avatar_800.png")
    print(f"made  {OUT / 'avatar_800.png'}")


def banner(painter, variant=1):
    style = BRAND["style_bible"]
    raw = OUT / "banner_raw.png"
    painter.generate(f"{style['positive']}, {BRAND['art']['banner_prompt']}", style["negative"], 777 + 1009 * (variant - 1), raw,
                     None, 0.0, 1536, 640, label="banner")
    img = rh.cover_resize(Image.open(raw).convert("RGB"), 2560, 1440)
    draw = ImageDraw.Draw(img)
    safe_x0, safe_w = (2560 - 1546) // 2, 1546          # area visible on every device
    font, lines = rh.fit_text(draw, BRAND["channel_name"], rh.TITLE_FONT_FILE, safe_w - 80, 220, 190)
    rh.draw_outlined(img, lines, font, 1280, 545, align="center", stroke_w=14)
    rh.draw_outlined(img, [BRAND["tagline"]], rh.load_font(rh.TITLE_FONT_FILE, 60), 1280, 545 + 215,
                     fill=(255, 255, 255), stroke_w=8, align="center")
    rh.draw_outlined(img, ["New songs every Mon - Wed - Fri"], rh.load_font(rh.TITLE_FONT_FILE, 44), 1280, 545 + 300,
                     fill=(255, 255, 255), stroke_w=7, align="center")
    img.save(OUT / "banner_2560x1440.png")
    print(f"made  {OUT / 'banner_2560x1440.png'} (safe area x {safe_x0}-{safe_x0 + safe_w}, y 508-931)")


def sounds(force=False, variant=1):
    """Channel jingle + outro bed with ACE-Step (instrumental), trimmed and faded; procedural if ACE-Step is down."""
    dest_dir = rh.ASSETS_DIR / "audio"
    dest_dir.mkdir(parents=True, exist_ok=True)
    fake_job = SimpleNamespace(spec={"song": {"music": {"bpm": 112, "key": "C Major", "time_signature": "4"}}})
    for name, key, length, seed in (("jingle.wav", "jingle_caption", 4.0, 31), ("outro_bed.wav", "outro_bed_caption", 6.0, 37)):
        dest = dest_dir / name
        if dest.exists() and not force:
            print(f"keep  {dest} (use --force to redo)")
            continue
        raw = OUT / f"raw_{name}"
        source = "ACE-Step"
        try:
            if rh.MOCK:
                raise OSError("MOCK=1")
            rh.Job._ace_generate(fake_job, "[Instrumental]", BRAND["art"][key] + ", instrumental, no vocals",
                                 10.0, seed + 1009 * variant, raw)
        except Exception as exc:  # keep going with an original procedural tune
            source = f"procedural ({exc})"
            rh.save_wav(raw, rh.mix_tracks([(rh.procedural_backing(112, length + 1, seed + variant), 0.0, 0.7)], length + 1))
        fade = 0.8 if length <= 4 else 1.5
        rh.run([rh.FFMPEG, "-y", "-i", str(raw), "-t", f"{length}", "-af",
                f"afade=t=in:d=0.05,afade=t=out:st={length - fade}:d={fade},loudnorm=I=-18:TP=-2:LRA=7",
                "-ar", "48000", "-ac", "2", str(dest)])
        print(f"made  {dest} from {source}. Listen to it; for another take run: --only sounds --force --variant N")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["cast", "avatar", "banner", "sounds"])
    ap.add_argument("--force", action="store_true", help="redo sounds even if they exist")
    ap.add_argument("--regen", help="char_id to regenerate")
    ap.add_argument("--variant", type=int, default=1, help="another take: with --regen, --only avatar, --only banner, or --only sounds --force")
    a = ap.parse_args()
    if a.only == "sounds":
        sounds(a.force, a.variant)
        return
    painter = rh.Painter()
    try:
        if a.regen:
            cast_sheets(painter, only=a.regen, variant=a.variant)
            review_sheet()
            return
        if a.only in (None, "cast"):
            cast_sheets(painter)
            review_sheet()
        if a.only in (None, "avatar"):
            avatar(painter, a.variant)
        if a.only in (None, "banner"):
            banner(painter, a.variant)
    finally:
        painter.release()
    if a.only is None:
        sounds(a.force, a.variant)


if __name__ == "__main__":
    main()
