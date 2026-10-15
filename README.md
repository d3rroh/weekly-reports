# Weekly Outcomes Review

A standalone Django + MySQL application for preparing, tracking and presenting the weekly operational review to management.

It does not connect to any other system. Every metric, answer, comment and commitment is entered manually. The application stores them, works out period-over-period comparisons from saved records, keeps the history, and produces the Wednesday presentation and PDF.

## What it does

| Area | Summary |
|---|---|
| Reporting calendar | Periods run Wednesday 00:00 to Tuesday 23:59:59 in a configurable business timezone and are presented the following Wednesday. Every period is exactly seven days. A database check constraint enforces this. Each period has a stable ID such as `WR-2026-10-07`. |
| Weekly review editor | Three tabs: **Details** (metrics, follow-through, all 12 questions), **Comments** and **History**. Edits save automatically, and there is also an explicit Save Draft button. |
| Metrics | Average response time, SLA %, missed calls and CSAT %, all entered manually. A missing value stays `NULL` and is never stored as zero. Absolute change, relative % change and percentage-point differences are calculated, with an improved/deteriorated/no change label. When a value can't be calculated, the screen shows "Not available" or "No previous data". |
| 12 management questions | Structured sub-fields for each question. Questions 7 and 8 (team performance) can only be seen by users with confidential access. |
| Comments | 11 categories. A comment can be linked to the whole report, a metric, a question or a commitment. Visibility is either *Management Report* or *Internal Only*, and the server enforces it. Every edit and deletion keeps a revision. |
| Commitments tracker | Three outcomes per week with measurable criteria. Progress is followed up in the next report, overdue and blocked items are flagged, completion requires evidence, and every status change is recorded. |
| History and trends | Search and compare any two reports. Chart.js trend charts use saved values only, and gaps show where data is missing. |
| Presentation and PDF | A read-only presentation view with print styling and PDF export, both built from the same context. Internal-only comments are always left out. |
| Workflow | Draft → Ready for Review → Submitted. An 8-item checklist shows completion %. Submitting an incomplete report needs explicit confirmation. Reopening a submitted report needs correction permission and a reason, and the submitted version is kept as a snapshot. |
| Security | Roles plus per-user permission flags, login throttling, CSRF, a strict CSP, secure cookies, an audit log, and server-side authorisation on every view. |

## Requirements

- Python 3.11+
- MySQL 8.0.16+ (check constraints are enforced from 8.0.16)
- MySQL client development headers to build `mysqlclient` (Debian/Ubuntu: `sudo apt install default-libmysqlclient-dev build-essential pkg-config`)

## Development setup

```bash
# 1. Python environment
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# 2. Database (as a MySQL admin user)
mysql -u root -p <<'SQL'
CREATE DATABASE weekly_outcomes CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'weekly_outcomes_app'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL PRIVILEGES ON weekly_outcomes.* TO 'weekly_outcomes_app'@'localhost';
-- the test runner creates/drops test_weekly_outcomes:
GRANT ALL PRIVILEGES ON test_weekly_outcomes.* TO 'weekly_outcomes_app'@'localhost';
SQL

# 3. Configuration
cp .env.example .env
#   edit .env: set DJANGO_SECRET_KEY, DB_* values, DJANGO_DEBUG=true and
#   SECURE_COOKIES=false for local http, EMAIL_BACKEND=...console.EmailBackend

# 4. Schema
python manage.py migrate
python manage.py createcachetable      # shared cache used for login throttling

# 5. Initial administrator
python manage.py createsuperuser       # superusers automatically get the Administrator role

# 6. Run
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in. Then:

1. **Settings** → set the business timezone (and organisation name).
2. **User Management** → add reviewers and grant permissions.
3. **New Weekly Review** → the latest completed period is preselected.

### Running the tests

```bash
python manage.py test apps            # against MySQL (needs CREATE privilege on test_<DB_NAME>)
DB_ENGINE=sqlite python manage.py test apps   # quick run without MySQL
```

The suite has 105 tests. They cover:

- the reporting calendar: boundaries, month and year ends, leap years, DST and timezone changes
- metric calculations and validation
- the draft → submit → reopen workflow and snapshots
- comment visibility and history
- commitment carry-forward, overdue detection and history
- authentication, throttling and permissions
- PDF export content: correct period and values, management comments included, internal comments excluded

## Roles and permissions

| Permission | Administrator | Reviewer (default) | Configurable per reviewer |
|---|---|---|---|
| View reports, trends, history | ✓ | ✓ | — |
| Create/edit drafts, comments, commitments | ✓ | ✓ | `can_edit_reports` |
| See Q7/Q8, other users' internal comments, restricted reports | ✓ | ✗ | `can_view_confidential` |
| Reopen/correct submitted reports, edit comments on them | ✓ | ✗ | `can_correct_submitted` |
| Manage users and application settings | ✓ | ✗ | — |

Reviewers can always see their own internal-only comments. Management-facing outputs (the presentation and the PDF) never include internal-only comments, whoever is viewing.

## Project layout

```
config/                 settings (env-driven), urls, wsgi
apps/accounts/          custom User (role + permission flags), login throttling, user management
apps/core/              AppSettings, AuditEvent, reporting-period service (periods.py), middleware
apps/reviews/
  models.py             ReportingPeriod, WeeklyReview, WeeklyMetrics, ReviewResponse, Priority,
                        Commitment, CommitmentHistory, Comment, CommentRevision, ReportRevision
  questions.py          the 12 questions and their structured sub-fields (single definition)
  services/             metrics comparison, workflow/checklist, editor save, access rules,
                        commitments, presentation context (shared by screen + PDF), trends
  views/                reviews/editor, comments, commitments, dashboard/history/trends
  tests/                automated tests
templates/, static/     Django templates, CSS, JS (Chart.js vendored locally — no CDN)
deploy/                 gunicorn config, systemd unit, nginx site, container entrypoint
Dockerfile              production container image (see DEPLOYMENT.md, "Container")
.github/workflows/      CI: tests on MySQL 8, builds and publishes the image to GHCR
scripts/                backup.sh, restore.sh
docs/                   DEPLOYMENT.md, BACKUP_RECOVERY.md
```

## Design notes

- **One calendar service.** All date arithmetic lives in `apps/core/periods.py`. Periods store explicit start, end and presentation dates, so changing the timezone later never alters an existing report.
- **Partial saves.** Autosave writes every field that validates and returns errors for the ones that don't. A single bad entry never throws away the rest of the form.
- **Historical integrity.** Each submission and each reopen stores a full JSON snapshot (`ReportRevision`). For a submitted report, the presentation shows each previous commitment's status as it was recorded at submission time, using its status history.
- **No fabricated data.** Dashboards and charts read saved records only and show proper empty states when there is nothing to show.

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for production and [docs/BACKUP_RECOVERY.md](docs/BACKUP_RECOVERY.md) for backups.
