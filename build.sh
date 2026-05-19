#!/usr/bin/env bash
set -euo pipefail

# ──────────────────────────────────────────────────
# build.sh — Automated Kodi addon build & deploy
# ──────────────────────────────────────────────────
# Builds the addon zip from addon/, updates repo_static/
# metadata, and deploys to gh-pages.
# ──────────────────────────────────────────────────

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
ADDON_SRC="$REPO_ROOT/addon"
REPO_STATIC="$REPO_ROOT/repo_static"
GH_PAGES_WT="${GH_PAGES_WORKTREE:-$REPO_ROOT/.gh-pages-worktree}"
GH_PAGES_BRANCH="gh-pages"
COMMIT_MSG="${COMMIT_MSG:-"chore: auto-build and deploy"}"
NO_PUSH="${NO_PUSH:-}"

cd "$REPO_ROOT"

# ── Read addon metadata ───────────────────────────
ADDON_LINE=$(grep -oP '<addon\s+[^>]*>' "$ADDON_SRC/addon.xml" | head -1)
ADDON_ID=$(echo "$ADDON_LINE" | grep -oP '(?<=id=")[^"]+')
ADDON_VERSION=$(echo "$ADDON_LINE" | grep -oP '(?<=version=")[^"]+')
ADDON_NAME=$(echo "$ADDON_LINE" | grep -oP '(?<=name=")[^"]+')

echo "=== Building $ADDON_ID v$ADDON_VERSION ==="

ZIP_NAME="${ADDON_ID}-${ADDON_VERSION}.zip"
ZIP_PATH="$REPO_STATIC/$ADDON_ID/$ZIP_NAME"

mkdir -p "$REPO_STATIC/$ADDON_ID"

# ── Build the addon zip ───────────────────────────
BUILD_TMP="$(mktemp -d)"
trap 'rm -rf "$BUILD_TMP"' EXIT

mkdir -p "$BUILD_TMP/$ADDON_ID"
cp -a "$ADDON_SRC"/* "$BUILD_TMP/$ADDON_ID/"

# Ensure LF line endings for all text files
find "$BUILD_TMP/$ADDON_ID" -type f \( \
  -name '*.py' -o -name '*.xml' -o -name '*.txt' -o -name '*.md' -o \
  -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.json' -o \
  -name '*.yml' -o -name '*.yaml' -o -name '*.cfg' -o -name '*.conf' -o \
  -name '*.ini' -o -name '*.sh' -o -name '*.rst' -o -name '*.nfo' -o \
  -name '*.svg' \
\) -exec sed -i 's/\r$//' {} \;

cd "$BUILD_TMP"
rm -f "$ZIP_PATH"
zip -r "$ZIP_PATH" "$ADDON_ID/" -x ".*" -x "*/__pycache__/*" -x "*.pyc"
cd "$REPO_ROOT"

echo "  ✓ Zip created: $ZIP_PATH"
echo "  Size: $(du -h "$ZIP_PATH" | cut -f1)"

# ── Update addons.xml via Python helper ────────────
python3 << PYEOF
import os, re

addons_xml_path = "$REPO_STATIC/addons.xml"
addon_id = "$ADDON_ID"

with open("$ADDON_SRC/addon.xml") as f:
    addon_entry = f.read().strip()

if os.path.exists(addons_xml_path) and os.path.getsize(addons_xml_path) > 0:
    with open(addons_xml_path) as f:
        content = f.read()
    content = re.sub(
        r'<addon\s+id="' + re.escape(addon_id) + r'"[^>]*>.*?</addon>',
        '',
        content,
        flags=re.DOTALL,
    )
    if '</addons>' in content:
        content = content.replace('</addons>', addon_entry + '\n</addons>')
    else:
        content += '\n' + addon_entry + '\n</addons>\n'
else:
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<addons>\n' + addon_entry + '\n</addons>\n'

lines = [l for l in content.split('\n')]
cleaned = []
prev_blank = False
for l in lines:
    if l.strip() == '':
        if not prev_blank and cleaned:
            cleaned.append('')
        prev_blank = True
    else:
        cleaned.append(l)
        prev_blank = False

with open(addons_xml_path, 'w') as f:
    f.write('\n'.join(cleaned) + '\n')

print("  ✓ Updated: " + addons_xml_path)
PYEOF

# ── Compute MD5 ───────────────────────────────────
printf '%s' "$(cat "$REPO_STATIC/addons.xml" | md5sum | cut -d' ' -f1)" > "$REPO_STATIC/addons.xml.md5"
echo "  ✓ MD5: $(cat "$REPO_STATIC/addons.xml.md5")"

# ── Generate per-addon index.html ─────────────────
ADDON_DIR_INDEX="$REPO_STATIC/$ADDON_ID/index.html"
cat > "$ADDON_DIR_INDEX" << HTMLEOF
<!DOCTYPE html>
<html><head><title>$ADDON_ID</title></head>
<body>
<h1>$ADDON_ID</h1>
<ul>
HTMLEOF

for f in $(ls "$REPO_STATIC/$ADDON_ID/"*.zip 2>/dev/null | sort -V); do
  fname="$(basename "$f")"
  echo "  <li><a href=\"$fname\">$fname</a></li>" >> "$ADDON_DIR_INDEX"
done

cat >> "$ADDON_DIR_INDEX" << 'HTMLEOF'
</ul>
</body></html>
HTMLEOF
echo "  ✓ Updated: $ADDON_DIR_INDEX"

# ── Generate repo root index.html ─────────────────
cat > "$REPO_STATIC/index.html" << HTMLEOF
<!DOCTYPE html>
<html><head><title>Kodi Xbox Proxy Repository</title></head><body>
<h1>Kodi Xbox Proxy Repository</h1>
<ul>
<li><a href="addons.xml">addons.xml</a></li>
<li><a href="addons.xml.md5">addons.xml.md5</a></li>
HTMLEOF

for addon_dir in "$REPO_STATIC"/*/; do
  [ -d "$addon_dir" ] || continue
  addon_slug="$(basename "$addon_dir")"
  echo "<li><a href=\"$addon_slug/\">$addon_slug/</a> Kodi add-on</li>" >> "$REPO_STATIC/index.html"
done

cat >> "$REPO_STATIC/index.html" << 'HTMLEOF'
</ul>
</body></html>
HTMLEOF
echo "  ✓ Updated: $REPO_STATIC/index.html"

echo ""
echo "=== Build complete. Artifacts ==="
echo "  Zip:       $ZIP_PATH"
echo "  addons.xml: $REPO_STATIC/addons.xml"
echo "  MD5:        $REPO_STATIC/addons.xml.md5"

# ── Deploy to gh-pages ────────────────────────────
echo ""
echo "=== Deploying to $GH_PAGES_BRANCH ==="

if [ -d "$GH_PAGES_WT" ]; then
  echo "  Worktree exists at $GH_PAGES_WT"
else
  echo "  Creating worktree at $GH_PAGES_WT"
  if git show-ref --verify "refs/remotes/origin/$GH_PAGES_BRANCH" >/dev/null 2>&1; then
    git worktree add "$GH_PAGES_WT" "origin/$GH_PAGES_BRANCH" 2>/dev/null || \
    git worktree add "$GH_PAGES_WT" "$GH_PAGES_BRANCH" 2>/dev/null || {
      echo "  Re-creating worktree..."
      git worktree prune
      git worktree add "$GH_PAGES_WT" "origin/$GH_PAGES_BRANCH"
    }
  else
    echo "  Creating orphan gh-pages branch..."
    git worktree add --orphan "$GH_PAGES_WT" "$GH_PAGES_BRANCH"
  fi
fi

rsync -a --delete "$REPO_STATIC/" "$GH_PAGES_WT/" --exclude='.git'

cd "$GH_PAGES_WT"

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
if [ "$CURRENT_BRANCH" != "$GH_PAGES_BRANCH" ]; then
  git checkout "$GH_PAGES_BRANCH" 2>/dev/null || \
  git checkout -b "$GH_PAGES_BRANCH"
fi

git add -A
if git diff --cached --quiet; then
  echo "  No changes on gh-pages - nothing to commit."
else
  # Ensure git identity is set
  git config user.name >/dev/null 2>&1 || git config user.name "Kodiapp Builder"
  git config user.email >/dev/null 2>&1 || git config user.email "builder@kodiapp.local"
  git commit -m "$COMMIT_MSG"
  echo "  ✓ Committed to $GH_PAGES_BRANCH"
fi

cd "$REPO_ROOT"

# ── Commit main branch changes ────────────────────
echo ""
echo "=== Committing main branch ==="

git add "$REPO_STATIC/" build.sh

if git diff --cached --quiet; then
  echo "  No changes on main - nothing to commit."
else
  git config user.name >/dev/null 2>&1 || git config user.name "Kodiapp Builder"
  git config user.email >/dev/null 2>&1 || git config user.email "builder@kodiapp.local"
  git commit -m "$COMMIT_MSG"
  echo "  ✓ Committed to main"
fi

# ── Push ──────────────────────────────────────────
if [ -n "$NO_PUSH" ]; then
  echo "  NO_PUSH is set - skipping push."
else
  echo ""
  echo "=== Pushing ==="
  git push origin main
  cd "$GH_PAGES_WT"
  git push origin "$GH_PAGES_BRANCH"
  cd "$REPO_ROOT"
  echo "  ✓ Both branches pushed."
fi

echo ""
echo "=== Done! $ADDON_ID v$ADDON_VERSION built and deployed ==="