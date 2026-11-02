#!/usr/bin/env sh
# One time: copy your local SQLite data (db.sqlite3) into the Docker Postgres database.
# The Docker database is emptied first. Run from the backend folder with the stack up (./dev.sh).
set -e
cd "$(dirname "$0")/.."
DUMP=.docker-import.json
.venv/bin/python manage.py dumpdata --natural-foreign --natural-primary \
  -e contenttypes -e auth.permission -e admin.logentry -e sessions -e token_blacklist \
  --output "$DUMP"
./dev.sh exec web python manage.py flush --noinput
./dev.sh exec web python manage.py loaddata "$DUMP"
rm -f "$DUMP"
echo "Imported. Media files are shared already (media/ is mounted into the containers)."
