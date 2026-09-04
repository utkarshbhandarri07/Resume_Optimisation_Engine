# Resume Optimization Agent

Full-stack two-agent resume optimization with FastAPI, LangGraph human review, Gemini evaluator/generator roles, Oracle persistence, email OTP authentication, deterministic ATS scoring, and a Django-rendered UI.

## Quick start

1. Extract the supplied wallet into `backend/wallet/` (the zip contains `tnsnames.ora`, `sqlnet.ora`, and wallet files). Keep `passwordforwallet.txt` private and set its value as `ORACLE_WALLET_PASSWORD`; do not commit either file. Run `backend/oracle_schema.sql` using the supplied Oracle schema credentials.
2. Copy `backend/.env.example` to `backend/.env` and set Oracle connection values and SMTP values. The UI asks each authenticated user for a Gemini API key; it is sent in `X-Gemini-API-Key` for the optimization request and is never persisted. For local testing use `APP_ENV=development` and `OTP_PROVIDER=mock`.
3. Create the Oracle application tables:

```powershell
cd backend
python migrate.py
```

4. Install and run the backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

5. Run the Django frontend in a second terminal:

```powershell
cd frontend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:FASTAPI_BASE_URL="http://localhost:8000/api"
python manage.py runserver 5173
```

Open `http://localhost:5173`. The backend API is at `http://localhost:8000/docs`.

## Notes

- The evaluator is fixed to `gemini-3.7-flash`. The UI lets the user choose `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`, or `gemini-3.1-flash-lite` for generation.
- The evaluator history, evaluation items, resume versions, and LangGraph checkpoints are session-scoped and must be persisted in Oracle for restart-safe operation.
- Mock OTP is development-only. Production requires SMTP configuration.
- `oracle.py` validates and opens the supplied wallet-backed Oracle pool, `oracle_schema.sql` defines the application tables, and `migrate.py` applies the schema. The store uses Oracle when credentials are configured and an in-process adapter for local smoke tests without a database.
- Generated PDFs use the server-owned LaTeX template and preserve the uploaded document's rendered page count. PDF uploads provide this count directly; DOCX uploads are rendered by LibreOffice first. The server rejects a rewrite that cannot fit the original page count without unsafe text shrinkage.
- Every `/api` route is limited to three requests per client in a ten-second window. A `429` response includes the retry delay and the UI displays it.

## Production deployment

Deploy the backend and frontend separately. The backend must be able to reach the
wallet-backed Autonomous Database; the frontend only needs the public backend URL.

### 1. Backend host

Copy the repository to a Linux VM/container (or a Python service such as Render,
Railway, Fly.io, or Cloud Run). Put the wallet files in a private directory such as
`backend/wallet/`; never commit the wallet archive or its password.

Create `backend/.env` from `.env.example` and set production values through the
platform's secret manager:

```dotenv
APP_ENV=production
JWT_SECRET=<long-random-secret>
CORS_ORIGINS=https://your-frontend.example.com
ORACLE_USER=<database-user>
ORACLE_PASSWORD=<database-password>
ORACLE_DSN=<wallet-service-name>
ORACLE_WALLET_DIR=/app/backend/wallet
ORACLE_WALLET_PASSWORD=<wallet-password>
OTP_PROVIDER=smtp
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<smtp-user>
SMTP_PASSWORD=<smtp-password>
EMAIL_FROM=<verified-sender>
```

Run the migration once during release/deploy (or as a one-off job), then start the
API. A typical Linux command is:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python migrate.py
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2
```

The production deployment script installs pinned Tectonic and LibreOffice before
starting the API. For a manual production install, run `sudo ops/install-resume-pdf-tools.sh` once from the repository root.

Use `/api/health/live` for a liveness check and `/api/health/ready` for readiness.
The readiness endpoint should report `oracle_configured: true` after the wallet and
credentials are valid. Configure the service to terminate TLS (or put it behind a
TLS reverse proxy) and restrict `CORS_ORIGINS` to the exact frontend origin.

### 2. Django frontend host

Configure the deployed FastAPI URL (including `/api`), collect static files, and
run Django's WSGI application:

```bash
cd frontend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=false
export DJANGO_SECRET_KEY=<long-random-secret>
export DJANGO_ALLOWED_HOSTS=your-frontend.example.com
export FASTAPI_BASE_URL=https://api.your-domain.example.com/api
python manage.py collectstatic --noinput
gunicorn resume_web.wsgi:application --bind 0.0.0.0:${PORT:-5173} --workers 2
```

Put the Django service behind HTTPS (for example, with Nginx or your platform's
managed reverse proxy). Whitenoise serves the collected static assets.

### 3. Operational/security requirements

- Use HTTPS for both origins. The Gemini key is intentionally browser-held and is
  sent in `X-Gemini-API-Key` for each optimization request; it is not stored in
  Oracle or backend state. Do not log request headers.
- Keep Oracle wallet files, database credentials, JWT secret, SMTP credentials, and
  provider credentials in deployment secrets, not in Git.
- Use a managed process supervisor/container restart policy and monitor the health
  endpoints. Run migrations before starting new application versions.
- For local development, keep `APP_ENV=development` and `OTP_PROVIDER=mock`; use
  SMTP OTP in production.
