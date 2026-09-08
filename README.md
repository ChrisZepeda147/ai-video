# Ai-Video

Short-form video pipeline: iMessage story renders, dark-luxury stills, voiceover, YouTube sourcing, and TikTok upload scripts.

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
