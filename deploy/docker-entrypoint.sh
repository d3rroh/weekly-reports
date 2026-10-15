#!/bin/sh
# Container entrypoint: optionally apply migrations, then run the command.
set -e

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    python manage.py migrate --noinput
    python manage.py createcachetable
fi

exec "$@"
