# Viral discovery — reference catalog

## REFERENCE VIDEO != PRODUCTION ASSET

This system collects **metadata only** about high-performing short-form videos so we can later analyze trends and generate **original** concepts.

| Reference (this system) | Production asset (existing pipelines) |
|-------------------------|---------------------------------------|
| Title, stats, URL, thumbnail URL | Downloaded MP4 in `downloads/` |
| Stored in `data/discovery/catalog.sqlite` | Tracked in `content/used.json` |
| Never rendered or published | Used by gameplay / iMessage / Kinocut / TikTok upload |

**Hard rules**

- Do **not** download video files from discovery.
- Do **not** write references into `content/used.json`.
- Do **not** call `content_reuse.register_video()` from discovery code.
- Do **not** auto-wire references into `youtube_popular_downloader`, `story_voiceover_pipeline`, `imessage_story_pipeline`, Kinocut, or `tiktok_upload`.

Discovery may inspire new stories and visuals, but production always uses **original** assets.

## Layout

```
discovery/schema.sql          # committed schema
data/discovery/catalog.sqlite # runtime database (gitignored)
scripts/discovery/            # Python package
```

## CLI

Run from the `scripts/` directory:

```powershell
cd scripts
python -m discovery.cli ingest youtube --query "creepy story" --limit 25 --niche horror
python -m discovery.cli ingest youtube --query "horror text" --shorts-only --limit 10
python -m discovery.cli discover --all --max-searches 20
python -m discovery.cli top --niche horror --min-score 70 --limit 25
python -m discovery.cli list
python -m discovery.cli stats
```

Requires `YOUTUBE_API_KEY` in `scripts/.env` for efficient API discovery (recommended). Without a key, yt-dlp metadata fallback is used (still no downloads).

Niche definitions: `config/niches.json`

Optional env vars in `scripts/.env`:

- `DISCOVERY_SEARCH_COOLDOWN_HOURS=12`
- `DISCOVERY_REFRESH_HOURS_VIRAL=6`
- `DISCOVERY_REFRESH_HOURS_RECENT=24`
- `DISCOVERY_REFRESH_HOURS_STABLE=72`
- `DISCOVERY_REFRESH_HOURS_OLD=168`

## Database

Tables:

- **`reference_videos`** — one row per platform video (`UNIQUE(platform, external_id)`), `production_asset` always `0`
- **`reference_metrics`** — virality score and raw velocity/engagement components
- **`reference_niches`** — many-to-many niche assignments with relevance scores
- **`search_history`** — search cooldown and efficiency tracking
- **`discovery_runs`** — audit log of ingest operations

## Creative DNA and concepts

```powershell
python -m discovery.cli analyze --reference-id 123
python -m discovery.cli concepts --reference-id 123 --count 10
python -m discovery.cli concepts --niche horror --top-reference --count 10
python -m discovery.cli concepts-list --reference-id 123
```

Requires `OPENAI_API_KEY` in `scripts/.env`, or use `--prompt-export` to write prompt files.

Optional: `DISCOVERY_MAX_CONCEPTS_PER_REFERENCE=12`, `DISCOVERY_CONCEPT_SIMILARITY_THRESHOLD=0.55`

## Future phases (not built yet)

- AI video generation from approved concepts
- Automatic story.json generation from concepts
- Multi-platform sources (TikTok, Instagram)
- Shared discovery across niches/accounts
