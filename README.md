# Hospital Management System (HMS)

A full-stack Hospital Management System for managing patients, clinical records, diagnostics, prescriptions, staff workflows, authentication, RBAC, audit logs, and a bounded AI clinical analysis workflow.

The backend is the source of truth for patient and clinical data. The AI layer is read-only and produces four-day risk signals for clinician review; it does not diagnose, prescribe, order tests, or modify clinical records.

## Stack

### Backend

* Python 3.12
* FastAPI
* PostgreSQL 17
* SQLAlchemy 2.0
* psycopg 3
* Alembic
* Pydantic
* pytest
* HTTPX

### Frontend

* React 19
* TypeScript
* Vite
* React Router
* CSS with shared design tokens/components
* Inter font
* oxlint

### Authentication / Security

* Server-side opaque bearer sessions
* SHA-256 token hashes stored in DB
* scrypt password hashing
* Dynamic RBAC
* Permission scopes: `ALL`, `OWN`
* Append-only audit events
* Session idle timeout and revocation
* Login failure lockout/rate limiting
* Security headers and request IDs

### AI

* LangGraph
* LangChain
* `langchain-openai` for OpenAI-compatible providers
* OpenRouter
* `inclusionai/ling-3.0-flash-sante:free`
* Gemini provider support retained
* Fake/deterministic provider for tests
* Pydantic/schema validation
* Prompt-injection, grounding, horizon and overreach checks

## Main modules

* Patient management
* Encounters and clinical timeline
* Observations / vitals
* Conditions
* Allergies
* Clinical notes
* Laboratory orders, samples and results
* Reports
* Prescriptions
* Departments and staff
* Appointments
* Admissions and transfers
* Workflow tasks
* Authentication and sessions
* Users, roles and permissions
* Audit trail
* AI clinical analysis
* Four-day risk analysis and clinician review

## Architecture

```text
React frontend
      │
      ▼
FastAPI API
      │
      ├── Auth / RBAC
      ├── Patient & clinical services
      ├── Workflow services
      ├── Audit
      └── AI service
             │
             ├── read-only clinical tools
             ├── evidence/context assembly
             ├── LLM
             ├── structured validation
             ├── grounding / safety checks
             └── human review
      │
      ▼
PostgreSQL
```

Clinical data is never written by the AI layer.

## AI workflow

The current stored analysis workflow is:

```text
Patient context
    ↓
Permission check
    ↓
Read-only clinical tools
    ↓
Evidence assembly
    ↓
Rule-based risk signals
    ↓
LLM explanation
    ↓
Schema / semantic validation
    ↓
Grounding + safety checks
    ↓
Stored analysis
    ↓
Clinician review
```

The four-day risk analysis uses the `demo-v1` signal ruleset.

`demo-v1` is a demonstration ruleset and is **not clinically validated**.

AI output is explicitly treated as:

```text
Observe → Analyze → Explain → Suggest for review → Stop
```

## Data

The project uses synthetic/demo clinical data.

The clinical model was designed with future Synthea data compatibility in mind, but a dedicated Synthea import pipeline is not part of the current application.

No real patient data should be committed to the repository.

## Repository structure

```text
hms/
├── app/
│   ├── api/
│   ├── ai/
│   ├── models/
│   ├── repositories/
│   ├── schemas/
│   ├── services/
│   └── main.py
├── alembic/
├── tests/
├── frontend/
│   ├── src/
│   └── ...
├── scratchpad/
├── .env.example
└── ...
```

## Local setup

### 1. Backend

Create/activate the virtual environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Configure `.env` with at least:

```env
APP_ENV=development

DATABASE_URL=postgresql+psycopg://...

TEST_DATABASE_URL=postgresql+psycopg://...

AUTH_TOKEN_TTL_MINUTES=480
AUTH_IDLE_TIMEOUT_MINUTES=30

LLM_PROVIDER=openrouter
LLM_MODEL=inclusionai/ling-3.0-flash-sante:free
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

LLM_MAX_OUTPUT_TOKENS=16384
LLM_TEMPERATURE=0.1
LLM_TIMEOUT_SECONDS=30

AI_RISK_RULESET=demo-v1
AI_RISK_EVIDENCE_LOOKBACK_HOURS=96
AI_RISK_EVENT_TRIGGERS=
```

Run the API:

```bash
uvicorn app.main:app --reload
```

API docs:

```text
http://localhost:8000/docs
```

Health check:

```text
http://localhost:8000/health
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Default Vite URL:

```text
http://localhost:5173
```

For normal local use, run both the backend and frontend.

## Database / migrations

Development and test databases are separate.

```text
hms_dev
hms_test
```

Use Alembic for schema changes:

```bash
alembic upgrade head
```

Do not use `create_all()` as the schema-management mechanism.

The test suite is isolated from the development database.

## Tests

Backend:

```bash
pytest
```

Frontend checks:

```bash
cd frontend
npm run build
```

The UI was verified through browser-based regression/integration checks during development. Those browser scripts are currently kept in the scratchpad rather than as a permanent frontend test runner.

## RBAC

Permissions are represented as:

```text
User
  → UserRole
    → Role
      → RolePermission
        → Permission + Scope
```

Scopes:

* `ALL` — all matching records
* `OWN` — records tied to the user's own staff context where the permission supports it

Backend authorization is always authoritative. Hiding a navigation item in the frontend is not considered a security control.

## Audit

Important authentication, authorization, clinical and administrative actions are recorded in an append-only audit trail.

Audit records are read-only through the API.

Sensitive credentials and clinical text are not intended to be stored in audit metadata.

## Environment notes

Do not commit:

```text
.env
API keys
passwords
database credentials
real patient data
```

`.env.example` is the configuration reference; `.env` contains local secrets and is git-ignored.

## Current limitations

* Clinical write UI is not available for every backend workflow; some operations remain API/backend driven.
* User-account creation is currently backend/API driven.
* Synthea import is not yet implemented as a dedicated pipeline.
* The frontend does not yet have a permanent Vitest/Playwright test runner.
* AI risk rules are demonstration rules, not clinically validated decision support.
* The active free OpenRouter model can occasionally fail output validation or hit provider limits; the HMS rejects those responses rather than accepting malformed or unsupported clinical content.

## Development rules

* Keep business/security rules in the backend.
* Treat the database schema as migration-managed.
* Keep AI read-only and patient-scoped.
* Never weaken grounding or authorization to make a demo pass.
* Prefer existing service/repository/API patterns over introducing parallel abstractions.
* Use synthetic data for development and testing.

## Status

The current repository contains the implemented HMS backend and frontend milestone through the full UI integration pass, including the AI clinical-analysis workflow.
