---
name: brother-sync
description: Keeps Stephen and Chris on the same GitHub copies and shared video library. Use when finishing a video, pushing, pulling, syncing with brother, shared_library, push-stephen, pull-import, or dual remotes.
---

# Brother sync

Stephen and Chris each have a private repo. Videos move Stephen → Chris through `shared_library/stephen/<slug>/` (Git LFS). Code moves both ways with a push to **both** remotes.

## Remotes

| Remote | URL |
|--------|-----|
| `origin` / `stephen` | `https://github.com/StephenZepeda/ai-video.git` |
| `chris` | `https://github.com/ChrisZepeda147/ai-video.git` |

`git pull` / default `git push` stay on `origin`. After a shared commit, also `git push chris`.

## Which machine

**Stephen** — `scripts/.env` has:

```
SHARED_LIBRARY_EXPORT_OWNER=stephen
```

**Chris** — that line is absent. Never set it on Chris. Chris only imports.

If remotes are missing:

```powershell
git remote add stephen https://github.com/StephenZepeda/ai-video.git
git remote add chris https://github.com/ChrisZepeda147/ai-video.git
```

One-time per machine: `git lfs install`.

## After a finished video (Stephen)

Render as normal. Env flag auto-exports into `shared_library/stephen/<slug>/`. Then:

```powershell
python scripts/shared_library_sync.py push-stephen
git push chris
```

`push-stephen` runs export first, then commits **only** `shared_library/stephen/` + `.gitattributes` and pushes `origin`.

If it returns `unrelated_changes`: stash other dirty files, rerun, pop stash.

First-time / all old jobs:

```powershell
python scripts/shared_library_sync.py export-stephen-existing --dry-run
python scripts/shared_library_sync.py export-stephen-existing
python scripts/shared_library_sync.py push-stephen
git push chris
```

Want `"exported": N` with `N > 0` (or skipped because already packaged).

## After Stephen pushes (Chris)

```powershell
git pull
python scripts/shared_library_sync.py pull-import
```

Or **Sync Stephen library** on `/library`.

## After any shared code commit (both)

```powershell
git push origin
git push chris
```

Do not leave one GitHub copy stale.

## Check

```powershell
python scripts/shared_library_sync.py status
```

Stephen: `packages_on_disk` > 0, `export_enabled` true after `.env` load.  
Chris after import: same package slugs on disk, imports recorded.

```powershell
dir shared_library\stephen
```

Only `.gitkeep` on Chris before first import means Stephen has not pushed yet.

## Do not

- Commit `scripts/.env`, `downloads/`, or `data/shared_library/*` (gitignored).
- Mix unrelated WIP into a `push-stephen` commit.
- Re-download or remake a job just to sync — export the existing `output/*.mp4`.
- Push library media as normal git blobs — LFS must track `shared_library/**/*.mp4` and `*.mp3` (see `.gitattributes`).
