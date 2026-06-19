# AGENTS.md — Backend (Django + DRF)

> Cross-tool agent rules. Read by Antigravity, Cursor, Claude Code, and Codex.
> This file governs the **backend repo only**. The frontend lives in a separate repo with its own AGENTS.md.

---

## Tech Stack
- Language: Python 3.12+
- Framework: Django 5.x + Django REST Framework
- Database: PostgreSQL (via Django ORM)
- API schema/docs: drf-spectacular (OpenAPI 3 + Swagger UI + ReDoc)
- Auth: JWT (djangorestframework-simplejwt) — adjust if project uses sessions
- Tooling: ruff (lint + format), mypy (types), pytest + pytest-django
- Env management: python-decouple / django-environ — secrets via env vars only

## Commands
- Install deps: `pip install -r requirements.txt`
- Run dev server: `python manage.py runserver`
- Make/apply migrations: `python manage.py makemigrations` / `migrate`
- Run tests: `pytest`
- Lint + format: `ruff check . --fix && ruff format .`
- Type check: `mypy .`
- Generate OpenAPI schema: `python manage.py spectacular --file schema.yml`

---

## Code Quality
- Follow PEP 8. Format with ruff; do not hand-format.
- Type hints on every function signature (params + return). Run mypy before declaring a task done.
- Keep functions small and single-purpose. Cyclomatic complexity target ≤ 10.
- Keep files focused; if a `views.py` or `serializers.py` exceeds ~400 lines, split by domain (e.g. `views/orders.py`).
- No commented-out dead code. No print() for logging — use the `logging` module.
- Prefer Django ORM over raw SQL. If raw SQL is unavoidable, always parameterize.
- Business logic belongs in services/selectors or model methods, NOT in views. Keep views thin.
- DRY: reuse serializers and mixins; don't copy-paste endpoint logic.

## Security (non-negotiable)
- **Never hardcode secrets** (API keys, DB passwords, JWT signing keys). Env vars only.
- **Never read or print the contents of `.env`** files.
- `DEBUG = False` assumptions in any production-path code. Never expose stack traces to clients.
- All input validated through DRF serializers — never trust request data directly.
- Use the ORM to prevent SQL injection; never build queries via string concatenation.
- Enforce authentication + permission classes on every endpoint. Default to `IsAuthenticated`; make public endpoints explicit and intentional.
- Configure CORS explicitly (django-cors-headers) — never `CORS_ALLOW_ALL_ORIGINS = True` in production.
- Rate-limit sensitive endpoints (login, password reset) via DRF throttling.
- Hash passwords with Django's built-in hashers — never store or log plaintext.
- Validate file uploads (type, size) and store outside the web root or on object storage.
- Sanitize/escape any user content rendered in responses or admin.

## API Documentation (Swagger / OpenAPI) — required for every endpoint
- Every endpoint MUST be documented via drf-spectacular.
- Add `@extend_schema` to views/viewsets with: summary, description, request body, responses (including error codes), and at least one example.
- Document all serializer fields; use `help_text` on model/serializer fields so it flows into the schema.
- Every response shape must be backed by a serializer (no undocumented ad-hoc dicts).
- Swagger UI served at `/api/docs/`, ReDoc at `/api/redoc/`, raw schema at `/api/schema/`.
- When you add or change an endpoint, regenerate `schema.yml` so the frontend repo can sync types.
- Document error responses (400/401/403/404/409/422/500) with their serializer/shape, not just the happy path.

## Code Documentation
- Module-level docstring on every non-trivial module describing its responsibility.
- Docstrings on all public classes, service functions, and complex methods (Google style).
- Explain *why*, not *what*, in inline comments. The code already says what.
- Keep `README.md` current: setup, env vars (names only, never values), how to run, how to test.
- Maintain a `.env.example` listing every required env var by name with a placeholder value.

## Testing
- Write tests for every new endpoint and service function (happy path + at least one failure/edge case).
- Use pytest + pytest-django; factory_boy or fixtures for test data.
- Test permissions/auth: confirm unauthorized requests are rejected.
- Keep coverage ≥ 80% on new/changed code.
- Tests must pass and lint must be clean before a task is considered complete.

## Database & Migrations (safety)
- Always create migrations for model changes; never edit applied migrations.
- **Ask for explicit approval before** running destructive operations (data migrations that delete/transform data, `flush`, dropping columns/tables).
- Never run migrations against a production database without confirmation.

## Git Conventions
- Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`.
- Never commit directly to `main`. Branch pattern: `type/short-description`.
- One logical change per commit. Never commit `.env`, secrets, or `db.sqlite3`.

## Agent Behavior & Guardrails
- Before starting, list every file you intend to create or modify.
- If a change touches more than ~5 files, pause and confirm the plan first.
- Ask for approval before any destructive shell command (rm, DB drops, force push).
- When you change an API contract (URL, request, or response shape), explicitly note it in your summary so the **frontend repo can be updated to match** — call out the new/changed endpoint, method, and response shape.
- After a multi-step task, summarize what changed in 3–5 bullets and note any follow-up needed in the frontend.

---

## Agent Skills (invoke when the task matches)
> Install targeted skills only — do not bulk-install. Use the right skill for the task below.

- **`backend-architect`** — invoke when designing a new app, module, or major feature, or when deciding service/selector/model boundaries. Use it before writing a large new endpoint set.
- **`api-design-principles`** — invoke when adding or changing any endpoint. Use it to keep URLs, status codes, pagination, and response shapes consistent before finalizing the contract.
- **`security-auditor`** — **invoke before committing any change that touches auth, permissions, user input, file uploads, or environment/secret handling.** Treat its findings as blocking, not optional.
- **`python-scaffold`** (or your Django scaffolding skill) — invoke when creating a new app or standard module layout, to keep structure consistent.
- **`full-stack-feature`** orchestration — invoke for any feature that spans backend + frontend, so the endpoint and the frontend consumer are built as one coherent flow. After the backend half, hand off the new contract for the frontend update.

### Skill guardrails
- Run `security-auditor` before declaring any auth/endpoint/input task complete.
- Don't let an irrelevant skill auto-activate hijack a task — if a skill fires that doesn't fit, ignore it and proceed with the task as specified here.