#!/usr/bin/env bash
# Back up the database (pg_dump) and uploaded files (media/ + private_media/).
# Runs nightly via admart-backup.timer; safe to run by hand:  bash deploy/backup.sh
#
# Env overrides: BACKUP_DIR (default /var/backups/admart), KEEP_DAYS (14),
# BACKUP_REMOTE (optional rclone destination, e.g. "b2:admart-backups/staging").
# .env is NOT backed up here: it holds every secret. Keep a copy of it (especially
# SECRET_KEY and SOCIAL_TOKEN_ENCRYPTION_KEY) in your password manager instead.
set -euo pipefail

main() {
  local app_dir backup_dir keep_days stamp dest
  app_dir="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
  backup_dir="${BACKUP_DIR:-/var/backups/admart}"
  keep_days="${KEEP_DAYS:-14}"

  env_get() {  # read KEY from .env without sourcing it (values may contain shell characters)
    grep -E "^$1=" "$app_dir/.env" | tail -1 | cut -d= -f2- | sed -E "s/^['\"](.*)['\"]$/\1/"
  }

  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  dest="$backup_dir/$stamp"
  umask 077                      # backups contain customer data: owner-only
  mkdir -p "$dest"

  PGPASSWORD="$(env_get POSTGRES_PASSWORD)" pg_dump \
    --format=custom --no-owner \
    --host="$(env_get POSTGRES_HOST || true)" --port="$(env_get POSTGRES_PORT || true)" \
    --username="$(env_get POSTGRES_USER)" --dbname="$(env_get POSTGRES_DB)" \
    --file="$dest/db.dump"

  local dirs=()
  for d in media private_media; do [ -d "$app_dir/$d" ] && dirs+=("$d"); done
  if [ "${#dirs[@]}" -gt 0 ]; then
    tar -C "$app_dir" -czf "$dest/files.tar.gz" "${dirs[@]}"
  fi

  (cd "$dest" && sha256sum -- * > SHA256SUMS)

  if [ -n "${BACKUP_REMOTE:-}" ]; then
    rclone copy "$dest" "$BACKUP_REMOTE/$stamp"
  fi

  find "$backup_dir" -mindepth 1 -maxdepth 1 -type d -mtime +"$keep_days" -exec rm -rf {} +
  echo "Backup written to $dest"
}

main "$@"
