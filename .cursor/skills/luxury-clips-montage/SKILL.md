---
name: luxury-clips-montage
description: Builds 9:16 motivational montages from shuffled YouTube B-roll clips with dark-luxury charcoal grade, speech audio, and burned-in word captions. Each new job must use a new unused speech from the configured speaker and new unused B-roll. Use when the user wants a luxury car/video montage, dark filter over YouTube clips, motivational speech over B-roll, or to recreate the car-luxury / Tate-style video workflow.
---

# Luxury clips montage

One script. Do not search, download, pick durations, clean, read `content/used.json`, read scripts, extract frames, or dump job logs.

```powershell
python scripts/build_motivation_job.py `
  --slug yacht-motivation `
  --broll-query "luxury yacht cinematic 4k short"
```

Script picks unused speech from configured speaker, unused B-roll, renders 9:16 + grade + word captions, rebuilds catalog, deletes leftovers.

## Who the speech is from

`downloads/motivational/config.json`:

```json
{"speaker": "Andrew Tate", "speech_query": ""}
```

Change `speaker` to whoever you want. Blank `speech_query` searches `{speaker} motivational speech`. `--speaker` / `--speech-query` override one run.

## Repeat speech

Script fingerprints the excerpt + source captions. Same words on a new YouTube id still counts as used. It skips that candidate and tries the next speech.

Do not copy `speech.mp3` / `subs.en.json3` from another job. Do not pass `--speech-url` of a speech already used, even a re-upload.

User deleted local speeches and wants them pickable again:

```powershell
python scripts/content_reuse.py reset-speeches
```

## Playback speed

Clips play at **80%** (`--playback-speed 0.80`). `1` = source speed.

## Subject in frame

`--broll-query` is the required on-screen subject. Make sure we check clips and clip out any frames without our subject. or any out of context clips.

Script:

1. Prefers source titles that name that subject
2. Skips the first 8s of each B-roll source (intros / talking heads)
3. Scans frames through each clip
4. Trims talking-head, title-card, empty, missing-subject, and out-of-context frames
5. Drops a clip if nothing usable remains

First seconds of the output must show the subject. If a Porsche job opens on a house or a host, the gate failed — do not ship it.

## Agent rules

1. Run the script. Do not copy audio from another job.
2. New `--slug` + new `--broll-query` every job.
3. After it finishes, open the output mp4. Confirm the subject is on screen from the first beat and no out-of-context cut slipped in. Read `job.json` only if you need IDs. Do not re-run by hand.

## Flags

| Flag | Default | When to set |
|---|---|---|
| `--slug` | required | Job folder name |
| `--broll-query` | required | Cars, yachts, watches, etc. |
| `--speech-url` | search | User already picked a speech |
| `--speaker` | `config.json` | One-run override |
| `--segment-length` | `12` | Faster=`8`/`6`. Do not go below `8` unless asked |
| `--playback-speed` | `0.80` | Lower = slower motion. `1` = source speed |
| `--intro-skip` | `8` | Skip more intro if hosts keep talking |
| `--min-seconds` / `--max-seconds` | `60` / `90` | Excerpt window |
| `--no-vision` | off | Local frame gate only |
| `--no-grade` | off | User wants raw color |
| `--keep-work` | off | Keep `clips/` |
| `--cleanup-only` | off | Clean job folders |
| `--rerender` | off | Remake existing slug (same speech + B-roll) |

Output: `downloads/motivational/{slug}/output/{slug}-motivation.mp4`

Charcoal / slate, light plum, 1080×1920. Do not brighten unless asked. Legal: only footage user owns or has rights to repost.
