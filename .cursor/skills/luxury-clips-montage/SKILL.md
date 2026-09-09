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

## Agent rules

1. Run the script. Do not copy audio from another job.
2. New `--slug` + new `--broll-query` every job.
3. After it finishes, open the output mp4. Read `job.json` only if you need IDs. Do not re-run by hand.

## Flags

| Flag | Default | When to set |
|---|---|---|
| `--slug` | required | Job folder name |
| `--broll-query` | required | Cars, yachts, watches, etc. |
| `--speech-url` | search | User already picked a speech |
| `--speaker` | `config.json` | One-run override |
| `--segment-length` | `8` | Slower=`10`/`12`, faster=`4` |
| `--min-seconds` / `--max-seconds` | `60` / `90` | Excerpt window |
| `--no-grade` | off | User wants raw color |
| `--keep-work` | off | Keep `clips/` |
| `--cleanup-only` | off | Clean job folders |
| `--rerender` | off | Remake existing slug (same speech + B-roll) |

Output: `downloads/motivational/{slug}/output/{slug}-motivation.mp4`

Charcoal / slate, light plum, 1080×1920. Do not brighten unless asked. Legal: only footage user owns or has rights to repost.
