---
name: luxury-clips-montage
description: Builds 9:16 motivational montages from shuffled YouTube B-roll clips with dark-luxury charcoal grade, speech audio, and DrivenVisuals phrase captions by default. Reuse of prior sources is allowed by default — check production library for context. Use when the user wants a luxury car/video montage, dark filter over YouTube clips, motivational speech over B-roll, or to recreate the car-luxury / Tate-style video workflow.
---

# Luxury clips montage

One script. Do not search, download, pick durations, clean, read `content/used.json`, or dump job logs.

```powershell
python scripts/build_motivation_job.py `
  --slug yacht-motivation `
  --broll-query "luxury yacht cinematic 4k short" `
  --hook "YOU ARE WASTING YOUR BEST YEARS" `
  --reuse-policy allow
```

Script searches speech + B-roll, renders 9:16 + grade + **phrase captions** (DrivenVisuals default), rebuilds catalog, deletes leftovers.

Creative preset: `content/driven-visuals-defaults.json` — fast opener pacing, hook styling, quality gate.

## Who the speech is from

`downloads/motivational/config.json`:

```json
{"speech_query": "motivational speech discipline mindset", "broll_query": "luxury car cinematic 4k short"}
```

Set any YouTube search for speech and visuals. `--speech-query` / `--broll-query` override one run.

## Reuse (advisory)

- Default `--reuse-policy allow`: same source/speaker/B-roll OK — pick a different excerpt or new visuals.
- Query prior usage: `python scripts/production_library_cli.py check-reuse --source-url "..."`
- Only add `--reuse-policy require_new` when the user explicitly asks for unused / never-used material.

## Leftover speech

Script takes ~20–28s (DrivenVisuals short default). Rest of that download is split into more excerpts and stashed in `downloads/motivational/speech-pool/{speaker}/` even when reuse is allowed. Next job for the same speaker uses the pool first — no new YouTube download.

## Repeat speech

Script fingerprints the excerpt + source captions. Same words on a new YouTube id still counts as used. It skips that candidate and tries the next speech. Leftover minutes from the same download are new excerpts, not repeats.

Do not copy `speech.mp3` / `subs.en.json3` from another job. Do not pass `--speech-url` of a speech already used, even a re-upload.

User deleted local speeches and wants them pickable again:

```powershell
python scripts/content_reuse.py reset-speeches
```

## Playback speed

Clips play at **source speed** by default (`--playback-speed 1`). Use `0.80` only when you want slower motion.

Drop B-roll under 50fps. Delete it. Do not keep 24p/25p/30p. 4K is optional — 1080p/1440p is fine. Output is 60fps.

## Subject in frame

`--broll-query` is the required on-screen subject.

Script:

1. Prefers source titles that name that subject
2. Skips the first 8s of each B-roll source (intros / talking heads)
3. Scans frames through each clip
4. Trims talking-head, title-card, empty, missing-subject, and out-of-context frames
5. Drops a clip if nothing usable remains
6. Splits each downloaded source into ~20s parts (full video, capped by `BROLL_MAX_PARTS_PER_SOURCE`), gates every part, and **copies passing clips into `downloads/motivational/broll-pool/`** for the next job

First seconds of the output must show the subject with **movement** when possible. If a Porsche job opens on a house or a host, the gate failed — do not ship it.

**Cars (required):** keep **exterior** frames only — drop cabin, dashboard, steering wheel, seats, interior POV. Opener is a **full view of the car** (front / three-quarter / side, most of the body) held **≥5 seconds** before a cut to detail. Check 0s, ~2.5s, and 5s on the output. See `.cursor/rules/car-exterior-frames.mdc`.

## Agent rules (Cursor checks — preferred)

Use **`--cursor-review`** so code gates defer to you:

```powershell
python scripts/build_motivation_job.py `
  --slug ... `
  --broll-query "..." `
  --cursor-review
```

Script writes `{job}/cursor-review/REVIEW.md` + `final/*.png`. **You** read those images + excerpt before ship. No OpenAI vision in pipeline.

Manual pack anytime:

```powershell
python scripts/prepare_cursor_montage_review.py --job-dir downloads/motivational/{slug}
```

1. Run the script. New `--slug` + new `--broll-query` every job.
2. Open `cursor-review/REVIEW.md` (or run prepare script). Read final stills + speech excerpt.
3. Ship only if line is punchy **and** opener frames pass car-exterior rules (cars). Otherwise remake. Do not vet every source clip unless user asked.

## Flags

| Flag | Default | When to set |
|---|---|---|
| `--slug` | required | Job folder name |
| `--broll-query` | required | Cars, yachts, watches, etc. |
| `--hook` | none | 4–7 word opener matching speech |
| `--speech-url` | search | User already picked a speech |
| `--speaker` | `config.json` | One-run override |
| `--reuse-policy` | `allow` | `require_new` only when user asked for unused-only |
| `--segment-length` | auto | Override uniform beat length |
| `--uniform-pacing` | off | Disable fast-open DrivenVisuals pacing |
| `--classic-captions` | off | Revert to single-word captions |
| `--playback-speed` | `1` | Source speed. Lower (e.g. `0.80`) = slower motion |
| `--intro-skip` | `8` | Skip more intro if hosts keep talking |
| `--min-seconds` / `--max-seconds` | `20` / `28` | Excerpt window. Longer cuts need explicit flags |
| `--cursor-review` | off | **Agent** ship gate; skips code vision/frame/segment/render gates |
| `--no-vision` | off | Skip GPT-4o-mini only (local frame gate still on) |
| `--no-frame-gate` | off | Skip B-roll scan/trim; fps still required |
| `--no-segment-gate` | off | Skip per-beat frame gate in montage |
| `--no-grade` | off | User wants raw color |
| `--skip-quality-gate` | off | Skip pre-ship checks |
| `--keep-work` | off | Keep `clips/` |
| `--cleanup-only` | off | Clean job folders |
| `--rerender` | off | Remake existing slug (same speech + B-roll) |

Output: `downloads/motivational/{slug}/output/{slug}-motivation.mp4`

Charcoal / slate, light plum, 1080×1920. Do not brighten unless asked. Legal: only footage user owns or has rights to repost.

Pre-ship (code mode only): `python scripts/check_render_quality.py --video ...`  
Pre-ship (agent mode): read `{job}/cursor-review/REVIEW.md` + PNGs — see `.cursor/rules/cursor-montage-review.mdc`
