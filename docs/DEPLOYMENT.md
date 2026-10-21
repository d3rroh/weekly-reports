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
3. **Publish** (not on pull requests): pushes to Docker Hub as `docker.io/<DOCKERHUB_USERNAME>/weekly-reports`, tagged with the branch name, short commit SHA (`sha-1a2b3c4`), `latest` for `main`, and `1.4.0` / `1.4` for version tags. It includes provenance and an SBOM.

The workflow needs two repository secrets: `DOCKERHUB_USERNAME`, and `DOCKERHUB_TOKEN` (a Docker Hub access token with Read & Write scope).

### Running the image

Keep the same variables as `.env.example` in an env file on the server, with `DB_HOST` pointing at your MySQL server, then:

```bash
docker run -d --name weekly-outcomes --restart unless-stopped \
  --env-file /etc/weekly-outcomes.env \
  -e GUNICORN_FORWARDED_ALLOW_IPS='*' \
  -p 127.0.0.1:8010:8000 \
  docker.io/d3rroh/weekly-reports:latest
```

Keep Nginx (step 5) in front for TLS. It already proxies to `127.0.0.1:8010`. `GUNICORN_FORWARDED_ALLOW_IPS='*'` is safe here only because the port is bound to localhost, so Nginx is the only client. Optional: `GUNICORN_WORKERS` (default: up to 4).

Create the first administrator inside the container:

```bash
docker exec -it weekly-outcomes python manage.py createsuperuser
```

Backups work as before. `scripts/backup.sh` runs on the host against MySQL, and the container holds no state.

To upgrade, back up, then `docker pull` the new tag and recreate the container. Migrations run on start.

## Kubernetes (k3s)

`deploy/k3s/weekly-reports.yaml` runs the site at `https://reports.derroh.co.ke` in the `weekly-reports` namespace: MySQL 8.4 on a 10 GiB Longhorn volume (storage class `longhorn`), the app behind ingress-nginx, a Let's Encrypt certificate from cert-manager, and a nightly `mysqldump` at 02:15 Nairobi time kept for 14 days. Migrations run in an init container before each new app pod starts. The app pod runs as uid 10001 on a read-only filesystem.

The domain is proxied through Cloudflare in **Flexible** SSL mode: Cloudflare serves HTTPS to visitors, redirects HTTP to HTTPS at the edge, and talks plain HTTP to the cluster. For that reason the Ingress sets `nginx.ingress.kubernetes.io/ssl-redirect: "false"` and Django has `SECURE_SSL_REDIRECT: "false"`. Do not turn either redirect on while Cloudflare is in Flexible mode, or every request loops with a 308. If you move Cloudflare to Full (strict), the origin certificate is used and both can be turned back on.

1. Install ingress-nginx if the cluster doesn't have it. Add a proxied (orange cloud) Cloudflare `A` record for `reports.derroh.co.ke` pointing at the node, and make sure ports 80 and 443 are open (Let's Encrypt validates over port 80).
2. Install cert-manager (once per cluster) and the issuer:
   ```bash
   kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.18.2/cert-manager.yaml
   kubectl -n cert-manager rollout status deploy/cert-manager-webhook
   kubectl apply -f deploy/k3s/cluster-issuer.yaml
   ```
3. Create the namespace and secret. Copy the template to `weekly-reports-secret.yaml`, which is git-ignored, and fill in the values (the template lists the commands that generate them):
   ```bash
   kubectl create namespace weekly-reports
   cp deploy/k3s/weekly-reports-secret.example.yaml deploy/k3s/weekly-reports-secret.yaml
   $EDITOR deploy/k3s/weekly-reports-secret.yaml
   kubectl apply -f deploy/k3s/weekly-reports-secret.yaml
   ```
   MySQL reads the passwords only when it first creates its data volume. Changing them in the secret later does not change them in the database.
4. Deploy and create the first administrator:
   ```bash
   kubectl apply -f deploy/k3s/weekly-reports.yaml
   kubectl -n weekly-reports rollout status deploy/web
   kubectl -n weekly-reports exec -it deploy/web -- python manage.py createsuperuser
   kubectl -n weekly-reports get certificate        # READY becomes True within a minute or two
   ```

Settings live in the `weekly-reports` ConfigMap at the top of the manifest. Password-reset email goes to the pod log (`kubectl -n weekly-reports logs deploy/web`) until you switch `EMAIL_BACKEND` to SMTP and fill in the `EMAIL_*` values.

**Upgrading.** The manifest pins an image by commit (`sha-…` tag), so `kubectl rollout undo` always returns to a known build. To release a new commit, run a backup (below), then:

```bash
kubectl -n weekly-reports set image deploy/web migrate=docker.io/d3rroh/weekly-reports:sha-<commit> web=docker.io/d3rroh/weekly-reports:sha-<commit>
```

and update the tag in the manifest to match.

**Backups.** Dumps are written to the `backups` Longhorn volume. Longhorn replicates it across nodes, but it still lives in the same cluster as the database, so copy dumps off the cluster too (or configure a Longhorn backup target). To run one now, copy one out, and restore one:

```bash
kubectl -n weekly-reports create job --from=cronjob/mysql-backup backup-manual
kubectl -n weekly-reports run backup-shell --rm -i --restart=Never --image=busybox:1.36 \
  --overrides='{"spec":{"volumes":[{"name":"b","persistentVolumeClaim":{"claimName":"backups"}}],"containers":[{"name":"backup-shell","image":"busybox:1.36","command":["sh","-c","ls -t /b/*.sql.gz | head -1 | xargs cat"],"volumeMounts":[{"name":"b","mountPath":"/b"}]}]}}' \
  > latest-backup.sql.gz
kubectl -n weekly-reports exec -i statefulset/mysql -- sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" weekly_outcomes' < <(zcat weekly_outcomes-YYYYMMDD-HHMMSS.sql.gz)
```

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
