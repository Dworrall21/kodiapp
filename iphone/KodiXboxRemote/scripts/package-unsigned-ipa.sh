#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-}"
OUTPUT_IPA="${2:-KodiXboxRemote-unsigned.ipa}"

if [[ -z "$APP_PATH" ]]; then
  echo "usage: $0 /path/to/KodiXboxRemote.app [output.ipa]" >&2
  exit 2
fi

if [[ ! -d "$APP_PATH" ]]; then
  echo "app bundle not found: $APP_PATH" >&2
  exit 1
fi

OUTPUT_DIR="$(dirname "$OUTPUT_IPA")"
OUTPUT_NAME="$(basename "$OUTPUT_IPA")"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
OUTPUT_ABS="$OUTPUT_DIR/$OUTPUT_NAME"

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$WORKDIR/Payload"
cp -R "$APP_PATH" "$WORKDIR/Payload/KodiXboxRemote.app"
(
  cd "$WORKDIR"
  /usr/bin/zip -qry "$OUTPUT_ABS" Payload
)
echo "Created $OUTPUT_ABS"
