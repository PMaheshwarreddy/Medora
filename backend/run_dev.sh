#!/usr/bin/env bash
# Starts the local Postgres (pgvector) container and the Medora API on :8100.
# Port 8000 is left alone because another service on this machine uses it.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "backend/.env is missing. Copy .env.example to .env and fill it in." >&2
  exit 1
fi
set -a; source .env; set +a

# The local container is only needed when the database URL points at this
# machine; a hosted database (for example Supabase) is used as-is.
db_host="$(python3 -c 'import os,urllib.parse as u; print(u.urlparse(os.environ["MEDORA_DATABASE_URL"]).hostname)')"
if [ "$db_host" != "localhost" ] && [ "$db_host" != "127.0.0.1" ]; then
  # 0.0.0.0: patients' phones on the same network reach the API (phone intake);
  # MEDORA_HOST=127.0.0.1 keeps it to this machine.
  exec uv run uvicorn app.main:app --host "${MEDORA_HOST:-0.0.0.0}" --port 8100 "$@"
fi

# The password is taken from MEDORA_DATABASE_URL so there is one source of truth.
db_password="$(python3 -c 'import os,urllib.parse as u; print(u.urlparse(os.environ["MEDORA_DATABASE_URL"]).password)')"

if ! docker ps -a --format '{{.Names}}' | grep -qx medora-db; then
  docker run -d --name medora-db \
    -e POSTGRES_USER=medora -e POSTGRES_PASSWORD="$db_password" -e POSTGRES_DB=medora \
    -p 127.0.0.1:5432:5432 -v medora_pgdata:/var/lib/postgresql/data \
    pgvector/pgvector:pg16 >/dev/null
else
  docker start medora-db >/dev/null
fi

until docker exec medora-db pg_isready -U medora -q; do sleep 0.5; done

# 0.0.0.0: patients' phones on the same network reach the API (phone intake);
  # MEDORA_HOST=127.0.0.1 keeps it to this machine.
  exec uv run uvicorn app.main:app --host "${MEDORA_HOST:-0.0.0.0}" --port 8100 "$@"
