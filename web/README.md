# Ai-Video Dashboard

Next.js production dashboard for the Ai-Video content pipeline. The Python scripts in `../scripts/` remain the backend engine — this app is the visual control surface.

## Quick start

Run **two terminals** — API first, then dashboard:

**Terminal 1 — API:**

```powershell
.\scripts\start-api.ps1
```

**Terminal 2 — dashboard:**

```powershell
.\scripts\start-dashboard.ps1
```

If port 3000 was stuck or you saw "Another next dev server is already running", either script auto-fixes it.
Full refresh (API + dashboard in new windows):

```powershell
npm run restart:dev
```

Manual equivalent:

```powershell
pip install -r requirements-api.txt
python -m uvicorn api.main:app --reload --port 8000

cd web
copy .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Discover and dashboard stats read from `data/discovery/catalog.sqlite` via the API.

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

## Add a Cursor render to the site

After any legacy script finishes (iMessage story, stills slideshow, voiceover, etc.):

1. Open [http://localhost:3000/videos](http://localhost:3000/videos)
2. Click **Add ready to site** (or **Add to site** on one video)

Or from the repo root:

```powershell
python scripts/register_site_video.py
```

Story/voiceover/stills pipelines auto-register when the discovery DB exists.

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server (port 3000) |
| `npm run build` | Production build |
| `npm run start` | Serve production build |
| `npm run lint` | Run ESLint |

## Stack

- Next.js (App Router)
- TypeScript
- Tailwind CSS
- Lucide React icons

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Dashboard overview |
| `/command` | **Natural-language commands** → Cursor Agent CLI |
| `/library` | Production library (videos + reusable components) |
| `/library/[id]` | Video detail + edit commands |
| `/create` | **Make Short** — quick motivation montage path |
| `/workbench` | Discovery find + Cursor generation handoff |
| `/videos` | Rendered Shorts dashboard (site + legacy) |
| `/discover` | Viral references (secondary) |
| `/review` | Approval queues |
| `/accounts` | Publishing accounts |
| `/analytics` | Performance metrics |
| `/settings` | Integrations and config |

## Cursor command flow

1. Install Cursor Agent CLI: `irm 'https://cursor.com/install?win32=true' | iex`
2. Set `CURSOR_API_KEY` in `scripts/.env` (or user env)
3. Open [http://localhost:3000/command](http://localhost:3000/command)
4. Type a plain-English request — backend runs `agent -p --force --trust` in this repo
5. When Cursor finishes, it must register the video:
   `python scripts/register_production_video.py --title "..." --final-path downloads/...`

Optional dry-run (no CLI): set `CURSOR_BRIDGE_DRY_RUN=1` before starting the API.

Optional internal auth: set matching `AI_VIDEO_INTERNAL_KEY` (API) and `NEXT_PUBLIC_AI_VIDEO_INTERNAL_KEY` (web).

## Architecture (planned)

```
Next.js dashboard → API layer → Python discovery/render workers → shared database
```

This phase is UI-only with placeholder data. Backend wiring, auth, and Supabase come later.
