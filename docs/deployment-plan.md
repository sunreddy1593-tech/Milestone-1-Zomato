# Deployment Plan — Railway (backend) + Vercel (frontend)

This document describes how to deploy the **AI-Powered Restaurant Recommendation
System** as two independently hosted pieces:

| Component | Host | What runs there |
|-----------|------|-----------------|
| Backend (FastAPI) | **Railway** | `/recommend`, `/recommend/chat`, `/meta`, `/health`, `/restaurants/{id}` + the dataset and Groq LLM calls |
| Frontend (static SPA) | **Vercel** | `frontend/index.html`, `app.js`, `styles.css` |

The frontend is a static single-page app that calls the backend over HTTPS.
Because the two live on different origins, the frontend must be told the
backend's public URL, and the backend must allow cross-origin requests (it
already does — see [CORS](#cors)).

```
 Browser ──HTTPS──▶  Vercel (static frontend)
    │
    └──────HTTPS (fetch)──────▶  Railway (FastAPI backend) ──▶ Groq API
```

---

## 0. Prerequisites

- The repo is pushed to GitHub: `sunreddy1593-tech/Milestone-1-Zomato`.
- A **Groq API key** (`GROQ_API_KEY`). The backend degrades gracefully to
  deterministic ranking without it, but LLM ranking/intent need it.
- Accounts on [railway.app](https://railway.app) and [vercel.com](https://vercel.com),
  both connected to the GitHub account that owns the repo.
- `data/restaurants.json` is committed (it is) so the backend image is
  self-contained — no data download at boot.

---

## 1. Required code changes before deploying

Two small changes are needed for a split deployment. Apply them, commit, and
push before configuring the hosts.

### 1.1 Backend — bind to Railway's `$PORT`

Railway injects the port to listen on via the `PORT` environment variable. The
current `Dockerfile` hardcodes `8000` using exec-form `CMD`, which does **not**
expand environment variables. Change it to shell form so `$PORT` is honored
(falling back to `8000` for local runs):

```dockerfile
# Dockerfile — replace the final CMD line
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --app-dir src"]
```

> Keep `EXPOSE 8000` as-is — it's only documentation; Railway routes to `$PORT`.

### 1.2 Frontend — point at the Railway backend URL

Today `frontend/app.js` resolves the API base like this:

```12:12:frontend/app.js
const API_BASE = location.protocol === "file:" ? "http://localhost:8000" : "";
```

On Vercel `location.protocol` is `https:`, so `API_BASE` becomes `""` (relative),
which would (incorrectly) target the Vercel domain that has no API. Make the base
URL configurable via a tiny config file that is easy to change per-deploy without
touching app logic.

**a. Create `frontend/config.js`:**

```js
// Set this to your Railway backend's public URL (no trailing slash).
// Leave empty ("") for local same-origin testing via the backend's /ui mount.
window.__API_BASE__ = "https://YOUR-RAILWAY-APP.up.railway.app";
```

**b. Load it before `app.js` in `frontend/index.html`** (add just above the
existing `app.js` script tag):

```html
<script src="config.js"></script>
<script src="app.js"></script>
```

**c. Update the first line of `frontend/app.js`** to prefer the configured base:

```js
const API_BASE =
  (typeof window !== "undefined" && window.__API_BASE__) ||
  (location.protocol === "file:" ? "http://localhost:8000" : "");
```

This keeps three workflows working:
- **Local file open** → falls back to `http://localhost:8000`.
- **Served by the backend at `/ui`** (single origin) → set `__API_BASE__ = ""`.
- **Vercel + Railway** → set `__API_BASE__` to the Railway URL.

> You'll fill in the real Railway URL in [section 3.4](#34-wire-the-frontend-to-the-backend),
> after the backend has a domain.

---

## 2. Deploy the backend on Railway

### 2.1 Create the project
1. Railway dashboard → **New Project** → **Deploy from GitHub repo**.
2. Select `sunreddy1593-tech/Milestone-1-Zomato`.
3. Railway detects the `Dockerfile` and uses it automatically (no Nixpacks build
   needed). The image copies `src/` and `data/`, so the dataset ships inside it.

### 2.2 Set environment variables
In the service's **Variables** tab, add:

| Variable | Value | Notes |
|----------|-------|-------|
| `GROQ_API_KEY` | `gsk_...` | **Required** for LLM ranking/intent |
| `DEFAULT_CITY` | `Bengaluru` | optional override |
| `GROQ_MODEL_INTENT` | `llama-3.1-8b-instant` | optional |
| `GROQ_MODEL_RANK` | `llama-3.3-70b-versatile` | optional |
| `LLM_RANK_CANDIDATES` | `20` | optional, controls tokens sent to LLM |
| `CACHE_ENABLED` | `true` | optional |
| `SEMANTIC_ENABLED` | `true` | optional |

> Do **not** set `PORT` yourself — Railway provides it. The app reads every
> setting in `src/app/config.py` from the environment (case-insensitive), so
> any of those fields can be overridden here. `.env` is git-ignored and is **not**
> used in production.

### 2.3 Health check & domain
1. **Settings → Networking → Generate Domain** to get a public URL like
   `https://milestone-1-zomato-production.up.railway.app`.
2. **Settings → Deploy → Health Check Path**: set to `/health`.
   - A healthy response returns `{"status":"ok","dataset_loaded":true,...}`.
3. Trigger a deploy (push to `main` or **Deploy** in the UI).

### 2.4 Verify the backend
```bash
# Liveness + dataset + Groq status
curl https://YOUR-RAILWAY-APP.up.railway.app/health

# A real recommendation
curl -X POST https://YOUR-RAILWAY-APP.up.railway.app/recommend \
  -H "Content-Type: application/json" \
  -d '{"filters":{"city":"bengaluru","locality":"indiranagar"},"top_n":5}'

# Filter options used by the UI dropdowns
curl https://YOUR-RAILWAY-APP.up.railway.app/meta
```
Expect `status: ok`, `dataset_loaded: true`, and `groq_configured: true`.

---

## 3. Deploy the frontend on Vercel

The frontend has **no build step** — it's plain HTML/CSS/JS. Vercel serves the
`frontend/` directory as static files.

### 3.1 Import the project
1. Vercel dashboard → **Add New… → Project** → import
   `sunreddy1593-tech/Milestone-1-Zomato`.
2. **Framework Preset:** `Other`.
3. **Root Directory:** `frontend`  ← important; this is where `index.html` lives.
4. **Build Command:** leave empty. **Output Directory:** leave empty (`.`).
5. **Install Command:** leave empty.

### 3.2 `frontend/vercel.json` (committed)
Vercel may otherwise auto-detect a framework and fail the build with
`No Next.js version detected...` because this app is plain static
HTML/CSS/JS with no `package.json`. The committed `frontend/vercel.json`
disables framework detection and the build step, serving the directory as
static files:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": null,
  "buildCommand": null,
  "installCommand": null,
  "outputDirectory": ".",
  "cleanUrls": true,
  "trailingSlash": false
}
```

> Also ensure the project's **Framework Preset** is `Other` and **Root
> Directory** is `frontend` in the Vercel dashboard. `vercel.json` is read from
> the Root Directory, so it must sit next to `index.html`.

### 3.3 Deploy
Click **Deploy**. Vercel gives a URL like `https://milestone-1-zomato.vercel.app`.

### 3.4 Wire the frontend to the backend
Set the Railway URL in `frontend/config.js` (from [section 1.2](#12-frontend--point-at-the-railway-backend-url)):

```js
window.__API_BASE__ = "https://YOUR-RAILWAY-APP.up.railway.app";
```

Commit and push — Vercel auto-redeploys on every push to `main`.

> Since the frontend is static (no build env injection), the backend URL lives
> in `config.js`. If you prefer not to commit the URL, you can instead hardcode
> it in `app.js`, but `config.js` keeps it in one obvious place.

---

## 4. CORS

The backend already allows any origin, so Vercel → Railway calls work out of the
box:

```69:75:src/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Optional hardening:** once the Vercel domain is known, restrict origins by
replacing `["*"]` with your domains and reading them from an env var, e.g.:

```python
# src/app/main.py
import os
_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
```
Then set `ALLOWED_ORIGINS=https://milestone-1-zomato.vercel.app` on Railway.

---

## 5. Optional: faster, smaller Railway builds

`pandas` and `datasets` are only used by the **offline** ingest script
(`src/app/data/ingest.py`). The committed `data/restaurants.json` means the
runtime never imports them, yet they make the image large and slow to build.

To slim the production image, split dependencies:

- **`requirements.txt`** (runtime only): `fastapi`, `uvicorn[standard]`,
  `pydantic`, `pydantic-settings`, `groq`, `python-dotenv`.
- **`requirements-ingest.txt`** (local data prep + tests): the above plus
  `pandas`, `datasets`, `httpx`, `pytest`, `pytest-asyncio`.

The `Dockerfile` keeps installing `requirements.txt`, so Railway builds only the
runtime set. Run ingest/tests locally with `pip install -r requirements-ingest.txt`.

> This is an optimization, not a requirement — the current single
> `requirements.txt` deploys fine.

---

## 6. End-to-end verification checklist

- [ ] Railway `/health` returns `status: ok`, `dataset_loaded: true`, `groq_configured: true`.
- [ ] Railway `/recommend` returns ranked results for a locality query.
- [ ] Vercel site loads; dropdowns are populated (confirms `/meta` reachable).
- [ ] A search on the Vercel site returns cards (confirms `/recommend` reachable cross-origin).
- [ ] Browser devtools **Network** tab shows requests going to the **Railway** domain, not the Vercel domain.
- [ ] No CORS errors in the browser console.
- [ ] Locality-specific search stays in the chosen area (e.g., Indiranagar).

---

## 7. Continuous deployment

Both platforms redeploy automatically on every push to `main`:
- **Railway** rebuilds the Docker image and restarts the service.
- **Vercel** re-publishes the static `frontend/`.

Recommended flow: feature branch → PR → merge to `main` → both auto-deploy.
Vercel also creates a unique **Preview URL** for each PR.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Railway deploy crashes immediately | `CMD` not binding `$PORT` | Apply the shell-form `CMD` in [1.1](#11-backend--bind-to-railways-port) |
| `/health` shows `groq_configured: false` | `GROQ_API_KEY` not set on Railway | Add it in **Variables** and redeploy |
| Frontend loads but no results; console shows requests to the Vercel domain | `__API_BASE__` not set / wrong | Set the Railway URL in `frontend/config.js`, push |
| `CORS policy` error in console | Origins locked down without Vercel domain | Keep `["*"]` or add the Vercel origin to `ALLOWED_ORIGINS` |
| Vercel shows a directory listing / 404 | Wrong **Root Directory** | Set Root Directory to `frontend` |
| Vercel build fails: `No Next.js version detected` | Framework auto-detected; no `package.json` | Commit `frontend/vercel.json` (`"framework": null`) and set Framework Preset to `Other` |
| 503 `service_unavailable` from API | Dataset missing from image | Ensure `data/restaurants.json` is committed and `COPY data/` is in the Dockerfile |
| Slow Railway builds | Heavy `pandas`/`datasets` install | Split requirements per [section 5](#5-optional-faster-smaller-railway-builds) |

---

## 9. Quick reference

**Backend (Railway)**
- Build: `Dockerfile` (auto-detected)
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --app-dir src`
- Health: `GET /health`
- Required env: `GROQ_API_KEY`

**Frontend (Vercel)**
- Root directory: `frontend`
- Build: none (static)
- Config: `frontend/config.js` → `window.__API_BASE__ = "<railway-url>"`
