#!/usr/bin/env bash
# Deploy the backend on the server. Run by CI over SSH (or by hand):
#   bash /srv/admart/backend/deploy/deploy.sh staging
# Everything is inside main() so bash reads the whole file before `git reset`
# replaces it with the new version.
set -euo pipefail

main() {
  local branch="${1:-staging}"
  local app_dir service api_host
  app_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  service="${SERVICE:-admart-backend}"
  cd "$app_dir"

  # Self-heal a CRLF .env (saved by a Windows editor). A trailing \r on the
  # ALLOWED_HOSTS line makes the health check below send an invalid Host header,
  # which gunicorn rejects with "Invalid HTTP Header: 'HOST'" -> a false 400 that
  # fails an otherwise-good deploy. .env is untracked, so `git reset --hard` never
  # rewrites it; strip CRLF here so one deploy permanently normalizes it.
  if [ -f .env ]; then sed -i 's/\r$//' .env; fi


  # The server copy has no local edits: .env, media/, private_media/ are untracked.
  git fetch --quiet origin "$branch"
  git checkout --quiet -B "$branch" "origin/$branch"
  git reset --quiet --hard "origin/$branch"

  .venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt
  .venv/bin/python manage.py migrate --noinput
  .venv/bin/python manage.py collectstatic --noinput --verbosity 0
  .venv/bin/python manage.py check --deploy --fail-level ERROR
  sudo systemctl restart "$service"

  # Health check through gunicorn, using the first ALLOWED_HOSTS entry as Host.
  # Strip all whitespace/CR (a CRLF .env would otherwise smuggle a bad Host header
  # that gunicorn rejects with "Invalid HTTP Header: 'HOST'") and fall back to
  # loopback so a blank or edited value can never fail an otherwise-good deploy.
  api_host="$(grep -E '^ALLOWED_HOSTS=' .env | head -1 | cut -d= -f2 | cut -d, -f1 | tr -d '[:space:]' || true)"
  : "${api_host:=127.0.0.1}"
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null -H "Host: ${api_host}" http://127.0.0.1:8001/api/credits/plans; then
      echo "Deployed $(git rev-parse --short HEAD) on ${branch}"
      return 0
    fi
    sleep 1
  done
  echo "Backend did not become healthy" >&2
  sudo systemctl status "$service" --no-pager | tail -20 >&2
  return 1
}

main "$@"
