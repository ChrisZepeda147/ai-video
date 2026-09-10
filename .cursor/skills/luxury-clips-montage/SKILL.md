---
name: luxury-clips-montage
description: Builds 9:16 motivational montages from shuffled YouTube B-roll clips with dark-luxury charcoal grade, speech audio, and burned-in word captions. Reuse of prior sources is allowed by default — check production library for context. Use when the user wants a luxury car/video montage, dark filter over YouTube clips, motivational speech over B-roll, or to recreate the car-luxury / Tate-style video workflow.
---

# Luxury clips montage

One script. Do not search, download, pick durations, clean, read `content/used.json`, read scripts, extract frames, or dump job logs.

```powershell
python scripts/build_motivation_job.py `
  --slug yacht-motivation `
  --broll-query "luxury yacht cinematic 4k short" `
  --reuse-policy allow
```

Script searches speech + B-roll, renders 9:16 + grade + word captions, rebuilds catalog, deletes leftovers.

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

## Agent rules

1. Run the script. Do not copy audio from another job unless the user asked to reuse it.
2. New `--slug` + new `--broll-query` every job (or intentional version of an existing video).
3. After it finishes, open the output mp4. Read `job.json` only if you need IDs. Do not re-run by hand.

## Flags

| Flag | Default | When to set |
|---|---|---|
| `--slug` | required | Job folder name |
| `--broll-query` | required | Cars, yachts, watches, etc. |
| `--speech-url` | search | User already picked a speech |
| `--speaker` | `config.json` | One-run override |
| `--reuse-policy` | `allow` | `require_new` only when user asked for unused-only |
| `--segment-length` | `8` | Slower=`10`/`12`, faster=`4` |
| `--min-seconds` / `--max-seconds` | `60` / `90` | Excerpt window |
| `--no-grade` | off | User wants raw color |
| `--keep-work` | off | Keep `clips/` |
| `--cleanup-only` | off | Clean job folders |
| `--rerender` | off | Remake existing slug (same speech + B-roll) |

Output: `downloads/motivational/{slug}/output/{slug}-motivation.mp4`

Charcoal / slate, light plum, 1080×1920. Do not brighten unless asked. Legal: only footage user owns or has rights to repost.
