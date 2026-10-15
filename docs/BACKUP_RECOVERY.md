# Backup and recovery

All application data lives in the MySQL database: reports, metrics, answers, comments, commitments, history, audit log, users and settings. Nothing is stored on disk except static assets, which can be rebuilt from the code.

## What to back up

| Item | How |
|---|---|
| MySQL database | `scripts/backup.sh` (daily) |
| `.env` | Copy it to your secrets manager or vault when it changes. It contains credentials, so never put it in the database backup location without encryption. |
| Application code | Version control or release archives |

## Taking backups

```bash
scripts/backup.sh /var/backups/weekly-outcomes
```

The script:

- reads the `DB_*` settings from `.env`
- passes credentials through a temporary `0600` option file, so they never appear in the process list
- runs `mysqldump --single-transaction` for a consistent snapshot without locking tables
- gzips the output and sets the file to mode 600
- checks that the archive is readable and contains the reports table
- deletes backups older than `RETENTION_DAYS`, which defaults to 30

To schedule it daily at 02:15, add this to the `weekly-outcomes` user's crontab (`sudo crontab -u weekly-outcomes -e`):

```
15 2 * * * /opt/weekly-outcomes/scripts/backup.sh /var/backups/weekly-outcomes >> /var/log/weekly-outcomes-backup.log 2>&1
```

Copy backups off the server as well, for example with `rsync` or object storage that has versioning. A backup kept only on the same machine does not protect against losing that machine.

## Testing a backup (do this monthly)

Restore into a scratch database without touching production:

```bash
F=/var/backups/weekly-outcomes/weekly_outcomes-YYYYMMDD-HHMMSS.sql.gz
mysql -u root -p -e "CREATE DATABASE restore_check CHARACTER SET utf8mb4;"
zcat "$F" | mysql -u root -p restore_check
mysql -u root -p -e "SELECT COUNT(*) FROM restore_check.reviews_weeklyreview; DROP DATABASE restore_check;"
```

## Restoring production

1. Stop the application: `sudo systemctl stop weekly-outcomes`
2. Take a backup of the current state, even if it is damaged: `scripts/backup.sh /var/backups/weekly-outcomes/pre-restore`
3. Restore. The script asks you to type `RESTORE` before it continues:
   ```bash
   scripts/restore.sh /var/backups/weekly-outcomes/weekly_outcomes-YYYYMMDD-HHMMSS.sql.gz
   ```
4. Apply any migrations newer than the backup: `.venv/bin/python manage.py migrate`
5. Recreate the cache table if it is missing: `.venv/bin/python manage.py createcachetable`
6. Start the application: `sudo systemctl start weekly-outcomes`
7. Sign in. Check that the latest report, its comments and the commitments tracker look right.
8. Record the restore (date, backup file, reason) in your operations log.

## Recovering from mistakes without a restore

| Situation | Remedy |
|---|---|
| A submitted report needs a correction | A user with *correct submitted* permission uses **Reopen for correction**. The submitted version is kept as a revision under History → Submitted versions. |
| A comment was edited or deleted by mistake | Earlier text is kept in `CommentRevision`. Edit the comment page to see previous versions. A deleted comment is soft-deleted and can be undeleted in the Django admin by clearing `deleted_at`. |
| A commitment status was changed by mistake | Set it back from the commitment's page. The full history stays in place. |
| You need to know who changed what | Settings → **Audit log** (administrators only). |

## Lost administrator access

```bash
cd /opt/weekly-outcomes
sudo -u weekly-outcomes .venv/bin/python manage.py changepassword <username>
# or create a new one:
sudo -u weekly-outcomes .venv/bin/python manage.py createsuperuser
```
