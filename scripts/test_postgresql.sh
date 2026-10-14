#!/usr/bin/env bash
# Disposable native PostgreSQL cluster. Never uses or clears the application DB.
set -Eeuo pipefail
TEST_PYTHON=${1:-python3}
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
PGBIN=$("$TEST_PYTHON" "$ROOT/scripts/linux_host.py" --pg-bindir)
export PATH="$PGBIN:$PATH"
pguser=$(if [[ $EUID == 0 ]]; then echo postgres; else id -un; fi)
cluster=$(mktemp -d /tmp/aster-pg-test.XXXXXXXX)
pg_run(){ if [[ $EUID == 0 ]]; then runuser -u postgres -- "$@"; else "$@"; fi; }
cleanup(){ pg_run "$PGBIN/pg_ctl" -D "$cluster/data" -m immediate stop >/dev/null 2>&1 || true; rm -rf "$cluster"; }
trap cleanup EXIT
if [[ $EUID == 0 ]]; then chown postgres:postgres "$cluster"; fi
pg_run "$PGBIN/initdb" -D "$cluster/data" --auth=trust --no-locale -E UTF8 >/dev/null
pg_run "$PGBIN/pg_ctl" -D "$cluster/data" -l "$cluster/server.log" -o "-k $cluster -c listen_addresses='' -c fsync=off" -w start >/dev/null
pg_run "$PGBIN/createdb" --no-password -h "$cluster" -p 5432 -U "$pguser" aster_test </dev/null
pg_run "$PGBIN/psql" --no-password -h "$cluster" -p 5432 -U "$pguser" -d aster_test -X -v ON_ERROR_STOP=1 -c "CREATE EXTENSION vector" </dev/null
cd "$ROOT"
ASTER_TEST_DATABASE_URL="postgresql://$pguser@/aster_test?host=$cluster&port=5432" "$TEST_PYTHON" -m pytest -q --maxfail=1 tests </dev/null
