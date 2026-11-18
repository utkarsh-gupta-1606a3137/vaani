#!/bin/sh
# Pinned portable tools only. No profile changes, global install, or installer execution.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
JSON=0
for arg in "$@"; do [ "$arg" != --json ] || JSON=1; done
STAGE=; LOCK=; LOCK_OWNED=0
FAILURE='Bootstrap failed; inspect stderr and rerun setup.'
onexit() {
  code=$?
  [ -z "$STAGE" ] || rm -rf "$STAGE"
  [ "$LOCK_OWNED" != 1 ] || rm -rf "$LOCK"
  if [ "$code" != 0 ] && [ "$JSON" = 1 ]; then
    printf '{"status":"failed","code":%s,"message":"%s","stage":"bootstrap","job_directory":null,"details":{}}\n' "$code" "$FAILURE"
  fi
}
trap onexit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
  FAILURE='Vaani requires Apple silicon macOS.'; echo "$FAILURE" >&2; exit 4
fi
MACOS_MAJOR=$(/usr/bin/sw_vers -productVersion | cut -d . -f 1)
if [ "$MACOS_MAJOR" -lt 26 ]; then
  FAILURE='Pinned MLX wheels require Apple silicon macOS 26 or newer.'; echo "$FAILURE" >&2; exit 4
fi
# A warm installation uses the same advisory lock as synthesis before any mutation.
if [ "${VAANI_BOOTSTRAP_LOCKED:-0}" != 1 ]; then
  for candidate in "$ROOT/.runtime/envs/control/bin/python" "$ROOT/.runtime/python/bin/python3.12" "$ROOT/.runtime/python.previous/bin/python3.12"; do
    if [ -x "$candidate" ] && "$candidate" -c "import fcntl,pathlib,subprocess" >/dev/null 2>&1; then
      exec "$candidate" "$ROOT/scripts/bootstrap_lock.py" "$ROOT" "$@"
    fi
  done
fi
ALLOW=0
for arg in "$@"; do [ "$arg" != --allow-download ] || ALLOW=1; done
mkdir -p "$ROOT/.runtime/tools" "$ROOT/tmp" "$ROOT/.state" "$ROOT/cache/bootstrap"
LOCK="$ROOT/.state/bootstrap.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  FAILURE='Another bootstrap holds .state/bootstrap.lock; check whether it is active before removing an abandoned lock.'; echo "$FAILURE" >&2; exit 5
fi
LOCK_OWNED=1
get() {
  url=$1; digest=$2; archive=$3
  if [ -f "$archive" ] && [ "$(shasum -a 256 "$archive" | awk '{print $1}')" = "$digest" ]; then return; fi
  [ "$ALLOW" = 1 ] || { FAILURE='Bootstrap assets missing: run ./bin/vaani setup --allow-download.'; echo "$FAILURE" >&2; exit 4; }
  curl --proto '=https' --tlsv1.2 -fL --retry 3 --connect-timeout 30 --max-time 900 "$url" -o "$archive.partial" || exit 4
  [ "$(shasum -a 256 "$archive.partial" | awk '{print $1}')" = "$digest" ] || { FAILURE='Bootstrap download checksum mismatch.'; echo "$FAILURE" >&2; rm -f "$archive.partial"; exit 4; }
  mv "$archive.partial" "$archive"
}
UV_SHA=5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca
PY_SHA=2f11b8aa3726bdbd87dd9eb76568412faddf4f47e26913fa45d6a2e424972acd
UV_ARCHIVE="$ROOT/cache/bootstrap/uv-0.13.9-aarch64-apple-darwin.tar.gz"
PY_ARCHIVE="$ROOT/cache/bootstrap/cpython-3.12.16-20261110-aarch64-apple-darwin.tar.gz"
# Verify archive on every run; reinstalling known tools repairs altered/missing files.
get https://github.com/astral-sh/uv/releases/download/0.13.9/uv-aarch64-apple-darwin.tar.gz "$UV_SHA" "$UV_ARCHIVE"
get 'https://github.com/astral-sh/python-build-standalone/releases/download/20261110/cpython-3.12.16%2B20261110-aarch64-apple-darwin-install_only_stripped.tar.gz' "$PY_SHA" "$PY_ARCHIVE"
STAGE=$(mktemp -d "$ROOT/tmp/bootstrap.XXXXXX")

tar -xzf "$UV_ARCHIVE" -C "$STAGE"
install -m 755 "$STAGE/uv-aarch64-apple-darwin/uv" "$ROOT/.runtime/tools/uv"
tar -xzf "$PY_ARCHIVE" -C "$STAGE"
# Copy into project Python, preserving relative internal symlinks; no global links.
"$STAGE/python/bin/python3.12" -c 'import json,ssl,sqlite3,venv; import sys; assert sys.version_info[:3] == (3,12,16)'
# Publish only the completely extracted, self-checked interpreter tree.
if [ -d "$ROOT/.runtime/python" ]; then
  rm -rf "$ROOT/.runtime/python.previous"
  mv "$ROOT/.runtime/python" "$ROOT/.runtime/python.previous"
fi
mv "$STAGE/python" "$ROOT/.runtime/python"
printf '%s\n' "$PY_SHA" > "$ROOT/.runtime/python/.vaani-bootstrap-complete"
rm -rf "$ROOT/.runtime/python.previous"
"$ROOT/.runtime/tools/uv" --version >&2
"$ROOT/.runtime/python/bin/python3.12" --version >&2
