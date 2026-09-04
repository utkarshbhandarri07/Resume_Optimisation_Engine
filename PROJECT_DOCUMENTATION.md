# Resume Optimisation Engine — Project Documentation

This document is the implementation and operations handover for the deployed
Resume Optimisation Engine. It describes the code and the live Oracle Cloud
deployment as verified on 4 September 2026. It deliberately does **not** include
database passwords, wallet files, JWT secrets, SMTP credentials, Gemini API
keys, OCI signing keys, or SSH private keys.

## 1. What the application does

The application helps a user tailor a factual, downloadable version of a resume
to a job description (JD). It is not a generic text editor: it is an
evaluator-first, human-approved workflow with persistent sessions.

From the user's perspective the flow is:

1. Open `http://resumeoptimiserbyub.gotdns.ch/` (or the VM IP URL).
2. Verify identity with an email one-time password (OTP).
3. Supply a Gemini API key in the browser and choose evaluator/writer model
   settings. The Gemini key is retained only in browser storage until Logout;
   it is sent in `X-Gemini-API-Key` for each LLM request and is never written to
   Oracle, LangGraph state, application logs, or Git.
4. Upload a PDF or DOCX resume and paste a JD. A new, persistent session is
   created for that exact pair of documents.
5. The evaluator model reviews the *complete* resume against the JD before any
   rewrite. The screen shows an overall fit score, category scores, evidence,
   and prioritized improvement items.
6. The user either selects the evaluator items and chooses **Improve resume**,
   or chooses **Give feedback**. Feedback must concern the resume or JD. The
   evaluator classifies irrelevant feedback and returns the user to review
   without rewriting.
7. The writer model rewrites only the approved areas while preserving protected
   facts. The server produces a structured resume representation, not model-
   generated LaTeX, and renders it through the server-owned LaTeX template.
8. The rewritten resume is rescored and re-evaluated by the same evaluator
   conversation. The UI shows a preview, evaluator comparison, ATS comparison,
   issue resolution state, and the current best version.
9. If the output fits exactly the original rendered page count, the user can
   download `optimized-resume.pdf`. Downloading clears the JD for the next
   session but retains the selected source file in the UI. **New session** is
   the only normal action that intentionally creates a fresh graph history.

The key product rules enforced by the implementation are:

- Do not invent experience, employers, titles, dates, skills, tools, metrics,
  responsibilities, or outcomes.
- Preserve role count and the exact bullet count of every original role.
- Preserve header/contact data, education, and certifications.
- Match the uploaded PDF's page count exactly. DOCX page count is determined
  from a headless LibreOffice PDF conversion.
- Limit public API traffic to three requests per ten seconds per authenticated
  token (or IP before authentication).

## 2. Repository map and component architecture

The GitHub repository is:

`https://github.com/utkarshbhandarri07/Resume_Optimisation_Engine`

The checked-out project root is:

`C:\Users\utkarsh\Desktop\Development\Resume_Optimisation_Project`

The live checkout is owned by the unprivileged VM account at:

`/opt/resume-optimizer/app`

### 2.1 Source tree

```text
Resume_Optimisation_Project/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI routes, API middleware, orchestration
│   │   ├── graph.py                # LangGraph state machine and interrupt nodes
│   │   ├── models.py               # ResumeState and request models
│   │   ├── llm.py                  # Gemini evaluator/writer clients and error mapping
│   │   ├── prompts.py              # evaluator and writer system contracts
│   │   ├── resume_parser.py        # PDF/DOCX extraction and source page count
│   │   ├── ats_scorer.py           # transparent deterministic ATS heuristic
│   │   ├── resume_layout.py        # structured-data validation and Tectonic render
│   │   ├── resume_template.tex     # locked server-owned visual template
│   │   ├── pdf_generator.py        # compatibility wrapper over resume_layout
│   │   ├── grounding.py            # retained grounding helpers
│   │   ├── oracle.py               # Oracle pool and OracleSaver checkpointer
│   │   ├── store.py                # session/document/version persistence
│   │   ├── auth.py                 # email OTP and bearer-token authentication
│   │   ├── rate_limit.py           # 3-request/10-second limiter
│   │   ├── logging_config.py       # IST-dated file logging
│   │   └── config.py               # environment-backed settings
│   ├── oracle_schema.sql           # application schema
│   ├── migrate.py                  # idempotent schema runner
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── manage.py
│   ├── resume_web/                 # Django project configuration and WSGI entrypoint
│   ├── web/
│   │   ├── views.py                # renders the single-page shell
│   │   ├── templates/web/index.html
│   │   └── static/web/app.js        # browser UI, caching, API calls and dialogs
│   ├── requirements.txt
│   └── .env.example
├── ops/
│   ├── deploy.sh                   # idempotent live deployment script
│   ├── install-resume-pdf-tools.sh # pinned Tectonic + LibreOffice installer
│   ├── resume-optimizer.cron       # midnight-IST deployment schedule
│   └── tectonic-smoke.tex          # deploy-time compiler warm-up document
├── README.md                       # concise setup guide
└── PROJECT_DOCUMENTATION.md         # this detailed handover
```

### 2.2 Runtime topology

```text
Browser
  │  Django HTML/CSS/JavaScript                         Gemini key in request header
  ▼                                                       (never server persisted)
Nginx :80 ── / ─────► Django/Gunicorn 127.0.0.1:5173
  │
  └──────── /api/ ──► FastAPI/Uvicorn 127.0.0.1:8000
                              │           │
                              │           ├── Gemini evaluator and writer APIs
                              │           ├── Tectonic + locked LaTeX template
                              │           └── LibreOffice (DOCX page-count conversion)
                              ▼
                    Oracle Autonomous Database via wallet
                    ├── application data: RO_* tables
                    └── LangGraph checkpoint tables: CHECKPOINTS, etc.
```

The split is deliberate:

- **Django** is the presentation layer. It serves the HTML shell and static
  assets with WhiteNoise. It has no direct Oracle or Gemini responsibilities.
- **FastAPI** is the application/API layer. It owns authentication, uploads,
  parsing, agent execution, persistence, PDF generation, rate limits, logging,
  and download streaming. Its OpenAPI-friendly routing and upload support fit
  this workload well.
- **LangGraph** is inside FastAPI rather than a separate process because graph
  invocations must use the authenticated session, source resume, and persistent
  checkpointer together.
- **Oracle Autonomous Database** holds data that must survive API process
  restarts and supports the cross-worker rate limiter and LangGraph resume
  checkpoints.
- **Nginx** is the only public process. The two app servers bind only to loopback
  addresses, so neither Django nor FastAPI is exposed directly to the Internet.

## 3. Frontend and API behavior

### 3.1 Django frontend

`frontend/resume_web/settings.py` reads these deployment settings:

```python
DJANGO_SECRET_KEY
DJANGO_DEBUG
DJANGO_ALLOWED_HOSTS
FASTAPI_BASE_URL
```

`frontend/web/views.py` renders `web/index.html` and supplies the configured
FastAPI base URL to the page. `frontend/web/static/web/app.js` implements the
interactive UI without a separate browser build pipeline. It calls the API,
shows loading/error/modal states, manages model retry dialogs, and renders
evaluator findings, scores, preview content, and downloads.

Browser caching is intentionally narrow and explicit:

- `localStorage`: bearer token, profile name/email, Gemini key, selected writer
  model, and selected evaluator model.
- `sessionStorage`: the active session response for up to five minutes, for a
  faster render after a reload.
- Logout removes every key in the `KEYS` map from both stores.

The source resume and JD are retained in the server-side session. A client
failure should not erase them. The recent frontend error handling also converts
an Nginx 504 HTML response into an actionable message rather than a meaningless
`Request failed.` dialog.

### 3.2 FastAPI routes

All application routes are in `backend/app/main.py`.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health/live` | Process liveness (`{"status":"ok"}`). |
| `GET` | `/api/health/ready` | Returns Oracle readiness/degraded state. |
| `POST` | `/api/auth/request-otp` | Send/store an email OTP. |
| `POST` | `/api/auth/verify-otp` | Verify OTP and issue bearer token. |
| `POST` | `/api/sessions` | Upload PDF/DOCX + JD, parse, persist, and run initial evaluation. |
| `GET` | `/api/sessions` | List the authenticated user's sessions. |
| `GET` | `/api/sessions/{sid}` | Read one persisted session. |
| `POST` | `/api/sessions/{sid}/decision` | Resume the interrupted graph with `improve`, `feedback`, or `retry_model`. |
| `GET` | `/api/sessions/{sid}/download` | Stream the verified, generated PDF. |

`main.py` removes `original_resume` from the response sent to the browser, but
retains it server-side for graph execution. Uploads are capped by
`MAX_UPLOAD_MB` (10 MB by default). CORS is controlled by `CORS_ORIGINS`.

## 4. LangGraph and the two-agent workflow

### 4.1 Why a graph instead of a linear request

A simple request/response rewrite would lose the point of this application:
the user must see an expert evaluation first, approve a subset of changes,
optionally add feedback, and continue the *same* evaluator conversation after a
rewrite. The flow can pause indefinitely at a human decision and must survive a
web/API restart.

`backend/app/graph.py` therefore uses a LangGraph `StateGraph(ResumeState)`.
LangGraph represents named operations as nodes, transitions as edges, and the
full workflow context as state. `interrupt()` stops the graph at a user review;
the `thread_id` is the application session UUID. Resumption uses:

```python
Command(resume=payload.model_dump())
config={"configurable": {"thread_id": sid}}
```

That same thread ID is critical: it reconnects the resume session to its
Oracle-backed LangGraph checkpoint and evaluator history.

### 4.2 State

`backend/app/models.py` defines the `ResumeState` TypedDict. Important fields
include:

- immutable/source context: `original_resume`, `jd`, `original_experience`,
  `resume_sections`, `source_template_data`, `target_page_count`;
- current work: `current_resume`, `resume_template_data`,
  `rewritten_experience`, `user_feedback`, `approved_improvement_ids`;
- scores: original/rewritten ATS scores and explanations,
  `best_evaluator_score`, `best_ats_score`, and `comparison`;
- evaluator conversation: `evaluation`, `improvement_items`, and ordered
  `evaluator_messages`;
- safety/flow: `grounding_valid`, `grounding_issues`, `layout_error`,
  `status`, `download_ready`, and model retry fields;
- configuration: `selected_writer_model` and `evaluator_model`.

The API key is intentionally absent from this state. It exists only as the
per-request `api_key` argument captured by `build_graph()`.

### 4.3 Nodes and edges implemented

```text
START
  │
  ▼
initial_evaluate ──capacity/model failure──► model_selection ──► retry target
  │
  ▼
review (LangGraph interrupt)
  ├── feedback ─► feedback ─► review
  └── improve  ─► generate ─► validate ─► rescore ─► reevaluate ─► finish ─► END
                                      │                 │
                                      └ model error ────┴──► model_selection
```

What each node actually does:

1. **`initial_evaluate`** creates `GeminiEvaluator` with the session evaluator
   model and evaluates `current_resume` against `jd`. It saves the structured
   evaluation, improvement items, the first evaluator message pair, and starts
   both best-score baselines.
2. **`review`** calls `interrupt()` with an `improve`/`feedback` action payload.
   An improvement action carries selected stable issue IDs; feedback carries up
   to 5,000 characters of user text.
3. **`feedback`** sends the previous evaluation and the ordered evaluator
   history to the *same evaluator model*. If `feedback_relevant` is false, it
   stores `feedback_error` and returns to review. Relevant feedback generates a
   revised evaluator issue list and returns to review for user approval.
4. **`generate`** filters `improvement_items` to exactly the user-approved IDs,
   invokes `GeminiWriter`, validates its structured result against the source,
   and attempts to render it. If exact page count fails, it asks the writer to
   shorten wording only and retries up to two additional times (three total
   render attempts). A persistent layout failure returns to review with
   `layout_error`; it does not create an invalid downloadable PDF.
5. **`validate`** currently marks the version `grounding_valid=True`. The strict
   protection occurs earlier in `validate_template_data()`—protected metadata,
   role/bullet count, education, certifications, and text escaping are enforced
   there. This is intentionally not a lexical "new named term" rejection,
   because the approved user/evaluator workflow may request JD-aligned wording.
6. **`rescore`** calculates deterministic ATS scores for original and current
   resume text.
7. **`reevaluate`** appends a re-evaluation turn to the evaluator's history,
   computes score deltas/resolved issue IDs, marks preview/download readiness,
   and updates the best score values.
8. **`model_selection`** is a second human interrupt used after a Gemini error.
   It exposes permitted models, records the chosen replacement, and re-enters
   the failed node. This avoids silently switching models.
9. **`finish`** ends the graph after an improved preview is ready.

### 4.4 Real example

For a session `S`:

1. `POST /api/sessions` parses `resume.pdf`, saves source bytes and state under
   `S`, and invokes `initial_evaluate` with LangGraph `thread_id=S`.
2. The evaluator returns issue IDs such as `SUMMARY-01` and `EXP-02`; the graph
   interrupts in `review` and FastAPI returns `awaiting_review` to the browser.
3. The user checks `SUMMARY-01` and `EXP-02` and sends an `improve` decision.
   FastAPI loads `S`, invokes `Command(resume=...)` using the same thread ID,
   and the graph resumes in `generate`.
4. The writer sees source resume text, JD, immutable template structure, and
   only those selected issue objects. It returns `resume_template` JSON.
5. The server restores protected fields, compiles a PDF in a temporary
   directory, checks the page count with `pypdf`, scores the new plain text,
   and sends it to the evaluator with conversation history from steps 1–2.
6. The graph persists checkpoint/state and returns `preview_ready`. The browser
   presents the new version. `GET /api/sessions/S/download` streams the stored
   generated PDF only when `download_ready` is true.

### 4.5 Models and prompts

The model layer is `backend/app/llm.py`; the prompt contracts are in
`backend/app/prompts.py`.

- `GeminiEvaluator` calls `generate_content(... response_mime_type="application/json")`
  with a 3,000-token response limit. Its system contract is a 10-years-
  experience technical HR leader. It returns fit/category scores, evidence,
  issue IDs and priorities, resolution IDs, score delta/comparison, and
  feedback relevance.
- `GeminiWriter` calls the same Gemini SDK with a 5,000-token JSON response.
  Its contract is a technical resume strategist using factual, concise X-Y-Z
  bullets only where source evidence supports each component.
- The evaluator/writer model choices are in `graph.py`:
  `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`,
  `gemini-3.5-flash-lite`, and `gemini-3.1-flash-lite`. The evaluator may use
  any listed model in the current implementation; writer choices omit 3.7.
- Provider 503/capacity is converted into `ModelTemporarilyUnavailable` with a
  `Retry-After: 30` response. Other model failures produce a controlled model
  selection interrupt rather than exposing raw provider internals.

## 5. Resume parsing, ATS scoring, grounding, and PDF rendering

### 5.1 Parsing

`backend/app/resume_parser.py` accepts only `.pdf` and `.docx`:

- **PDF:** `pypdf.PdfReader(BytesIO(data))` extracts text from each page. Its
  native page count becomes `target_page_count`.
- **DOCX:** `python-docx` reads paragraph text. Because DOCX has no reliable
  fixed rendered-page count, headless LibreOffice converts the uploaded file to
  PDF in a temporary directory; `pypdf` counts that rendered PDF's pages.
- `_sections()` detects `Experience`, `Work Experience`, `Professional
  Experience`, and `Employment History`, plus short all-caps headings. The
  parser requires an Experience section and nonempty extractable text.

This is text extraction, not OCR. Image-only/scanned PDFs and very complex
multi-column documents can fail to provide usable text; they should be OCR'd or
exported as a text-bearing PDF before upload.

### 5.2 Deterministic ATS heuristic

`backend/app/ats_scorer.py` is intentionally transparent. It is not a claim to
replicate a commercial ATS. `score_experience(experience, jd)` normalizes terms
with a regular expression, excludes a small stop-word set, and returns a score,
explanation, matched keywords, and missing keywords.

| Component | Maximum | Actual rule |
|---|---:|---|
| JD keyword match | 50 | `50 × matched_unique_JD_terms / unique_JD_terms` |
| Quantified achievements | 20 | 5 points per number/percent/money/scale match, capped at 20 |
| Action verbs | 20 | 4 points per recognized verb, capped at 20 |
| Length/readability | 10 | 10 points for 40–260 normalized words; 6 for 20–350; otherwise 3 |

The recognized action verbs include `built`, `led`, `designed`, `developed`,
`implemented`, `created`, `managed`, `improved`, `delivered`, `automated`,
`optimized`, `reduced`, `increased`, `launched`, `architected`, and `integrated`.
The response explanation reports the four component totals, e.g. `30/50 keyword
match ... 10/20 quantified achievements ...`.

FastAPI records an original score at session creation and recalculates original
and rewritten scores in the graph `rescore` node. The evaluator's fit score is
separate: it is an LLM judgment with category scores, while ATS is deterministic
and reproducible from the same text/JD inputs.

### 5.3 Structured grounding and rendering

The server owns formatting. Gemini never supplies raw LaTeX.

1. `source_template_data()` converts parsed source into header, summary, skill
   groups, role metadata/bullets, education, and certifications.
2. The generation prompt receives that as `IMMUTABLE TEMPLATE STRUCTURE`.
3. `validate_template_data()` requires summary/skills/experience/education/
   certifications, preserves role count and bullet count, overwrites title,
   company, dates, location, header, education, and certifications from source,
   and rejects empty/invalid arrays.
4. `_latex()` escapes all special LaTeX characters in model/user text. The only
   TeX commands originate in `backend/app/resume_template.tex` and
   `resume_layout.py`.
5. `render_pdf()` substitutes safe structured data into the template, invokes
   Tectonic in an isolated temporary directory, and uses `pypdf` to reject any
   result whose page count differs from `target_page_count`.

The deployment installs pinned Tectonic 0.16.9 for ARM64 and LibreOffice. The
deployment script compiles `ops/tectonic-smoke.tex` as `resumeopt` to warm
Tectonic's package cache before user traffic.

## 6. Rate limiting

`backend/app/rate_limit.py` implements `SlidingWindowRateLimiter` with the
configured default of **3 requests per 10 seconds**. `backend/app/main.py`
enforces it in HTTP middleware for every path beginning `/api/`.

### Algorithm

- The client identifier is the `Authorization` header when present; otherwise
  it is the request IP address.
- The identifier is SHA-256 hashed before storage, so Oracle does not retain
  raw bearer tokens/IP identifiers as rate-limit keys.
- With Oracle unavailable (local development), a thread-safe `deque` holds
  monotonic timestamps. Expired timestamps are discarded before deciding.
- With Oracle configured (production), `RO_RATE_LIMITS` contains one row per
  hash. The row is selected `FOR UPDATE`, making concurrent Uvicorn workers
  serialize their update. The row either starts/restarts a fixed 10-second
  window, increments count, or returns a computed retry delay.
- Rejected requests return HTTP `429`, JSON detail, `retry_after`, and a
  `Retry-After` header. The frontend includes that wait time in its error.

This protects OTP endpoints, upload/LLM work, session APIs, and the Oracle
pool from accidental double clicks, scripted bursts, and low-effort abuse. It
is deliberately a small per-client operational limiter, not a substitute for a
WAF, DDoS protection, or a distributed edge rate limiter.

## 7. Oracle Autonomous Database persistence

### 7.1 Why wallet-backed Oracle

The application uses Oracle Autonomous Database with a wallet because the wallet
provides the trusted network/TLS configuration and `tnsnames.ora` aliases for
the Autonomous service. The deployment uses the wallet service alias
`project1_medium`.

`backend/app/oracle.py` creates a python-oracledb connection pool only when
`ORACLE_USER`, `ORACLE_PASSWORD`, and `ORACLE_DSN` are all configured. It passes
the wallet directory as both `config_dir` and `wallet_location`, passes the
wallet password, and sets `TNS_ADMIN`. The pool is sized `min=1, max=4` and has
a session callback that runs `ALTER SESSION DISABLE PARALLEL DML`; this avoids
the Autonomous parallel-DML/checkpoint conflict observed during implementation.

When no Oracle configuration is present locally, the store uses process memory
and LangGraph uses `MemorySaver`. That fallback is useful for smoke tests, but
it is not restart-safe and is not the deployed production mode.

### 7.2 Schema

`backend/oracle_schema.sql` creates these tables:

| Table | Purpose and current use |
|---|---|
| `RO_USERS` | OTP-authenticated user identity by email/display name. |
| `RO_OTP_REQUESTS` | Hashed OTP, expiry, attempts, request audit data. |
| `RO_SESSIONS` | User-owned JD, serialized graph/application state, status, evaluator and writer model names. |
| `RO_DOCUMENTS` | Source upload and generated PDF BLOBs with filename/MIME data. |
| `RO_RESUME_VERSIONS` | Ordered persisted resume state snapshots, text, ATS/evaluator fields, grounding state. |
| `RO_EVALUATOR_MESSAGES` | Ordered user/model evaluator conversation messages per session. |
| `RO_EVALUATIONS` | Structured evaluator JSON and score delta associated with a version. |
| `RO_IMPROVEMENT_ITEMS` | Schema support for stable issue metadata, approval, and resolution state. The graph currently keeps current issue objects in session state; this table is provisioned for normalized item persistence/reporting. |
| `RO_RATE_LIMITS` | Cross-worker persisted limiter state keyed by SHA-256 client identifier. |
| `RO_MIGRATIONS` | Idempotent application-schema migration marker. |

`OracleSaver.setup()` additionally creates and uses LangGraph's checkpoint
tables: `CHECKPOINTS`, `CHECKPOINT_BLOBS`, `CHECKPOINT_WRITES`, and
`CHECKPOINT_MIGRATIONS`. These are graph-engine persistence, separate from the
application's `RO_*` schema.

`backend/app/store.py` writes source files, generated PDFs, session state,
versions, evaluation JSON, and evaluator messages. It correctly handles Oracle
JSON values returned either as serialized text or already-decoded dictionaries.

### 7.3 Migration behavior

Run from the backend directory:

```bash
/opt/resume-optimizer/app/backend/.venv/bin/python migrate.py
```

`backend/migrate.py` first creates `RO_MIGRATIONS` if absent, executes schema
statements, treats `ORA-00955` (already exists) and `ORA-01408` (duplicate
index) as safe idempotent cases, then upserts migration version
`001_resume_optimizer`. This is why the daily deployment can run migrations
without deleting/recreating data.

## 8. Oracle Cloud deployment architecture

### 8.1 Live compute and network inventory

The site runs in **ap-mumbai-1** on a running Oracle Linux 8.10 ARM64 VM:

| Item | Live value |
|---|---|
| Instance display name | `resume-optimizer-a1` |
| Shape | `VM.Standard.A1.Flex` |
| OCPUs / RAM | 2 OCPUs / 12 GB |
| Boot volume | 50 GB, 10 VPUs/GB |
| Availability domain | `pjae:AP-MUMBAI-1-AD-1` |
| Public IP | `92.4.68.63` |
| Private IP | `10.0.1.250` |
| VCN | `resume-optimizer-vcn`, `10.0.0.0/16`, DNS label `resumeopt` |
| Public subnet | `resume-optimizer-public-subnet`, `10.0.1.0/24`, DNS label `public1` |
| Internet gateway | `resume-optimizer-igw` |
| Route | `0.0.0.0/0` to the Internet Gateway |

The A1.Flex shape and requested OCPU/memory allocation are Always Free eligible
in the tenancy allocation used for deployment. The VM is public because it
hosts an Internet-facing web application; data services remain in Oracle
Autonomous Database rather than being hosted on the VM.

The public subnet permits a public IP (`prohibit_public_ip_on_vnic=false`). Its
security list has public TCP ingress for ports **22**, **80**, and **443**, plus
the expected ICMP rules. The VM's local firewalld zone `public` permits `ssh`
and `http`; SELinux is **Enforcing**. Port 443 is permitted at OCI level for a
future HTTPS configuration but Nginx currently listens only on port 80.

Raw tenancy, instance, VCN, subnet, route-table, security-list, VNIC, and
gateway OCIDs are intentionally omitted from this public repository. They are
identifiers rather than credentials, but publishing infrastructure inventory in
source control is unnecessary. They can be queried with the OCI commands below.

### 8.2 From bare VM to live service

The deployment work followed this sequence:

1. Used OCI CLI authenticated for the Mumbai region to perform read-only
   discovery, then created the approved A1.Flex Oracle Linux 8 instance and
   50-GB boot volume inside the public subnet.
2. Generated a dedicated local ED25519 SSH key pair for VM administration.
   The private key stays outside the repository under the user's `.ssh`
   directory and is never copied to the VM or GitHub. The public half was added
   to instance metadata.
3. Added OCI security-list ingress for SSH (22), HTTP (80), and HTTPS (443),
   then allowed `ssh`/`http` through firewalld. Nginx fronted application ports;
   Uvicorn/Gunicorn were bound to `127.0.0.1` only.
4. Installed Oracle Linux dependencies, Git, Python virtual environments,
   Nginx, Gunicorn, Uvicorn, LibreOffice, and the pinned ARM64 Tectonic runtime.
5. Cloned the GitHub repository to `/opt/resume-optimizer/app`, created the
   `resumeopt` service account, and installed requirements into separate
   `backend/.venv` and `frontend/.venv` environments.
6. Copied the wallet archive and deployment environment files through SCP into
   private VM locations, extracted the wallet outside Git tracking, and created
   protected `/etc/resume-optimizer/*.env` files. No wallet or secret ever went
   through Git.
7. Ran the idempotent Oracle migration and initialized OracleSaver checkpoints.
8. Created systemd units, Nginx proxy configuration, daily deployment cron,
   date-based logs, and health checks.
9. Created the No-IP hostname `resumeoptimiserbyub.gotdns.ch` pointing to the
   public IP and added that hostname to Nginx's `server_name` directive.

### 8.3 Useful read-only OCI discovery commands

Run these from the configured Windows machine; do not print the OCI config or
private signing key:

```powershell
$oci = 'C:\Program Files (x86)\Oracle\oci_cli\oci.exe'
$cfg = 'C:\Users\utkarsh\.oci\config'
& $oci iam region list --config-file $cfg --output json

# Substitute the current tenancy/instance OCIDs from the OCI Console or IMDS.
& $oci compute instance get --instance-id $instanceId --config-file $cfg
& $oci compute vnic-attachment list --compartment-id $compartmentId `
  --instance-id $instanceId --config-file $cfg
& $oci network subnet get --subnet-id $subnetId --config-file $cfg
& $oci network security-list get --security-list-id $securityListId --config-file $cfg
```

## 9. Nginx, hostname, and HTTPS status

The current live file is `/etc/nginx/conf.d/resume-optimizer.conf`:

```nginx
server {
    listen 80;
    server_name 92.4.68.63 resumeoptimiserbyub.gotdns.ch;
    client_max_body_size 12m;

    location /api/ {
        proxy_connect_timeout 15s;
        proxy_send_timeout 240s;
        proxy_read_timeout 240s;
        send_timeout 240s;
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Directive-by-directive:

- `listen 80` receives public HTTP. `server_name` matches both the original IP
  access and the No-IP host; without the hostname Nginx selected the Oracle
  Linux default welcome-site server.
- `client_max_body_size 12m` is aligned with the FastAPI 10-MB application
  upload cap while allowing multipart overhead.
- `/api/` is forwarded to FastAPI on private loopback port 8000. It has a
  15-second connection timeout and 240-second send/read/client timeouts because
  a Gemini call plus LaTeX compile can exceed Nginx's default 60 seconds.
- `/` is forwarded to Django/Gunicorn on private loopback port 5173, including
  static page delivery.
- HTTP/1.1 and the forwarded headers preserve host, original client IP,
  proxy chain, and original scheme for application logging and URL/security
  decisions.

The No-IP hostname is **HTTP only at present**. It is not yet an HTTPS/TLS
deployment: there is no `listen 443 ssl`, certificate, or redirect in the live
Nginx config. Before treating email OTP, bearer tokens, or Gemini-key traffic as
production Internet traffic, configure a real domain or ensure the dynamic-DNS
provider supports ACME validation, issue a Let's Encrypt certificate, add the
443 server block, and redirect HTTP to HTTPS. The OCI security list already
permits port 443, so the missing work is certificate/Nginx configuration, not
cloud ingress.

Validate/reload after a future Nginx change:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -H 'Host: resumeoptimiserbyub.gotdns.ch' http://127.0.0.1/
```

## 10. systemd services and logging

`systemd` is used rather than manually running terminals because it starts
processes after boot/network availability, runs them under the unprivileged
`resumeopt` account, restarts a failed web/API service, centralizes logs under
`journalctl`, and gives deployment a reliable service-control interface.

### 10.1 API service

`/etc/systemd/system/resume-optimizer-api.service`:

```ini
[Unit]
Description=Resume Optimizer FastAPI service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=resumeopt
Group=resumeopt
WorkingDirectory=/opt/resume-optimizer/app/backend
EnvironmentFile=/etc/resume-optimizer/backend.env
EnvironmentFile=/etc/resume-optimizer/backend-secrets.env
ExecStart=/opt/resume-optimizer/app/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 10.2 Web service

`/etc/systemd/system/resume-optimizer-web.service`:

```ini
[Unit]
Description=Resume Optimizer Django web service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=resumeopt
Group=resumeopt
WorkingDirectory=/opt/resume-optimizer/app/frontend
EnvironmentFile=/etc/resume-optimizer/frontend.env
ExecStart=/opt/resume-optimizer/app/frontend/.venv/bin/gunicorn resume_web.wsgi:application --bind 127.0.0.1:5173 --workers 2 --access-logfile - --error-logfile -
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 10.3 Migration service

`/etc/systemd/system/resume-optimizer-migrate.service` is a `Type=oneshot`
service run as `resumeopt`. It has the same backend environment files and runs:

```ini
ExecStart=/opt/resume-optimizer/app/backend/.venv/bin/python migrate.py
```

Useful operational commands:

```bash
sudo systemctl status resume-optimizer-api.service resume-optimizer-web.service
sudo journalctl -u resume-optimizer-api.service -u resume-optimizer-web.service -n 200 --no-pager
sudo systemctl restart resume-optimizer-api.service resume-optimizer-web.service
```

`backend/app/logging_config.py` also creates an IST-dated log file:

```text
/var/log/resume-optimizer/resume-optimizer-YYYY-MM-DD.log
```

It logs request IDs, method/path/status, latency, rate-limit events, and safe
exception context. It intentionally does not log document contents, OTPs,
Gemini keys, DB passwords, or wallet data. Files are mode `0640`; the log
directory is created for `resumeopt` by `ops/deploy.sh`.

## 11. Security decisions

### 11.1 Source control and secrets

Root `.gitignore` excludes:

- `.env`/`.env.*` (except examples), `backend-secrets.env*`, credential text
  files, and password files;
- all wallet directories/files and common private material: `**/wallet/`,
  `*.wallet`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`,
  `Wallet_Project1.zip`, and `passwordforwallet.txt`;
- virtual environments, Python caches, Node modules, static/build output,
  logs, editor files, and OS artifacts.

The wallet and secret environment data were transferred to the VM via SCP into
private host paths, then referenced from root-owned service `EnvironmentFile`
files. SCP was chosen because it is encrypted SSH transport and does not place
secrets in Git history, GitHub Actions logs, issue trackers, or deployment
artifacts. Do not use `git add -f`, paste secret contents in chat, or put wallet
files inside `/opt/resume-optimizer/app` unless the directory is strictly
protected and excluded from Git.

### 11.2 Network/process hardening

- SSH uses a dedicated ED25519 key; its private half remains on the developer
  machine. Use `-o IdentitiesOnly=yes -o BatchMode=yes` for noninteractive
  administration.
- Nginx is public; Gunicorn/Uvicorn are loopback-only.
- OCI ingress exposes only needed ports 22/80/443. Local firewalld exposes
  `ssh` and `http`; SELinux remains enforcing.
- Services use `resumeopt`, not root, plus `NoNewPrivileges=true` and
  `PrivateTmp=true`.
- API authentication uses email OTP then bearer tokens. `JWT_EXPIRY_MINUTES`
  is 300 (five hours) in deployment configuration.
- Gemini API keys are browser-only by design. The API key header must be sent
  on every LLM operation because it is never persisted server-side.
- Model output cannot inject raw TeX because the server escapes special
  characters and owns the template.
- Oracle rate-limit keys are hashed before persistence.

### 11.3 Remaining security work

The live No-IP endpoint is HTTP only. Configure HTTPS before sharing the app
broadly. Also consider narrowing SSH ingress to known administrator IP ranges,
rotating environment/JWT/SMTP credentials periodically, adding backups and
retention rules for uploaded resume PII, and placing a WAF/CDN in front of the
VM if traffic grows.

## 12. Deployment and update runbook

### 12.1 Normal update path

The deployment model is GitHub main → VM pull → idempotent deploy script.

1. Make and test a change locally.
2. Confirm secrets/build artifacts are not staged:

   ```powershell
   git status --short
   git diff --cached --name-only
   ```

3. Commit and push only intended project files:

   ```powershell
   git add <specific-files>
   git commit -m "Describe the change"
   git push origin main
   ```

4. Either wait for the scheduled deployment or run it immediately over SSH:

   ```powershell
   $key = 'C:\Users\utkarsh\.ssh\resume_optimisation_oracle_a1_20260904'
   ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes opc@92.4.68.63 `
     'sudo /opt/resume-optimizer/app/ops/deploy.sh'
   ```

5. Verify services, Nginx, and API readiness:

   ```powershell
   ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes opc@92.4.68.63 `
     'sudo systemctl is-active resume-optimizer-api.service resume-optimizer-web.service; sudo nginx -t; curl -sS http://127.0.0.1:8000/api/health/live'
   ```

6. Test the public app in a new browser session. For a frontend asset update,
   use `Ctrl+F5` to bypass cached static assets.

### 12.2 Scheduled deployment

The installed cron file is `/etc/cron.d/resume-optimizer-deploy`:

```cron
CRON_TZ=Asia/Kolkata
0 0 * * * root /opt/resume-optimizer/app/ops/deploy.sh
```

It runs every day at **00:00 IST**. The VM itself can remain in UTC; `CRON_TZ`
sets the intended schedule.

`ops/deploy.sh` is safe to run repeatedly:

1. creates/owns the application log directory and opens a lock at
   `/var/lock/resume-optimizer-deploy.lock` using `flock`;
2. `git fetch`es `origin/main` as `resumeopt` and exits with no downtime if the
   remote commit equals current `HEAD`;
3. on change, stops web/API, fast-forwards `main`, installs/verifies PDF tools,
   warms Tectonic, reinstalls pinned Python requirements, runs Django
   `collectstatic`, invokes the migration service, restarts both services, and
   validates/reloads Nginx;
4. if a deployment command fails, its trap attempts to restart API/web services;
5. logs deployment events to `/var/log/resume-optimizer/deploy.log`.

Run the no-change preflight manually with:

```bash
sudo /opt/resume-optimizer/app/ops/deploy.sh --check
```

### 12.3 Updating environment or wallet data

Never commit changes to `/etc/resume-optimizer/backend-secrets.env`,
`/etc/resume-optimizer/backend.env`, or the wallet. Transfer a replacement
secret file/wallet over SCP, apply restrictive ownership/mode on the VM, update
the relevant `EnvironmentFile` content, then restart the affected service.

Example transport pattern (do not put real secret values on the command line):

```powershell
$key = 'C:\Users\utkarsh\.ssh\resume_optimisation_oracle_a1_20260904'
scp -i $key -o IdentitiesOnly=yes <local-secret-file> `
  opc@92.4.68.63:/tmp/resume-optimizer-secret-upload
```

Then use a privileged, audited VM shell to place it under
`/etc/resume-optimizer/` with owner `root` and restrictive permissions, and
restart `resume-optimizer-api.service`. Do not leave secret uploads in `/tmp`.

### 12.4 Diagnostics

| Symptom | Check | Likely response |
|---|---|---|
| Default Oracle Linux Nginx page | `sudo nginx -T` | Ensure hostname appears in `server_name`; test/reload Nginx. |
| Browser says request failed after ~60s | Nginx error log and proxy values | Current `/api/` proxy read timeout is 240s; inspect Gemini/PDF processing if it exceeds that. |
| Gemini capacity error | API response/graph status | Choose an offered alternate evaluator/writer model or retry later. |
| `Session could not continue` | `journalctl` plus daily app log | Find request ID; session/resume/JD stay persisted unless user starts a new session. |
| PDF cannot fit | `layout_error` in session | Writer gets bounded shortening attempts; do not lower font size or add pages automatically. |
| Oracle readiness degraded | `/api/health/ready`, API journal | Verify wallet path/permissions and private environment values; never print them. |
| Migration errors | `journalctl -u resume-optimizer-migrate.service` | Rerun service after config fix; `ORA-00955`/`ORA-01408` are intentionally idempotent. |

### 12.5 Post-update checklist

- `git status --short` is clean except deliberately untracked local scratch
  material.
- Both systemd services report `active`.
- `sudo nginx -t` passes.
- `/api/health/live` returns `{"status":"ok"}` and readiness shows Oracle
  configured in production.
- Browser opens both `http://92.4.68.63/` and
  `http://resumeoptimiserbyub.gotdns.ch/`.
- OTP, session creation, evaluator review, model error handling, improvement,
  preview, and download are tested with a non-sensitive test resume/JD.
- No secret/wallet/private key/log file is in the staged Git file list.

## 13. Important operational limitations to remember

- The HTTP No-IP hostname is convenient but is not yet a production-grade TLS
  endpoint. Treat HTTPS as a required next hardening step.
- The parser does not OCR scanned resumes and may need improvement for complex
  multi-column layouts.
- The deterministic ATS score is transparent guidance, not a commercial ATS
  prediction.
- The evaluator depends on an end-user Gemini key and the selected provider
  model being available. Provider capacity is surfaced to the user and must not
  be hidden by silently switching a model.
- Resume data is sensitive personal data. Oracle persistence and generated
  document BLOBs need a documented retention/deletion policy before broad use.
- `RO_IMPROVEMENT_ITEMS` exists in the schema, while present runtime code keeps
  active improvement items in persisted session state. If normalized reporting
  or administrator analytics is added, extend `store.py` to write/read that
  table explicitly.

