# Prayer Video Automation (Windows)

Turns the prayers in `Batch.md` into finished vertical videos. For every day it:

1. reads only the **EMOTIONAL HOOK** and the **PRAYER** text (titles, descriptions and tags are ignored),
2. makes the voiceover with **Piper** (hook, a pause, then the prayer),
3. cuts random trims from your clips in a repeating 4s, 4s, 4s, 8s pattern (slow zoom and transitions on the 8s trims only),
4. shows the hook and the prayer as two on-screen text blocks that animate in and out together,
5. adds random background music (half as loud as the voice, lowered further while the voice speaks) and exports the video.

The voice starts **4 seconds in**, and the video continues **8 seconds** after the voice ends.

## One-time setup

1. **Python 3.8+** and **FFmpeg** (`winget install Gyan.FFmpeg`). Open a new terminal afterwards and check `python --version` and `ffmpeg -version`.
2. **Pillow**, used to draw the text: `pip install pillow`
3. **Piper** (already installed) and your voice model. Put both files in the `voice` folder:
   ```
   voice\en_US-bryce-medium.onnx
   voice\en_US-bryce-medium.onnx.json
   ```
4. Put `make_videos.py`, `config.json`, `look.json` and `Batch.md` in one folder (the "root" folder).
5. Check that Piper and the voice work:
   ```
   python make_videos.py --test-voice
   ```
   It writes `voiceovers\_voice_test.wav`. Open it and listen. If it fails, the message tells you what is wrong (see Troubleshooting).

## Folders

```
root folder\
  make_videos.py   config.json   look.json   Batch.md
  clips\         your source videos (3+ files, each at least ~10s)
  music\         royalty-free tracks (mp3/wav/m4a)
  voice\         your Piper voice model (.onnx + .onnx.json)
  voiceovers\    made by the script: Day1.wav, Day2.wav ...
  output\        finished videos + a .json log for each
  fonts\         optional: extra .ttf files (Windows fonts are found automatically)
```

Missing folders are created on the first run.

## Run it

Open a terminal in the root folder (type `cmd` in the folder's address bar), then:

| Command | What it does |
|---|---|
| `python make_videos.py` | Makes a video for every day in Batch.md |
| `python make_videos.py --days 1,3-5` | Only those days |
| `python make_videos.py --count 2` | Only the first 2 days |
| `python make_videos.py --ratio 16:9` | Force landscape (default: 9:16 vertical, or 16:9 if most of your clips are landscape) |
| `python make_videos.py --dry-run` | Show the plan (voice length is an estimate), render nothing |
| `python make_videos.py --test-voice` | Check Piper and the voice model |
| `python make_videos.py --seed 123` | Repeat an earlier random result (every run prints and logs its seed) |

Finished videos are named like `Day1_letting-the-tears-fall.mp4`. If a file with that name exists, the new one gets `_2` and so on. If one day fails, the others still finish and the error is printed.

Voiceovers are saved in `voiceovers\` and reused while the text, the voice and the voice settings are unchanged, so re-runs are faster. Change a prayer or a voice setting and that day's voiceover is made again.

## Batch.md format

Each day starts with a `## DAY n - TITLE` line, then bold labels:

```
## DAY 1 — LETTING THE TEARS FALL

**EMOTIONAL HOOK**

You don't have to hold it together here.

**PRAYER**

Lord Jesus, I'm tired of pretending I'm fine. ...

**YOUTUBE SHORTS TITLE**   (ignored, like every other section)
```

The labels the script looks for are set in `config.json` (`batch`). Markdown marks such as `**bold**` and emoji are removed from the spoken and on-screen text.

## The timeline of a video

| Time | What happens |
|---|---|
| 0 - 3.5s | Clips and music only |
| 3.5 - 4.1s | The hook and the prayer animate in together |
| 4.0s | The voice starts: hook, pause, prayer |
| voice ends + 0.3s | The text animates out |
| last ~7s | Clips and music only; the video ends 8s after the voice |

Total length = 4s + voiceover + 8s.

- **Text effect:** every video gets **one** random effect, used for the way the text comes in and goes out. Effects are not repeated within a batch until all have been used. Available: `fade`, `rise`, `drop`, `slide_from_left`, `slide_from_right`, `zoom_in`, `zoom_out`, `pop`.
- **Text layout:** the hook sits in the upper area, the prayer in the middle. If a text is too long for its area, the font shrinks automatically (never below `min_font_size`).
- **Trims:** 4s, 4s, 4s, 8s, repeating; the last trim is shortened so the length is exact. The 8s trims get a slow 15% zoom-in, and a random transition (one per video) is used at the 8s trims only. Cuts between the 4s trims are plain cuts. Original clip audio is removed.
- **Music:** a random track, set to half the loudness of the voice, lowered further while the voice speaks, with fade in and out. The whole video ends up at about -14 LUFS.

## config.json

Lines starting with `_` are notes. Folder names are relative to the root folder. In Windows paths use forward slashes (`C:/piper/piper.exe`) or doubled backslashes.

| Setting | What it does | Default |
|---|---|---|
| `folders` | Names of the clips, music, voice, voiceovers, output and fonts folders | as listed above |
| `batch_file`, `look_file` | The prayers file and the text design file | `Batch.md`, `look.json` |
| `piper.command` | `auto` finds Piper itself; otherwise the full path of `piper.exe` | `auto` |
| `piper.model` | Voice model file name (inside `voice\`) or a full path | `en_US-bryce-medium.onnx` |
| `piper.voice_speed` | 1.0 normal, 0.9 slower, 1.1 faster | 1.0 |
| `piper.pause_between_hook_and_prayer` | Seconds of silence between hook and prayer | 0.8 |
| `piper.sentence_pause` | Seconds of silence between sentences, or `null` for the voice's own | `null` |
| `piper.speaker` | Speaker number for multi-speaker models, otherwise `null` | `null` |
| `timing.voice_starts_at` | When the voice starts | 4 |
| `timing.seconds_after_voice` | How long the video continues after the voice | 8 |
| `text.enabled` | `false` = no on-screen text | true |
| `text.in_before_voice` | The text starts coming in this many seconds before the voice | 0.5 |
| `text.out_after_voice` | The text starts going out this many seconds after the voice ends | 0.3 |
| `text.effect_duration` | How long the in and out animations last | 0.6 |
| `text.effects` | The effects to choose from (keep at least as many as days per batch) | all 8 |
| `text.no_repeat_effects_in_batch`, `text.no_repeat_looks_in_batch` | Avoid repeats until everything has been used | true |
| `video.ratio` | `auto`, `9:16` or `16:9` | `auto` |
| `video.fps`, `video.crf`, `video.preset` | Frame rate, quality (lower = better), render speed | 30, 20, `fast` |
| `video.trim_pattern`, `video.long_trim_seconds` | Trim lengths; trims at least `long_trim_seconds` long get zoom and transitions | `[4,4,4,8]`, 8 |
| `video.zoom_percent` | Zoom over an 8s trim | 15 |
| `video.transition_seconds`, `video.transitions_at` | Transition length; `both`, `into` or `out` of the 8s trims | 0.4, `both` |
| `video.clips_per_video` | Random number of different clips per video | `[3,5]` |
| `video.allow_clip_repeat` | `false` = every trim in a video comes from a different clip (needs ~8-14 clips) | true |
| `music.volume_vs_voice` | 0.5 = music half as loud as the voice | 0.5 |
| `music.target_loudness_lufs` | Overall loudness of the video | -14 |

## look.json (on-screen text designs)

It has one list of design sets for the **hook** and a separate list for the **prayer**. Every video picks one random set for each (not repeated within a batch until all have been used). The hook is always shown in UPPERCASE (`"text_case": "upper"`) and the prayer in normal casing (`"normal"`).

Each set can contain:

| Field | Meaning |
|---|---|
| `name` | Any label, shown in the log |
| `font` | A Windows font file name (for example `georgiab.ttf`) or a `.ttf` in the `fonts` folder |
| `font_size`, `min_font_size` | Largest size, and the smallest the text may shrink to (pixels on a 1080px-wide video) |
| `color` | Text color, `#RRGGBB` |
| `line_spacing`, `align` | Line height as a multiple of the font size; `center`, `left` or `right` |
| `margins` | Pixels kept clear from the screen edges (`left`, `right`, `top`, `bottom`) |
| `zone` | Where the text sits, as % of the screen height (`top`, `bottom`), and `vertical_align` inside that area |
| `background` | The box behind the text: `enabled`, `color`, `opacity` (0-1), `radius`, `padding_x`, `padding_y` |
| `outline` | `width` (0 = none) and `color` around each letter |
| `shadow` | `enabled`, `color`, `opacity`, `offset_x`, `offset_y`, `blur` |

To add a design, copy one set, change it and add a comma. To make a design appear more or less often, copy or remove sets. Keep at least as many sets as days in a batch to avoid repeats (7 sets each are included).

Common Windows font files: `arial.ttf`, `arialbd.ttf`, `ariblk.ttf` (Arial Black), `georgia.ttf`, `georgiab.ttf`, `impact.ttf`, `times.ttf`, `timesbd.ttf`, `verdana.ttf`, `verdanab.ttf`, `trebuc.ttf`, `trebucbd.ttf`, `segoeui.ttf`, `segoeuib.ttf`, `calibri.ttf`, `pala.ttf`, `tahoma.ttf`. If a font is missing the script prints a warning and uses a fallback font.

## Troubleshooting

- **"Could not start Piper" / "Piper does not seem to be installed"**: set `piper.command` in `config.json` to the full path of `piper.exe`, e.g. `"command": "C:/piper/piper.exe"`. If you installed Piper with pip, run the script with the same Python that has it.
- **"Piper voice model not found"**: the `.onnx` file and its `.onnx.json` file must both be in the `voice` folder, and `piper.model` must match the file name.
- **Wrong or odd pronunciation**: Piper reads what is written. Change the wording in Batch.md (for example write "3 A M" instead of "3 a.m." if it sounds wrong).
- **"font ... not found"**: the font is not installed; the script uses a fallback. Fix the file name in `look.json` or put the `.ttf` in the `fonts` folder.
- **"text is too long for its area"**: shorten the prayer, or lower `min_font_size` in `look.json`.
- **"this version of FFmpeg cannot animate the text size"**: the zoom effects are skipped; update FFmpeg (`winget upgrade Gyan.FFmpeg`).
- **"ffmpeg not found"**: open a new terminal after installing, or restart Windows.
- **Slow renders**: set `video.preset` to `veryfast`.
- Captions are not included, per your plan: the on-screen text is whole blocks, not word-synced.
