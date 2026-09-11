# Social OAuth setup (Chris + Stephen)

Use when wiring YouTube, TikTok, Instagram, and Facebook analytics for two owners with up to **2 accounts per platform each**.

## Architecture

| Layer | Where | Shared? |
|-------|--------|---------|
| Developer app keys | `scripts/.env` | Same Google/Meta/TikTok apps on both PCs (gitignored) |
| Machine owner | `PUBLISHING_OWNER=stephen\|chris` | Per machine |
| OAuth tokens | `data/publishing/credentials/` | Per machine, per connected social account |
| Dashboard view | `/accounts`, `/analytics` owner tabs | Either owner |

## Redirect URI (all platforms)

```
http://localhost:3000/accounts/callback
```

Register in Google Cloud, TikTok Login Kit, and Meta Facebook Login. Copy from **Settings → Publishing setup**.

## Per machine

**Stephen**
```env
PUBLISHING_OWNER=stephen
SHARED_LIBRARY_EXPORT_OWNER=stephen
```

**Chris**
```env
PUBLISHING_OWNER=chris
```

Add the same developer keys (`YOUTUBE_CLIENT_*`, `TIKTOK_CLIENT_*`, `META_APP_*`) to each `scripts/.env`.

Unset `DISCOVERY_PUBLISH_PROVIDER=mock` and `DISCOVERY_PUBLISH_DRY_RUN`.

Set matching `AI_VIDEO_INTERNAL_KEY` + `web/.env.local` → `NEXT_PUBLIC_AI_VIDEO_INTERNAL_KEY`.

## Connect flow (×2 per platform per owner)

1. Open `/settings` — confirm credentials show **configured**
2. `/accounts` → Stephen or Chris tab
3. Enter label (e.g. `stephen main`, `stephen backup`)
4. Click platform → approve on real site → auto-return to callback
5. Repeat for second account on same platform
6. Other brother repeats on their PC for their channels

## Portal checklist

### YouTube
1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Enable YouTube Data API v3
3. OAuth consent → add test users
4. OAuth client → redirect `http://localhost:3000/accounts/callback`
5. `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` → `scripts/.env`

### TikTok
1. [developers.tiktok.com](https://developers.tiktok.com/)
2. App → Login Kit → redirect `http://localhost:3000/accounts/callback`
3. `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` → `scripts/.env`

### Instagram + Facebook (one Meta app)
1. [developers.facebook.com](https://developers.facebook.com/)
2. Facebook Login + Instagram Graph API products
3. Redirect `http://localhost:3000/accounts/callback`
4. Permissions: `pages_show_list`, `pages_read_engagement`, `read_insights`, `instagram_basic`, `instagram_manage_insights`
5. `META_APP_ID`, `META_APP_SECRET` → `scripts/.env`
6. IG must be Business/Creator linked to a Facebook Page

## Verify

```powershell
# API running, then:
curl http://127.0.0.1:8000/api/config/publishing-setup
```

Dashboard: **Settings** matrix should show `2/2` per cell when done. **Analytics** → owner tab → Refresh.

Per-video stats: **Videos → Link post** after manual upload.

## Troubleshooting

| Error | Fix |
|-------|-----|
| Missing YOUTUBE_CLIENT_ID | Add keys to `scripts/.env`, restart API |
| redirect_uri_mismatch | Must match Settings copy exactly in developer portal |
| DISCOVERY_PUBLISH_PROVIDER=mock | Remove from `.env` |
| Link post fails | Set `AI_VIDEO_INTERNAL_KEY` pair |
| Meta no Pages | Link IG to Page in Business Suite; add self as app tester in Dev mode |
