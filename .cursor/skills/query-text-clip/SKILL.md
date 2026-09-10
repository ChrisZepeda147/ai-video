---
name: query-text-clip
description: Builds short vertical clips from YouTube search queries or reused B-roll, stitches them into ~20s montages, and burns static centered text. Use when the user wants query-based video downloads, reused clip montages, short text-over-video clips, or TikTok-style quote overlays on B-roll.
---

# Query text clip

One script. Do not hand-download, hand-stitch, or rebuild the pipeline unless the script fails.

```powershell
python scripts/build_text_clip.py `
  --slug ocean-waves `
  --query "ocean waves cinematic 4k short" `
  --text "Discipline beats motivation."
```

Output: `downloads/text-clips/{slug}/output/{slug}-text.mp4`

## What it does

1. Pulls unused clips from `downloads/text-clips/broll-pool/` when query matches
2. Downloads new YouTube B-roll if pool is short
3. Stitches shuffled beats into a fixed-length silent montage (default **20s**)
4. Burns one static text line at chosen position
5. Stashes unused clips back into pool, rebuilds catalog

No speech. No word captions. Just B-roll + your text.

## Agent rules

1. Run the script. New `--slug` + new `--query` every job.
2. After render, open output mp4. Confirm subject matches query from first beat.
3. Do not copy clips from another job folder unless user asked to reuse that exact set.
4. Montage jobs skip manual `content/used.json` reads — script handles reuse.

## Text placement

`--text-place` options:

| Value | Position |
|---|---|
| `mid-center` | default — middle of frame |
| `top-center` | upper third |
| `bottom-center` | lower third |
| `top-left`, `top-right` | corners / edges |
| `mid-left`, `mid-right` | side middle |
| `bottom-left`, `bottom-right` | lower corners |

## Flags

| Flag | Default | When to set |
|---|---|---|
| `--slug` | required | Job folder name |
| `--query` | required | Search subject — cars, ocean, yacht, city, etc. |
| `--text` | required | Line burned on video |
| `--text-place` | `mid-center` | Move text up/down/side |
| `--duration` | `20` | Clip length in seconds |
| `--segment-length` | auto (~5s on 20s) | Faster cuts — try `4` |
| `--playback-speed` | `1` | Slower motion — `0.8` |
| `--intro-skip` | `8` | Skip talking-head intros |
| `--clips-dir` | job `clips/` | Use local mp4 folder only |
| `--local-only` | off | Re-render from job clips, no download |
| `--no-vision` | off | Faster, local gate only |
| `--no-grade` | off | Raw source color |
| `--keep-work` | off | Keep `clips/` folder |
| `--seed` | random | Reproducible shuffle |

## Reuse clips

Same subject query pulls from shared pool first (like luxury montage jobs).

Re-render existing job clips only:

```powershell
python scripts/build_text_clip.py `
  --slug ocean-waves `
  --query "ocean waves cinematic 4k short" `
  --text "New line here." `
  --local-only
```

## vs luxury-clips-montage

| | query-text-clip | luxury-clips-montage |
|---|---|---|
| Audio | none | motivational speech |
| Captions | one static line | word-by-word burn-in |
| Length | default 20s | 60–90s |
| Output dir | `downloads/text-clips/` | `downloads/motivational/` |

Legal: only footage user owns or has rights to repost.
