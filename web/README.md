# Ai-Video Dashboard

Next.js production dashboard for the Ai-Video content pipeline. The Python scripts in `../scripts/` remain the backend engine — this app is the visual control surface.

## Quick start

Run **two terminals** — FastAPI backend first, then the dashboard:

**Terminal 1 — discovery API (from repo root):**

```powershell
pip install -r requirements-api.txt
python -m uvicorn api.main:app --reload --port 8000
```

**Terminal 2 — dashboard:**

```powershell
cd web
copy .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Discover and dashboard stats read from `data/discovery/catalog.sqlite` via the API.

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

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
| `/` | Dashboard overview (demo data) |
| `/discover` | Viral references and benchmark channels |
| `/create` | Creative DNA, concepts, visual briefs |
| `/videos` | Generated visuals and rendered videos |
| `/review` | Approval queues |
| `/accounts` | Publishing accounts |
| `/analytics` | Performance metrics |
| `/settings` | Integrations and config |

## Architecture (planned)

```
Next.js dashboard → API layer → Python discovery/render workers → shared database
```

This phase is UI-only with placeholder data. Backend wiring, auth, and Supabase come later.
