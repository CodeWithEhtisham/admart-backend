#!/usr/bin/env sh
# Run the local Docker stack as your own user (so files it writes stay yours).
#   ./dev.sh                 build if needed, start everything, follow the logs
#   ./dev.sh down | ps | logs worker | exec web python manage.py createsuperuser ...
set -e
cd "$(dirname "$0")"
export DOCKER_UID="$(id -u)" DOCKER_GID="$(id -g)"
if [ $# -eq 0 ]; then
  docker compose up --build -d
  docker compose ps
  exec docker compose logs -f --tail=20
fi
exec docker compose "$@"
