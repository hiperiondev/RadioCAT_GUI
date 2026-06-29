#!/usr/bin/env python3
"""
Compile all locale/*/LC_MESSAGES/cat_gui.po -> cat_gui.mo
Requires: msgfmt (GNU gettext tools) in PATH.
"""
import subprocess, pathlib, sys

LOCALE_DIR = pathlib.Path(__file__).parent.parent / "locale"
errors = 0

for po in sorted(LOCALE_DIR.rglob("cat_gui.po")):
    mo = po.with_suffix(".mo")
    result = subprocess.run(["msgfmt", "-o", str(mo), str(po)], check=False)
    if result.returncode == 0:
        print(f"[compile] OK  {po.parent.parent.name}")
    else:
        print(f"[compile] ERR {po}", file=sys.stderr)
        errors += 1

sys.exit(1 if errors else 0)
