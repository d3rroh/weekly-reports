# Gunicorn configuration for Weekly Outcomes Review.
# Usage: gunicorn -c deploy/gunicorn.conf.py config.wsgi:application
# Defaults suit the systemd + Nginx setup; the container image overrides
# them through the GUNICORN_* environment variables.
import multiprocessing
import os

bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8010")
workers = int(os.environ.get("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() * 2 + 1)))
timeout = 60            # PDF export can take a few seconds
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "127.0.0.1")
