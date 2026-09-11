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

## Reuse policy for this command: require_new
- allow (default): previously used sources/speakers/topics/segments/components are OK.
- prefer_new: rank fresher material first, but fall back if needed.
- require_new: ONLY when the user explicitly asked for unused / never-used / do-not-reuse material.

Run toolchain check before downloads:
`python -c "from toolchain_env import check_toolchain; import json; print(json.dumps(check_toolchain(), indent=2))"`

## Production library snapshot
Production library memory (advisory — reuse allowed unless user asked for unused-only):
- Video 15 (video_000015): Jocko Willink, motivation, source DG-oAF1i_UA [completed]
- Video 14 (video_000014): Andrew Tate, motivation, source E6CkSdE6Y5E [completed]
- Video 13 (video_000013): Andrew Tate, motivation, source E6CkSdE6Y5E [completed]
- Video 12 (video_000012): Andrew Tate, motivation, source E6CkSdE6Y5E [completed]
- Video 11 (video_000011): Andrew Tate, motivation, source E6CkSdE6Y5E [completed]
- Video 4 (video_000004): Andrew Tate, motivation, source 4degEyoCkXU [completed]
- Video 3 (video_000003): Andrew Tate, motivation, source 4degEyoCkXU [completed]
- Video 2 (video_000002): Andrew Tate, motivation, source DJuQu8X2s_I [completed]
- Video 1 (video_000001): Andrew Tate, motivation, source DJuQu8X2s_I [completed]

## User command
Make a new 9:16 motivational Short using the luxury-clips-montage workflow.
Run `python scripts/build_motivation_job.py` with appropriate flags — do not reimplement FFmpeg or download logic.
Owner account: chris — record combination usage for this owner when done.

Before picking audio or visuals:
- Query production library: `python scripts/production_library_cli.py list`
- Check combinations catalog / existing transcripts — do not reuse the same excerpt unless instructions allow.
- Set speaker from actual clip title/channel (not search query). If search was Goggins but clip is Jocko, register as Jocko Willink.
- Use `--reuse-policy require_new` when instructions say do not reuse.

Search for audio (any type — speech, podcast clip, interview, etc.): david goggins motivational speech
Visual / B-roll search: beautiful rooftop views and sunsets
Default target length: 60–90 seconds unless extra instructions override.

Extra instructions:
create two videos around the same clips you are pulling, making the task more time consies. with each other being different. 30 seconds each. less or little more is okay, first clip should be of a beautiful view of a sunset from a balcony or beach.

Before downloading audio, query the production library and check existing transcripts — avoid reusing the same excerpt unless instructions say otherwise.
Register the finished video in the production library when done.

## Helpful commands
- Motivation job (reuse allowed): `python scripts/build_motivation_job.py --slug ... --broll-query ... --reuse-policy allow`
- Reuse advisory check: `python scripts/production_library_cli.py check-reuse --transcript "..."`
- Register video: `python scripts/register_production_video.py --help`
- List library: `python scripts/production_library_cli.py list`

Project root: C:/Users/chris/Youtube AI/ai-video