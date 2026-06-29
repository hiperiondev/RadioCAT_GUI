#!/usr/bin/env python3
"""
Extract translatable strings from cat_gui.py and generate/update cat_gui.pot.
Requires: xgettext (GNU gettext tools) in PATH.
"""
import subprocess, pathlib, sys

ROOT   = pathlib.Path(__file__).parent.parent
POT    = ROOT / "locale" / "cat_gui.pot"
SOURCE = ROOT / "cat_gui.py"

cmd = [
    "xgettext",
    "--language=Python",
    "--keyword=_",
    "--keyword=ngettext:1,2",
    "--keyword=pgettext:1c,2",
    "--from-code=UTF-8",
    "--add-comments=Translators:",
    "--output", str(POT),
    str(SOURCE),
]

result = subprocess.run(cmd, check=False)
if result.returncode == 0:
    print(f"[extract] Written: {POT}")
else:
    print("[extract] xgettext failed — is GNU gettext installed?", file=sys.stderr)
    sys.exit(1)
