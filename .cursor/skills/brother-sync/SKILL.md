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

## Start of every agent session (both machines)

Before other work:

```powershell
git fetch origin
git pull --ff-only origin main
```

**Chris only** — import Stephen packages (skip second pull if you just pulled):

```powershell
python scripts/shared_library_sync.py pull-import --skip-pull
```

If pull fails due to local edits, tell the user — do not force. Stash or commit first.

## While API is running (automatic)

With `.\scripts\start-api.ps1` (defaults on):

| What | Env | Interval |
|------|-----|----------|
| Videos + code + **deletions** | `SHARED_LIBRARY_AUTO_SYNC=1`, `BROTHER_AUTO_PULL=1` | **~10 min** (`BROTHER_SYNC_MINUTES=10`) |

Each tick: pull `shared_library/` (including `deletions.json`), apply brother deletions locally, import packages, then `git pull --ff-only` when tree clean.

**Deletes:** Removing a production library video records `shared_library/deletions.json`, removes the Git package folder, pushes both remotes. The other machine drops DB row + local package on next sync (~10 min).

Disable auto sync: `BROTHER_AUTO_PULL=0` or `SHARED_LIBRARY_AUTO_SYNC=0` in `scripts/.env`.

Check status:

```powershell
python scripts/shared_library_sync.py status
```

Shows `last_code_pull_at`, `commits_behind`, `brother_auto_pull_enabled`.

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
git pull --ff-only origin main
python scripts/shared_library_sync.py pull-import --skip-pull
```

Or **Sync Stephen library** on `/library` (packages only).

## After any shared code commit (both)

Post-commit hook (installed by `start-dev` / `install_brother_git_hooks.ps1`) runs:

```powershell
git push origin
git push chris
```

Manual push still OK. Stephen’s machine: **API startup brother sync** + **AiVideoGitHubSync** every 5 min — no manual `git pull` if dev stack or scheduled task is running.

## Check

One line — synced or not:

```powershell
python scripts/shared_library_sync.py health
```

Full dump:

```powershell
python scripts/shared_library_sync.py status
```

Or open `/library` — green **Synced** / amber **Not synced**.

Stephen: `packages_on_disk` > 0, `export_enabled` true after `.env` load.  
Chris after import: same package slugs on disk, imports recorded.

## Periodic (set and forget)

Both machines, once:

```powershell
powershell -File scripts/github_brother_sync.ps1 install
```

Windows task `AiVideoGitHubSync` every 5 min (silent `wscript` launcher, no CMD flash): fetch both remotes, auto-commit source, merge his commits (incoming wins on clash), push origin + chris. Both machines need `install`. Never force-push. Re-run `install` after pulling this change so the hidden launcher replaces the old powershell task.

```powershell
powershell -File scripts/github_brother_sync.ps1 uninstall
```

```powershell
dir shared_library\stephen
```

Only `.gitkeep` on Chris before first import means Stephen has not pushed yet.

## Do not

- Commit `scripts/.env`, `downloads/`, or `data/shared_library/*` (gitignored).
- Mix unrelated WIP into a `push-stephen` commit.
- Re-download or remake a job just to sync — export the existing `output/*.mp4`.
- Push library media as normal git blobs — LFS must track `shared_library/**/*.mp4` and `*.mp3` (see `.gitattributes`).
