# Bulk Certificate Generator (Django + Django REST Framework)

Backend API that accepts a list of recipients, generates a PDF certificate for each from
one predefined template, tracks progress, and lets you download the results.

**Stack:** Python 3.10+, Django, Django REST Framework, SQLite (default), ReportLab (PDF).

## Setup

```bash
python -m venv .venv &&  .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
```

## Run

```bash
python manage.py runserver
```

Open http://127.0.0.1:8000/api/jobs/ — DRF's **browsable API**. It shows a form at the bottom:
paste JSON into the "Content" box and press POST. Every URL returned in `links` is clickable.

| Env var | Default | Purpose |
|---|---|---|
| `CERT_STORAGE_DIR` | `./generated_certificates` | Where PDFs are written |
| `MAX_RECIPIENTS` | `1000` | Max recipients per job |
| `DJANGO_SECRET_KEY` / `DJANGO_DEBUG` | dev defaults | Set properly for any real deployment |

## Run tests

```bash
python manage.py test
```

(22 tests; they use a temporary DB and storage directory. A traceback printed during the run
is the expected log line from the deliberate "generation failure" test.)

## API

All endpoints are under `/api/`.

### Submit a request — `POST /api/jobs/` → `202 Accepted`

```bash
curl -X POST http://127.0.0.1:8000/api/jobs/ -H "Content-Type: application/json" -d '{
  "certificate": {
    "title": "Certificate of Completion",
    "course_name": "Python Bootcamp",
    "issued_by": "Acme Academy",
    "issue_date": "2026-09-30"
  },
  "recipients": [
    {"name": "Asha Patil", "email": "asha@example.com"},
    {"name": "Rahul Deshmukh"},
    {"name": "", "email": "blank-name@example.com"}
  ]
}'
```

`title` and `issue_date` are optional (defaults: "Certificate of Completion", today);
recipient `email` is optional.

### Check progress — `GET /api/jobs/{job_id}/`

Returns `status`, `total`, `succeeded`, `failed`, `pending`, `progress_percent`, timestamps and `links`.
Status: `queued` → `processing` → `completed` | `completed_with_errors` | `failed`.

### Per-recipient results — `GET /api/jobs/{job_id}/certificates/`

Filter with `?status=pending|success|failed`; paginate with `?limit=&offset=` (default 100, max 1000).
Each item has `position` (index in your list), `status`, `error` and `download_url` (success only).

### Retrieve

* One PDF: `GET /api/certificates/{certificate_id}/download/` (409 if pending, 404 if failed)
* ZIP of everything generated so far: `GET /api/jobs/{job_id}/download/`

### Also

* `GET /api/jobs/` — list jobs, newest first (paginated).
* `python manage.py resume_jobs` — finish jobs interrupted by a restart (see below).
* `/admin/` — Django admin for Job/Certificate (create a user with `createsuperuser`).

## Design decisions

**Asynchronous processing.** A job can hold up to 1000 recipients, so `POST` validates, stores
the job and returns `202` immediately; generation runs in a background thread
(`services.enqueue`) and the client polls the job. I chose a thread over Celery because it
needs no broker or worker process for this scope. Each thread closes its own DB connection when done.
Trade-off: work lives in the web process. If the server restarts mid-job, the job is left
`processing`; run `python manage.py resume_jobs` to finish it. This is safe because only
certificates still `pending` are processed, so nothing is duplicated (run it when no server is
actively working on that job). At larger scale, `services.process_job(job_id)` can be moved
unchanged into a Celery task.

**Two levels of validation (DRF serializers).**
* *Request-level* problems (empty list, missing `course_name`/`issued_by`, more than
  `MAX_RECIPIENTS`) reject the whole request with `400` and DRF's standard error body.
* *Recipient-level* problems (blank/missing name, malformed email, wrong type, unsupported
  characters) do **not** reject the request. `RecipientSerializer` validates each entry on its
  own; a bad one is stored as a `failed` certificate with a readable `error` (and the name/email
  that was sent, so it can be identified), while valid recipients are still generated.

**Failure isolation.** Each certificate is generated inside its own `try/except` and saved
individually, so one error is recorded on that row and the rest continue; saving per
certificate also makes progress visible live. PDFs are written to a temp file then renamed,
so a crash never leaves a half-written file marked as success.

**Counts are derived, not stored.** `succeeded/failed/pending` come from one aggregate query
over certificate rows, so they can't drift from the real results.

**Template.** One landscape A4 certificate drawn with ReportLab (title, name, course, date, issuer).

## Known limitations

* Names are limited to Latin characters (ReportLab's built-in Helvetica can't render e.g.
  Devanagari); such names are rejected per recipient with a clear message. Supporting them
  needs a bundled Unicode font plus complex-script shaping.
* No authentication — anyone with a job ID can read it (IDs are random UUIDs). Add DRF
  authentication/permissions before real use.
* SQLite is for development; use PostgreSQL for concurrent production use.
* Generated files are never cleaned up automatically.
