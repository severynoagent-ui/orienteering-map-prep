#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z "${ORIMAP_GOOGLE_API:-}" ]]; then
  echo "Skipping Drive upload test: ORIMAP_GOOGLE_API is not set" >&2
  exit 0
fi
OUT_ROOT="${TMPDIR:-/tmp}/orimap-drive-test-projects"
CACHE_ROOT="${TMPDIR:-/tmp}/orimap-drive-test-cache"
PID="test-drive-cleanup-$(date +%Y%m%d-%H%M%S)"
/usr/bin/python3 -m orimap_prep.cli   --input-gpx tests/fixtures_rajec_tiny.gpx   --project-id "$PID"   --project-root "$OUT_ROOT"   --cache-root "$CACHE_ROOT"   --drive-folder-name "Test Drive cleanup $PID"   --contours 25   --products dem,hillshade,contours   --drive-upload   --cleanup-local-after-drive   --json
test ! -e "$OUT_ROOT/$PID"
test ! -e "$OUT_ROOT/$PID.zip"
