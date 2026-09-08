---
name: kinocut
description: Use Kinocut for guarded video editing, source-backed planning, FFmpeg operations, media analysis, subtitles, audio workflows, Hyperframes rendering, repurposing packages, and release checkpoints through an MCP server, Python client, or CLI. Trigger when an agent needs to inspect, plan, edit, render, validate, or package local media safely.
---

# Kinocut

Use Kinocut when an agent needs a structured video-editing surface instead of hand-writing FFmpeg commands. It exposes MCP tools, a Python client, and a CLI for editing, analysis, subtitles, audio, Hyperframes, layered compositing, and local repurposing workflows.

## Default path (do this first)

1. `kino doctor` then `kino --format json info <file>`.
2. Plan with `video_intent` (optional `goal=` compiles a cutfile; a 360/desk/table/`x4` goal also proposes a `360_assembly_plan`) — do not list 196 tools.
3. Render (`video_cutfile_render`, `video_edit`, workflow, or a single engine tool). For 360: `video_review_decide` approve/reject on that plan, then render — never render a `proposed` plan. `.insv` is rejected; need a stitched 360 MP4. Guide: `docs/360_ASSEMBLY.md`.
4. `video-quality-check` / `assert_quality`. Sync `repurpose` and `shorts-package` fail-closed at score 80 unless skipped/`allow_fail`.
5. Human visual/audio review. Never treat a receipt as published.

Depth (rescue, salvage, composite, Hyperframes, thin sound S12): `docs/TOOLS.md`, `docs/RESCUE.md`, `docs/WORKFLOWS.md`. Workflow allowlist: probe, trim, resize, convert, crop, add_text, merge, composite_layers, burn_in.

## Start Here

- Read `tools/kinocut/README.md` for install and the safety contract.
- Run `kino doctor` from `tools/kinocut` before FFmpeg / Hyperframes / AI extras.

## Choose A Surface

- MCP: use the local `kinocut` server already configured in this workspace (`tools\kinocut\.venv\Scripts\kino.exe --mcp`).
- CLI: `.\tools\kinocut\.venv\Scripts\kino.exe` for direct local edits, diagnostics, and JSON output.
- Python client: activate `tools\kinocut\.venv` then `from kinocut import Client`.

## Workflow

1. Inspect the input first: `kino info <file>` or the MCP/Python equivalent.
2. Make a low-risk plan: trim, resize, normalize audio, subtitles, overlays, effects.
3. Prefer previews or dry-run manifests before expensive exports.
4. Produce release artifacts before publishing: `video-quality-check`, `storyboard`/`thumbnail`, `video_release_checkpoint`.
5. Ask for human visual/audio review before treating generated media as final.

## Guardrails

- Do not publish or hand off media without a quality check and human review.
- Prefer structured Kinocut tools over raw FFmpeg shell commands.
- Keep output paths explicit so generated media is easy to inspect.
