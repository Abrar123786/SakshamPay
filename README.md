# SakshamPay

AI-assisted, pre-transaction fraud-risk assessment for simulated digital payments in India.
SakshamPay scores each payment with transparent rules and an anomaly model, explains what
looks unusual, and lets the user cancel, verify or continue before the simulated
authorisation.

> **Prototype.** All payments are simulated. SakshamPay is not connected to UPI, NPCI,
> any payment app or any bank, and its risk scores are not fraud probabilities.

| Layer | Technology |
| --- | --- |
| Frontend | React 19, Vite 8, Tailwind CSS 4, React Router, Axios, Lucide icons |
| Backend | Python 3.13, FastAPI, Pydantic, SQLAlchemy 2, Alembic, Uvicorn |
| Database | PostgreSQL (psycopg 3 driver) |
| ML | scikit-learn (Isolation Forest), pandas, NumPy |
| Auth | Argon2id password hashing, JWT (HS256) |
| Hosting | Vercel (frontend), Render (backend), managed PostgreSQL |

Architecture decisions: [`docs/architecture.md`](docs/architecture.md).

## Repository layout

```text
sakshampay/
├── frontend/               React app (Vite)
│   ├── public/             static files (favicon)
│   ├── src/
│   │   ├── assets/         images and fonts used by components
│   │   ├── components/     reusable UI (ErrorBoundary, Logo, ...)
│   │   ├── layouts/        page shells (AppLayout)
│   │   ├── pages/          one component per route
│   │   ├── hooks/          reusable stateful logic
│   │   ├── services/       API client and one module per API group
│   │   ├── context/        React context providers (auth, later)
│   │   ├── utils/          helpers (validated env access)
│   │   ├── styles/         Tailwind entry and design tokens
│   │   ├── App.jsx         route table
│   │   └── main.jsx        entry point
│   ├── .env.example
│   ├── vercel.json         SPA rewrites + security headers
│   ├── package.json
│   └── vite.config.js
├── backend/                FastAPI app
│   ├── app/
│   │   ├── core/           settings, logging, exceptions
│   │   ├── database/       Database (engine, sessions, connectivity check), declarative base
│   │   ├── models/         ORM models (later)
│   │   ├── schemas/        Pydantic schemas
│   │   ├── repositories/   data access (later)
│   │   ├── routes/         system router (/, /health, /health/ready) + /api/v1 router
│   │   ├── services/       business logic (later)
│   │   ├── fraud_detection/ risk engine (later)
│   │   ├── middleware/     request ID, access log, security headers
│   │   ├── utils/
│   │   └── main.py         application factory
│   ├── migrations/         Alembic
│   ├── tests/
│   ├── .env.example
│   ├── alembic.ini
│   ├── requirements.txt
│   └── requirements-dev.txt
├── docs/
├── .gitignore
├── README.md
└── LICENSE
```

## Prerequisites

| Tool | Version | Check |
| --- | --- | --- |
| Node.js | 20.19+ or 22.12+ (required by Vite 8) | `node --version` |
| npm | 10+ | `npm --version` |
| Python | 3.13 (3.11+ should work) | `python --version` |
| Git | any recent | `git --version` |
| PostgreSQL | 16 recommended | `psql --version` |

PostgreSQL is not needed to run the app yet (`/health` does not use it), but it is needed
from the next stage. To install it:

- **Windows:** install from the EnterpriseDB installer at postgresql.org/download/windows and
  add its `bin` folder to PATH.
- **macOS:** `brew install postgresql@16 && brew services start postgresql@16`
- **Ubuntu/Debian:** `sudo apt install postgresql && sudo service postgresql start`

Then create a development database:

```bash
psql -U postgres -c "CREATE ROLE sakshampay_dev LOGIN PASSWORD 'choose-a-local-password';"
psql -U postgres -c "CREATE DATABASE sakshampay_dev OWNER sakshampay_dev;"
```

(On Linux use `sudo -u postgres psql -c ...`.)

## Local setup

### Backend

```bash
cd backend
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows (PowerShell):
.venv\Scripts\Activate.ps1

pip install -r requirements-dev.txt
cp .env.example .env          # Windows: copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Without `DATABASE_URL` the server still starts (development only) and logs a warning.

| URL | Purpose |
| --- | --- |
| http://localhost:8000/ | Service info and entry points |
| http://localhost:8000/health | Liveness: the process is up (never touches the database) |
| http://localhost:8000/health/ready | Readiness: 503 when a configured database is unreachable |
| http://localhost:8000/docs | Swagger UI (not available in production) |
| `http://localhost:8000/api/v1/...` | Versioned business API (endpoints arrive from P-4) |

#### Windows PowerShell

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
# If activation is blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env          # Windows: copy .env.example .env
npm run dev
```

Open http://localhost:5173. The "API connection" panel should report
**Connected to SakshamPay API v1.0.0** while the backend is running.

Run both servers in two terminals at the same time.

## Environment variables

### `backend/.env`

`backend/.env.example` documents every variable. Development-only defaults apply when a
value is left unset: `DEBUG=true`, `LOG_LEVEL=DEBUG`, `LOG_FORMAT=console`.

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_NAME` | `SakshamPay` | Returned by `/` and `/health` |
| `APP_ENV` | `development` | `development`, `test` or `production` |
| `DEBUG` | true in development, else false | Rejected in production |
| `API_V1_PREFIX` | `/api/v1` | Prefix for all versioned endpoints |
| `DATABASE_URL` | empty | `postgresql://user:pass@host:5432/db`; normalised to psycopg 3; required in production |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `5` / `5` | Connection pool size |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | Wait for a free pooled connection |
| `DB_CONNECT_TIMEOUT_SECONDS` | `5` | Fail fast when the server is unreachable |
| `DB_STATEMENT_TIMEOUT_MS` | `3000` | PostgreSQL cancels longer queries |
| `DB_ECHO` | `false` | Logs SQL with parameters; rejected in production |
| `JWT_SECRET_KEY` | empty | Required in production, 32+ characters. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `JWT_ALGORITHM` | `HS256` | Only HS256 is accepted |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | 1–1440 |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS allowlist, comma-separated `scheme://host[:port]`; https only in production |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Larger declared bodies get 413 |
| `LOG_LEVEL` | DEBUG in development, else INFO | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | console in development, else json | `json` (structured) or `console` (readable) |

### `frontend/.env`

| Variable | Example | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Public: embedded in the JS bundle. Never put secrets in frontend env files. |

`.env` files are git-ignored. Only `.env.example` files are committed.

## Tests and checks

```bash
# backend (from backend/, venv active)
pytest

# optional PostgreSQL integration test against a disposable database
#   bash:       TEST_DATABASE_URL=postgresql://... pytest
#   PowerShell: $env:TEST_DATABASE_URL="postgresql://..."; pytest

# frontend (from frontend/)
npm run lint
npm run build
```

## Database migrations

```bash
cd backend
alembic current                               # verifies the DATABASE_URL connection
alembic revision --autogenerate -m "message"  # after model changes (later stages)
alembic upgrade head
```

## Deployment notes

**Render (backend):** root directory `backend`; build command
`pip install -r requirements.txt`; start command
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`; health check path `/health`.
Set `APP_ENV=production`, `DEBUG=false`, `JWT_SECRET_KEY`, `DATABASE_URL`,
`FRONTEND_ORIGIN=https://<your-vercel-domain>` and the Python version (`.python-version`
pins 3.13).

**Vercel (frontend):** root directory `frontend`; framework preset Vite; set
`VITE_API_BASE_URL=https://<your-render-service>/api/v1`.

## Status

P-3 (backend configuration and core infrastructure) complete. Authentication, database models, payments and
fraud detection are implemented in later stages.

## License

MIT; see [LICENSE](LICENSE).
