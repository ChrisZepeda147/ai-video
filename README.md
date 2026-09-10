# Ai-Video

Short-form video pipeline: iMessage story renders, dark-luxury stills, voiceover, YouTube sourcing, and TikTok upload scripts.

## Dashboard (Next.js)

Visual production dashboard in `web/` — reads live discovery data via FastAPI. Python scripts remain the backend engine.

```powershell
# Terminal 1 — API (repo root)
pip install -r requirements-api.txt
python -m uvicorn api.main:app --reload --port 8000

# Terminal 2 — dashboard
cd web
copy .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). See [web/README.md](web/README.md) for details.

### Command Cursor from the site

Private `/command` page sends plain-English requests to **Cursor Agent CLI** (`agent -p`). Cursor runs in this repo using existing Python tools. Completed videos register via:

```powershell
python scripts/register_production_video.py --title "..." --final-path downloads/.../final.mp4
```

Production library: `/library` · Reuse checks: `python scripts/production_library_cli.py check-reuse ...`

## Setup

```powershell
cd scripts
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-imessage.txt
pip install -r requirements-youtube.txt
copy .env.example .env
# fill in API keys in .env
```

### Kinocut (video editing MCP)

Kinocut is not committed — clone it into `tools/`:

```powershell
git clone https://github.com/KyaniteLabs/kinocut.git tools/kinocut
cd tools/kinocut
python -m venv .venv
.\.venv\Scripts\pip install -e .
```

Cursor MCP config (`.cursor/mcp.json`) expects `tools/kinocut/.venv/Scripts/kino.exe`.

## Content reuse

Before creating new stories, photos, or background videos, check the catalog:

```powershell
python scripts/content_reuse.py list
```

After adding content, rebuild the catalog:

```powershell
python scripts/content_reuse.py rebuild
```
