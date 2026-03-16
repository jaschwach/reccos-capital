# Reccos Capital — SaaS Trading Platform

## Overview

Full-stack SaaS trading platform built with Python/Flask. The project lives in a pnpm monorepo, but the actual application is a Flask app with Jinja2 templates, JWT auth, and SQLite storage.

---

## Application Architecture

### Development

| Workflow | Command | Port | Role |
|---|---|---|---|
| `artifacts/reccos-capital: web` | `python startup.py` | 24339 | Flask app — serves all pages **and** `/rpc/*` API routes |
| `artifacts/api-server: API Server` | `tsx src/index.ts` | 8080 (proxy) → 8180 (Flask) | Production-only proxy; runs a second Flask instance in dev (not used for browser traffic) |

In dev, **all browser traffic goes to the reccos-capital workflow** (Flask on 24339). The api-server workflow is present but unused for browser requests.

### Production

| Artifact | Role |
|---|---|
| `artifacts/api-server` (runnable, port 8080) | Node.js proxy: spawns Flask on port 8180, listens on 8080, rewrites `/api/` → `/rpc/` before forwarding |
| `artifacts/reccos-capital` (static, `dist/public/`) | Pre-rendered HTML files for all pages; static files use `/api/` prefix for JS fetch calls |

**Request routing in production:**
- `/api/*` → api-server (port 8080) → Flask (port 8180, rewritten to `/rpc/*`)
- `/` and all page routes → static handler serving `dist/public/`

---

## Key Files

| File | Purpose |
|---|---|
| `main_app.py` | Flask application — all routes, auth, DB access |
| `startup.py` | Reads `PORT` env var, starts gunicorn |
| `build_static.py` | Generates `dist/public/` static HTML (run by `pnpm build` in reccos-capital) |
| `reccos.db` | SQLite database (WAL mode) |
| `templates/` | Jinja2 templates |
| `artifacts/api-server/src/index.ts` | Node.js proxy that spawns Flask and proxies `/api/` to Flask's `/rpc/` |
| `artifacts/api-server/dist/index.cjs` | Built production bundle (esbuild CJS) |
| `artifacts/reccos-capital/dist/public/` | Generated static HTML for production |

---

## API Endpoints (Flask, `/rpc/` prefix)

All endpoints use cookie-based JWT auth (`rc_token` cookie).

```
POST /rpc/auth/login          — email + password + optional TOTP code
POST /rpc/auth/logout
GET  /rpc/auth/me             — returns current user info
POST /rpc/auth/2fa/enroll     — returns QR code + secret
POST /rpc/auth/2fa/verify     — activates 2FA, returns backup codes
POST /rpc/auth/2fa/disable
POST /rpc/auth/password-reset — request/reset
POST /rpc/auth/change-password
POST /rpc/waitlist            — public; adds email to waitlist

GET  /rpc/admin/users         — list all users (admin only)
POST /rpc/admin/users         — create user (admin only)
POST /rpc/admin/users/<id>/toggle — enable/disable user (admin only)
GET  /rpc/admin/stats         — platform stats (admin only)
GET  /rpc/admin/waitlist      — waitlist entries (admin only)

GET  /rpc/portfolio/trades    — user's trade history
GET  /rpc/portfolio/pnl       — portfolio P&L timeseries
POST /rpc/broker/connect      — save broker API key
POST /rpc/broker/disconnect   — remove broker connection
GET  /rpc/market/intel        — market intelligence feed
GET  /rpc/strategies          — strategy marketplace
```

**Note:** Static production pages use `/api/` prefix → api-server proxy rewrites to `/rpc/` before forwarding to Flask. Dev templates use `/rpc/` directly.

---

## API Base Detection (templates)

All templates include:
```html
<meta name="api-base" content="/rpc">
```
JS reads this: `const API_BASE = document.querySelector('meta[name="api-base"]').content;`

- **Dev templates** (Jinja2, served by Flask): `content="/rpc"` — direct Flask access
- **Production static files** (dist/public): `content="/api"` — rewritten by build_static.py

---

## Auth

- JWT stored in `rc_token` HttpOnly cookie (8h expiry)
- `PyJWT v2` — `sub` claim is always a string
- TOTP 2FA via `pyotp` + `qrcode`
- Bcrypt password hashing

---

## Database (SQLite)

Tables: `users`, `waitlist`, `trade_history`, `strategies`, `market_intel`, `broker_connections`

Initialized via `init_db()` on startup. Seeded with admin user on first boot.

---

## Default Admin Credentials

- **Email**: `jory@andium.com`
- **Password**: `ReccosCap2026!`
- **Role**: `admin`

---

## Building for Production

```bash
# 1. Generate static HTML pages (api-base switches to /api/)
python build_static.py

# 2. Build the Node.js proxy bundle
pnpm --filter @workspace/api-server run build
# Output: artifacts/api-server/dist/index.cjs

# Or run both via pnpm workspace build:
pnpm run build
```

---

## Dependencies (Python)

Flask, bcrypt, PyJWT, pyotp, qrcode[pil], Pillow, gunicorn

---

## Monorepo Structure

```text
/
├── main_app.py              # Flask app
├── startup.py               # gunicorn launcher
├── build_static.py          # static HTML generator
├── reccos.db                # SQLite database
├── templates/               # Jinja2 templates
│   ├── landing.html
│   ├── login.html
│   ├── subscriber/          # base.html + portfolio/strategies/market/broker/settings
│   └── admin/               # index.html
├── artifacts/
│   ├── api-server/          # Node.js proxy (production entry point)
│   │   ├── src/index.ts     # proxy source
│   │   └── dist/index.cjs   # production bundle
│   ├── reccos-capital/      # Flask web artifact
│   │   └── dist/public/     # generated static HTML (for production)
│   └── mockup-sandbox/      # Component preview server (Vite)
├── lib/                     # Shared TS libraries (api-spec, api-client-react, api-zod, db)
└── pnpm-workspace.yaml
```
