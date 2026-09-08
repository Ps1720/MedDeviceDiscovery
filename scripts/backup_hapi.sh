#!/usr/bin/env bash
# Back up the HAPI Postgres volume — the only copy of the seeded patients and
# every device documented since. `docker compose down -v` destroys it.
#
#   ./scripts/backup_hapi.sh                 -> ./backups/hapi-<timestamp>.sql.gz
#   ./scripts/backup_hapi.sh /path/to/dir
#
# Restore:
#   docker compose up -d hapi-db
#   gunzip -c backups/hapi-<timestamp>.sql.gz \
#     | docker compose exec -T hapi-db psql -U hapi -d hapi
#   docker compose up -d
#
# A logical dump (pg_dump) is used rather than a tar of the volume: it restores
# into a fresh volume and survives a Postgres image upgrade.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-$REPO/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$OUT_DIR/hapi-$STAMP.sql.gz"

cd "$REPO"

if ! docker compose ps --status running --services 2>/dev/null | grep -qx "hapi-db"; then
  echo "hapi-db is not running. Start it first:  docker compose up -d hapi-db" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
echo "Dumping HAPI database..."
docker compose exec -T hapi-db pg_dump -U hapi -d hapi --clean --if-exists \
  | gzip -9 > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
echo "Wrote $OUT ($SIZE)"

# Sanity-check: a dump that restores nothing is worse than no dump.
if [ "$(gunzip -c "$OUT" | head -c 200 | grep -c 'PostgreSQL database dump')" -eq 0 ]; then
  echo "WARNING: dump does not look like a pg_dump file — verify before relying on it" >&2
  exit 1
fi

PATIENTS=$(gunzip -c "$OUT" | grep -c "^INSERT INTO public.hfj_resource" || true)
echo "Contains $(gunzip -c "$OUT" | wc -l | tr -d ' ') lines. Verified as a PostgreSQL dump."

echo
echo "Existing backups:"
ls -lh "$OUT_DIR" | tail -5
