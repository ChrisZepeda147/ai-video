Make a new 9:16 motivational Short using the luxury-clips-montage workflow.
Run `python scripts/build_motivation_job.py` with appropriate flags — do not reimplement FFmpeg or download logic.
Owner account: chris — record combination usage for this owner when done.

Before picking audio or visuals:
- Query production library: `python scripts/production_library_cli.py list`
- Check combinations catalog / existing transcripts — skip the same excerpt unless Extra instructions allow a remake.
- Set speaker from actual clip title/channel (not search query). If search was Goggins but clip is Jocko, register as Jocko Willink.
- Reuse of prior sources is allowed by default. Unused-only only if Extra instructions say unused / never used.

Use job slug: `weekly-chris-2026-09-28-mon-3` for downloads under downloads/motivational/.

Search for audio (any type — speech, podcast clip, interview, etc.): C motivational speech
Visual / B-roll search: v3
Pipeline: download speech from YouTube, scrape captions for the clip, search B-roll for the visual line, grade + phrase captions, register in production library.
Default target length: 60–90 seconds unless extra instructions override.

Before downloading audio, query the production library and check existing transcripts — skip the same excerpt unless Extra instructions allow a remake.
Register the finished video in the production library when done.