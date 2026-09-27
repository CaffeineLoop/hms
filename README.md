# Hospital Management System (HMS) — MVP

A FastAPI + PostgreSQL hospital management system with a bounded, read-only AI clinical-analysis
assistant. **Prototype / MVP: not production-ready and not clinically validated.**

## Modules

| Module | Stage | Main API prefixes |
|---|---|---|
| Patient management | 1 | `/api/patients` |
| Clinical records & timeline | 2 | `/api/patients/{id}/encounters|observations|conditions|allergies|clinical-notes|timeline` |
| Diagnostics, laboratory, reports, prescriptions | 3 | `/api/patients/{id}/lab-orders|reports|prescriptions`, `/api/lab-orders`, `/api/reports`, `/api/prescriptions` |
| Staff & hospital workflows | 4 | `/api/staff`, `/api/departments`, `/api/appointments`, `/api/admissions`, `/api/workflow-tasks` |
| Authentication & dynamic RBAC | 5 | `/api/auth`, `/api/users`, `/api/roles`, `/api/permissions` |
| Audit, security & hardening | 6 | `/api/audit-events` |
| AI assistant (read-only analysis) | 7 | `/api/ai/capabilities`, `/api/ai/analyses` |
| Four-day potential risk analysis + human review | 8 | `/api/ai/analyses` (`FOUR_DAY_RISK`), `/api/ai/risk-analyses` |
| AI guardrails & adversarial evaluation | 9–10 | see `docs/ai-evaluation/` |

Layering: **Router → Service → Repository → SQLAlchemy → PostgreSQL**. Schema changes only through
Alembic (`alembic/versions`, linear chain 0001–0010). Every protected route declares its permission;
authorship is bound to the authenticated staff member; security-relevant actions go to an
append-only audit trail.

## Setup (local)

1. Provision the least-privilege role and the two databases (as a PostgreSQL superuser; the password is
   supplied at run time and never stored):
   `psql -U postgres -h localhost -v app_password="<choose one>" -f scripts/provision_databases.sql`
2. `python -m venv .venv` and `pip install -r requirements-dev.txt`
3. Copy `.env.example` to `.env` (git-ignored) and fill in `DATABASE_URL` (hms_dev) and
   `TEST_DATABASE_URL` (hms_test). For the live AI set `GEMINI_API_KEY`; for offline use set
   `LLM_PROVIDER=fake`.
4. `alembic upgrade head`
5. Create the first administrator: `python -m app.cli create-admin --username admin --employee-code ADM-0001 --first-name ... --last-name ...`
   (password from `HMS_ADMIN_PASSWORD` or an interactive prompt).
6. Run: `uvicorn app.main:app --reload` (OpenAPI docs at `/docs` outside production).

Administrators create staff, users and roles through the API. No default role holds `ai.analysis`
or `ai.review`; grant them deliberately.

## Tests

- `pytest tests/unit` — no database.
- `pytest tests/integration` — uses **only** `TEST_DATABASE_URL` (a guard refuses to run against the
  development database). Destructive migration tests run on hms_test only.
- Automated AI tests use deterministic fake models; the live provider is never called by the suite.
- On low-memory machines run integration files one per process.
- Adversarial AI evaluation: see `docs/ai-evaluation/stage9-adversarial-evaluation.md`
  (`HMS_AI_EVAL_REPORT=... pytest ...` then `python scripts/ai_eval_report.py ...`).

## AI boundary

The assistant analyses **one patient's existing records** for a clinician with `ai.analysis` and
patient view scope ALL. It uses nine argument-free, patient-bound, permission-gated read tools inside a
READ ONLY database transaction; it has no write tools. Output is validated (schema, citations,
grounding of measurements and named clinical entities, overreach, certainty, patient isolation) and
always requires human review. `FOUR_DAY_RISK` explains signals computed by a deterministic
**demonstration rule set that is not clinically validated**, over a fixed horizon of exactly four days;
results are stored as AI suggestions (`ai_risk_analyses`) for review by a user with `ai.review`.
It never diagnoses, prescribes, orders tests, modifies records or executes workflow actions.

## Out of scope (by design)

Student Clinical Case Portal, de-identification, eligibility/outcome transfer, synchronisation with
downstream systems, the Synthea/FHIR importer (compatibility is verified in
`tests/integration/test_synthea_compatibility.py`), advanced scheduling and pharmacy inventory.
