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

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

mkdir -p "$WORKDIR/Payload"
cp -R "$APP_PATH" "$WORKDIR/Payload/KodiXboxRemote.app"
(
  cd "$WORKDIR"
  /usr/bin/zip -qry "$OUTPUT_IPA" Payload
)
mkdir -p "$(dirname "$OUTPUT_IPA")"
mv "$WORKDIR/$OUTPUT_IPA" "$OUTPUT_IPA"
echo "Created $OUTPUT_IPA"
