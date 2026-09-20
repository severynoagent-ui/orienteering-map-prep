#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
OUT_ROOT="${TMPDIR:-/tmp}/orimap-test-projects"
CACHE_ROOT="${TMPDIR:-/tmp}/orimap-test-cache"
/usr/bin/python3 -m py_compile orimap_prep/*.py
/usr/bin/python3 -m orimap_prep.cli --input-gpx tests/fixtures_rajec_tiny.gpx --project-id test-rajec-tiny --project-root "$OUT_ROOT" --cache-root "$CACHE_ROOT" --contours 5,25 --products dem,hillshade,contours --no-drive-upload --json
