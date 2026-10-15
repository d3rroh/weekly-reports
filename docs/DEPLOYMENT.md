# Production deployment

This guide covers Ubuntu/Debian with MySQL 8, Gunicorn behind Nginx, and TLS. The paths assume the app lives in `/opt/weekly-outcomes` and runs as the `weekly-outcomes` system user.

## 1. System packages

```bash
sudo apt update
sudo apt install python3 python3-venv python3-dev build-essential pkg-config \
     default-libmysqlclient-dev mysql-server nginx
```

## 2. Database

```bash
sudo mysql <<'SQL'
CREATE DATABASE weekly_outcomes CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'weekly_outcomes_app'@'localhost' IDENTIFIED BY '<strong-generated-password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES, LOCK TABLES
  ON weekly_outcomes.* TO 'weekly_outcomes_app'@'localhost';
SQL
```

`DROP`, `CREATE`, `ALTER` and `INDEX` are needed for migrations. If you prefer, run migrations with a separate privileged account and give the runtime user only DML privileges.

## 3. Application

```bash
sudo useradd --system --home /opt/weekly-outcomes --shell /usr/sbin/nologin weekly-outcomes
sudo mkdir -p /opt/weekly-outcomes && sudo chown weekly-outcomes: /opt/weekly-outcomes
# copy the project into /opt/weekly-outcomes (git clone, rsync, or release archive), then:
cd /opt/weekly-outcomes
sudo -u weekly-outcomes python3 -m venv .venv
sudo -u weekly-outcomes .venv/bin/pip install -r requirements.txt
```

Create `/opt/weekly-outcomes/.env` from `.env.example`:

```bash
sudo -u weekly-outcomes cp .env.example .env
sudo chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # paste as DJANGO_SECRET_KEY
```

Required production values:

| Variable | Value |
|---|---|
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | long random value, unique per environment |
| `DJANGO_ALLOWED_HOSTS` | your hostname(s), comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://your-hostname` |
| `DB_*` | database credentials from step 2 |
| `SECURE_COOKIES` | `true` |
| `USE_X_FORWARDED_PROTO` | `true` (Nginx terminates TLS) |
| `SECURE_HSTS_SECONDS` | `31536000` once HTTPS is confirmed working |
| `EMAIL_*` | SMTP settings, needed for password-reset emails |

Initialise:

```bash
sudo -u weekly-outcomes .venv/bin/python manage.py migrate
sudo -u weekly-outcomes .venv/bin/python manage.py createcachetable
sudo -u weekly-outcomes .venv/bin/python manage.py collectstatic --noinput
sudo -u weekly-outcomes .venv/bin/python manage.py createsuperuser
sudo -u weekly-outcomes .venv/bin/python manage.py check --deploy
```

`check --deploy` will report `SECURE_HSTS_INCLUDE_SUBDOMAINS` and `SECURE_HSTS_PRELOAD` as warnings. Enable those only if every subdomain of your domain is served over HTTPS.

## 4. Gunicorn (systemd)

```bash
sudo cp deploy/weekly-outcomes.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now weekly-outcomes
sudo systemctl status weekly-outcomes
```

Gunicorn listens on `127.0.0.1:8010` (see `deploy/gunicorn.conf.py`).

## 5. Nginx and TLS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/weekly-outcomes
sudo sed -i 's/reports.example.com/your-hostname/g' /etc/nginx/sites-available/weekly-outcomes
sudo ln -s /etc/nginx/sites-available/weekly-outcomes /etc/nginx/sites-enabled/
sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx -d your-hostname
sudo nginx -t && sudo systemctl reload nginx
```

Nginx serves `/static/` directly from `staticfiles/`. WhiteNoise also serves those files, so the app still works if Nginx is not used.

## 6. After deployment

1. Sign in as the administrator. Go to **Settings** and set the **business timezone** before you create any reports.
2. Add users in **User Management**. Grant *confidential access* only to people who may read team-performance notes.
3. Schedule backups (see [BACKUP_RECOVERY.md](BACKUP_RECOVERY.md)).

## Container (alternative to steps 1, 3 and 4)

The `Dockerfile` builds a production image: Python 3.12 slim, dependencies compiled in a separate build stage, static files collected at build time and served by WhiteNoise, Gunicorn on port 8000, running as a non-root user (uid 10001). On start the entrypoint runs `migrate` and `createcachetable`; set `RUN_MIGRATIONS=false` to skip this (for example when several replicas start at once and you migrate separately).

### GitHub Actions

`.github/workflows/container.yml` runs on pushes and pull requests to `main`, on tags like `v1.4.0`, and on demand:

1. **Test**: runs `manage.py check`, a missing-migrations check and the full test suite against a MySQL 8.4 service container.
2. **Build**: builds the image (cached between runs) and smoke-tests it: the container must start, apply migrations and serve the sign-in page and stylesheet.
3. **Publish** (not on pull requests): pushes to the GitHub Container Registry as `ghcr.io/<owner>/<repo>`, tagged with the branch name, short commit SHA, `latest` for `main`, and `1.4.0` / `1.4` for version tags. It includes provenance and an SBOM.

No secrets need configuring; the workflow uses the built-in `GITHUB_TOKEN`. New GHCR packages are private. To pull from a server, run `docker login ghcr.io` with a personal access token that has `read:packages`, or make the package public in the repository's package settings.

### Running the image

Keep the same variables as `.env.example` in an env file on the server, with `DB_HOST` pointing at your MySQL server, then:

```bash
docker run -d --name weekly-outcomes --restart unless-stopped \
  --env-file /etc/weekly-outcomes.env \
  -e GUNICORN_FORWARDED_ALLOW_IPS='*' \
  -p 127.0.0.1:8010:8000 \
  ghcr.io/<owner>/<repo>:latest
```

Keep Nginx (step 5) in front for TLS. It already proxies to `127.0.0.1:8010`. `GUNICORN_FORWARDED_ALLOW_IPS='*'` is safe here only because the port is bound to localhost, so Nginx is the only client. Optional: `GUNICORN_WORKERS` (default: up to 4).

Create the first administrator inside the container:

```bash
docker exec -it weekly-outcomes python manage.py createsuperuser
```

Backups work as before. `scripts/backup.sh` runs on the host against MySQL, and the container holds no state.

To upgrade, back up, then `docker pull` the new tag and recreate the container. Migrations run on start.

## Upgrading

```bash
cd /opt/weekly-outcomes
scripts/backup.sh /var/backups/weekly-outcomes           # always back up first
# update code
sudo -u weekly-outcomes .venv/bin/pip install -r requirements.txt
sudo -u weekly-outcomes .venv/bin/python manage.py migrate
sudo -u weekly-outcomes .venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart weekly-outcomes
```

## Security checklist

- [ ] `DJANGO_DEBUG=false`, unique `DJANGO_SECRET_KEY`, `.env` is mode 600 and not in version control
- [ ] HTTPS only. `SECURE_COOKIES=true`, `USE_X_FORWARDED_PROTO=true`, HSTS enabled
- [ ] The database user has privileges on `weekly_outcomes` only, and MySQL is not exposed publicly
- [ ] Backups are scheduled and a restore has been tested
- [ ] Only trusted users have administrator or confidential access
- [ ] The Django admin at `/django-admin/` is only for emergency data repair. Normal administration happens in the app.

## Notes on behaviour

- **Login throttling.** After 5 failed attempts for a username, or 20 from one IP, within 15 minutes, sign-in is blocked for the rest of the window. Both values can be changed with `LOGIN_THROTTLE_*`. The counters are kept in the database cache table, so they work across Gunicorn workers.
- **Sessions** expire after 8 hours (`SESSION_COOKIE_AGE`) and when the browser closes.
- **Content-Security-Policy.** Every script and stylesheet is served from the app itself (Chart.js is vendored in `static/vendor/`). The app makes no external network calls.
