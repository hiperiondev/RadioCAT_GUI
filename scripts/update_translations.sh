#!/usr/bin/env bash
# Full translation update cycle:
#   1. Extract new strings into .pot
#   2. Merge .pot into each existing .po (preserving fuzzy matches)
#   3. Compile all .po -> .mo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCALE_DIR="$PROJECT_DIR/locale"

cd "$PROJECT_DIR"

echo "=== Extracting strings ==="
python i18n/extract.py

echo "=== Merging into existing .po files ==="
for po in "$LOCALE_DIR"/*/LC_MESSAGES/cat_gui.po; do
    lang=$(basename "$(dirname "$(dirname "$po")")")
    echo "  Merging $lang ..."
    msgmerge --update --no-fuzzy-matching "$po" "$LOCALE_DIR/cat_gui.pot"
done

echo "=== Compiling .mo files ==="
python i18n/compile.py

echo "=== Done ==="
