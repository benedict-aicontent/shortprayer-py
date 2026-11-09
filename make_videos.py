#!/usr/bin/env python3
"""
make_videos.py - turns the prayers in Batch.md into ready-to-upload videos.

For every DAY in Batch.md the script
  1. reads only the EMOTIONAL HOOK and the PRAYER text,
  2. makes the voiceover with Piper (hook, a short pause, then the prayer),
  3. cuts random trims from your clips in a repeating 4s, 4s, 4s, 8s pattern
     (slow zoom and transitions only on the 8s trims),
  4. shows the hook and the prayer as two on-screen text blocks that animate in
     and out together (one random effect per video, never repeated in a batch),
  5. adds random background music and exports the video.

The voiceover starts 4 seconds in and the video runs 8 seconds past its end.

Files next to this script:
    make_videos.py   this script
    config.json      folders, Piper voice, speed, pauses, timing and other settings
    look.json        the on-screen text designs (hook sets and prayer sets)
    Batch.md         your prayers
    clips/ music/ voice/ voiceovers/ output/ fonts/   (folders, see config.json)

Usage:
    python make_videos.py                  make a video for every day in Batch.md
    python make_videos.py --days 1,3-5     only those days
    python make_videos.py --count 2        only the first 2 days
    python make_videos.py --ratio 16:9     force landscape (default: 9:16 vertical,
                                           or 16:9 when most of your clips are landscape)
    python make_videos.py --dry-run        print the plan, render nothing
    python make_videos.py --test-voice     check that Piper and your voice model work

Needs: Python 3.8+, FFmpeg 4.4+ (ffmpeg and ffprobe on PATH), Piper, and Pillow
(pip install pillow).
"""
from __future__ import annotations

import argparse
import array
import copy
import hashlib
import json
import math
import os
import random
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:                     # reported nicely in main()
    Image = ImageDraw = ImageFilter = ImageFont = None

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080)}

PREFERRED_TRANSITIONS = [
    "fade", "dissolve", "fadeblack", "wipeleft", "wiperight", "wipeup",
    "wipedown", "slideleft", "slideright", "slideup", "slidedown",
    "smoothleft", "smoothright", "smoothup", "smoothdown", "circleopen",
    "circleclose", "radial", "zoomin", "horzopen", "vertopen",
]

# On-screen text effects. The same effect is used for the way a video's text
# comes in and the way it goes out (it plays in reverse).
#   dx, dy   : how far (px, on a 1080px-wide design) the text starts from its place
#   zoom     : size the text starts at (1.0 = no zoom)
#   overshoot: the text grows a little past its size and settles back (a "pop")
EFFECTS = {
    "fade":             {"dx": 0,    "dy": 0,   "zoom": 1.0},
    "rise":             {"dx": 0,    "dy": 70,  "zoom": 1.0},
    "drop":             {"dx": 0,    "dy": -70, "zoom": 1.0},
    "slide_from_left":  {"dx": -260, "dy": 0,   "zoom": 1.0},
    "slide_from_right": {"dx": 260,  "dy": 0,   "zoom": 1.0},
    "zoom_in":          {"dx": 0,    "dy": 0,   "zoom": 0.80},
    "zoom_out":         {"dx": 0,    "dy": 0,   "zoom": 1.20},
    "pop":              {"dx": 0,    "dy": 0,   "zoom": 0.60, "overshoot": True},
}

DEFAULT_CONFIG = {
    "folders": {
        "clips": "clips", "music": "music", "voice": "voice",
        "voiceovers": "voiceovers", "output": "output", "fonts": "fonts",
    },
    "batch_file": "Batch.md",
    "look_file": "look.json",
    "batch": {
        "hook_labels": ["EMOTIONAL HOOK", "HOOK"],
        "prayer_labels": ["PRAYER", "PRAYER TEXT"],
    },
    "piper": {
        "command": "auto",
        "model": "en_US-bryce-medium.onnx",
        "speaker": None,
        "voice_speed": 1.0,
        "pause_between_hook_and_prayer": 0.8,
        "sentence_pause": None,
    },
    "timing": {"voice_starts_at": 4.0, "seconds_after_voice": 8.0},
    "text": {
        "enabled": True,
        "in_before_voice": 0.5,
        "out_after_voice": 0.3,
        "effect_duration": 0.6,
        "effects": list(EFFECTS),
        "no_repeat_effects_in_batch": True,
        "no_repeat_looks_in_batch": True,
        "fallback_fonts": ["segoeui.ttf", "arial.ttf"],
    },
    "video": {
        "ratio": "auto", "fps": 30, "crf": 20, "preset": "fast",
        "trim_pattern": [4, 4, 4, 8], "long_trim_seconds": 8,
        "zoom_percent": 15,
        "transition_seconds": 0.4, "transitions_at": "both",
        "clips_per_video": [3, 5], "allow_clip_repeat": True,
    },
    "music": {"volume_vs_voice": 0.5, "target_loudness_lufs": -14},
}

# ---- values the rest of the script reads (set from config.json) -------------
VO_DELAY = 4.0
AFTER_VOICE = 8.0
PATTERN = [(4.0, False), (4.0, False), (4.0, False), (8.0, True)]
MIN_LAST = 1.5              # the final trim is never shorter than this
CLIPS_MIN, CLIPS_MAX = 3, 5
ALLOW_CLIP_REPEAT = True
XFADE = 0.4
TRANSITIONS_AT = "both"     # "both", "into" or "out of" each long trim
ZOOM_TOTAL = 0.15
MUSIC_VS_VOICE = 0.5
TARGET_LUFS = -14.0
EDGE_MARGIN = 0.3           # stay this far from the end of a clip
LONG_SECONDS = 8.0
ZOOM_RATE = ZOOM_TOTAL / LONG_SECONDS
MIN_CLIP_SECONDS = LONG_SECONDS + MIN_LAST + EDGE_MARGIN


def apply_config(cfg):
    global VO_DELAY, AFTER_VOICE, PATTERN, CLIPS_MIN, CLIPS_MAX, ALLOW_CLIP_REPEAT
    global XFADE, TRANSITIONS_AT, ZOOM_TOTAL, MUSIC_VS_VOICE, TARGET_LUFS
    global LONG_SECONDS, ZOOM_RATE, MIN_CLIP_SECONDS
    VO_DELAY = float(cfg["timing"]["voice_starts_at"])
    AFTER_VOICE = float(cfg["timing"]["seconds_after_voice"])
    v = cfg["video"]
    long_min = float(v["long_trim_seconds"])
    PATTERN = [(float(s), float(s) >= long_min) for s in v["trim_pattern"]]
    if not PATTERN:
        raise ValueError("video.trim_pattern in config.json is empty")
    lows, highs = v["clips_per_video"]
    CLIPS_MIN, CLIPS_MAX = int(lows), int(highs)
    ALLOW_CLIP_REPEAT = bool(v["allow_clip_repeat"])
    XFADE = float(v["transition_seconds"])
    TRANSITIONS_AT = v["transitions_at"]
    ZOOM_TOTAL = float(v["zoom_percent"]) / 100.0
    longs = [d for d, is_long in PATTERN if is_long]
    LONG_SECONDS = max(longs) if longs else max(d for d, _ in PATTERN)
    ZOOM_RATE = ZOOM_TOTAL / LONG_SECONDS
    MIN_CLIP_SECONDS = LONG_SECONDS + MIN_LAST + EDGE_MARGIN
    MUSIC_VS_VOICE = float(cfg["music"]["volume_vs_voice"])
    TARGET_LUFS = float(cfg["music"]["target_loudness_lufs"])


def deep_merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        sys.exit("ERROR: %s is not valid JSON (line %d, column %d): %s.\n"
                 "Check for a missing comma or quote near that spot."
                 % (path.name, e.lineno, e.colno, e.msg))


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def run_capture(cmd):
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )


def slugify(text, limit=40):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].strip("-")


def parse_days(spec):
    """'1,3-5' -> {1, 3, 4, 5}"""
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


class Rotator:
    """Hands out items in random order, never repeating one until all were used."""

    def __init__(self, items, rng, no_repeat=True):
        self.items, self.rng, self.no_repeat = list(items), rng, no_repeat
        self.queue, self.last, self.cycled = [], None, False

    def next(self):
        if not self.no_repeat:
            return self.rng.choice(self.items)
        if not self.queue:
            if self.last is not None:
                self.cycled = True
            q = self.items[:]
            self.rng.shuffle(q)
            if len(q) > 1 and q[0] is self.last:
                q[0], q[-1] = q[-1], q[0]
            self.queue = q
        self.last = self.queue.pop(0)
        return self.last


# --------------------------------------------------------------------------
# Batch.md
# --------------------------------------------------------------------------
DAY_RE = re.compile(r"^\s*#{1,6}\s*DAY\s*(\d+)\b[\s\u2014\u2013:.\-]*(.*)$", re.I)
HEADER_RE = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$")
RULE_RE = re.compile(r"^[-*_]{3,}$")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B50\uFE0F\u200D]")


def clean_inline(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)([*_])(?=\S)(.+?)(?<=\S)\1(?!\w)", r"\2", text)
    text = text.replace("`", "")
    text = EMOJI_RE.sub("", text)
    return " ".join(text.split())


def paragraphs(lines):
    out, buf = [], []
    for ln in lines + [""]:
        if ln.strip():
            buf.append(ln.strip())
        elif buf:
            p = clean_inline(" ".join(buf))
            if p:
                out.append(p)
            buf = []
    return out


def parse_batch(path, hook_labels, prayer_labels):
    """Read Batch.md. Only the hook and the prayer text of each DAY are kept; every
    other section (titles, descriptions, tags ...) is ignored."""
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    hooks = {x.upper() for x in hook_labels}
    prayers = {x.upper() for x in prayer_labels}
    days, cur, section = [], None, None
    for line in raw.splitlines():
        m = DAY_RE.match(line)
        if m:
            cur = {"number": int(m.group(1)), "title": clean_inline(m.group(2) or ""),
                   "hook": [], "prayer": []}
            days.append(cur)
            section = None
            continue
        if cur is None:
            continue
        s = line.strip()
        if RULE_RE.match(s):
            section = None
            continue
        hm = HEADER_RE.match(s)
        if hm:
            shown = hm.group(1).strip().rstrip(":").strip()
            label = shown.upper()
            rest = hm.group(2).strip()
            if label in hooks or label in prayers:
                section = "hook" if label in hooks else "prayer"
                if rest:
                    cur[section].append(rest)
                continue
            if not rest and shown == shown.upper():   # an ALL-CAPS label, e.g. **YOUTUBE TITLE**
                section = None
                continue
        if section:
            cur[section].append(s)

    result = []
    for d in days:
        hook, prayer = paragraphs(d["hook"]), paragraphs(d["prayer"])
        result.append({
            "number": d["number"], "title": d["title"],
            "hook": " ".join(hook), "prayer": "\n".join(prayer),
            "prayer_flat": " ".join(prayer),
        })
    return result


def speakable(text):
    """Text for the voice: one line, and it always ends with punctuation."""
    t = " ".join(text.split())
    if t and t[-1] not in ".!?\u2026\"'\u201d\u2019)":
        t += "."
    return t


# --------------------------------------------------------------------------
# Piper voiceover
# --------------------------------------------------------------------------
PIPER = {"variant": None}      # remembers which command-line spelling worked


def piper_base_command(spec):
    if isinstance(spec, list):
        return [str(x) for x in spec]
    spec = (spec or "auto").strip()
    if spec.lower() == "auto":
        exe = shutil.which("piper")
        return [exe] if exe else [sys.executable, "-m", "piper"]
    if os.path.exists(spec) or shutil.which(spec):
        return [spec]
    return shlex.split(spec, posix=(os.name != "nt"))


def resolve_model(model, voice_dir):
    p = Path(model)
    if not p.is_absolute() and p.parent == Path("."):
        p = voice_dir / model
    return p


def piper_check(base_cmd, model_path):
    if not model_path.exists():
        raise RuntimeError("Piper voice model not found: %s\n"
                           "Put the .onnx file (and its .onnx.json file) in that folder, or "
                           "change piper.model in config.json." % model_path)
    cfg_file = Path(str(model_path) + ".json")
    if not cfg_file.exists():
        raise RuntimeError("The voice's config file is missing: %s\n"
                           "It must sit next to the .onnx file and be named %s"
                           % (cfg_file, cfg_file.name))
    try:
        r = run_capture(base_cmd + ["--help"])
    except OSError as e:
        raise RuntimeError("Could not start Piper (%s).\nInstall it with:  pip install piper-tts\n"
                           "or set piper.command in config.json to the full path of piper.exe."
                           % e)
    text = (r.stdout + r.stderr).lower()
    if r.returncode != 0 and "usage" not in text:
        raise RuntimeError("Piper does not seem to be installed for this Python:\n%s\n"
                           "Install it with:  pip install piper-tts\n"
                           "or set piper.command in config.json to the full path of piper.exe."
                           % (r.stderr.strip()[-300:] or r.stdout.strip()[-300:]))


def piper_synthesize(text, out_wav, base_cmd, model_path, speed, speaker, sentence_pause):
    """Run Piper on `text`. Piper versions spell some options differently
    (--length-scale or --length_scale) and take the text either on stdin or after
    '--', so the combinations are tried in turn and the one that works is kept."""
    length_scale = 1.0 / speed if speed and speed > 0 else 1.0
    variants = [("stdin", "-"), ("stdin", "_"), ("arg", "-"), ("arg", "_")]
    if PIPER["variant"] in variants:
        variants.remove(PIPER["variant"])
        variants.insert(0, PIPER["variant"])
    last_error = ""
    for feed, sep in variants:
        flag = lambda name: "--" + name.replace("_", sep)
        cmd = base_cmd + ["-m", str(model_path), "-f", str(out_wav)]
        if speaker is not None:
            cmd += ["-s", str(speaker)]
        if abs(length_scale - 1.0) > 1e-6:
            cmd += [flag("length_scale"), "%.4f" % length_scale]
        if sentence_pause is not None:
            cmd += [flag("sentence_silence"), "%.3f" % float(sentence_pause)]
        if feed == "arg":
            cmd += ["--", text]
        if Path(out_wav).exists():
            Path(out_wav).unlink()
        try:
            r = subprocess.run(cmd, input=text.encode("utf-8") if feed == "stdin" else None,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            raise RuntimeError("Could not start Piper: %s" % e)
        err = r.stderr.decode("utf-8", errors="replace").strip()
        if r.returncode == 0 and Path(out_wav).exists() and Path(out_wav).stat().st_size > 100:
            PIPER["variant"] = (feed, sep)
            return
        last_error = err or ("exit code %d" % r.returncode)
        low = err.lower()
        wrong_spelling = any(k in low for k in (
            "unrecognized", "unknown option", "invalid option", "usage:", "required",
            "expected one argument", "no text", "empty"))
        if not wrong_spelling and r.returncode != 0:
            break                  # a real problem (bad model, ...): more tries won't help
    raise RuntimeError("Piper failed:\n%s" % last_error[-600:])


def wav_info(path):
    with wave.open(str(path), "rb") as w:
        return w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()


TRIM_KEEP = 0.05      # seconds of quiet kept at each end of a trimmed Piper clip


def trim_wav_silence(path, threshold=150, keep=TRIM_KEEP):
    """Cut the silence Piper leaves at the start and end of a clip, so the pause
    between hook and prayer is exactly what config.json says (and the voiceover
    length is the length of the speech)."""
    with wave.open(str(path), "rb") as w:
        params, frames = w.getparams(), w.readframes(w.getnframes())
    if params.sampwidth != 2 or not frames:
        return
    samples = array.array("h")
    samples.frombytes(frames)
    if sys.byteorder == "big":
        samples.byteswap()
    ch = params.nchannels
    n = len(samples) // ch

    def loud(i):
        return any(abs(samples[i * ch + c]) > threshold for c in range(ch))

    first = next((i for i in range(n) if loud(i)), None)
    if first is None:
        return
    last = next(i for i in range(n - 1, -1, -1) if loud(i))
    pad = int(keep * params.framerate)
    start, end = max(0, first - pad), min(n, last + 1 + pad)
    with wave.open(str(path), "wb") as o:
        o.setnchannels(ch)
        o.setsampwidth(2)
        o.setframerate(params.framerate)
        o.writeframes(frames[start * ch * 2:end * ch * 2])


def join_wavs(first, pause, second, out):
    """first + `pause` seconds of silence + second -> out (all plain PCM WAV)."""
    with wave.open(str(first), "rb") as a, wave.open(str(second), "rb") as b:
        pa, pb = a.getparams()[:3], b.getparams()[:3]
        if pa != pb:
            raise RuntimeError("The two Piper clips have different audio formats.")
        rate, width, channels = a.getframerate(), a.getsampwidth(), a.getnchannels()
        silence = b"\x00" * (int(round(pause * rate)) * width * channels)
        with wave.open(str(out), "wb") as o:
            o.setnchannels(channels)
            o.setsampwidth(width)
            o.setframerate(rate)
            o.writeframes(a.readframes(a.getnframes()))
            o.writeframes(silence)
            o.writeframes(b.readframes(b.getnframes()))


def voice_key(day, pcfg, model_path):
    stat = model_path.stat() if model_path.exists() else None
    blob = json.dumps({
        "hook": speakable(day["hook"]), "prayer": speakable(day["prayer_flat"]),
        "model": model_path.name, "model_size": stat.st_size if stat else 0,
        "speed": pcfg["voice_speed"], "pause": pcfg["pause_between_hook_and_prayer"],
        "speaker": pcfg["speaker"], "sentence_pause": pcfg["sentence_pause"],
        "trimmed": 2,
    }, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def voice_paths(day, voiceovers_dir):
    wav = voiceovers_dir / ("Day%d.wav" % day["number"])
    return wav, wav.with_suffix(".voice.json")


def cached_voice(day, pcfg, model_path, voiceovers_dir):
    wav, meta = voice_paths(day, voiceovers_dir)
    if not (wav.exists() and meta.exists()):
        return None
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if info.get("key") != voice_key(day, pcfg, model_path):
        return None
    return {"path": wav, "duration": float(info["seconds"]), "cached": True,
            "hook_seconds": info.get("hook_seconds"), "prayer_seconds": info.get("prayer_seconds")}


def make_voiceover(day, pcfg, base_cmd, model_path, voiceovers_dir):
    hit = cached_voice(day, pcfg, model_path, voiceovers_dir)
    if hit:
        return hit
    wav, meta = voice_paths(day, voiceovers_dir)
    pause = float(pcfg["pause_between_hook_and_prayer"])
    with tempfile.TemporaryDirectory(prefix="piper_") as tmp:
        hook_wav, prayer_wav = Path(tmp) / "hook.wav", Path(tmp) / "prayer.wav"
        for text, target in ((speakable(day["hook"]), hook_wav),
                             (speakable(day["prayer_flat"]), prayer_wav)):
            piper_synthesize(text, target, base_cmd, model_path, float(pcfg["voice_speed"]),
                             pcfg["speaker"], pcfg["sentence_pause"])
        trim_wav_silence(hook_wav)
        trim_wav_silence(prayer_wav)
        ch, sw, rate, hook_frames = wav_info(hook_wav)
        _, _, _, prayer_frames = wav_info(prayer_wav)
        # the trimmed clips keep a little quiet at their edges, so insert a bit less
        # silence: the audible gap between hook and prayer is then exactly `pause`
        gap = max(0.0, pause - 2 * TRIM_KEEP)
        join_wavs(hook_wav, gap, prayer_wav, wav)
    hook_s, prayer_s = hook_frames / rate, prayer_frames / rate
    seconds = hook_s + gap + prayer_s
    meta.write_text(json.dumps({
        "key": voice_key(day, pcfg, model_path), "seconds": round(seconds, 3),
        "hook_seconds": round(hook_s, 3), "prayer_seconds": round(prayer_s, 3),
    }, indent=2), encoding="utf-8")
    return {"path": wav, "duration": seconds, "cached": False,
            "hook_seconds": hook_s, "prayer_seconds": prayer_s}


def estimate_voice_seconds(day, pcfg):
    """Rough length for --dry-run when the voiceover has not been made yet."""
    chars = len(day["hook"]) + len(day["prayer_flat"])
    return chars / 14.0 / max(0.3, float(pcfg["voice_speed"])) \
        + float(pcfg["pause_between_hook_and_prayer"])


# --------------------------------------------------------------------------
# clips, music, ratio (unchanged behaviour)
# --------------------------------------------------------------------------
def probe(path):
    """Return duration, stream types and displayed width/height (rotation
    applied), or None if the file is unreadable."""
    r = run_capture([
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height"
        ":stream_tags=rotate:stream_side_data=rotation",
        "-of", "json", str(path),
    ])
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout)
        duration = float(data["format"]["duration"])
    except (ValueError, KeyError, TypeError):
        return None
    streams = data.get("streams", [])
    kinds = {s.get("codec_type") for s in streams}

    width = height = 0
    for s in streams:
        if s.get("codec_type") != "video" or width:
            continue
        w, h = int(s.get("width") or 0), int(s.get("height") or 0)
        rot = 0
        try:
            rot = int(float((s.get("tags") or {}).get("rotate", 0)))
        except ValueError:
            pass
        for sd in s.get("side_data_list") or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                except ValueError:
                    pass
        if abs(rot) % 180 == 90:   # phone clips stored sideways, shown upright
            w, h = h, w
        width, height = w, h

    return {"duration": duration, "has_video": "video" in kinds,
            "has_audio": "audio" in kinds, "width": width, "height": height}


def detect_ratio(clips):
    """9:16 unless more clips are landscape than portrait."""
    portrait = sum(1 for c in clips if c["height"] > c["width"])
    landscape = sum(1 for c in clips if c["width"] > c["height"])
    return ("16:9" if landscape > portrait else "9:16"), portrait, landscape


def supported_transitions():
    """Keep only the xfade transitions this FFmpeg build actually has."""
    r = run_capture(["ffmpeg", "-hide_banner", "-h", "filter=xfade"])
    text = r.stdout + r.stderr
    found = [t for t in PREFERRED_TRANSITIONS
             if re.search(r"\b%s\b" % re.escape(t), text)]
    return found or ["fade", "dissolve", "wipeleft", "wiperight",
                     "slideleft", "slideright"]


def scan(folder, extensions, need_video=False, min_duration=0.0):
    items = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.suffix.lower() not in extensions:
            continue
        info = probe(p)
        if info is None:
            print("  skip (unreadable): %s" % p.name)
            continue
        if need_video and not info["has_video"]:
            print("  skip (no video stream): %s" % p.name)
            continue
        if not need_video and not info["has_audio"]:
            print("  skip (no audio stream): %s" % p.name)
            continue
        if info["duration"] < min_duration:
            print("  skip (%.1fs long, needs at least %.1fs): %s"
                  % (info["duration"], min_duration, p.name))
            continue
        items.append({"path": p, "duration": info["duration"],
                      "width": info["width"], "height": info["height"]})
    return items


def cycle_pick(items, n, rng):
    """n picks from items: shuffled rounds, never the same item twice in a row."""
    order = []
    while len(order) < n:
        rnd = items[:]
        rng.shuffle(rnd)
        if order and len(rnd) > 1 and rnd[0] is order[-1]:
            rnd[0], rnd[1] = rnd[1], rnd[0]
        order.extend(rnd)
    return order[:n]


_LUFS_CACHE = {}


def parse_lufs(text):
    values = re.findall(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", text)
    return float(values[-1]) if values else None


def measure_lufs(path):
    """Integrated loudness of an audio file in LUFS (None if it can't be read)."""
    key = str(path)
    if key not in _LUFS_CACHE:
        r = run_capture(["ffmpeg", "-hide_banner", "-nostats", "-i", key, "-vn",
                         "-af", "ebur128=framelog=quiet", "-f", "null", "-"])
        lufs = parse_lufs(r.stderr)
        _LUFS_CACHE[key] = None if lufs is None or lufs < -60 else lufs
    return _LUFS_CACHE[key]


# --------------------------------------------------------------------------
# planning one video
# --------------------------------------------------------------------------
def transition_at(prev_long, cur_long):
    """Does the cut between two neighbouring trims get a transition?"""
    if TRANSITIONS_AT == "into":
        return cur_long
    if TRANSITIONS_AT == "out":
        return prev_long
    return prev_long or cur_long


def plan_timeline(total, fps):
    """Trim lengths following PATTERN, trimmed so the video is exactly `total`
    seconds long once the transition overlaps are taken out."""
    def q(x):                       # snap to whole frames
        return round(x * fps) / fps
    xf = q(XFADE)

    def effective(segs):
        eff = 0.0
        for i, s in enumerate(segs):
            eff += s["duration"]
            if i and transition_at(segs[i - 1]["long"], s["long"]):
                eff -= xf
        return eff

    segs, i = [], 0
    while effective(segs) < total - 1e-9:
        length, is_long = PATTERN[i % len(PATTERN)]
        segs.append({"duration": q(length), "long": is_long})
        i += 1

    excess = effective(segs) - total
    last_len = segs[-1]["duration"] - excess
    if last_len >= MIN_LAST or len(segs) < 2:
        segs[-1]["duration"] = q(last_len)
    else:                           # leftover too short: give it to the trim before
        segs.pop()
        segs[-1]["duration"] = q(segs[-1]["duration"] + (total - effective(segs)))
    return segs


def unique_order(clips, plan, rng):
    """One clip per trim and no clip used twice (when there are enough clips).
    Longest trims are filled first so they get clips that are long enough."""
    n = len(plan)
    order = [None] * n
    free = clips[:]
    rng.shuffle(free)
    for j in sorted(range(n), key=lambda j: -plan[j]["duration"]):
        need = plan[j]["duration"] + EDGE_MARGIN
        pick = next((c for c in free if c["duration"] >= need), None)
        if pick is not None:
            free.remove(pick)
            order[j] = pick

    # more trims than clips: reuse the least-used clip that isn't a neighbour
    uses = {id(c): 0 for c in clips}
    for c in order:
        if c is not None:
            uses[id(c)] += 1
    for j in range(n):
        if order[j] is not None:
            continue
        need = plan[j]["duration"] + EDGE_MARGIN
        near = {id(order[x]) for x in (j - 1, j + 1) if 0 <= x < n and order[x] is not None}
        options = ([c for c in clips if id(c) not in near and c["duration"] >= need]
                   or [c for c in clips if id(c) not in near] or clips)
        low = min(uses[id(c)] for c in options)
        pick = rng.choice([c for c in options if uses[id(c)] == low])
        order[j] = pick
        uses[id(pick)] += 1
    return order


def repeating_order(clips, plan, rng):
    """A clip for every trim when clips may be reused: never the same clip twice in
    a row, every chosen clip used at least once, longer clips used more."""
    n = len(plan)
    count = {id(c): 0 for c in clips}
    taken = {id(c): 0.0 for c in clips}
    order, prev = [], None
    for slot in plan:
        d = slot["duration"]
        fits = [c for c in clips if c["duration"] >= d + EDGE_MARGIN] or clips
        pool = [c for c in fits if c is not prev] or fits
        weights = [max(0.3, c["duration"] - EDGE_MARGIN - taken[id(c)])
                   * (6.0 if count[id(c)] == 0 else 1.0) for c in pool]
        pick = rng.choices(pool, weights=weights)[0]
        order.append(pick)
        count[id(pick)] += 1
        taken[id(pick)] += d
        prev = pick

    for c in clips:                 # make sure no chosen clip was left out
        if count[id(c)] > 0:
            continue
        for j in rng.sample(range(n), n):
            cur = order[j]
            if count[id(cur)] < 2 or c["duration"] < plan[j]["duration"] + EDGE_MARGIN:
                continue
            if (j > 0 and order[j - 1] is c) or (j < n - 1 and order[j + 1] is c):
                continue
            count[id(cur)] -= 1
            count[id(c)] += 1
            order[j] = c
            break
    return order


def pick_segments(clips, plan, rng):
    """Give every planned trim a clip and a random start time. Trims taken from the
    same clip avoid overlapping each other where the footage allows it."""
    order = (repeating_order if ALLOW_CLIP_REPEAT else unique_order)(clips, plan, rng)
    used = {id(c): [] for c in clips}
    segs = []
    for clip, slot in zip(order, plan):
        d = slot["duration"]
        hi = max(0.0, clip["duration"] - d - EDGE_MARGIN)
        best_start, best_overlap = 0.0, None
        for _ in range(80):
            start = rng.uniform(0.0, hi)
            overlap = sum(max(0.0, min(start + d, b) - max(start, a))
                          for a, b in used[id(clip)])
            if best_overlap is None or overlap < best_overlap:
                best_start, best_overlap = start, overlap
                if overlap == 0.0:
                    break
        used[id(clip)].append((best_start, best_start + d))
        segs.append({"clip": clip, "start": round(best_start, 3),
                     "duration": d, "long": slot["long"]})
    return segs


def pick_transition(available, previous, rng):
    """One random transition for a whole video, different from the last video's."""
    choices = [t for t in available if t != previous] or available
    return rng.choice(choices)


# --------------------------------------------------------------------------
# on-screen text: layout and drawing (Pillow)
# --------------------------------------------------------------------------
class Fonts:
    """Finds Windows fonts by file name (e.g. georgiab.ttf)."""

    def __init__(self, extra_dir, fallbacks):
        dirs = [extra_dir]
        win = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
        if win:
            dirs.append(Path(win) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
        dirs += [Path("/usr/share/fonts"), Path("/Library/Fonts")]   # Linux / macOS
        self.dirs = [d for d in dirs if d]
        self.fallbacks = fallbacks
        self.cache, self.warned = {}, set()

    def find(self, name):
        p = Path(name)
        if p.is_absolute():
            return p if p.exists() else None
        lower = name.lower()
        for d in self.dirs:
            if not d.is_dir():
                continue
            hit = d / name
            if hit.exists():
                return hit
            try:
                for f in d.iterdir():
                    if f.is_file() and f.name.lower() == lower:
                        return f
            except OSError:
                pass
        return None

    def load(self, name, size):
        size = max(8, int(round(size)))
        key = (name, size)
        if key in self.cache:
            return self.cache[key]
        for candidate in [name] + list(self.fallbacks):
            path = self.find(candidate)
            if path:
                if candidate != name and name not in self.warned:
                    print("  WARNING: font %s not found, using %s instead." % (name, candidate))
                    self.warned.add(name)
                font = ImageFont.truetype(str(path), size)
                self.cache[key] = (font, path.name)
                return self.cache[key]
        if name not in self.warned:
            print("  WARNING: font %s not found (and no fallback font either); using a "
                  "plain built-in font. Check the font names in look.json." % name)
            self.warned.add(name)
        font = ImageFont.load_default(size)
        self.cache[key] = (font, "built-in")
        return self.cache[key]


def parse_color(value, opacity=None):
    v = str(value).lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    a = int(v[6:8], 16) if len(v) >= 8 else 255
    if opacity is not None:
        a = int(round(255 * max(0.0, min(1.0, float(opacity)))))
    return (r, g, b, a)


def apply_case(text, case):
    case = (case or "normal").lower()
    if case == "upper":
        return text.upper()
    if case == "lower":
        return text.lower()
    if case == "title":
        return text.title()
    return text


def split_long_word(word, font, max_w):
    if font.getlength(word) <= max_w:
        return [word]
    pieces, cur = [], ""
    for ch in word:
        if cur and font.getlength(cur + ch) > max_w:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    return pieces + ([cur] if cur else [])


def wrap_lines(text, font, max_w):
    lines = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for w in words:
            for piece in split_long_word(w, font, max_w):
                trial = piece if not cur else cur + " " + piece
                if not cur or font.getlength(trial) <= max_w:
                    cur = trial
                else:
                    lines.append(cur)
                    cur = piece
        lines.append(cur)
    return lines


def wrap_balanced(text, font, max_w):
    """Wrap to max_w, then narrow the lines as far as possible without adding a
    line, so the block is evenly filled instead of ending in a single stray word."""
    lines = wrap_lines(text, font, max_w)
    n = len(lines)
    if n < 2:
        return lines
    lo, hi, best = max_w * 0.45, max_w, lines
    for _ in range(12):
        mid = (lo + hi) / 2
        trial = wrap_lines(text, font, mid)
        if len(trial) <= n:
            best, hi = trial, mid
        else:
            lo = mid
    return best


def render_text_block(text, style, W, H, scale, fonts):
    """Fit `text` into its zone (shrinking the font if needed) and draw it onto a
    transparent image. Returns the image and where it sits on the frame."""
    size = float(style.get("font_size", 54)) * scale
    size_min = float(style.get("min_font_size", style.get("font_size", 54) * 0.65)) * scale
    spacing = float(style.get("line_spacing", 1.25))
    align = style.get("align", "center")

    m = style.get("margins", {})
    m_left, m_right = float(m.get("left", 70)) * scale, float(m.get("right", 70)) * scale
    m_top, m_bottom = float(m.get("top", 0)) * scale, float(m.get("bottom", 0)) * scale
    zone = style.get("zone", {"top": 35, "bottom": 82, "vertical_align": "center"})
    z_top = max(float(zone.get("top", 35)) / 100.0 * H, m_top)
    z_bottom = min(float(zone.get("bottom", 82)) / 100.0 * H, H - m_bottom)

    bg = style.get("background", {})
    bg_on = bool(bg.get("enabled", False))
    pad_x = float(bg.get("padding_x", 40)) * scale if bg_on else 0.0
    pad_y = float(bg.get("padding_y", 28)) * scale if bg_on else 0.0
    radius = float(bg.get("radius", 24)) * scale

    ol = style.get("outline", {})
    ol_w = int(round(float(ol.get("width", 0)) * scale)) if ol.get("width") else 0
    sh = style.get("shadow", {})
    sh_on = bool(sh.get("enabled", False))
    sh_blur = float(sh.get("blur", 6)) * scale
    sh_dx, sh_dy = float(sh.get("offset_x", 3)) * scale, float(sh.get("offset_y", 4)) * scale
    extra = ol_w + (int(math.ceil(sh_blur * 2 + max(abs(sh_dx), abs(sh_dy)))) if sh_on else 0) + 2

    avail_w = W - m_left - m_right - 2 * pad_x - 2 * ol_w
    avail_h = z_bottom - z_top
    name = style.get("font", "segoeui.ttf")

    shrink = 0
    while True:
        font, font_file = fonts.load(name, size)
        lines = wrap_balanced(text, font, avail_w)
        ascent, descent = font.getmetrics()
        pitch = font.size * spacing
        text_h = (len(lines) - 1) * pitch + ascent + descent
        text_w = max([font.getlength(ln) for ln in lines] + [1])
        box_h = text_h + 2 * pad_y + 2 * ol_w
        if box_h <= avail_h or size <= size_min:
            break
        size = max(size_min, size * 0.96)
        shrink += 1
    fits = box_h <= avail_h + 0.5

    cw = int(math.ceil(text_w + 2 * pad_x + 2 * ol_w + 2 * extra))
    ch = int(math.ceil(text_h + 2 * pad_y + 2 * ol_w + 2 * extra))
    bg_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    if bg_on:
        ImageDraw.Draw(bg_layer).rounded_rectangle(
            [extra, extra, cw - extra - 1, ch - extra - 1], radius=radius,
            fill=parse_color(bg.get("color", "#000000"), bg.get("opacity", 0.5)))

    anchor_x = {"left": extra + pad_x + ol_w, "right": cw - extra - pad_x - ol_w}.get(align, cw / 2)
    anchor = {"left": "la", "right": "ra"}.get(align, "ma")
    color = parse_color(style.get("color", "#FFFFFF"))
    ol_color = parse_color(ol.get("color", "#000000"))

    def draw_lines(layer, dx, dy, fill, stroke_fill=None, stroke=0):
        d = ImageDraw.Draw(layer)
        for i, line in enumerate(lines):
            if line:
                y = extra + pad_y + ol_w + i * pitch + dy
                d.text((anchor_x + dx, y), line, font=font, fill=fill, anchor=anchor,
                       stroke_width=stroke, stroke_fill=stroke_fill)

    layers = [bg_layer]
    if sh_on:
        shadow = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        sc = parse_color(sh.get("color", "#000000"), sh.get("opacity", 0.6))
        draw_lines(shadow, sh_dx, sh_dy, sc, sc, ol_w)
        layers.append(shadow.filter(ImageFilter.GaussianBlur(sh_blur)))
    text_layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw_lines(text_layer, 0, 0, color, ol_color if ol_w else None, ol_w)
    layers.append(text_layer)
    img = layers[0]
    for layer in layers[1:]:
        img = Image.alpha_composite(img, layer)

    v_align = zone.get("vertical_align", "center")
    if v_align == "top":
        top = z_top
    elif v_align == "bottom":
        top = z_bottom - ch
    else:
        top = z_top + (avail_h - ch) / 2.0
    top = max(0.0, min(top, H - ch))
    cx = (m_left + (W - m_right)) / 2.0
    return {"image": img, "cx": cx, "cy": top + ch / 2.0, "w": cw, "h": ch,
            "font_size": int(round(font.size)), "font_file": font_file,
            "lines": len(lines), "fits": fits, "shrunk": shrink > 0}


def effect_expressions(name, cx, cy, scale, t_in, t_out, d):
    """FFmpeg expressions for where the text block is (x, y) and how big it is
    (zoom, or None) at time t, for the chosen effect."""
    eff = EFFECTS[name]
    p_in = "clip((t-%.3f)/%.3f,0,1)" % (t_in, d)
    p_out = "clip((t-%.3f)/%.3f,0,1)" % (t_out, d)
    away = "(pow(1-%s,3)+pow(%s,3))" % (p_in, p_out)   # 1 = fully away, 0 = in place
    x = "%.2f-w/2" % cx
    y = "%.2f-h/2" % cy
    if eff["dx"]:
        x += "+(%.2f)*%s" % (eff["dx"] * scale, away)
    if eff["dy"]:
        y += "+(%.2f)*%s" % (eff["dy"] * scale, away)
    zoom, z0 = None, eff["zoom"]
    if eff.get("overshoot"):
        back = "(1+2.70158*pow(%s-1,3)+1.70158*pow(%s-1,2))" % (p_in, p_in)
        zoom = "(%.3f+%.3f*%s-%.3f*pow(%s,3))" % (z0, 1 - z0, back, 1 - z0, p_out)
    elif z0 != 1.0:
        zoom = "(1+(%.3f)*%s)" % (z0 - 1, away)
    return x, y, zoom


# --------------------------------------------------------------------------
# FFmpeg
# --------------------------------------------------------------------------
def zoom_filter(fps):
    """Smooth slow zoom-in toward the centre (sub-pixel accurate, no shimmer)."""
    z = "(1+%.6f*in/%d)" % (ZOOM_RATE, fps)
    hw = "W/(2*%s)" % z
    hh = "H/(2*%s)" % z
    return ("perspective=x0='W/2-{hw}':y0='H/2-{hh}':x1='W/2+{hw}':y1='H/2-{hh}':"
            "x2='W/2-{hw}':y2='H/2+{hh}':x3='W/2+{hw}':y3='H/2+{hh}':"
            "interpolation=cubic:eval=frame").format(hw=hw, hh=hh)


def video_graph(segs, cuts, transition, size, fps, out_label):
    """Filter graph: fit every trim to the frame (zoom on the long ones), join trims
    with plain cuts, and join the groups with the video's transition."""
    width, height = size
    xf = round(XFADE * fps) / fps
    parts = []
    for i, s in enumerate(segs):
        chain = ("[%d:v]setpts=PTS-STARTPTS,fps=%d,"
                 "scale=%d:%d:force_original_aspect_ratio=increase,"
                 "crop=%d:%d,setsar=1,format=yuv420p"
                 % (i, fps, width, height, width, height))
        if s["long"]:
            chain += "," + zoom_filter(fps) + ",setsar=1"
        parts.append("%s[v%d]" % (chain, i))

    blocks = [[0]]                  # runs of trims joined by plain cuts
    for i in range(1, len(segs)):
        if cuts[i - 1]:
            blocks.append([i])
        else:
            blocks[-1].append(i)

    labels, lengths = [], []
    for b, idxs in enumerate(blocks):
        lengths.append(sum(segs[i]["duration"] for i in idxs))
        if len(idxs) == 1:
            labels.append("v%d" % idxs[0])
        else:
            parts.append("%sconcat=n=%d:v=1:a=0,fps=%d[b%d]"
                         % ("".join("[v%d]" % i for i in idxs), len(idxs), fps, b))
            labels.append("b%d" % b)

    prev, acc = labels[0], lengths[0]
    for k in range(1, len(labels)):
        offset = acc - xf
        parts.append("[%s][%s]xfade=transition=%s:duration=%.4f:offset=%.4f[x%d]"
                     % (prev, labels[k], transition, xf, offset, k))
        acc = offset + lengths[k]
        prev = "x%d" % k
    parts.append("[%s]tpad=stop_mode=clone:stop_duration=1.0[%s]" % (prev, out_label))
    return parts


def zoom_effects_work():
    """Quick self-test: does this FFmpeg re-evaluate a scale() size on every frame?
    The zoom-type text effects (pop, zoom_in, zoom_out) depend on it. Returns False
    when the size stays frozen, so the script can skip those effects instead of
    producing text at the wrong size."""
    graph = ("color=c=white:s=40x20:r=10:d=2,format=rgba,"
             "fade=t=in:st=0:d=0.1:alpha=1,"
             "scale=w='max(2,round(iw*(1+0.5*t)))':h='max(2,round(ih*(1+0.5*t)))':eval=frame[s];"
             "color=c=black:s=200x60:r=10:d=2[bg];"
             "[bg][s]overlay=x='(W-w)/2':y='(H-h)/2':eval=frame,format=gray")
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-filter_complex", graph,
                            "-f", "rawvideo", "-"], stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    size = 200 * 60
    frames = [r.stdout[i:i + size] for i in range(0, len(r.stdout) - size + 1, size)]
    if len(frames) < 18:
        return False

    def width(frame):               # lit pixels across the middle row
        return sum(1 for v in frame[30 * 200:31 * 200] if v > 128)
    return width(frames[16]) - width(frames[3]) >= 10     # ~72px vs ~46px when it works


def text_graph(blocks, in_label, effect, t_in, t_out, d, scale):
    """Overlay the text blocks (one PNG input each) with the chosen effect."""
    parts, prev = [], in_label
    for k, b in enumerate(blocks):
        x, y, zoom = effect_expressions(effect, b["cx"], b["cy"], scale, t_in, t_out, d)
        chain = ("[%d:v]format=rgba,fade=t=in:st=%.3f:d=%.3f:alpha=1,"
                 "fade=t=out:st=%.3f:d=%.3f:alpha=1" % (b["input"], t_in, d, t_out, d))
        if zoom:
            # No "format" filter after this scale: with one behind it, some FFmpeg
            # builds stop re-evaluating the size on every frame and the text would
            # stay stuck at its starting size (zoom_effects_work() checks for this).
            chain += (",scale=w='max(2,round(iw*%s))':h='max(2,round(ih*%s))':"
                      "eval=frame" % (zoom, zoom))
        parts.append("%s[tb%d]" % (chain, k))
        out = "vt%d" % k if k < len(blocks) - 1 else "vout"
        parts.append("[%s][tb%d]overlay=x='%s':y='%s':eval=frame[%s]" % (prev, k, x, y, out))
        prev = out
    return parts


def audio_graph(vi, mi, total, music_gain):
    """Voiceover (starts VO_DELAY in) + music at music_gain that ducks while the
    voice speaks. Ends at label [mixed]."""
    delay_ms = int(VO_DELAY * 1000)
    return [
        "[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "adelay=%d|%d,apad,atrim=0:%.3f,asetpts=PTS-STARTPTS,asplit=2[vo1][vo2]"
        % (vi, delay_ms, delay_ms, total),
        "[%d:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "atrim=0:%.3f,asetpts=PTS-STARTPTS,volume=%.4f,"
        "afade=t=in:st=0:d=1.5,afade=t=out:st=%.3f:d=2.0[mus]"
        % (mi, total, music_gain, total - 2.0),
        "[mus][vo2]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=400[duck]",
        "[vo1][duck]amix=inputs=2:duration=longest:normalize=0[mixed]",
    ]


def music_input(music, music_start, loop_music):
    args = []
    if loop_music:
        args += ["-stream_loop", "-1"]
    if music_start > 0:
        args += ["-ss", "%.3f" % music_start]
    return args + ["-i", str(music["path"])]


def measure_mix(vo, music, music_start, loop_music, total, music_gain):
    """Loudness (LUFS) of the voice+music mix before the final level is set."""
    graph = ";".join(audio_graph(0, 1, total, music_gain)
                     + ["[mixed]ebur128=framelog=quiet:peak=true[m]"])
    cmd = (["ffmpeg", "-hide_banner", "-nostats", "-i", str(vo["path"])]
           + music_input(music, music_start, loop_music)
           + ["-filter_complex", graph, "-map", "[m]", "-f", "null", "-"])
    return parse_lufs(run_capture(cmd).stderr)


def build_command(segs, cuts, transition, vo, music, music_start, loop_music,
                  music_gain, mix_lufs, total, size, fps, preset, crf, out_path, text=None):
    n = len(segs)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y"]
    for s in segs:  # video inputs: fast seek to the start, read only the trim
        cmd += ["-an", "-ss", "%.3f" % s["start"], "-t", "%.3f" % s["duration"],
                "-i", str(s["clip"]["path"])]
    cmd += ["-i", str(vo["path"])]
    cmd += music_input(music, music_start, loop_music)
    if text:
        for k, b in enumerate(text["blocks"]):
            cmd += ["-loop", "1", "-framerate", str(fps), "-t", "%.3f" % total,
                    "-i", str(b["png"])]
            b["input"] = n + 2 + k

    parts = video_graph(segs, cuts, transition, size, fps, "vbase" if text else "vout")
    if text:
        parts += text_graph(text["blocks"], "vbase", text["effect"], text["t_in"],
                            text["t_out"], text["duration"], text["scale"])
    parts += audio_graph(n, n + 1, total, music_gain)
    if mix_lufs is not None:        # exact, constant gain: keeps voice/music balance
        parts.append("[mixed]volume=%.2fdB,alimiter=limit=0.89:level=disabled,"
                     "aresample=48000[aout]" % (TARGET_LUFS - mix_lufs))
    else:
        parts.append("[mixed]loudnorm=I=%.0f:TP=-1.5:LRA=11,aresample=48000[aout]"
                     % TARGET_LUFS)

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[vout]", "-map", "[aout]",
            "-t", "%.3f" % total,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-r", str(fps),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", str(out_path)]
    return cmd


def unique_path(folder, stem, suffix):
    p = folder / (stem + suffix)
    n = 2
    while p.exists():
        p = folder / ("%s_%d%s" % (stem, n, suffix))
        n += 1
    return p


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="Turn the prayers in Batch.md into videos (Piper voice, clips, music, text).")
    ap.add_argument("--days", default="", help="only these days, e.g. 1,3-5")
    ap.add_argument("--count", type=int, default=0, help="only the first N days")
    ap.add_argument("--ratio", choices=["auto"] + sorted(SIZES), default=None,
                    help="auto, 9:16 or 16:9 (default: from config.json)")
    ap.add_argument("--base", default="",
                    help="folder with config.json, Batch.md and the other folders "
                         "(default: the folder this script is in)")
    ap.add_argument("--config", default="", help="path to config.json (default: next to the script)")
    ap.add_argument("--seed", type=int, default=None,
                    help="repeat a previous random result (seed is printed and logged)")
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--crf", type=int, default=None)
    ap.add_argument("--preset", default=None, help="x264 speed preset (default: from config.json)")
    ap.add_argument("--dry-run", action="store_true", help="plan only, do not render")
    ap.add_argument("--test-voice", action="store_true",
                    help="make a short test voiceover to check Piper and the voice model")
    args = ap.parse_args()

    base = Path(args.base).resolve() if args.base else Path(__file__).resolve().parent
    cfg_path = Path(args.config) if args.config else base / "config.json"
    if cfg_path.exists():
        cfg = deep_merge(DEFAULT_CONFIG, load_json(cfg_path))
    else:
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print("Created %s with the default settings." % cfg_path.name)
    try:
        apply_config(cfg)
    except (KeyError, ValueError, TypeError) as e:
        sys.exit("ERROR: a setting in config.json is wrong (%s). Delete that setting to "
                 "go back to its default." % e)

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit("ERROR: %s not found on PATH. Install FFmpeg, then open a NEW "
                     "terminal window and try again." % tool)
    if Image is None:
        sys.exit("ERROR: Pillow is not installed. Run:  pip install pillow")

    folders = {k: base / v for k, v in cfg["folders"].items()}
    for name in ("voiceovers", "output", "fonts"):
        folders[name].mkdir(parents=True, exist_ok=True)
    pcfg = cfg["piper"]
    model_path = resolve_model(pcfg["model"], folders["voice"])
    base_cmd = piper_base_command(pcfg["command"])

    # ---- voice test ----------------------------------------------------------
    if args.test_voice:
        folders["voice"].mkdir(parents=True, exist_ok=True)
        try:
            piper_check(base_cmd, model_path)
            out = folders["voiceovers"] / "_voice_test.wav"
            piper_synthesize("This is a test of the Piper voice. If you can hear this, "
                             "the voice is working.", out, base_cmd, model_path,
                             float(pcfg["voice_speed"]), pcfg["speaker"], pcfg["sentence_pause"])
            ch, sw, rate, frames = wav_info(out)
            print("OK - Piper made %s (%.1f seconds). Open it to listen." % (out, frames / rate))
        except RuntimeError as e:
            sys.exit("Voice test failed:\n%s" % e)
        return

    missing = False
    for name in ("clips", "music", "voice"):
        if not folders[name].exists():
            folders[name].mkdir(parents=True)
            print("Created empty folder: %s" % folders[name])
            missing = True
    if missing:
        sys.exit("Put your files in those folders, then run the script again.")

    batch_path = base / cfg["batch_file"]
    look_path = base / cfg["look_file"]
    if not batch_path.exists():
        sys.exit("ERROR: %s not found. Put Batch.md next to the script." % batch_path)
    if not look_path.exists():
        sys.exit("ERROR: %s not found. Put look.json next to the script." % look_path)
    look = load_json(look_path)
    for role in ("hook", "prayer"):
        if not look.get(role, {}).get("styles"):
            sys.exit("ERROR: look.json has no styles for '%s'." % role)

    print("Scanning folders in %s" % base)
    clips = scan(folders["clips"], VIDEO_EXT, need_video=True, min_duration=MIN_CLIP_SECONDS)
    tracks = scan(folders["music"], AUDIO_EXT)
    days = parse_batch(batch_path, cfg["batch"]["hook_labels"], cfg["batch"]["prayer_labels"])
    print("Found %d clips, %d music tracks, %d days in %s"
          % (len(clips), len(tracks), len(days), batch_path.name))
    if len(clips) < 2:
        sys.exit("ERROR: need at least 2 usable clips (3-5 recommended) in %s/" % folders["clips"].name)
    if len(clips) < CLIPS_MIN:
        print("WARNING: only %d usable clips; 3 or more gives better variety." % len(clips))
    if not tracks:
        sys.exit("ERROR: no music files in %s/" % folders["music"].name)
    if not days:
        sys.exit("ERROR: no days found in %s. Each day should start with a line like "
                 "'## DAY 1 - TITLE'." % batch_path.name)

    ready = []
    for d in days:
        if not d["hook"] or not d["prayer"]:
            print("  skip Day %d: %s not found in %s"
                  % (d["number"], "the EMOTIONAL HOOK" if not d["hook"] else "the PRAYER text",
                     batch_path.name))
        else:
            ready.append(d)
    days = ready
    if args.days:
        wanted = parse_days(args.days)
        days = [d for d in days if d["number"] in wanted]
    if args.count > 0:
        days = days[:args.count]
    if not days:
        sys.exit("Nothing to make.")

    seed = args.seed if args.seed is not None else random.randrange(1 << 30)
    rng = random.Random(seed)
    print("Random seed: %d  (use --seed %d to repeat this exact run)" % (seed, seed))

    vcfg = cfg["video"]
    ratio_setting = args.ratio or vcfg["ratio"]
    if ratio_setting == "auto":
        ratio, n_portrait, n_landscape = detect_ratio(clips)
        print("Aspect ratio: %s (auto: %d portrait, %d landscape clips)"
              % (ratio, n_portrait, n_landscape))
    else:
        ratio = ratio_setting
        print("Aspect ratio: %s (set by you)" % ratio)
    W, H = SIZES[ratio]
    scale = min(W, H) / 1080.0
    fps = args.fps or int(vcfg["fps"])
    crf = args.crf if args.crf is not None else int(vcfg["crf"])
    preset = args.preset or vcfg["preset"]

    tcfg = cfg["text"]
    effects = [e for e in tcfg["effects"] if e in EFFECTS]
    for e in tcfg["effects"]:
        if e not in EFFECTS:
            print("  WARNING: unknown text effect '%s' in config.json ignored (known: %s)"
                  % (e, ", ".join(EFFECTS)))
    if tcfg["enabled"] and not effects:
        sys.exit("ERROR: text.effects in config.json has no valid effect.")
    zoomers = [e for e in effects if EFFECTS[e]["zoom"] != 1.0]
    if tcfg["enabled"] and zoomers and not zoom_effects_work():
        print("  WARNING: this version of FFmpeg cannot animate the text size, so the zoom "
              "effects (%s) are skipped. Updating FFmpeg fixes this." % ", ".join(zoomers))
        effects = [e for e in effects if e not in zoomers] or ["fade"]
    fonts = Fonts(folders["fonts"], tcfg["fallback_fonts"])

    transitions_available = supported_transitions()
    music_order = cycle_pick(tracks, len(days), rng)
    effect_pick = Rotator(effects, rng, tcfg["no_repeat_effects_in_batch"]) if effects else None
    hook_pick = Rotator(look["hook"]["styles"], rng, tcfg["no_repeat_looks_in_batch"])
    prayer_pick = Rotator(look["prayer"]["styles"], rng, tcfg["no_repeat_looks_in_batch"])
    tag = ratio.replace(":", "x")
    previous_transition = None

    # ---- Piper preflight (only when some voiceover still has to be made) --------
    if not args.dry_run and any(not cached_voice(d, pcfg, model_path, folders["voiceovers"])
                                for d in days):
        try:
            piper_check(base_cmd, model_path)
        except RuntimeError as e:
            sys.exit("ERROR: %s" % e)

    done, failed = 0, 0
    for idx, day in enumerate(days):
        music = music_order[idx]
        label = "Day %d" % day["number"]
        print("\n[%d/%d] %s - %s" % (idx + 1, len(days), label, day["title"] or "(no title)"))
        try:
            # ---- voiceover -----------------------------------------------------
            if args.dry_run:
                hit = cached_voice(day, pcfg, model_path, folders["voiceovers"])
                vo = hit or {"path": voice_paths(day, folders["voiceovers"])[0],
                             "duration": estimate_voice_seconds(day, pcfg), "cached": False}
                note = "saved voiceover" if hit else "estimate"
            else:
                started_v = time.time()
                vo = make_voiceover(day, pcfg, base_cmd, model_path, folders["voiceovers"])
                note = "reused saved voiceover" if vo["cached"] else \
                    "made with Piper in %.0fs" % (time.time() - started_v)
            total = round(VO_DELAY + vo["duration"] + AFTER_VOICE, 3)
            print("  voiceover %.1fs (%s) -> video %.1fs, %s"
                  % (vo["duration"], note, total, ratio))

            # ---- clips, music, transition -------------------------------------
            plan = plan_timeline(total, fps)
            if ALLOW_CLIP_REPEAT:
                chosen = rng.sample(clips, min(rng.randint(CLIPS_MIN, CLIPS_MAX), len(clips)))
            else:
                chosen = clips
                if len(clips) < len(plan):
                    print("  WARNING: %d trims but only %d clips, so some clips must repeat "
                          "(add %d more clips to avoid it)."
                          % (len(plan), len(clips), len(plan) - len(clips)))
            segs = pick_segments(chosen, plan, rng)
            cuts = [transition_at(segs[i]["long"], segs[i + 1]["long"])
                    for i in range(len(segs) - 1)]
            transition = pick_transition(transitions_available, previous_transition, rng)
            previous_transition = transition

            music_start, loop_music = 0.0, False
            if music["duration"] >= total + 2.0:
                music_start = rng.uniform(0.0, music["duration"] - total - 1.0)
            elif music["duration"] < total + 0.5:
                loop_music = True

            # ---- on-screen text ------------------------------------------------
            effect, hook_style, prayer_style, info = None, None, None, {}
            t_in = t_out = 0.0
            blocks_img = []
            if tcfg["enabled"]:
                effect = effect_pick.next()
                hook_style, prayer_style = hook_pick.next(), prayer_pick.next()
                hook_text = apply_case(day["hook"], look["hook"].get("text_case", "upper"))
                prayer_text = apply_case(day["prayer"], look["prayer"].get("text_case", "normal"))
                for role, text, style in (("hook", hook_text, hook_style),
                                          ("prayer", prayer_text, prayer_style)):
                    blk = render_text_block(text, style, W, H, scale, fonts)
                    blk["role"], blk["style"] = role, style
                    blocks_img.append(blk)
                    info[role] = {"style": style.get("name", "?"), "font": blk["font_file"],
                                  "font_size": blk["font_size"], "lines": blk["lines"]}
                    if not blk["fits"]:
                        print("  WARNING: the %s text is too long for its area even at the "
                              "smallest font size; shorten it or edit look.json." % role)
                d_eff = float(tcfg["effect_duration"])
                t_in = max(0.0, VO_DELAY - float(tcfg["in_before_voice"]))
                t_out = VO_DELAY + vo["duration"] + float(tcfg["out_after_voice"])
                t_out = max(t_in + d_eff, min(t_out, total - d_eff - 0.1))

            print("  music: %s%s" % (music["path"].name,
                                     " (looped)" if loop_music else
                                     " (from %.0fs)" % music_start if music_start else ""))
            print("  transition (8s trims only): %s" % transition)
            if effect:
                print("  text effect: %s | hook look: %s (%dpx) | prayer look: %s (%dpx, %d lines)"
                      % (effect, info["hook"]["style"], info["hook"]["font_size"],
                         info["prayer"]["style"], info["prayer"]["font_size"],
                         info["prayer"]["lines"]))
            for i, s in enumerate(segs):
                nxt = ""
                if i < len(cuts):
                    nxt = "  -> %s" % (transition if cuts[i] else "cut")
                print("  %2d. %-22s %5.1f-%5.1fs  %4.1fs%s%s" % (
                    i + 1, s["clip"]["path"].name, s["start"], s["start"] + s["duration"],
                    s["duration"], " slow zoom" if s["long"] else "           ", nxt))
            if args.dry_run:
                continue

            # ---- render ---------------------------------------------------------
            vo_lufs, music_lufs = measure_lufs(vo["path"]), measure_lufs(music["path"])
            if vo_lufs is None or music_lufs is None:
                music_gain = 0.3
                print("  WARNING: could not measure loudness; using a fixed music level.")
            else:
                music_gain = MUSIC_VS_VOICE * 10 ** ((vo_lufs - music_lufs) / 20.0)
                music_gain = min(8.0, max(0.02, music_gain))
            mix_lufs = measure_mix(vo, music, music_start, loop_music, total, music_gain)

            name = "Day%d" % day["number"]
            if day["title"]:
                name += "_" + slugify(day["title"])
            out_path = unique_path(folders["output"], name, ".mp4")
            with tempfile.TemporaryDirectory(prefix="prayer_text_") as tmp:
                text = None
                if blocks_img:
                    for blk in blocks_img:
                        blk["png"] = Path(tmp) / ("%s.png" % blk["role"])
                        blk["image"].save(blk["png"])
                    text = {"blocks": blocks_img, "effect": effect, "t_in": t_in,
                            "t_out": t_out, "duration": float(tcfg["effect_duration"]),
                            "scale": scale}
                cmd = build_command(segs, cuts, transition, vo, music, music_start, loop_music,
                                    music_gain, mix_lufs, total, (W, H), fps, preset, crf,
                                    out_path, text)
                started = time.time()
                result = subprocess.run(cmd)
            print()
            if result.returncode != 0 or not out_path.exists():
                if out_path.exists():
                    out_path.unlink()
                raise RuntimeError("FFmpeg failed - see the error above.")

            log = {
                "output": out_path.name, "day": day["number"], "title": day["title"],
                "ratio": ratio, "length_seconds": total, "seed": seed,
                "hook": day["hook"], "prayer": day["prayer"],
                "voiceover": vo["path"].name, "voiceover_seconds": round(vo["duration"], 3),
                "voiceover_starts_at": VO_DELAY,
                "text": ({"effect": effect, "appears_at": round(t_in, 3),
                          "disappears_at": round(t_out + float(tcfg["effect_duration"]), 3),
                          "hook": info["hook"], "prayer": info["prayer"]} if effect else None),
                "transition": transition,
                "music": music["path"].name, "music_start": round(music_start, 3),
                "music_looped": loop_music, "music_vs_voice": MUSIC_VS_VOICE,
                "music_gain_db": round(20.0 * math.log10(music_gain), 1),
                "segments": [
                    {"clip": s["clip"]["path"].name, "start": s["start"],
                     "duration": s["duration"], "slow_zoom": s["long"],
                     "then": (transition if cuts[i] else "cut") if i < len(cuts) else None}
                    for i, s in enumerate(segs)
                ],
            }
            out_path.with_suffix(".json").write_text(json.dumps(log, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")
            done += 1
            print("  done in %.0fs -> %s" % (time.time() - started, out_path.name))
        except Exception as e:                       # one bad day must not stop the batch
            failed += 1
            print("  FAILED (%s): %s - moving on." % (label, e))

    if effect_pick is not None and effect_pick.cycled and not args.dry_run:
        print("\nNOTE: this batch has more days than text effects, so some effects were "
              "used again. Add more effects in config.json to avoid it.")
    if args.dry_run:
        print("\nDry run only - nothing was rendered.")
    else:
        print("\nFinished: %d made, %d failed. Output folder: %s"
              % (done, failed, folders["output"]))


if __name__ == "__main__":
    main()
