# Progress

## Status

Implemented and validated.

## Completed

- Added backend `DispatchSchedule` model and Alembic migration.
- Added schedule CRUD/run endpoints under `/api/dispatch`.
- Added scheduler tick that scans DB-backed schedules.
- Added frontend API client types/functions.
- Added dispatch settings UI for creating, editing, deleting, and running schedules.
- Added i18n keys and job type labels.
- Updated `.env.example` and README.

## Validation

- `.\.venv\Scripts\python.exe -m compileall backend\app\dispatch backend\app\jobs\scheduler.py backend\app\config.py backend\app\db\models.py backend\tests\test_dispatch.py backend\tests\test_database_migrations.py`
- `$env:PYTHONPATH='backend'; .\.venv\Scripts\python.exe -m pytest -p no:cacheprovider backend\tests\test_dispatch.py backend\tests\test_database_migrations.py`
- `npm run lint` from `frontend`
- `npm exec tsc -- --noEmit --incremental false` from `frontend`
- `git diff --check` produced only existing CRLF conversion warnings.

## Decisions

- Store the full dispatch preview request in `request_json` so future template/radar options remain scheduleable without schema churn.
- Use a per-schedule run key of local date + send time + timezone for idempotency.
- Manual run uses a `manual:` run key so it does not consume the scheduled minute.
