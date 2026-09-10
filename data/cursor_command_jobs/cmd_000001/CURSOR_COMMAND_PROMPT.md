# Ai-Video production command

You are operating inside the ai-video private production repo.
Use existing Python scripts and project rules. Do NOT reimplement video logic in the backend.
The dashboard / production library is **memory for Cursor** — organization, component lookup, and history.
Reuse detection is **informational by default**. Do NOT reject a source, timestamp, audio segment,
visual, or component merely because it was used before. Tell the user where it was used; reuse when
the new composition meaningfully differs (new visuals, new excerpt, new hook, version line, etc.).
Discovery references are separate — never put discovery reference IDs into content/used.json.

## Mandatory workflow
1. Query production library for prior usage context (advisory — never an eligibility filter).
2. Use existing production tooling (build_motivation_job.py, story pipelines, stills, etc.).
3. Create a NEW version when modifying an existing video — do not overwrite originals.
4. Register every completed production video:
   `python scripts/register_production_video.py --title "..." --final-path downloads/...`
5. Preserve modular components (audio, transcript, scenes, visuals, captions, final).

## Reuse policy for this command: allow
- allow (default): previously used sources/speakers/topics/segments/components are OK.
- prefer_new: rank fresher material first, but fall back if needed.
- require_new: ONLY when the user explicitly asked for unused / never-used / do-not-reuse material.

Run toolchain check before downloads:
`python -c "from toolchain_env import check_toolchain; import json; print(json.dumps(check_toolchain(), indent=2))"`

## Production library snapshot
Production library is empty.

## User command
Make a test video about focus.

## Helpful commands
- Motivation job (reuse allowed): `python scripts/build_motivation_job.py --slug ... --broll-query ... --reuse-policy allow`
- Reuse advisory check: `python scripts/production_library_cli.py check-reuse --transcript "..."`
- Register video: `python scripts/register_production_video.py --help`
- List library: `python scripts/production_library_cli.py list`

Project root: C:/Users/chris/Youtube AI/ai-video