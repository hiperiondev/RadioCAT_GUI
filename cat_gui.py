#!/usr/bin/env python3
"""
cat_gui.py
"""
import argparse, array, cmath, collections, json, logging, math, os, queue, socket, struct, sys, threading, time, traceback, datetime
import tkinter as tk
from tkinter import messagebox

# ── Optional NumPy (used for FFT when available) ──────────────────────────────
try:
    import numpy as _np
except ImportError:
    _np = None

# ── TOML config support ───────────────────────────────────────────────────────
try:
    import tomllib as _tomllib          # Python 3.11+
except ImportError:
    try:
        import tomli as _tomllib        # pip install tomli
    except ImportError:
        _tomllib = None

_GUI_CONFIG_NAME = "cat_gui.toml"

_GUI_CONFIG_DEFAULTS = {
    "display": {
        "bg":            "dark",
        "full_screen":   False,
        "scale":         0,
        "disable_scale": False,
        "freq_font":     "",
        "gui_font":      "",
    },
    "connection": {
        "host": "",
        "port": 0,          # 0 = not set; both host and port must be non-empty/non-zero
        "autoconnect": False,  # if true, connect on startup and hide the host/port/connect row
    },
    "audio": {
        "mic":                       -1,   # -1 = system default
        "speaker":                   -1,
        "disable_soundcard_select":  False,
    },
}

_GUI_CONFIG_TEMPLATE = """\
# CAT GUI configuration
# CLI flags override these values at runtime without modifying this file.
# Use --config PATH to load a file from a non-default location.

[display]
bg = "dark"           # "light" or "dark"
full_screen = false   # start in full-screen mode
scale = 0             # HiDPI scale level, -5 to 5
disable_scale = false # hide the +/- scale controls (set an explicit scale above too)
freq_font = ""        # path to TTF/OTF font for frequency digits  (empty = system default)
gui_font = ""         # path to TTF/OTF font for all other GUI text (empty = system default)

[connection]
# Leave host empty and port 0 to show the GUI connection fields.
# Both must be filled, with autoconnect = true, to connect automatically
# on startup (this also hides the host/port/connect row entirely).
host = ""
port = 0
autoconnect = false

[audio]
# Device indices from --audio-list; -1 means use the system default.
# Both mic and speaker must be set together (or both left at -1).
mic = -1
speaker = -1
disable_soundcard_select = false
"""

def _parse_simple_toml(text):
    """Minimal TOML parser (strings, ints, bools, flat [sections]) used when
    neither tomllib nor tomli is available."""
    def _strip_comment(raw):
        """Return *raw* with any trailing TOML comment removed.
        A '#' is only a comment delimiter when it appears outside a
        double-quoted string; e.g.  bg = "#FFECD6"  must survive intact."""
        in_quote = False
        for i, ch in enumerate(raw):
            if ch == '"':
                in_quote = not in_quote
            elif ch == '#' and not in_quote:
                return raw[:i].strip()
        return raw.strip()

    result = {}
    section = result
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            sec_name = line[1:-1].strip()
            section = result.setdefault(sec_name, {})
            continue
        if '=' in line:
            k, _, v = line.partition('=')
            k = k.strip(); v = v.strip()
            if v.startswith('"') and v.endswith('"'):
                try:
                    section[k] = json.loads(v)   # handles \", \\, \n, etc.
                except json.JSONDecodeError:
                    section[k] = v[1:-1]         # fall back for malformed input
            elif v == 'true':
                section[k] = True
            elif v == 'false':
                section[k] = False
            else:
                try:    section[k] = int(v)
                except ValueError:
                    try: section[k] = float(v)
                    except ValueError: section[k] = v
    return result

def _load_gui_config(path):
    """Return the parsed TOML dict, or {} on any error."""
    try:
        if _tomllib is not None:
            with open(path, "rb") as f:
                return _tomllib.load(f)
        else:
            with open(path, "r", encoding="utf-8") as f:
                return _parse_simple_toml(f.read())
    except Exception as e:
        print(f"[config] WARNING: could not read {path}: {e}")
        return {}

_GUI_CONFIG_KEY_ORDER = {
    "display": ["bg", "full_screen", "scale", "disable_scale", "freq_font", "gui_font"],
    "connection": ["host", "port", "autoconnect"],
    "audio": ["mic", "speaker", "disable_soundcard_select"],
}
_GUI_CONFIG_SECTION_ORDER = ["display", "connection", "audio"]

_GUI_CONFIG_HEADER = (
    "# CAT GUI configuration\n"
    "# CLI flags override these values at runtime without modifying this file.\n"
    "# Use --config PATH to load a file from a non-default location."
)

# Inline "key = value  # comment" trailers for the [display] section.
_GUI_CONFIG_KEY_COMMENTS = {
    "bg":            '"light" or "dark"',
    "full_screen":   "start in full-screen mode",
    "scale":         "HiDPI scale level, -5 to 5",
    "disable_scale": "hide the +/- scale controls (set an explicit scale above too)",
    "freq_font":     "path to TTF/OTF font for frequency digits  (empty = system default)",
    "gui_font":      "path to TTF/OTF font for all other GUI text (empty = system default)",
}

# Block comments shown once, above the key=value lines, for other sections.
_GUI_CONFIG_SECTION_COMMENTS = {
    "connection":
        "# Leave host empty and port 0 to show the GUI connection fields.\n"
        "# Both must be filled, with autoconnect = true, to connect automatically\n"
        "# on startup (this also hides the host/port/connect row entirely).",
    "audio":
        "# Device indices from --audio-list; -1 means use the system default.\n"
        "# Both mic and speaker must be set together (or both left at -1).",
}


def _fmt_toml_value_gui(v):
    """Render a Python value back into TOML literal syntax."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    return str(v)


def _merge_gui_config_with_defaults(cfg):
    """Fill in any section/key missing from cfg using _GUI_CONFIG_DEFAULTS.

    Returns (merged, added): merged is a complete config dict (every default
    section/key present, existing values always win) and added is an ordered
    list of "section.key" strings that were absent from cfg and had to be
    filled in with their default value.
    """
    merged = {}
    added = []
    for sec, sec_defaults in _GUI_CONFIG_DEFAULTS.items():
        _cfg_sec_raw = cfg.get(sec, {})
        cfg_sec = _cfg_sec_raw if isinstance(_cfg_sec_raw, dict) else {}
        merged_sec = {}
        for key, default_val in sec_defaults.items():
            if key in cfg_sec:
                merged_sec[key] = cfg_sec[key]
            else:
                merged_sec[key] = default_val
                added.append(f"{sec}.{key}")
        merged[sec] = merged_sec
    return merged, added


def _render_gui_config(cfg):
    """Render a complete, well-formed TOML document from a fully-merged config
    dict, reproducing the same comments/layout as _GUI_CONFIG_TEMPLATE."""
    lines = [_GUI_CONFIG_HEADER]
    for sec in _GUI_CONFIG_SECTION_ORDER:
        lines.append("")
        lines.append(f"[{sec}]")
        block_comment = _GUI_CONFIG_SECTION_COMMENTS.get(sec)
        if block_comment:
            lines.append(block_comment)
        sec_vals = cfg.get(sec, {})
        for key in _GUI_CONFIG_KEY_ORDER[sec]:
            val = sec_vals.get(key, _GUI_CONFIG_DEFAULTS[sec][key])
            line = f"{key} = {_fmt_toml_value_gui(val)}"
            trailer = _GUI_CONFIG_KEY_COMMENTS.get(key) if sec == "display" else None
            if trailer:
                line += f"  # {trailer}"
            lines.append(line)
    return "\n".join(lines) + "\n"


def _ensure_gui_config(path):
    """Create the config file with defaults if it does not exist, then load it.

    If the file already exists but is missing a parameter known to this
    version of the GUI (i.e. one with a corresponding CLI flag/default), the
    file is corrected in place: the missing parameter is added at its default
    value and rewritten to disk, so the config keeps itself up to date as new
    options are introduced in later versions.
    """
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_GUI_CONFIG_TEMPLATE)
            print(f"[config] Created default config: {path}")
        except Exception as e:
            print(f"[config] WARNING: could not write default config: {e}")
        return _load_gui_config(path)

    _cfg = _load_gui_config(path)
    merged, added = _merge_gui_config_with_defaults(_cfg)
    if added:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_render_gui_config(merged))
            print(f"[config] Corrected {path}: added missing parameter(s) with "
                  f"default value(s) — {', '.join(added)}")
        except Exception as e:
            print(f"[config] WARNING: {path} is missing parameter(s) "
                  f"({', '.join(added)}) but could not be corrected: {e} — "
                  f"using built-in defaults for this run")
    return merged

# ── CLI argument parsing ─────────────────────────────────────────────────────
def _parse_args():
    # ── Phase 1: extract --config before full parsing ─────────────────────────
    _pre = argparse.ArgumentParser(add_help=False)
    _pre.add_argument('--config', default=None)
    _pre_args, _ = _pre.parse_known_args()
    _config_path = _pre_args.config or os.path.join(os.getcwd(), _GUI_CONFIG_NAME)

    # ── Load / create TOML config ─────────────────────────────────────────────
    _cfg  = _ensure_gui_config(_config_path)
    _disp = _cfg.get("display",    {})
    _conn = _cfg.get("connection", {})
    _aud  = _cfg.get("audio",      {})
    _D    = _GUI_CONFIG_DEFAULTS

    # Effective defaults = config value falling back to built-in default
    _def_bg     = _disp.get("bg",            _D["display"]["bg"])
    _def_full   = bool(_disp.get("full_screen",   _D["display"]["full_screen"]))
    _def_scale  = int(_disp.get("scale",          _D["display"]["scale"]))
    _def_dscale = bool(_disp.get("disable_scale", _D["display"]["disable_scale"]))
    _def_ffont  = _disp.get("freq_font", _D["display"]["freq_font"]) or None
    _def_gfont  = _disp.get("gui_font",  _D["display"]["gui_font"])  or None
    _def_host   = _conn.get("host", _D["connection"]["host"]) or None
    _raw_port   = _conn.get("port", _D["connection"]["port"])
    _def_port   = int(_raw_port) if _raw_port else None
    _def_autoconnect = bool(_conn.get("autoconnect", _D["connection"]["autoconnect"]))
    _raw_mic    = _aud.get("mic",     _D["audio"]["mic"])
    _def_mic    = None if int(_raw_mic) == -1 else int(_raw_mic)
    _raw_spk    = _aud.get("speaker", _D["audio"]["speaker"])
    _def_spk    = None if int(_raw_spk) == -1 else int(_raw_spk)
    _def_dsc    = bool(_aud.get("disable_soundcard_select",
                                _D["audio"]["disable_soundcard_select"]))

    # ── Phase 2: full argument parse (SUPPRESS = "not given on CLI") ──────────
    ap = argparse.ArgumentParser(description='CAT GUI Interface', add_help=True)
    ap.add_argument('--config', metavar='PATH', default=None,
                    help=f'Path to TOML config file (default: ./{_GUI_CONFIG_NAME})')
    ap.add_argument('--freq-font', metavar='PATH', default=argparse.SUPPRESS,
                    help='TTF/OTF font file for LO/Tune frequency digit displays')
    ap.add_argument('--gui-font',  metavar='PATH', default=argparse.SUPPRESS,
                    help='TTF/OTF font file for all other GUI elements')
    ap.add_argument('--scale', metavar='INT', type=int, default=argparse.SUPPRESS,
                    help='Initial scale level (-5..5, default 0)')
    ap.add_argument('--bg', choices=['light','dark'], default=argparse.SUPPRESS,
                    help='Background theme: "light" sets all interface '
                         'backgrounds to #FFECD6, "dark" keeps the default colours')
    ap.add_argument('--full-screen', action='store_true', default=argparse.SUPPRESS,
                    help='Start in full-screen mode')
    ap.add_argument('--resolution', metavar='WxH', default=argparse.SUPPRESS,
                    help='Initial window size in pixels, e.g. 1280x720')
    ap.add_argument('--disable-scale', action='store_true', default=argparse.SUPPRESS,
                    help='Hide the HiDPI scale +/- controls and scale level number '
                         '(requires --scale to also be specified on the command line)')
    ap.add_argument('--host', metavar='HOST', default=argparse.SUPPRESS,
                    help='Server hostname or IP to connect to (must be used together with --port)')
    ap.add_argument('--port', metavar='PORT', type=int, default=argparse.SUPPRESS,
                    help='Server port to connect to (must be used together with --host)')
    ap.add_argument('--autoconnect', action='store_true', default=argparse.SUPPRESS,
                    help='Connect to the server automatically on startup. Requires '
                         'host and port to be set, either via --host/--port or in '
                         'the config file. Hides the host/port/connect row in the GUI.')
    ap.add_argument('--audio-list', action='store_true', default=False,
                    help='List all audio input/output devices on this system, with the '
                         'same index numbers shown in the GUI Soundcard dialog, then exit. '
                         'Use the indices with --audio-mic / --audio-speaker.')
    ap.add_argument('--audio-mic', metavar='INDEX', type=int, default=argparse.SUPPRESS,
                    help='Select the microphone (input) device by index (see --audio-list). '
                         'Must be used together with --audio-speaker.')
    ap.add_argument('--audio-speaker', metavar='INDEX', type=int, default=argparse.SUPPRESS,
                    help='Select the speaker/headphone (output) device by index (see --audio-list). '
                         'Must be used together with --audio-mic.')
    ap.add_argument('--disable-soundcard-select', action='store_true',
                    default=argparse.SUPPRESS,
                    help='Hide the Soundcard button in the GUI, preventing audio device '
                         'selection from being changed at runtime.')
    _raw = ap.parse_args()

    # ── Merge: CLI overrides config; config overrides built-in default ────────
    args = argparse.Namespace()
    args.config    = _config_path
    args.freq_font = _raw.freq_font if hasattr(_raw, 'freq_font') else _def_ffont
    args.gui_font  = _raw.gui_font  if hasattr(_raw, 'gui_font')  else _def_gfont
    args.scale     = _raw.scale     if hasattr(_raw, 'scale')     else _def_scale
    args.scale_explicit = hasattr(_raw, 'scale')   # True only when --scale given on CLI
    args.bg        = _raw.bg        if hasattr(_raw, 'bg')        else _def_bg
    args.full_screen              = _raw.full_screen  if hasattr(_raw, 'full_screen')  else _def_full
    args.disable_scale            = _raw.disable_scale if hasattr(_raw, 'disable_scale') else _def_dscale

    # --resolution WxH
    if hasattr(_raw, 'resolution'):
        _res = _raw.resolution
        try:
            _rw, _rh = _res.lower().split('x')
            args.resolution = (int(_rw), int(_rh))
            if args.resolution[0] <= 0 or args.resolution[1] <= 0:
                raise ValueError
        except (ValueError, AttributeError):
            ap.error(f'--resolution must be WIDTHxHEIGHT in pixels, e.g. 1280x720 (got: {_res!r})')
    else:
        args.resolution = None
    args.disable_soundcard_select = _raw.disable_soundcard_select \
                                    if hasattr(_raw, 'disable_soundcard_select') else _def_dsc
    args.audio_list = _raw.audio_list   # one-shot flag; intentionally not stored in config

    _cli_host = hasattr(_raw, 'host')
    _cli_port = hasattr(_raw, 'port')
    args.host = _raw.host if _cli_host else _def_host
    args.port = _raw.port if _cli_port else _def_port

    _cli_autoconnect = hasattr(_raw, 'autoconnect')
    args.autoconnect = _raw.autoconnect if _cli_autoconnect else _def_autoconnect

    _cli_mic = hasattr(_raw, 'audio_mic')
    _cli_spk = hasattr(_raw, 'audio_speaker')
    args.audio_mic     = _raw.audio_mic     if _cli_mic else _def_mic
    args.audio_speaker = _raw.audio_speaker if _cli_spk else _def_spk

    # ── Validations ───────────────────────────────────────────────────────────
    if args.audio_list:
        # Strip --config and its value, then ensure nothing else is present
        _skip = False
        _other = []
        for _a in sys.argv[1:]:
            if _skip:             _skip = False; continue
            if _a == '--config':  _skip = True;  continue
            if _a.startswith('--config='): continue
            if _a == '--audio-list':       continue
            _other.append(_a)
        if _other:
            ap.error('--audio-list must be used alone, without other flags')

    if hasattr(_raw, 'disable_scale') and not hasattr(_raw, 'scale'):
        # --disable-scale on CLI requires --scale on CLI (config values don't satisfy this)
        ap.error('--disable-scale requires --scale to also be specified')

    if (args.host is None) != (args.port is None):
        if _cli_host or _cli_port:
            # At least one side was given on the CLI — report it as a CLI mistake
            ap.error('--host and --port must be specified together')
        else:
            # Both sides came from the TOML file — report the config file as the source
            print(f"[config] ERROR: 'host' and 'port' must both be set together in "
                  f"{_config_path}", file=sys.stderr)
            sys.exit(1)
    if (args.audio_mic is None) != (args.audio_speaker is None):
        if _cli_mic or _cli_spk:
            ap.error('--audio-mic and --audio-speaker must be specified together')
        else:
            print(f"[config] ERROR: 'mic' and 'speaker' must both be set together in "
                  f"{_config_path}", file=sys.stderr)
            sys.exit(1)
    if args.autoconnect and (args.host is None or args.port is None):
        if _cli_autoconnect:
            ap.error('--autoconnect requires host and port to be set, either via '
                      '--host/--port on the command line or in the [connection] '
                      f'section of {_config_path}')
        else:
            print(f"[config] ERROR: 'autoconnect' is true in {_config_path} but "
                  f"'host'/'port' are not both set (in the config file or via "
                  f"--host/--port)", file=sys.stderr)
            sys.exit(1)
    return args

# _ARGS is intentionally None at import time; main() sets it via _parse_args()
# so that importing this module as a library never consumes sys.argv or calls
# sys.exit().  All code that reads _ARGS lives inside functions/methods which
# are only ever reached after main() has initialised it.
_ARGS = None

# ── TTF path (same directory as this script) ──────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_TTF        = os.path.join(_SCRIPT_DIR, 'morgenta_regular.ttf')

# ── Font family names resolved after Tk is up ────────────────────────────────
_FREQ_FONT_FAMILY = None   # font family for frequency digits (LO/Tune)
_GUI_FONT_FAMILY  = None   # font family for all other GUI text

def _load_custom_fonts(root):
    """Register custom TTF/OTF font files with Tk.

    Works without any third-party packages on Linux/macOS/Windows by:
      1. Copying the font file into ~/.local/share/fonts/  (Linux/macOS) or
         C:/Windows/Fonts/ equivalent and refreshing the OS font cache so Tk's
         underlying fontconfig/FreeType stack picks it up.
      2. Deriving the PostScript family name from the file using fonttools if
         available, otherwise falling back to filename-stem heuristics.
      3. Verifying the family actually appears in tkinter.font.families()
         after a forced Tk update; if not, logging a clear warning.

    On Windows the font is registered in the user font directory via
    ctypes / AddFontResourceEx so no admin rights are needed.
    """
    global _FREQ_FONT_FAMILY, _GUI_FONT_FAMILY
    import tkinter.font as tkfont
    import shutil, subprocess, platform

    _USER_FONT_DIR_LINUX  = os.path.expanduser("~/.local/share/fonts")
    _USER_FONT_DIR_MAC    = os.path.expanduser("~/Library/Fonts")

    def _install_font_linux(path):
        os.makedirs(_USER_FONT_DIR_LINUX, exist_ok=True)
        dst = os.path.join(_USER_FONT_DIR_LINUX, os.path.basename(path))
        if not os.path.exists(dst) or os.path.getmtime(path) > os.path.getmtime(dst):
            shutil.copy2(path, dst)
        try:
            subprocess.run(["fc-cache", "-f", _USER_FONT_DIR_LINUX],
                           check=False, capture_output=True, timeout=10)
        except Exception:
            pass

    def _install_font_mac(path):
        os.makedirs(_USER_FONT_DIR_MAC, exist_ok=True)
        dst = os.path.join(_USER_FONT_DIR_MAC, os.path.basename(path))
        if not os.path.exists(dst) or os.path.getmtime(path) > os.path.getmtime(dst):
            shutil.copy2(path, dst)

    def _install_font_windows(path):
        import ctypes
        from ctypes import wintypes
        # FR_PRIVATE (0x10) | FR_NOT_ENUM (0x20) — private, no admin needed
        gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi.AddFontResourceExW(path, 0x10 | 0x20, None)

    def _family_from_fonttools(path):
        """Return the PostScript family name embedded in the font file."""
        try:
            from fontTools.ttLib import TTFont
            tt = TTFont(path, fontNumber=0)
            name_table = tt["name"]
            # nameID 1 = Family name, 16 = Preferred family
            for nid in (16, 1):
                rec = name_table.getName(nid, 3, 1, 0x0409)  # Windows/Unicode/EN
                if rec is None:
                    rec = name_table.getName(nid, 1, 0, 0)   # Mac
                if rec:
                    return rec.toUnicode().strip()
        except Exception:
            pass
        return None

    def _family_from_fc(path):
        """Ask fontconfig for the family name (Linux/macOS only)."""
        try:
            r = subprocess.run(
                ["fc-query", "--format=%{family}\n", path],
                capture_output=True, text=True, timeout=5)
            lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
            if lines:
                # fc-query may return comma-separated or newline-separated names;
                # take the first token
                return lines[0].split(",")[0].strip()
        except Exception:
            pass
        return None

    def _family_from_stem(path):
        stem = os.path.splitext(os.path.basename(path))[0]
        return stem.replace("_", " ").replace("-", " ").title()

    def _wait_for_family(root, family):
        """Return True if family is visible to Tk after one event-loop flush.

        _register_appfont() calls FcConfigAppFontAddFile() / CTFontManager which
        mutate the live in-process font config synchronously — the family is
        either present immediately after root.update() drains any pending Tk
        redraws, or polling with time.sleep() won't help.  Removing the sleep
        loop eliminates up to 720 ms of blocking startup time.
        """
        root.update()
        return family in set(tkfont.families(root))

    def _register_appfont(path, plat):
        """Register the font directly with *this process's* live font
        config so Tk can see it immediately — no root, no waiting.

        Copying the file into ~/.local/share/fonts and running fc-cache
        (done in _install_font_linux above) only refreshes the on-disk
        fontconfig cache. The Xft font backend Tk is already using in
        this running process opened its own in-memory FcConfig at
        startup, and that in-memory copy has no way to know a new file
        appeared on disk — fontconfig only rescans after its cache
        rescan interval (default 30s), and even then only on a cold
        lookup. That's why the family shows up as "not visible to Tk"
        right after install, regardless of whether you're root.

        FcConfigAppFontAddFile() mutates that same in-memory FcConfig
        object in place (this is the identical mechanism GTK/Pango use
        for "private" application fonts), so the family appears in
        tkinter.font.families() the instant this call returns. macOS
        gets the CoreText equivalent, scoped to the process only.
        """
        if plat == "Linux":
            try:
                import ctypes, ctypes.util
                libname = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
                fc = ctypes.CDLL(libname)
                fc.FcConfigAppFontAddFile.restype = ctypes.c_int
                fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                return bool(fc.FcConfigAppFontAddFile(None, path.encode("utf-8")))
            except Exception:
                return False
        elif plat == "Darwin":
            try:
                import ctypes
                cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
                ct = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
                cf.CFStringCreateWithCString.restype  = ctypes.c_void_p
                cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
                cf.CFURLCreateWithFileSystemPath.restype  = ctypes.c_void_p
                cf.CFURLCreateWithFileSystemPath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
                ct.CTFontManagerRegisterFontsForURL.restype  = ctypes.c_int
                ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                kCFStringEncodingUTF8      = 0x08000100
                kCFURLPOSIXPathStyle       = 0
                kCTFontManagerScopeProcess = 1
                cfstr = cf.CFStringCreateWithCString(None, path.encode("utf-8"), kCFStringEncodingUTF8)
                cfurl = cf.CFURLCreateWithFileSystemPath(None, cfstr, kCFURLPOSIXPathStyle, False)
                return bool(ct.CTFontManagerRegisterFontsForURL(cfurl, kCTFontManagerScopeProcess, None))
            except Exception:
                return False
        return False

    def _load(path, tag):
        if not path:
            return None
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            print(f"[font] WARNING: {tag} font file not found: {path}")
            return None

        plat = platform.system()

        # ── Step 1: install / register the font file with the OS ────────────
        try:
            if plat == "Linux":
                _install_font_linux(path)
            elif plat == "Darwin":
                _install_font_mac(path)
            elif plat == "Windows":
                _install_font_windows(path)
        except Exception as e:
            print(f"[font] WARNING: {tag} OS font install failed: {e}")

        # ── Step 1b: register with *this* process's live font config ────────
        # The OS-level install above is for persistence (other apps, future
        # runs); this is what actually makes the family visible to Tk right
        # now. See _register_appfont() docstring for why this is necessary.
        if _register_appfont(path, plat):
            root.update()

        # ── Step 2: determine the PostScript family name ─────────────────────
        family = None

        # fonttools gives the authoritative embedded name
        family = _family_from_fonttools(path)

        # fc-query is a reliable second source on Linux/macOS
        if not family and plat in ("Linux", "Darwin"):
            family = _family_from_fc(path)

        # fall back to filename stem
        if not family:
            family = _family_from_stem(path)

        # ── Step 3: verify Tk can actually see the family ────────────────────
        if _wait_for_family(root, family):
            print(f"[font] {tag}: loaded → \"{family}\"")
            return family

        # Family not found even after waiting — log candidates for debugging
        fams = sorted(tkfont.families(root))
        stem = _family_from_stem(path)
        # try case-insensitive match as a last resort
        lc_family  = (family or "").lower()
        lc_stem    = stem.lower()
        for f in fams:
            if f.lower() == lc_family or f.lower() == lc_stem:
                print(f"[font] {tag}: case-insensitive match → \"{f}\"")
                return f

        print(f"[font] WARNING: {tag}: family \"{family}\" not visible to Tk after install.")
        print(f"[font]   Install the font system-wide, or: pip install fonttools")
        return None

    _FREQ_FONT_FAMILY = _load(_ARGS.freq_font, "freq")
    _GUI_FONT_FAMILY  = _load(_ARGS.gui_font,  "gui")

    # Propagate the gui font into all of Tk's named system fonts so that every
    # widget using TkDefaultFont / TkTextFont / TkFixedFont etc. picks it up
    # automatically without needing individual overrides.
    if _GUI_FONT_FAMILY:
        for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                      "TkHeadingFont", "TkCaptionFont", "TkSmallCaptionFont",
                      "TkIconFont", "TkTooltipFont"):
            try:
                tkfont.nametofont(named).configure(family=_GUI_FONT_FAMILY)
            except Exception:
                pass
        print(f'[font] gui font "{_GUI_FONT_FAMILY}" applied to all Tk system fonts')


def _freq_font(size, *modifiers):
    fam = _FREQ_FONT_FAMILY or 'TkDefaultFont'
    return (fam, size) + modifiers if modifiers else (fam, size)

def _gui_font(size, *modifiers):
    fam = _GUI_FONT_FAMILY or 'TkDefaultFont'
    return (fam, size) + modifiers if modifiers else (fam, size)

# ── Colour palette ────────────────────────────────────────────────────────────
C = dict(
    win_bg      = "#020814",   # outer window / waterfall background — deep dark blue
    panel_bg    = "#0c1525",   # left control panel
    panel_mid   = "#0e1a2e",   # toolbar / dividers
    spec_bg     = "#010610",   # spectrum/AF canvas bg — near-black navy
    btn_gray    = "#182438",   # default button
    btn_grn     = "#0e3018",   # green highlight button face
    btn_grn_fg  = "#22dd44",   # green button text
    btn_red_fg  = "#dd2222",   # red "Exit" text
    btn_sel     = "#1a3c6a",   # selected/active blue button
    btn_sel_fg  = "#50c0ff",   # active text
    text        = "#b8cce8",   # normal
    text_dim    = "#4a6080",   # dim labels
    text_grn    = "#22dd44",   # green text (date, active mode)
    freq_amber  = "#ffb800",   # LO/Tune digits
    grid        = "#1a2a3a",   # grid lines — muted dark-blue-gray
    grid_text   = "#6080a0",   # grid labels — slightly lighter gray
    trace       = "#22cc44",   # spectrum trace — green
    trace_fill  = "#05200a",   # trace fill — very dark green
    filter_fill_overlay = "#1e3f70",  # IF passband overlay
    filter_edge = "#3060e0",   # IF passband edge
    vfo_line    = "#ff2828",   # VFO line
    smeter_grn  = "#28ee50",
    smeter_red  = "#ff3830",
    peak_bar    = "#e0e8ff",   # peak/hold line — bright white-blue (matches reference)
    toolbar_wf  = "#ff3030",   # "Waterfall" label red
    toolbar_sp  = "#c8d8f0",   # "Spectrum" label
    sep         = "#1a3050",
)


NUM_BINS = 900
AF_BINS  = 600

BANDS = [
    ("160m",1_850_000),("80m",3_700_000),("60m",5_330_000),
    ("40m",7_100_000),("30m",10_120_000),("20m",14_195_000),
    ("17m",18_100_000),("15m",21_200_000),("12m",24_900_000),
    ("10m",28_500_000),("6m",50_100_000),
]

# ── Base geometry constants (at scale=1.0) ────────────────────────────────────
BASE = dict(
    win_w=1520, win_h=870,
    min_w=1100, min_h=720,
    left_w=398,
    spec_h=145,
    af_spec_h=140,
    smeter_w=280, smeter_h=85,
    toolbar_h=20,
    freq_digit_size=26,
    freq_sep_size=26,
    freq_label_size=9,
    btn_font_size=8,
    btn_big_size=11,    # transport symbols
    clock_size=11,
    grid_font_size=7,
    smeter_label_size=6,
    smeter_dbm_size=8,
    peak_size=8,
    filter_label_size=9,
    scale_pct_size=7,
    scale_btn_size=9,
    conn_dot_size=12,
)

# ── helpers ───────────────────────────────────────────────────────────────────

def _auto_scale_for_screen(screen_w, screen_h):
    """Return the best integer scale level (-5..5) so the default window
    (BASE win_w x win_h) fits comfortably inside the given screen resolution.

    Common targets:
      1024x768   → level  0  (1.00×)
      1280x720   → level  0
      1366x768   → level  0
      1920x1080  → level  1  (1.25×)
      2560x1440  → level  2  (1.56×)
      3840x2160  → level  4  (2.44×)
      4096x2160  → level  4
    """
    # Leave 10% margin for window chrome / taskbar
    avail_w = screen_w * 0.90
    avail_h = screen_h * 0.90
    best = 0
    for lvl in range(5, -6, -1):   # try largest first
        sc = 1.25 ** lvl
        w  = BASE['win_w'] * sc
        h  = BASE['win_h'] * sc
        if w <= avail_w and h <= avail_h:
            best = lvl
            break
    return best

def db_to_rgb(db, dmin=-150.0, dmax=0.0):
    t = max(0.0, min(1.0, (db-dmin)/(dmax-dmin)))
    stops = [(0.00,(2,5,30)),(0.20,(0,10,130)),(0.40,(0,90,220)),
             (0.57,(0,210,210)),(0.70,(0,200,0)),(0.82,(220,210,0)),
             (0.92,(255,100,0)),(1.00,(255,255,220))]
    for i in range(len(stops)-1):
        t0,c0 = stops[i]; t1,c1 = stops[i+1]
        if t<=t1 or i==len(stops)-2:
            f=max(0.0,min(1.0,(t-t0)/(t1-t0) if t1>t0 else 0.0))
            return (int(c0[0]+(c1[0]-c0[0])*f),
                    int(c0[1]+(c1[1]-c0[1])*f),
                    int(c0[2]+(c1[2]-c0[2])*f))
    return stops[-1][1]

# Colormap data mirroring the stops in db_to_rgb — kept in sync manually.
_CMAP_T  = (0.00, 0.20, 0.40, 0.57, 0.70, 0.82, 0.92, 1.00)
_CMAP_R  = (  2,    0,    0,    0,    0,  220,  255,  255)
_CMAP_G  = (  5,   10,   90,  210,  200,  210,  100,  255)
_CMAP_B  = ( 30,  130,  220,  210,    0,    0,    0,  220)

def _db_array_to_rgb_bytes(db_arr, dmin=-150.0, dmax=0.0):
    """Vectorised (numpy) conversion of a 1-D dB array → packed RGB bytes.

    Returns a bytes object of length 3*len(db_arr) suitable for use with
    PhotoImage.put() after reshaping.  Falls back to the scalar path when
    numpy is not available.
    """
    if _np is None:
        # Pure-Python fallback: reuse existing scalar helper.
        out = bytearray(3 * len(db_arr))
        for i, db in enumerate(db_arr):
            r, g, b = db_to_rgb(db, dmin, dmax)
            out[3*i] = r; out[3*i+1] = g; out[3*i+2] = b
        return bytes(out)

    t_arr = _np.clip(((_np.asarray(db_arr, dtype=_np.float32) - dmin)
                      / (dmax - dmin)), 0.0, 1.0)

    ct = _np.array(_CMAP_T, dtype=_np.float32)
    cr = _np.array(_CMAP_R, dtype=_np.float32)
    cg = _np.array(_CMAP_G, dtype=_np.float32)
    cb = _np.array(_CMAP_B, dtype=_np.float32)

    # For each sample, find which colour-stop segment it falls in.
    # searchsorted gives the index of the *right* stop; clamp to valid range.
    idx = _np.searchsorted(ct, t_arr, side='right') - 1
    idx = _np.clip(idx, 0, len(ct) - 2)

    t0 = ct[idx]; t1 = ct[idx + 1]
    span = _np.where(t1 > t0, t1 - t0, 1.0)
    f = _np.clip((t_arr - t0) / span, 0.0, 1.0)

    r = (cr[idx] + (cr[idx+1] - cr[idx]) * f).astype(_np.uint8)
    g = (cg[idx] + (cg[idx+1] - cg[idx]) * f).astype(_np.uint8)
    b = (cb[idx] + (cb[idx+1] - cb[idx]) * f).astype(_np.uint8)

    return _np.stack([r, g, b], axis=1).tobytes()

def nice_step(x):
    if x<=0: return 1
    e=math.floor(math.log10(x)); b=10**e
    for m in (1,2,5,10):
        if b*m>=x-1e-9: return b*m
    return b*10

def scaled(key, sc):
    """Return BASE[key] scaled and rounded to int."""
    return max(1, int(round(BASE[key] * sc)))


# ── RTP Audio constants (must match server) ───────────────────────────────────
AUDIO_SAMPLE_RATE = 8000
AUDIO_FRAME_MS    = 20
AUDIO_FRAME_SAMPS = int(AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS / 1000)  # 160
PT_PCMU           = 0    # RTP payload type: G.711 µ-law (RFC 3551)

# ── RTP helpers (GUI side) ────────────────────────────────────────────────────

def _rtp_pack_gui(payload: bytes, seq: int, ts: int, ssrc: int = 0xABCD1234) -> bytes:
    byte0 = 0x80
    byte1 = PT_PCMU & 0x7F   # payload type in bits 6-0; bit 7 = marker (clear)
    return struct.pack("!BBHII", byte0, byte1, seq & 0xFFFF, ts, ssrc) + payload

def _rtp_unpack_gui(data: bytes):
    if len(data) < 12:
        return None
    hdr = struct.unpack("!BBHII", data[:12])
    return data[12:], hdr[2], hdr[3]

# ── u-law <-> linear16 codec ────────────────────────────────────────────────
# NOTE: this is intentionally NOT the standard ITU-T G.711 mu-law curve — it
# uses a bias of 33 (0x21) and a mantissa shift of 1, which works out to be
# exactly 1/4 the amplitude of the textbook formula (BIAS=132, shift=3) that
# audioop.ulaw2lin()/lin2ulaw() implement. Swapping in audioop would silently
# change playback/transmit volume by 4x and could desync from whatever the
# server side expects. audioop is also deprecated (PEP 594) and removed in
# Python 3.13+, so it's not a safe long-term dependency either. Instead, the
# exact original per-sample math is preserved but pushed into precomputed
# lookup tables built once at import time, so the hot path becomes a pure
# table lookup with no bit-shifting, branching, or struct (un)packing.

def _build_ulaw_decode_table():
    """256-entry table: u-law byte -> decoded int16 sample."""
    table = []
    for raw in range(256):
        b = ~raw & 0xFF
        sign = b & 0x80
        exp = (b >> 4) & 0x07
        mantissa = b & 0x0F
        s = ((mantissa << 1) | 0x21) << exp
        s -= 33
        if sign:
            s = -s
        s = max(-32768, min(32767, s))
        table.append(s)
    return tuple(table)

def _build_linear_to_ulaw_table():
    """65536-entry table: unsigned 16-bit sample value (signed sample + 0x10000
    if negative, i.e. `sample & 0xFFFF`) -> encoded u-law byte."""
    table = bytearray(65536)
    for sample in range(-32768, 32768):
        s = sample
        sign = 0 if s >= 0 else 0x80
        if s < 0:
            s = -s
        s = min(s, 32767)
        s += 33
        s = min(s, 8191)
        exp = 0
        for e in range(7, -1, -1):
            if s >= (1 << (e + 5)):
                exp = e
                break
        mantissa = (s >> (exp + 1)) & 0x0F
        ulaw = ~(sign | (exp << 4) | mantissa) & 0xFF
        table[sample & 0xFFFF] = ulaw
    return bytes(table)

_ULAW_DECODE_TABLE      = _build_ulaw_decode_table()
_LINEAR_TO_ULAW_TABLE   = _build_linear_to_ulaw_table()

def _ulaw_to_linear16_gui(ulaw_bytes: bytes) -> bytes:
    table = _ULAW_DECODE_TABLE
    out = array.array('h', (table[b] for b in ulaw_bytes))
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes()

def _linear16_to_ulaw_gui(samples: bytes) -> bytes:
    in_arr = array.array('h')
    in_arr.frombytes(samples)
    if sys.byteorder != "little":
        in_arr.byteswap()
    table = _LINEAR_TO_ULAW_TABLE
    return bytes(table[s & 0xFFFF] for s in in_arr)


# ── Local AF (audio-frequency) spectrum analysis ─────────────────────────────
# The AF spectrum/waterfall box is driven from the *actual* decoded RTP audio
# that the client receives and plays — not from any value the server reports
# separately — so what's drawn always matches the real received signal.
_AF_FFT_N            = 512   # FFT window size, samples (power of 2)
_AF_FFT_HOP          = 256   # samples advanced between successive FFTs (50% overlap)
_AF_DISPLAY_RANGE_HZ = 3000  # 0..this Hz is shown in the AF spectrum/waterfall
_AF_RING_MAX         = 10 * _AF_FFT_N   # hard cap on _af_ring length (~5 s at 8 kHz)

_af_hamming_cache = {}
def _af_hamming(n):
    """Cached Hamming window of length n.

    Returns a numpy array when numpy is available, otherwise a plain list.
    """
    w = _af_hamming_cache.get(n)
    if w is None:
        if _np is not None:
            w = _np.hamming(n) if n > 1 else _np.ones(n)
        else:
            w = ([0.54 - 0.46*math.cos(2*math.pi*i/(n-1)) for i in range(n)]
                 if n > 1 else [1.0]*n)
        _af_hamming_cache[n] = w
    return w

def _af_fft(x):
    """Radix-2 FFT — used only when numpy is not available.

    len(x) must be a power of 2.
    """
    n = len(x)
    if n > 1 and (n & (n - 1)) != 0:
        raise ValueError(f"_af_fft: length {n} is not a power of 2")
    if n <= 1:
        return x
    even = _af_fft(x[0::2])
    odd  = _af_fft(x[1::2])
    twiddles = [cmath.exp(-2j*math.pi*k/n) * odd[k] for k in range(n//2)]
    return [even[k] + twiddles[k] for k in range(n//2)] + \
           [even[k] - twiddles[k] for k in range(n//2)]

def _af_spectrum_db(samples):
    """Convert a window of decoded int16 PCM samples (the real received
    audio) into a one-sided dB spectrum (index 0 = 0 Hz), scaled to the
    same -150..0 dB range SpecCanvas/WFCanvas already use for display.

    Uses numpy.fft.rfft when numpy is available for significantly better
    performance; falls back to the pure-Python recursive FFT otherwise.
    """
    n = len(samples)
    win = _af_hamming(n)
    if _np is not None:
        x = _np.array(samples, dtype=_np.float64) * win
        X = _np.fft.rfft(x)          # length n//2 + 1, one-sided
        win_sum = win.sum() or 1.0
        mag = _np.abs(X) * 2.0 / win_sum
        db = 20.0 * _np.log10(mag / 32768.0 + 1e-9)
        db = _np.clip(db, -150.0, 0.0)
        return db.tolist()
    else:
        x = [complex(samples[i]*win[i], 0.0) for i in range(n)]
        X = _af_fft(x)
        win_sum = sum(win) or 1.0
        out = []
        for k in range(n//2 + 1):
            mag = abs(X[k]) * 2.0 / win_sum
            db = 20.0*math.log10(mag/32768.0 + 1e-9)
            out.append(max(-150.0, min(0.0, db)))
        return out


class RTPAudioClient:
    """
    Manages the GUI side of the RTP/UDP audio channel.

    Behaviour driven by PTT state:
      PTT OFF → open speaker stream, receive RTP from server and play
      PTT ON  → mute speaker, open mic stream, send RTP to server

    PyAudio is imported lazily so the GUI still runs on machines without it
    (audio features silently disabled with a console warning).
    """

    def __init__(self, server_host: str = "", server_port: int = 0):
        """Construct an RTPAudioClient.

        ``server_host`` and ``server_port`` are accepted for backwards
        compatibility but are **never used** here; the real network
        parameters are supplied (and the socket is opened) by :meth:`open`.
        Do not rely on constructor values being honoured without a subsequent
        call to ``open()``.
        """
        self._host       = server_host
        self._port       = server_port
        self._sock       = None
        self._alive      = False
        self._ptt        = False
        self._seq        = 0
        self._ts         = 0
        self._pa         = None
        self._rx_stream  = None
        self._tx_stream  = None
        self._lock       = threading.Lock()
        self._local_port = None
        self._in_device  = None   # PyAudio input  device index (None = system default)
        self._out_device = None   # PyAudio output device index (None = system default)
        # Ring buffer shared between _rx_loop (producer) and the PyAudio
        # output callback (consumer).  Using a deque avoids blocking the UDP
        # receive thread when the PyAudio buffer is temporarily full.
        self._rx_buf     = collections.deque()
        self._sample_rate  = AUDIO_SAMPLE_RATE
        self._frame_ms     = AUDIO_FRAME_MS
        self._frame_samps  = AUDIO_FRAME_SAMPS
        # Rolling buffer of decoded int16 PCM samples (real received audio)
        # used to compute the AF spectrum/waterfall locally.
        self._af_ring    = array.array('h')
        self._af_last_put = 0.0   # timestamp of last AF frame posted to GUI queue
        self._af_app     = None   # set externally to the App instance

    # ── device enumeration ────────────────────────────────────────────────────
    def get_devices(self):
        """Return list of dicts describing all audio devices on this machine.
        Returns [] if pyaudio is not available."""
        try:
            import pyaudio
        except ImportError:
            return []
        pa = self._pa
        own = False
        if pa is None:
            try:
                pa = pyaudio.PyAudio()
                own = True
            except Exception:
                return []
        devices = []
        try:
            for i in range(pa.get_device_count()):
                try:
                    info = pa.get_device_info_by_index(i)
                    devices.append({
                        "index":               i,
                        "name":                info["name"],
                        "max_input_channels":  int(info["maxInputChannels"]),
                        "max_output_channels": int(info["maxOutputChannels"]),
                        "default_sample_rate": int(info["defaultSampleRate"]),
                    })
                except Exception:
                    pass
        finally:
            if own:
                try:
                    pa.terminate()
                except Exception:
                    pass
        return devices

    def set_devices(self, in_index, out_index):
        """Set input/output device indices (None = system default).
        Restarts any active stream immediately on the new devices."""
        with self._lock:
            self._in_device  = in_index
            self._out_device = out_index
        if self._alive:
            self._close_streams()
            if self._ptt:
                self._open_tx_stream()
            else:
                self._open_rx_stream()

    def get_selected_devices(self):
        """Return (in_device, out_device) indices currently selected.
        Either value may be None, meaning «use the system default»."""
        with self._lock:
            return (self._in_device, self._out_device)

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def open(self, server_host: str, server_udp_port: int,
             sample_rate: int = AUDIO_SAMPLE_RATE,
             frame_ms: int = AUDIO_FRAME_MS):
        """Call this when the server sends audio_port."""
        if self._alive:        # guard against double-open
            self.close()
        self._host        = server_host
        self._port        = server_udp_port
        self._sample_rate = sample_rate
        self._frame_ms    = frame_ms
        self._frame_samps = int(sample_rate * frame_ms / 1000)
        with self._lock:                        # BUG-4: guard rebind against concurrent _rx_loop reads
            self._af_ring     = array.array('h')   # discard any samples from a prior session
            self._af_last_put = 0.0                # ensure first AF frame of new session is not skipped

        # Open UDP socket
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.05)
        self._sock.bind(("0.0.0.0", 0))   # OS picks a port
        self._local_port = self._sock.getsockname()[1]
        self._alive = True

        # Try to import PyAudio
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
        except ImportError:
            print("[audio] WARNING: pyaudio not installed — audio disabled. "
                  "Install with: pip install pyaudio")
            self._pa = None

        # Send a hello packet so the server learns our (ip, port)
        # (also carries our local UDP port via the TCP channel — done externally)
        hello = _rtp_pack_gui(b"\x00" * self._frame_samps, 0, 0)
        try:
            self._sock.sendto(hello, (self._host, self._port))
        except OSError:
            pass

        threading.Thread(target=self._rx_loop, daemon=True).start()
        threading.Thread(target=self._af_worker, daemon=True).start()  # BUG-6
        # PTT starts OFF → open speaker stream immediately so audio plays on connect
        self._open_rx_stream()
        print(f"[audio] RTP client open  local_udp={self._local_port}"
              f"  server={self._host}:{self._port}")

    def close(self):
        self._alive = False
        self._close_streams()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        print("[audio] RTP client closed")

    def local_udp_port(self):
        return self._local_port

    # ── PTT control ──────────────────────────────────────────────────────────
    def set_ptt(self, active: bool):
        with self._lock:
            if active == self._ptt:
                return
            self._ptt = active
        self._close_streams()
        if active:
            self._open_tx_stream()
        else:
            self._open_rx_stream()

    # ── stream helpers ────────────────────────────────────────────────────────
    def _close_streams(self):
        self._rx_buf.clear()   # discard buffered audio before tearing down streams
        for attr in ("_rx_stream", "_tx_stream"):
            s = getattr(self, attr, None)
            if s:
                try:
                    s.stop_stream()
                    s.close()
                except Exception:
                    pass
                setattr(self, attr, None)

    def _open_rx_stream(self):
        if not self._pa:
            return
        try:
            import pyaudio
            kw = {}
            if self._out_device is not None:
                kw["output_device_index"] = self._out_device
            self._rx_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=self._frame_samps,
                stream_callback=self._rx_callback,
                **kw,
            )
            self._rx_stream.start_stream()
        except Exception as e:
            print(f"[audio] speaker stream error: {e}")

    def _rx_callback(self, in_data, frame_count, time_info, status):
        """PyAudio output callback — drain samples from the ring buffer."""
        needed = frame_count * 2  # 16-bit mono → 2 bytes per sample
        try:
            chunk = self._rx_buf.popleft()
            if len(chunk) >= needed:
                data = chunk[:needed]
                remainder = chunk[needed:]
                if remainder:
                    self._rx_buf.appendleft(remainder)
            else:
                # Short chunk: greedily consume more buffered chunks before padding
                data = bytearray(chunk)
                while len(data) < needed:
                    try:
                        chunk = self._rx_buf.popleft()
                        data.extend(chunk)
                    except IndexError:
                        break
                if len(data) > needed:
                    self._rx_buf.appendleft(bytes(data[needed:]))
                    data = data[:needed]
                data = bytes(data) + b"\x00" * (needed - len(data))
        except IndexError:
            # Buffer empty (normal underrun) or cleared by _close_streams()
            # racing between our check and pop — either way, emit silence.
            data = b"\x00" * needed
        return (data, 0)  # 0 == pyaudio.paContinue

    def _open_tx_stream(self):
        if not self._pa:
            return
        try:
            import pyaudio
            kw = {}
            if self._in_device is not None:
                kw["input_device_index"] = self._in_device
            self._tx_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self._sample_rate,
                input=True,
                frames_per_buffer=self._frame_samps,
                stream_callback=self._tx_callback,
                **kw,
            )
            self._tx_stream.start_stream()
        except Exception as e:
            print(f"[audio] mic stream error: {e}")

    def _tx_callback(self, in_data, frame_count, time_info, status):
        """PyAudio input callback — encode and send one RTP packet."""
        payload = _linear16_to_ulaw_gui(in_data)
        pkt = _rtp_pack_gui(payload, self._seq, self._ts)
        self._seq = (self._seq + 1) & 0xFFFF
        self._ts  = (self._ts + frame_count) & 0xFFFFFFFF
        sock = self._sock          # capture reference once
        if sock is None:
            return (None, 0)
        try:
            sock.sendto(pkt, (self._host, self._port))
        except OSError:
            pass
        return (None, 0)  # 0 == pyaudio.paContinue

    # ── RX loop ───────────────────────────────────────────────────────────────
    def _rx_loop(self):
        while self._alive:
            try:
                data, _ = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            result = _rtp_unpack_gui(data)
            if result is None:
                continue
            payload, seq, ts = result

            with self._lock:
                ptt_active = self._ptt

            if ptt_active:
                continue  # we are TX-ing, discard any incoming echo

            pcm = _ulaw_to_linear16_gui(payload)
            if self._rx_stream:
                # Non-blocking: push decoded PCM into the ring buffer so the
                # PyAudio output callback (_rx_callback) can drain it at its
                # own pace without ever stalling this receive thread.
                self._rx_buf.append(pcm)

            # Feed the same decoded samples — the real audio received from
            # the server — into the local AF spectrum analyzer so the AF
            # spectrum/waterfall box always reflects the actual received
            # signal, independent of whether local playback is available.
            # BUG-6: FFT is offloaded to _af_worker; just buffer here.
            samples = array.array('h')
            samples.frombytes(pcm)
            if sys.byteorder != "little":
                samples.byteswap()
            with self._lock:                    # BUG-4: guard extend against concurrent open() rebind
                self._af_ring.extend(samples)
                if len(self._af_ring) > _AF_RING_MAX:
                    del self._af_ring[:-_AF_FFT_N]   # keep only the most recent window


    # ── AF spectrum worker ────────────────────────────────────────────────────
    def _af_worker(self):
        """Dedicated thread: drains _af_ring and posts AF spectrum to the GUI
        queue.  Keeps FFT computation off the UDP receive thread (BUG-6)."""
        while self._alive:
            with self._lock:
                if len(self._af_ring) >= _AF_FFT_N:
                    window = list(self._af_ring[:_AF_FFT_N])
                    del self._af_ring[:_AF_FFT_HOP]
                else:
                    window = None
            if window:
                spectrum = _af_spectrum_db(window)
                bin_hz = self._sample_rate / _AF_FFT_N
                max_bin = min(len(spectrum) - 1, int(_AF_DISPLAY_RANGE_HZ / bin_hz))
                if self._af_app is not None:
                    with self._lock:
                        _now = time.monotonic()
                        _should_put = (_now - self._af_last_put) >= 0.05
                        if _should_put:
                            self._af_last_put = _now
                    if _should_put:
                        self._af_app.q.put({
                            "type":        "af_local",
                            "af_spectrum": spectrum[:max_bin + 1],
                            "af_range":    _AF_DISPLAY_RANGE_HZ,
                        })
            else:
                time.sleep(0.005)


def _print_audio_devices():
    """Print every input- and output-capable audio device on this system,
    in the same format and with the same index numbers as the GUI's
    Soundcard dialog, for use with --audio-mic / --audio-speaker.
    Works standalone — no Tk root or display needed."""
    devices = RTPAudioClient("", 0).get_devices()
    if not devices:
        print("[audio] pyaudio not installed, or no audio devices found. "
              "Install with: pip install pyaudio")
        return

    def _fmt(d, ch):
        sr = d["default_sample_rate"]
        return f"  [{d['index']:2d}]  {d['name']}  ({ch}ch  {sr // 1000}kHz)"

    print("[audio] Input devices (microphones) — use with --audio-mic INDEX:")
    in_devs = [d for d in devices if d["max_input_channels"] > 0]
    if in_devs:
        for d in in_devs:
            print(_fmt(d, d["max_input_channels"]))
    else:
        print("  (none found)")

    print("[audio] Output devices (speakers) — use with --audio-speaker INDEX:")
    out_devs = [d for d in devices if d["max_output_channels"] > 0]
    if out_devs:
        for d in out_devs:
            print(_fmt(d, d["max_output_channels"]))
    else:
        print("  (none found)")


# ── networking ────────────────────────────────────────────────────────────────

class Net:
    def __init__(self,app):
        self.app=app; self.sock=None; self.connected=False
        self._lk=threading.Lock()

    def connect(self,host,port):
        try: s=socket.create_connection((host,port),timeout=3)
        except OSError as e: return False,str(e)
        s.settimeout(5.0); self.sock=s; self.connected=True
        threading.Thread(target=self._rx,daemon=True).start()
        return True,"ok"

    def disconnect(self):
        with self._lk:
            self.connected = False
            sock, self.sock = self.sock, None
        if sock:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass
            try: sock.close()
            except OSError: pass

    def send(self,obj):
        with self._lk:
            if not self.connected or not self.sock: return False
            sock = self.sock          # capture reference under lock
        d=(json.dumps(obj)+"\n").encode()
        try:
            sock.sendall(d)           # use captured reference, not self.sock
            return True
        except (OSError, socket.timeout):
            self.connected=False
            self.app.q.put({"type":"disconnected"})
            return False

    _RX_BUF_MAX = 4 * 1024 * 1024   # 4 MiB — guard against unbounded buffer growth

    def _rx(self):
        buf=b""
        while self.connected:
            try: data=self.sock.recv(65536)
            except OSError: break
            if not data: break
            buf+=data
            if len(buf) > self._RX_BUF_MAX:
                logging.warning(
                    "_rx: receive buffer exceeded %d bytes with no line boundary "
                    "— likely malformed/unterminated JSON; closing socket",
                    self._RX_BUF_MAX,
                )
                self._rx_overflow_reason = (
                    "Receive buffer overflow — malformed server data"
                )
                break
            while b"\n" in buf:
                line,buf=buf.split(b"\n",1)
                line=line.strip()
                if not line: continue
                try: self.app.q.put(json.loads(line.decode()))
                except (json.JSONDecodeError, UnicodeDecodeError): pass
        # Snapshot the flag *before* clearing it: if disconnect() already set it
        # to False, the user initiated the close intentionally and the GUI should
        # not be notified.  If it is still True here, the loop fell out due to a
        # network fault and the GUI needs to surface the error.
        was_unexpected = self.connected
        self.connected = False
        if was_unexpected:
            reason = getattr(self, '_rx_overflow_reason', None)
            self._rx_overflow_reason = None
            msg = {"type": "disconnected"}
            if reason:
                msg["reason"] = reason
            self.app.q.put(msg)

# ── Waterfall canvas ──────────────────────────────────────────────────────────

class WFCanvas(tk.Canvas):
    """Waterfall display using incremental PhotoImage.put() row prepending.

    Instead of rebuilding a full PPM image from all stored rows on every
    incoming frame (O(rows) work that freezes the GUI once the waterfall
    fills up), we maintain a single PhotoImage the same size as the canvas
    and on each new row we:
      1. Copy the existing image down by one pixel using .put() of a
         pre-built row string, preceded by a copy_from scroll trick, OR
         simply use the Tk image's built-in copy+scroll path.
      2. Write the single new row of pixels into row 0.

    This makes each add_row() call O(canvas_width) instead of O(rows *
    canvas_width), which eliminates the freeze entirely.
    """

    def __init__(self,master,af=False,**kw):
        kw.setdefault("bg",C["win_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.af=af
        self.f0=28_490_000.0; self.f1=28_510_000.0
        self._app=None
        self._img=None          # current PhotoImage (canvas-sized)
        self._img_w=0           # width  of _img in pixels
        self._img_h=0           # height of _img in pixels
        self._iid=self.create_image(0,0,anchor="nw")
        self._tx_active=False
        # Scroll-speed throttle: 1 (slowest) .. 10 (fastest/full-rate).
        # Default 10 preserves legacy behaviour (a row is added on every
        # incoming frame) unless the operator turns the Speed control down.
        # _speed_acc is a fixed-point accumulator: it gains `speed` units on
        # every incoming frame and a row is drawn whenever it reaches 10,
        # so speed=10 draws every frame and speed=1 draws roughly 1 frame
        # in 10 (i.e. the waterfall scrolls ~10x slower).
        self.speed=10
        self._speed_acc=0
        self.bind("<Configure>",self._on_resize)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _lbl_h(self):
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        return max(10,int(round(12*sc)))

    def _alloc_img(self,w,h):
        """(Re)create the backing PhotoImage at the given pixel size."""
        self._img=tk.PhotoImage(width=w,height=h)
        self._img_w=w; self._img_h=h
        self.itemconfig(self._iid,image=self._img)

    def _on_resize(self,event=None):
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        lbl_h=self._lbl_h()
        img_h=max(1,ch-lbl_h)
        # Only reallocate if size actually changed
        if cw!=self._img_w or img_h!=self._img_h:
            self._alloc_img(cw,img_h)
        self.coords(self._iid,0,0)
        self._draw_overlay()

    @staticmethod
    def _row_to_tk_data(spectrum,out_w,dmin=-150,dmax=0):
        """Convert a spectrum array to a Tk-compatible color row string.

        Returns a string of space-separated hex colors: "{#rrggbb #rrggbb …}"
        suitable for PhotoImage.put(data, to=(0, y)).
        This format lets Tk decode the row natively without building PPM headers.
        """
        n=len(spectrum)
        if n==0:
            return "{" + " ".join(["#000000"]*out_w) + "}"
        # Resample spectrum to output width first, then colourise.
        if _np is not None:
            src = _np.asarray(spectrum, dtype=_np.float32)
            xi  = (_np.arange(out_w) * n / out_w).astype(_np.intp)
            xi  = _np.clip(xi, 0, n - 1)
            resampled = src[xi]
            rgb = _db_array_to_rgb_bytes(resampled, dmin, dmax)
            # rgb is a flat bytes object: [R0,G0,B0, R1,G1,B1, ...]
            parts = [f"#{rgb[i]:02x}{rgb[i+1]:02x}{rgb[i+2]:02x}"
                     for i in range(0, len(rgb), 3)]
        else:
            parts=[]
            for x in range(out_w):
                si=min(int(x*n/out_w),n-1)
                r,g,b=db_to_rgb(spectrum[si],dmin,dmax)
                parts.append(f"#{r:02x}{g:02x}{b:02x}")
        return "{" + " ".join(parts) + "}"

    # ── public API ────────────────────────────────────────────────────────────

    def set_tx(self, active: bool):
        """Freeze (active=True) or unfreeze (active=False) the waterfall during TX.

        When frozen a prominent "● TX" badge is drawn over the top-left corner
        so the operator sees immediately that the display is paused.  The badge
        is removed the moment PTT is released and normal scrolling resumes.
        """
        self._tx_active = active
        self.delete("wf_tx_badge")
        if active:
            sc  = getattr(self._app, '_sc', 1.0) if self._app else 1.0
            pad = max(4, int(round(5 * sc)))
            fs  = max(7, int(round(8 * sc)))
            self.create_text(pad, pad, text="\u25cf TX", anchor="nw",
                             fill="#ff3030", font=("TkFixedFont", fs, "bold"),
                             tags="wf_tx_badge")

    def set_freq_range(self,f0,f1):
        self.f0=f0; self.f1=f1; self._draw_overlay()

    def set_speed(self,v):
        """Set waterfall scroll speed, 1 (slowest) .. 10 (fastest/full-rate)."""
        self.speed=max(1,min(10,int(v)))

    def add_row(self,spectrum,dmin=-150,dmax=0):
        """Add one new row at the top of the waterfall (newest = top).

        Uses PhotoImage.copy() + scroll to shift the existing image down by
        one row, then writes the new row into row 0 with put().  This is
        O(canvas_width) regardless of how many rows have accumulated.
        """
        if self._tx_active: return
        if len(spectrum)==0: return

        # Throttle scroll rate per the Speed control: accumulate `speed`
        # units per incoming frame and only draw once the accumulator
        # reaches 10. This skips frames (rather than time-averaging them),
        # which is cheap and keeps the waterfall in sync with whatever the
        # most recent spectrum looked like.
        self._speed_acc+=self.speed
        if self._speed_acc<10:
            return
        self._speed_acc-=10

        # Ensure backing image exists and matches current canvas size
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        lbl_h=self._lbl_h()
        img_h=max(1,ch-lbl_h)

        if self._img is None or cw!=self._img_w or img_h!=self._img_h:
            self._alloc_img(cw,img_h)
            self.coords(self._iid,0,0)

        img=self._img
        img_h=self._img_h
        img_w=self._img_w

        if img_h<=1:
            # Degenerate: just paint the single row
            row_data=self._row_to_tk_data(spectrum,img_w,dmin,dmax)
            img.put(row_data,to=(0,0))
            self._draw_overlay()
            return

        # Scroll existing content down by 1 pixel using Tcl's photo copy
        # directly.  Python's PhotoImage.copy() accepts no arguments, so we
        # drop to tk.call().  Tk buffers the read before the write internally,
        # so a self-copy (src == dst) with overlapping regions is safe.
        img.tk.call(img, 'copy', img,
                    '-from', 0, 0, img_w, img_h - 1,
                    '-to', 0, 1)

        # Write the new row at y=0
        row_data=self._row_to_tk_data(spectrum,img_w,dmin,dmax)
        img.put(row_data,to=(0,0))

        self._draw_overlay()

    def _draw_overlay(self):
        """Draw frequency axis grid lines and labels on top of the waterfall image."""
        self.delete("wf_overlay")
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        span=self.f1-self.f0
        if span<=0: return
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        gfont=("TkFixedFont",max(6,int(round(7*sc))))
        lbl_h=max(10,int(round(12*sc)))

        step=nice_step(span/12)
        f=math.ceil(self.f0/step)*step
        while f<self.f1:
            x=(f-self.f0)/span*cw
            # Vertical grid line spanning the waterfall image area only
            self.create_line(x,0,x,ch-lbl_h,fill=C["grid"],tags="wf_overlay")
            lbl=f"{f:.0f}" if self.af else f"{f/1000:.0f}"
            # Label drawn in the reserved bottom strip, below the image.
            # BUG-10: skip labels whose left edge would be clipped at the canvas
            # border (mirrors the same guard in SpecCanvas.draw()).
            _lbl_min_x = max(4, int(round(4 * sc)))
            if x >= _lbl_min_x:
                self.create_text(x+2,ch-2,text=lbl,fill=C["grid_text"],
                                 anchor="sw",font=gfont,tags="wf_overlay")
            f+=step
        # Horizontal bottom axis line
        self.create_line(0,ch-lbl_h,cw,ch-lbl_h,fill=C["sep"],tags="wf_overlay")

# ── Spectrum canvas ───────────────────────────────────────────────────────────

class SpecCanvas(tk.Canvas):
    GRAB=6

    def __init__(self,master,app,show_filter=False,af=False,**kw):
        kw.setdefault("bg",C["spec_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.app=app; self.show_filter=show_filter; self.af=af
        # Reference level: DB_MAX is the top of the display (adjustable via
        # SCALE control); DB_MIN is always 150 dB below it.
        self.DB_MAX = 0.0
        self.DB_MIN = -150.0
        if af:
            self.f0 = 0.0
            self.f1 = float(_AF_DISPLAY_RANGE_HZ)   # 3000.0
        else:
            self.f0 = 28_490_000.0
            self.f1 = 28_510_000.0
        self.data=[]
        self.drag=None; self._last=0.0
        self._tx_active=False
        self._peak       = None   # BUG-5: per-bin peak dB array (None until first draw)
        self._peak_decay = 0.5    # BUG-5: dB/frame decay rate for peak-hold
        # BUG-7: compute once — stipple is platform-constant for the process lifetime
        self._stipple = "gray50" if sys.platform.startswith("linux") else ""

        # ── Retained canvas items (created once; updated via coords/itemconfig) ──
        # Drawing order (back → front): fill polygon, trace line, filter overlay,
        # peak line, dB grid, freq grid, separator.  Items tagged "grid" or
        # "filter_overlay" are shown/hidden rather than deleted and re-created.
        # A tiny placeholder polygon/line keeps the item IDs valid before the
        # first real draw(); coords() replaces them on every subsequent frame.
        _ph = [0, 0, 1, 0]   # degenerate placeholder — invisible until first draw
        self._id_fill   = self.create_polygon(_ph, fill=C["trace_fill"], outline="", state="hidden")
        self._id_trace  = self.create_line(_ph,    fill=C["trace"],      width=1,    state="hidden")
        self._id_filt_r = self.create_rectangle(0, 0, 1, 1,
                              fill=C["filter_fill_overlay"], outline="",
                              stipple=self._stipple, state="hidden")
        self._id_filt_lo = self.create_line(_ph, fill=C["filter_edge"], width=1, state="hidden")
        self._id_filt_hi = self.create_line(_ph, fill=C["filter_edge"], width=1, state="hidden")
        self._id_vfo     = self.create_line(_ph, fill=C["vfo_line"],    width=1, dash=(4,3), state="hidden")
        self._id_peak   = self.create_line(_ph,    fill=C["peak_bar"],   width=1,    state="hidden")
        self._id_sep    = self.create_line(0, 0, 1, 0, fill=C["sep"],               state="hidden")
        # dB grid rows — dense 5 dB spacing, text only every 25 dB (every 5th line)
        _db_labels = list(range(0, -155, -5))   # 0, -5, -10, ..., -150
        self._id_db_lines = [self.create_line(0,0,1,0, fill=C["grid"])           for _ in _db_labels]
        self._id_db_texts = []
        for i, db in enumerate(_db_labels):
            show = (i % 5 == 0)   # text only at 0, -25, -50, -75, -100, -125, -150
            txt = (f"{db} dB" if db == 0 else str(db)) if show else ""
            self._id_db_texts.append(
                self.create_text(0, 0, text=txt, fill=C["grid_text"], anchor="nw")
            )
        self._db_labels = _db_labels
        # Frequency grid items are variable-count (depends on span/step/width),
        # so we keep a pool that grows as needed and hide unused slots.
        self._id_freq_lines = []
        self._id_freq_texts = []
        self._freq_labels   = []   # text strings for each active slot

        self.bind("<Configure>",lambda e:self.draw())
        if show_filter:
            self.bind("<Button-1>",self._press)
            self.bind("<B1-Motion>",self._drag)
            self.bind("<ButtonRelease-1>",self._rel)
            self.bind("<Motion>",self._motion)
            self.bind("<MouseWheel>",lambda e:self.app.adj_zoom(1 if e.delta>0 else -1))
            self.bind("<Button-4>",lambda e:self.app.adj_zoom(1))
            self.bind("<Button-5>",lambda e:self.app.adj_zoom(-1))

    def _fx(self,f):
        w=max(self.winfo_width(),1); s=self.f1-self.f0
        return (f-self.f0)/s*w if s else 0
    def _xf(self,x):
        w=max(self.winfo_width(),1)
        return self.f0+x/w*(self.f1-self.f0)
    def _dy(self,db,draw_h=None):
        h=draw_h if draw_h is not None else max(self.winfo_height(),1)
        t=(db-self.DB_MIN)/(self.DB_MAX-self.DB_MIN)
        return h-max(0.0,min(1.0,t))*h

    def update_data(self,f0,f1,spec):
        if self._tx_active: return
        self.f0=f0; self.f1=f1; self.data=spec; self.draw()

    def set_tx(self, active: bool):
        """Freeze (active=True) or unfreeze (active=False) the spectrum during TX.

        A "● TX" badge is shown top-left while transmitting so the operator
        knows the trace is paused.  Removed immediately on PTT release.
        """
        self._tx_active = active
        self.delete("spec_tx_badge")
        if active:
            sc  = getattr(self.app, '_sc', 1.0)
            pad = max(4, int(round(5 * sc)))
            fs  = max(7, int(round(8 * sc)))
            self.create_text(pad, pad, text="\u25cf TX", anchor="nw",
                             fill="#ff3030", font=("TkFixedFont", fs, "bold"),
                             tags="spec_tx_badge")

    def set_ref(self, db):
        """Set spectrum reference level (top of display) in dB and redraw.

        ``db`` is snapped to the nearest 5-dB step and clamped to [-50, +10].
        DB_MIN is always 150 dB below DB_MAX so the displayed range is fixed.
        """
        db = float(max(-50, min(10, round(db / 5) * 5)))
        self.DB_MAX = db
        self.DB_MIN = db - 150.0
        self.draw()

    def draw(self):
        # ── Retained-item draw: no delete("all").  Every canvas object was
        # created once in __init__; here we only reposition and show/hide them.
        # This eliminates per-frame Tcl/Tk object churn (the dominant cost for
        # a spectrum canvas with ~900 bins and ~7 grid lines).
        w,h=self.winfo_width(),self.winfo_height()
        if w<2 or h<2: return
        sc = getattr(self.app, '_sc', 1.0)
        gfont = ("TkFixedFont", max(6, int(round(7*sc))))
        # Reserve bottom strip for frequency labels so they don't overlap trace
        lbl_h = max(10, int(round(12*sc)))
        draw_h = h - lbl_h   # usable height for trace / dB grid

        # ── 1. Spectrum trace (drawn FIRST = behind everything) ───────────────
        n=len(self.data)
        if n>=2:
            if _np is not None:
                xs = _np.linspace(0.0, w, n, endpoint=False)
                db_arr = _np.asarray(self.data, dtype=_np.float64)
                ys = draw_h - _np.clip((db_arr - self.DB_MIN) /
                                       (self.DB_MAX - self.DB_MIN), 0.0, 1.0) * draw_h
                pts = _np.empty(2 * n, dtype=_np.float64)
                pts[0::2] = xs; pts[1::2] = ys
                pts = pts.tolist()
            else:
                pts=[]
                for i,db in enumerate(self.data):
                    pts.extend([i/(n-1)*w,self._dy(db, draw_h)])
            fill_pts = pts + [w, draw_h, 0, draw_h]
            self.coords(self._id_fill,  fill_pts)
            self.coords(self._id_trace, pts)
            self.itemconfig(self._id_fill,  state="normal")
            self.itemconfig(self._id_trace, state="normal")
        else:
            self.itemconfig(self._id_fill,  state="hidden")
            self.itemconfig(self._id_trace, state="hidden")

        # ── 2. IF filter overlay (behind grid, over trace) ────────────────────
        if self.show_filter:
            ctr=(self.f0+self.f1)/2
            fl=self.app.state["filter_lo"]; fh=self.app.state["filter_hi"]
            x1=self._fx(ctr+fl); x2=self._fx(ctr+fh)
            xc=self._fx(ctr)
            # BUG-7: self._stipple is computed once in __init__; no per-frame import.
            self.coords(self._id_filt_r,  x1, 0, x2, draw_h)
            self.coords(self._id_filt_lo, x1, 0, x1, draw_h)
            self.coords(self._id_filt_hi, x2, 0, x2, draw_h)
            self.coords(self._id_vfo,     xc, 0, xc, draw_h)
            self.itemconfig(self._id_filt_r,  state="normal")
            self.itemconfig(self._id_filt_lo, state="normal")
            self.itemconfig(self._id_filt_hi, state="normal")
            self.itemconfig(self._id_vfo,     state="normal")
        else:
            self.itemconfig(self._id_filt_r,  state="hidden")
            self.itemconfig(self._id_filt_lo, state="hidden")
            self.itemconfig(self._id_filt_hi, state="hidden")
            self.itemconfig(self._id_vfo,     state="hidden")

        # ── 3. dB grid lines + labels (ON TOP of trace) ───────────────────────
        # Compute grid labels dynamically so they shift with DB_MAX (SCALE control).
        # Always 31 levels from DB_MAX down to DB_MIN in 5-dB steps; text only
        # every 5th line (every 25 dB).  The pre-allocated item pool is exactly
        # 31 items, matching this count regardless of the reference offset.
        _dyn_labels = [self.DB_MAX - i * 5 for i in range(31)]
        for idx, db in enumerate(_dyn_labels):
            y = self._dy(db, draw_h)
            self.coords(self._id_db_lines[idx], 0, y, w, y)
            self.coords(self._id_db_texts[idx], 2, y+1)
            if idx % 5 == 0:
                _db_int = int(db)
                txt = (f"{_db_int} dB" if _db_int == 0 else str(_db_int))
            else:
                txt = ""
            self.itemconfig(self._id_db_texts[idx], text=txt, font=gfont)

        # ── 4. Frequency grid lines + labels (ON TOP of trace) ────────────────
        # BUG-12: measure the actual rendered width of the widest dB label
        # ("-150", 4 chars) so that X-axis frequency labels don't overlap the
        # Y-axis dB labels, even when a wide custom --gui-font is in use or the
        # scale is high enough to push TkFixedFont wider than the old estimate.
        try:
            import tkinter.font as _tkfont
            _db_lbl_w = _tkfont.Font(font=gfont).measure("-150") + 4
        except Exception:
            _db_lbl_w = max(28, int(round(30 * sc)))
        span=self.f1-self.f0
        freq_slots = []   # list of (x, lbl) for active grid positions
        if span>0:
            step=nice_step(span/12)
            f=math.ceil(self.f0/step)*step
            while f<self.f1:
                x=self._fx(f)
                lbl=f"{f:.0f}" if self.af else f"{f/1000:.0f}"
                freq_slots.append((x, lbl, x >= _db_lbl_w))
                f+=step

        # Grow the retained pool if we need more slots than we have
        while len(self._id_freq_lines) < len(freq_slots):
            self._id_freq_lines.append(self.create_line(0,0,1,0, fill=C["grid"]))
            self._id_freq_texts.append(self.create_text(0,0, text="",
                                        fill=C["grid_text"], anchor="sw", font=gfont))
            self._freq_labels.append("")

        # Update visible slots
        for i, (x, lbl, show_lbl) in enumerate(freq_slots):
            self.coords(self._id_freq_lines[i], x, 0, x, draw_h)
            self.itemconfig(self._id_freq_lines[i], state="normal")
            if show_lbl:
                self.coords(self._id_freq_texts[i], x+2, draw_h+lbl_h-1)
                if self._freq_labels[i] != lbl:
                    self.itemconfig(self._id_freq_texts[i], text=lbl, font=gfont)
                    self._freq_labels[i] = lbl
                self.itemconfig(self._id_freq_texts[i], state="normal")
            else:
                self.itemconfig(self._id_freq_texts[i], state="hidden")

        # Hide unused pool slots
        for i in range(len(freq_slots), len(self._id_freq_lines)):
            self.itemconfig(self._id_freq_lines[i], state="hidden")
            self.itemconfig(self._id_freq_texts[i], state="hidden")

        # ── 5. Separator line between trace area and label strip ──────────────
        self.coords(self._id_sep, 0, draw_h, w, draw_h)
        self.itemconfig(self._id_sep, state="normal")

        # ── 6. Green peak/hold line (tracks per-bin maximum with decay) ─────────
        if n >= 2:
            if _np is not None:
                data_arr = _np.asarray(self.data, dtype=_np.float64)
                # Initialise or resize peak buffer when bin count changes
                if self._peak is None or len(self._peak) != n:
                    self._peak = data_arr.copy()
                else:
                    pk = _np.asarray(self._peak, dtype=_np.float64)
                    self._peak = _np.maximum(pk - self._peak_decay, data_arr)
                xs = _np.linspace(0.0, w, n, endpoint=False)
                ys = draw_h - _np.clip((self._peak - self.DB_MIN) /
                                       (self.DB_MAX - self.DB_MIN), 0.0, 1.0) * draw_h
                pk_flat = _np.empty(2 * n, dtype=_np.float64)
                pk_flat[0::2] = xs; pk_flat[1::2] = ys
                peak_pts = pk_flat.tolist()
            else:
                # Initialise or resize peak buffer when bin count changes
                if self._peak is None or len(self._peak) != n:
                    self._peak = list(self.data)
                else:
                    # Decay existing peaks toward current data; never rise above 0 dB
                    self._peak = [
                        max(p - self._peak_decay, d)
                        for p, d in zip(self._peak, self.data)
                    ]
                peak_pts = []
                for i in range(n):
                    peak_pts.extend([i / (n - 1) * w, self._dy(self._peak[i], draw_h)])
            self.coords(self._id_peak, peak_pts)
            self.itemconfig(self._id_peak, state="normal")
        else:
            self.itemconfig(self._id_peak, state="hidden")

    def _motion(self,e):
        ctr=(self.f0+self.f1)/2
        x1=self._fx(ctr+self.app.state["filter_lo"])
        x2=self._fx(ctr+self.app.state["filter_hi"])
        if abs(e.x-x1)<=self.GRAB or abs(e.x-x2)<=self.GRAB:
            self.config(cursor="sb_h_double_arrow")
        else: self.config(cursor="crosshair")

    def _press(self,e):
        ctr=(self.f0+self.f1)/2
        x1=self._fx(ctr+self.app.state["filter_lo"])
        x2=self._fx(ctr+self.app.state["filter_hi"])
        if abs(e.x-x1)<=self.GRAB: self.drag="lo"
        elif abs(e.x-x2)<=self.GRAB: self.drag="hi"
        else:
            self.drag=None
            self.app.set_frequency(round(self._xf(e.x)/10)*10)

    def _drag(self,e):
        if not self.drag: return
        ctr=(self.f0+self.f1)/2; off=self._xf(e.x)-ctr
        fl=self.app.state["filter_lo"]; fh=self.app.state["filter_hi"]
        if self.drag=="lo": fl=min(off,fh-50)
        else: fh=max(off,fl+50)
        self.app.state["filter_lo"]=round(fl)
        self.app.state["filter_hi"]=round(fh)
        self.draw()
        now=time.monotonic()
        if now-self._last>0.05:
            self._last=now
            self.app.net.send({"cmd":"set_filter","lo":round(fl),"hi":round(fh)})

    def _rel(self,e):
        if self.drag:
            self.app.net.send({"cmd":"set_filter",
                                "lo":self.app.state["filter_lo"],
                                "hi":self.app.state["filter_hi"]})
        self.drag=None

# ── S-Meter ────────────────────────────────────────────────────────────────────

class SMeter(tk.Canvas):
    LO=-127.0; HI=-33.0; S9=-73.0; AL=165.0; AR=15.0
    MAJOR=[(-121,"1"),(-109,"3"),(-97,"5"),(-85,"7"),(-73,"9"),(-53,"+20"),(-33,"+40")]
    MINOR=[-115,-103,-91,-79,-63,-43]

    def __init__(self,master,**kw):
        kw.setdefault("bg",C["panel_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.dbm=self.LO; self.txt="S0"
        self._tx_mode=False   # when True: needle at floor, label forced to 0.0 dBm
        self._sc=1.0   # current scale factor, updated by App
        self.bind("<Configure>",lambda e:self._draw())

    def set_value(self,dbm,txt):
        # Ignore incoming RX readings while TX is active.
        if self._tx_mode:
            return
        self.dbm=dbm; self.txt=txt; self._draw()

    def set_tx(self, active):
        """Switch meter into TX freeze (needle=floor, label=0.0 dBm) or back to RX."""
        self._tx_mode = bool(active)
        if active:
            self.dbm = self.LO   # pins needle to leftmost zero position
            self.txt = "TX"
        self._draw()

    def _frac(self,db): return (max(self.LO,min(self.HI,db))-self.LO)/(self.HI-self.LO)
    def _ang(self,f): return self.AL-f*(self.AL-self.AR)
    def _pt(self,cx,cy,r,f):
        a=math.radians(self._ang(f))
        return cx+r*math.cos(a),cy-r*math.sin(a)

    def _draw(self):
        self.delete("all")
        w,h=self.winfo_width(),self.winfo_height()
        if w<30 or h<20: return
        sc=self._sc
        # fonts — scale with sc
        label_fs = max(5, int(round(6*sc)))
        dbm_fs   = max(6, int(round(8*sc)))
        dbm_box_w = max(60, int(round(90*sc)))
        dbm_box_h = max(14, int(round(18*sc)))
        dbm_box_h2= max(12, int(round(16*sc)))

        cx=w/2; cy=h-max(10,int(round(14*sc))); R=min(w*0.46,cy)-3
        if R<8: return
        tick_outer=R-2
        tick_major_inner=R-max(6,int(round(10*sc)))
        tick_minor_inner=R-max(4,int(round(6*sc)))
        tick_label_r=R-max(12,int(round(19*sc)))
        arc_r=R-max(3,int(round(5*sc)))
        arc_w=max(2,int(round(3*sc)))
        needle_w=max(1,int(round(2*sc)))
        pivot_r=max(2,int(round(3*sc)))
        needle_inner=R-max(4,int(round(6*sc)))

        sw=self.AL-self.AR; bb=(cx-R,cy-R,cx+R,cy+R)
        self.create_arc(bb,start=self.AR,extent=sw,style="pieslice",
                        fill="#040c1a",outline="")
        self.create_arc(bb,start=self.AR,extent=sw,style="arc",
                        outline=C["sep"],width=1)
        ar=arc_r; sb=(cx-ar,cy-ar,cx+ar,cy+ar)
        aL=self._ang(0); aS=self._ang(self._frac(self.S9)); aR=self._ang(1)
        self.create_arc(sb,start=aS,extent=aL-aS,style="arc",
                        outline=C["smeter_grn"],width=arc_w)
        self.create_arc(sb,start=aR,extent=aS-aR,style="arc",
                        outline=C["smeter_red"],width=arc_w)
        for db,lbl in self.MAJOR:
            f=self._frac(db)
            col=C["smeter_red"] if db>self.S9 else C["text"]
            x1,y1=self._pt(cx,cy,tick_outer,f)
            x2,y2=self._pt(cx,cy,tick_major_inner,f)
            self.create_line(x1,y1,x2,y2,fill=col,width=max(1,int(round(2*sc))))
            xl,yl=self._pt(cx,cy,tick_label_r,f)
            self.create_text(xl,yl,text=lbl,fill=col,
                             font=_gui_font(label_fs,"bold"))
        for db in self.MINOR:
            f=self._frac(db)
            col=C["smeter_red"] if db>self.S9 else C["text"]
            x1,y1=self._pt(cx,cy,tick_outer,f)
            x2,y2=self._pt(cx,cy,tick_minor_inner,f)
            self.create_line(x1,y1,x2,y2,fill=col,width=1)
        # digital readout
        self.create_rectangle(2,h-dbm_box_h,dbm_box_w,h-2,
                               fill="#0a1820",outline=C["sep"])
        dbm_label = "0.0 dBm" if self._tx_mode else f"{self.dbm:.1f} dBm"
        self.create_text(max(3,int(round(5*sc))),h-max(2,int(round(4*sc))),
                         text=dbm_label,
                         fill=C["smeter_grn"],
                         font=_gui_font(dbm_fs,"bold"),anchor="sw")
        # needle
        f=self._frac(self.dbm)
        nx,ny=self._pt(cx,cy,needle_inner,f)
        self.create_line(cx,cy,nx,ny,fill=C["vfo_line"],width=needle_w)
        self.create_oval(cx-pivot_r,cy-pivot_r,cx+pivot_r,cy+pivot_r,
                         fill=C["vfo_line"],outline="")

# ── Frequency display ─────────────────────────────────────────────────────────

class FreqDisp(tk.Frame):
    """Large amber LCD-style 9-digit frequency display."""
    ND=9  # digits (without separators)

    def __init__(self,master,app,label="LO A",on_change=None,lo_select_cmd=None,**kw):
        super().__init__(master,bg=C["spec_bg"],**kw)
        self.app=app; self._lbl=[]; self._sep_lbls=[]; self._row_lbl=None
        self.value=28_495_000
        self.on_change=on_change
        self._lo_select_cmd=lo_select_cmd   # callable when label-button clicked
        self._label_text=label

        self._build_widgets()
        self.set_value(self.value,notify=False)

    def _build_widgets(self):
        # clear old
        for w in self.winfo_children(): w.destroy()
        self._lbl=[]; self._sep_lbls=[]
        sc=getattr(self.app,'_sc',1.0)
        digit_fs=max(12,int(round(BASE['freq_digit_size']*sc)))
        sep_fs=max(12,int(round(BASE['freq_sep_size']*sc)))
        lbl_fs=max(7,int(round(BASE['freq_label_size']*sc)))

        lbl_text=getattr(self,'_label_text','LO A')
        if self._lo_select_cmd:
            # Selectable button for LO A / LO B
            # width=4 is fixed to the widest label ("LO A"/"LO B") so the
            # button never resizes when the text is swapped to "TX"/"RX".
            self._row_lbl=tk.Button(self,text=lbl_text,
                     bg=C["btn_sel"],fg=C["btn_sel_fg"],
                     font=_gui_font(lbl_fs,"bold"),relief="flat",bd=0,
                     width=4,
                     padx=max(2,int(round(3*sc))),pady=0,
                     command=self._lo_select_cmd)
        else:
            self._row_lbl=tk.Label(self,text=lbl_text,
                     bg=C["spec_bg"],fg=C["text_dim"],
                     font=_gui_font(lbl_fs))
        self._row_lbl.grid(row=0,column=0,sticky="w",padx=(6,4))

        # Inner frame holds the digit/separator labels as a group so it can
        # be centered within the expanding column 1, independent of the
        # fixed-position label button in column 0.
        digits_frame=tk.Frame(self,bg=C["spec_bg"])
        digits_frame.grid(row=0,column=1,sticky="")
        self.grid_columnconfigure(0,weight=0)
        self.grid_columnconfigure(1,weight=1)

        # When background is light, amber on light is hard to read — use dark orange
        _is_light = _ARGS.bg == 'light'
        _freq_fg = "#b35000" if _is_light else C["freq_amber"]

        col=0
        for i in range(self.ND):
            if i in (3,6):
                sl=tk.Label(digits_frame,text=",",bg=C["spec_bg"],fg=_freq_fg,
                         font=_freq_font(sep_fs,"bold"),
                         padx=0)
                sl.grid(row=0,column=col,sticky="s",pady=(0,1))
                self._sep_lbls.append(sl); col+=1
            d=tk.Label(digits_frame,text="0",bg=C["spec_bg"],fg=_freq_fg,
                       font=_freq_font(digit_fs,"bold"),
                       width=1,padx=1,pady=0)
            d.grid(row=0,column=col,sticky="nsew")
            d.bind("<MouseWheel>",lambda e,i=i:self._bump(i,1 if e.delta>0 else -1))
            d.bind("<Button-4>",  lambda e,i=i:self._bump(i,1))
            d.bind("<Button-5>",  lambda e,i=i:self._bump(i,-1))
            d.bind("<Button-1>",  lambda e,i=i:self._bump(i,1))
            d.bind("<Button-3>",  lambda e,i=i:self._bump(i,-1))
            d.bind("<Double-Button-1>",self._edit)
            self._lbl.append(d); col+=1

    def rescale(self):
        self._build_widgets()
        self.set_value(self.value,notify=False)

    def _bump(self,idx,d):
        self.set_value(max(0,self.value+d*10**(self.ND-1-idx)),notify=True)

    def set_value(self,hz,notify=True):
        hz=int(max(0,min(hz,10**self.ND-1)))
        self.value=hz; s=f"{hz:0{self.ND}d}"
        for i,ch in enumerate(s): self._lbl[i].config(text=ch)
        if notify:
            (self.on_change or self.app.on_freq_changed)(hz)

    def _edit(self,_=None):
        top=tk.Toplevel(self); top.title("Set Frequency")
        top.configure(bg=C["panel_bg"]); top.transient(self.winfo_toplevel())
        top.grab_set()
        tk.Label(top,text="Frequency (Hz):",bg=C["panel_bg"],
                 fg=C["text"]).pack(padx=12,pady=(12,4))
        var=tk.StringVar(value=str(self.value))
        ent=tk.Entry(top,textvariable=var,width=16,justify="right",
                     bg=C["btn_gray"],fg=C["text"],
                     insertbackground=C["text"],relief="flat")
        ent.pack(padx=12,pady=4); ent.select_range(0,"end"); ent.focus_set()
        def apply(_=None):
            try: v=int(float(var.get()))
            except ValueError:
                ent.config(highlightthickness=2,highlightbackground="#cc2222",
                           highlightcolor="#cc2222")
                ent.after(1200,lambda:ent.config(highlightthickness=1,
                                                  highlightbackground=C["sep"],
                                                  highlightcolor=C["sep"]))
                return
            self.set_value(v,notify=True); top.destroy()
        ent.bind("<Return>",apply)
        tk.Button(top,text="Set",command=apply,bg=C["btn_gray"],
                  fg=C["text"]).pack(pady=(4,12))

# ── toolbar strip (between RF waterfall and AF area) ─────────────────────────

def _toolbar(parent,rbw="23.4 Hz",avg="2",bg=None,sc=1.0,app=None,box_id="rf",initial_view=None,
             spec_ref=0,spec_ave=None):
    if bg is None: bg=C["panel_mid"]
    h=max(16,int(round(BASE['toolbar_h']*sc)))
    fs=max(6,int(round(8*sc)))
    bar=tk.Frame(parent,bg=bg,height=h)
    bar.pack(side="top",fill="x"); bar.pack_propagate(False)

    # Resolve initial AVE: caller may pass spec_ave (int) or fall back to avg string
    if spec_ave is None:
        try:    spec_ave = max(1, min(10, int(avg)))
        except (ValueError, TypeError): spec_ave = 2

    def lbl(txt,fg,font=None):
        if font is None: font=_gui_font(fs)
        tk.Label(bar,text=txt,bg=bg,fg=fg,font=font).pack(side="left",padx=max(1,int(round(2*sc))))

    def sep():
        tk.Label(bar,text="──",bg=bg,fg=C["text_dim"],
                 font=_gui_font(max(5,int(round(7*sc))))).pack(side="left")

    # ── Mutually exclusive Waterfall / Spectrum toggle buttons ──────────────
    _state_key = f"toolbar_view_{box_id}"
    _wf_state = {"sel": initial_view if initial_view in ("Waterfall","Spectrum") else "Waterfall"}

    def _make_toggle(name, btn_ref_key):
        def _cmd():
            _wf_state["sel"] = name
            _update_toggle_colors()
            if app:
                app.state[_state_key] = name
                # Distinct commands per box and per button
                app.net.send({"cmd": "ui_display",
                               "box": box_id,
                               "view": name.lower()})
        return _cmd

    def _update_toggle_colors():
        sel = _wf_state["sel"]
        for bname, btn in _toggle_btns.items():
            if bname == sel:
                btn.config(bg=C["btn_sel"], fg=C["btn_sel_fg"])
            else:
                btn.config(bg=bg, fg=C["toolbar_wf"] if bname=="Waterfall" else C["toolbar_sp"])

    _toggle_btns = {}
    # Apply initial colours from seeded state
    _update_toggle_colors()

    def _set_view(name):
        if name in ("Waterfall", "Spectrum"):
            _wf_state["sel"] = name
            _update_toggle_colors()
    bar.set_view = _set_view

    # ── SCALE control: adjusts spectrum reference level (top of display) ─────
    # Step 5 dB, range −50..+10. Sends set_spec_ref to server and updates the
    # SpecCanvas directly so the display shifts without waiting for a data frame.
    _bfs = max(6, int(round(7*sc)))   # slightly smaller font for ± buttons
    _ref_state = {"v": max(-50, min(10, int(round(spec_ref / 5)) * 5))}

    def _spec_canvas():
        """Return the SpecCanvas for this toolbar's box (rf or af)."""
        if app is None:
            return None
        return getattr(app, "rf_spec" if box_id == "rf" else "af_spec", None)

    lbl("SCALE", C["text_dim"])
    _ref_lbl = tk.Label(bar, text=str(_ref_state["v"]), bg=C["btn_gray"],
                        fg=C["text"], font=_gui_font(_bfs), width=4, relief="flat",
                        anchor="center")
    _ref_lbl.pack(side="left", padx=max(1,int(round(1*sc))))

    def _adj_ref(delta):
        new_v = max(-50, min(10, _ref_state["v"] + delta))
        if new_v == _ref_state["v"]:
            return
        _ref_state["v"] = new_v
        _ref_lbl.config(text=str(new_v))
        sc_obj = _spec_canvas()
        if sc_obj:
            sc_obj.set_ref(new_v)
        if app:
            app.state[f"spec_ref_{box_id}"] = new_v
            app.net.send({"cmd": "set_spec_ref", "box": box_id, "value": new_v})

    tk.Button(bar, text="−", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_ref(-5)).pack(side="left", padx=0)
    tk.Button(bar, text="+", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_ref(+5)).pack(side="left", padx=0)
    lbl("dB", C["text_dim"])
    sep()

    # ── AVE control: FFT averaging count 1–10 ────────────────────────────────
    # Sent to the server as set_spec_ave; the server applies it on the SDR side.
    _ave_state = {"v": max(1, min(10, int(spec_ave)))}

    lbl("AVE", C["text_dim"])
    _ave_lbl = tk.Label(bar, text=str(_ave_state["v"]), bg=C["btn_gray"],
                        fg=C["text"], font=_gui_font(_bfs), width=2, relief="flat",
                        anchor="center")
    _ave_lbl.pack(side="left", padx=max(1,int(round(1*sc))))

    def _adj_ave(delta):
        new_v = max(1, min(10, _ave_state["v"] + delta))
        if new_v == _ave_state["v"]:
            return
        _ave_state["v"] = new_v
        _ave_lbl.config(text=str(new_v))
        if app:
            app.state[f"spec_ave_{box_id}"] = new_v
            app.net.send({"cmd": "set_spec_ave", "box": box_id, "value": new_v})

    tk.Button(bar, text="−", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_ave(-1)).pack(side="left", padx=0)
    tk.Button(bar, text="+", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_ave(+1)).pack(side="left", padx=0)
    sep()

    # ── Expose state-sync methods for _refresh() ──────────────────────────────
    def _set_ref_from_state(db):
        """Push a reference-level value from app.state into the toolbar and canvas."""
        new_v = max(-50, min(10, int(round(float(db) / 5)) * 5))
        if new_v != _ref_state["v"]:
            _ref_state["v"] = new_v
            _ref_lbl.config(text=str(new_v))
            sc_obj = _spec_canvas()
            if sc_obj:
                sc_obj.set_ref(new_v)

    def _set_ave_from_state(n):
        """Push an AVE value from app.state into the toolbar label."""
        new_v = max(1, min(10, int(n)))
        if new_v != _ave_state["v"]:
            _ave_state["v"] = new_v
            _ave_lbl.config(text=str(new_v))

    bar.set_ref = _set_ref_from_state
    bar.set_ave = _set_ave_from_state

    # ── ZOOM control: adjusts the RF spectrum/waterfall span ─────────────────
    # Mirrors app.adj_zoom()'s doubling/halving steps (1x..32x). This is a
    # property of the RF receiver span only — the AF box always shows a
    # fixed 0-3 kHz range — so the control is only shown on the RF toolbar.
    # (Mouse-wheel over the RF spectrum already calls the same adj_zoom();
    # these buttons just expose it directly with a readout.)
    if box_id == "rf":
        _zoom_state = {"v": int(app.state.get("zoom", 1)) if app else 1}

        lbl("Zoom", C["text_dim"])
        _zoom_lbl = tk.Label(bar, text=f'{_zoom_state["v"]}x', bg=C["btn_gray"],
                             fg=C["text"], font=_gui_font(_bfs), width=3, relief="flat",
                             anchor="center")
        _zoom_lbl.pack(side="left", padx=max(1,int(round(1*sc))))

        def _adj_zoom(delta):
            if not app:
                return
            app.adj_zoom(delta)
            new_v = int(app.state.get("zoom", _zoom_state["v"]))
            if new_v != _zoom_state["v"]:
                _zoom_state["v"] = new_v
                _zoom_lbl.config(text=f"{new_v}x")

        tk.Button(bar, text="−", bg=C["btn_gray"], fg=C["text"],
                  font=_gui_font(_bfs), relief="flat", bd=0,
                  padx=max(1,int(round(2*sc))), pady=0,
                  command=lambda: _adj_zoom(-1)).pack(side="left", padx=0)
        tk.Button(bar, text="+", bg=C["btn_gray"], fg=C["text"],
                  font=_gui_font(_bfs), relief="flat", bd=0,
                  padx=max(1,int(round(2*sc))), pady=0,
                  command=lambda: _adj_zoom(+1)).pack(side="left", padx=0)

        def _set_zoom_from_state(z):
            """Push a zoom value (e.g. after a server-side change) into the toolbar."""
            new_v = max(1, min(32, int(z)))
            if new_v != _zoom_state["v"]:
                _zoom_state["v"] = new_v
                _zoom_lbl.config(text=f"{new_v}x")

        bar.set_zoom = _set_zoom_from_state
        sep()

    # ── SPEED control: waterfall scroll speed for this box's canvas ──────────
    # 1 (slowest) .. 10 (fastest/full-rate). Throttles how often an incoming
    # spectrum frame is actually drawn as a new waterfall row — see
    # WFCanvas.add_row()/set_speed(). Each box (RF / AF) has its own
    # waterfall canvas and its own independent speed setting.
    _wf_attr = "rf_wf" if box_id == "rf" else "af_wf"
    _speed_state = {"v": max(1, min(10, int(app.state.get(f"wf_speed_{box_id}", 10)))) if app else 10}

    def _wf_canvas():
        return getattr(app, _wf_attr, None) if app else None

    lbl("Speed", C["text_dim"])
    _speed_lbl = tk.Label(bar, text=str(_speed_state["v"]), bg=C["btn_gray"],
                          fg=C["text"], font=_gui_font(_bfs), width=2, relief="flat",
                          anchor="center")
    _speed_lbl.pack(side="left", padx=max(1,int(round(1*sc))))

    def _adj_speed(delta):
        new_v = max(1, min(10, _speed_state["v"] + delta))
        if new_v == _speed_state["v"]:
            return
        _speed_state["v"] = new_v
        _speed_lbl.config(text=str(new_v))
        wf = _wf_canvas()
        if wf:
            wf.set_speed(new_v)
        if app:
            app.state[f"wf_speed_{box_id}"] = new_v

    tk.Button(bar, text="−", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_speed(-1)).pack(side="left", padx=0)
    tk.Button(bar, text="+", bg=C["btn_gray"], fg=C["text"],
              font=_gui_font(_bfs), relief="flat", bd=0,
              padx=max(1,int(round(2*sc))), pady=0,
              command=lambda: _adj_speed(+1)).pack(side="left", padx=0)

    def _set_speed_from_state(v):
        """Push a speed value into the toolbar label and the live canvas."""
        new_v = max(1, min(10, int(v)))
        if new_v != _speed_state["v"]:
            _speed_state["v"] = new_v
            _speed_lbl.config(text=str(new_v))
        wf = _wf_canvas()
        if wf:
            wf.set_speed(new_v)

    bar.set_speed = _set_speed_from_state
    # Apply the initial speed to the canvas now (it already exists by the
    # time the toolbar is built — see _build_left()/_build_main()).
    _set_speed_from_state(_speed_state["v"])

    return bar

# ── CAT GUI function button helper ──────────────────────────────────────────────

def _fbtn(parent,text,fg=None,bg=None,command=None,sc=1.0,**kw):
    if fg is None: fg=C["btn_sel_fg"]   # match LO A button fg
    if bg is None: bg=C["btn_grn"]
    fs=max(6,int(round(8*sc)))
    # No fixed width/padx — button auto-sizes to contain its label
    b=tk.Button(parent,text=text,bg=bg,fg=fg,
                activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                font=_gui_font(fs),relief="flat",bd=1,
                command=command or (lambda:None),**kw)
    return b

# ── Main Application ──────────────────────────────────────────────────────────

class App:
    def __init__(self,root):
        self.root=root
        self.root.title("CAT GUI Interface")
        self.root.configure(bg=C["win_bg"])

        try:
            root.tk.call("font","create","_MorgentaLoad","-family","Morgenta Regular")
        except tk.TclError: pass
        try:
            root.option_add("*Font","TkDefaultFont")
        except tk.TclError: pass
        try:
            # Disabled labels use the same dim color as the LO A label
            root.option_add("*Label.disabledForeground",C["text_dim"])
        except tk.TclError: pass

        self.net=Net(self); self.q=queue.Queue()
        self.rtp_audio = RTPAudioClient("", 0)   # configured when server sends audio_port
        self.rtp_audio._af_app = self  # lets it push real-time AF spectrum updates
        # PTT must stay disabled until the RTP socket has actually bound and
        # local_udp_port() can return a real value — otherwise an early click
        # would send {"udp_port": None} to the server (see _ptt_click below).
        self._ptt_enabled = False

        # Apply --audio-mic / --audio-speaker device selection, if given.
        if _ARGS.audio_mic is not None or _ARGS.audio_speaker is not None:
            devices = self.rtp_audio.get_devices()
            by_idx  = {d["index"]: d for d in devices}

            def _check(idx, tag, key):
                if idx is None:
                    return None
                d = by_idx.get(idx)
                if d is None or d[key] <= 0:
                    print(f"[audio] WARNING: --audio-{tag} {idx} is not a valid "
                          f"{'input' if key=='max_input_channels' else 'output'} "
                          f"device index — see --audio-list. Using system default.")
                    return None
                return idx

            mic_idx = _check(_ARGS.audio_mic,     "mic",     "max_input_channels")
            spk_idx = _check(_ARGS.audio_speaker, "speaker", "max_output_channels")
            self.rtp_audio.set_devices(mic_idx, spk_idx)
            mic_name = by_idx[mic_idx]["name"] if mic_idx is not None else "System default"
            spk_name = by_idx[spk_idx]["name"] if spk_idx is not None else "System default"
            print(f"[audio] CLI device selection — mic={mic_idx} ({mic_name})  "
                  f"speaker={spk_idx} ({spk_name})")

        self.state=dict(
            lo_freq=28_495_000, lo_b_freq=28_495_000, tune_freq=28_505_000,
            filter_lo=100, filter_hi=600,
            mode="USB",
            rf_gain=20.0, volume=80.0, squelch=-130.0,
            agc_thresh=-100.0,
            zoom=1, sample_rate=192_000.0, running=False,
            ptt=False,
            user_buttons=[{"label":"","type":"normal"} for _ in range(14)],
            user_btn_state=[False]*14,
            rf_usr_btns=[{"label":"","type":"normal"} for _ in range(11)],
            rf_usr_btn_state=[False]*11,
            user_mod_labels=[""]*10,  # up to 10 user-defined modulation buttons
            user_mod_types=["normal"]*10,
            toolbar_view_rf="Waterfall",
            toolbar_view_af="Waterfall",
            # Spectrum display controls (G90 SCALE and AVE).
            # spec_ref_* = reference level in dB (top of spectrum, step 5 dB).
            # spec_ave_* = FFT averaging count (1–10).
            spec_ref_rf=0, spec_ave_rf=2,
            spec_ref_af=0, spec_ave_af=1,
            # Waterfall scroll speed per box (1 slowest .. 10 fastest); see
            # WFCanvas.set_speed(). Default 10 = full rate (legacy behaviour).
            wf_speed_rf=10, wf_speed_af=10,
            split=False,
        )
        self._sup=False
        # True only when the operator explicitly pressed Stop — used by
        # _on_connect_result to decide whether to auto-send "start" on
        # reconnect.  False on first connect so the radio always starts up.
        self._user_stopped = False
        # HiDPI / 4K scaling state
        _requested_scale = max(-5, min(5, _ARGS.scale))
        # When the user hasn't explicitly set a scale (default=0 from config),
        # auto-pick the best level for the current display resolution so the GUI
        # fits comfortably from 1024x768 all the way up to 3840x2160 and beyond.
        # If --scale was given on the CLI, always honour it exactly — never
        # override it with auto-detection, even when the value happens to be 0.
        if not _ARGS.scale_explicit:
            _sw = self.root.winfo_screenwidth()
            _sh = self.root.winfo_screenheight()
            _requested_scale = _auto_scale_for_screen(_sw, _sh)
        self._scale_level = _requested_scale  # from --scale flag (or auto-detected)
        self._sc = 1.25 ** self._scale_level  # current visual scale factor
        self._build()
        self._refresh()
        self._clock()
        self.poll()
        if _ARGS.autoconnect:
            # Kick off the connection attempt once the window has finished
            # building, reusing the normal connect/result flow so behavior
            # (hello burst, auto-start, error handling) is identical to a
            # manual click — there's just no button for the operator to click.
            self.root.after(50, self._toggle_connect)

    # ──────────────────────────────────────────────────────────────────────────
    def _build(self):
        r=self.root
        sc=self._sc

        # Apply initial geometry for the requested --scale, clamped to the
        # screen size so the window can't be created larger than the display
        # (which would crop control rows off-screen).
        screen_w=r.winfo_screenwidth(); screen_h=r.winfo_screenheight()
        init_w=min(scaled('win_w',sc), screen_w)
        init_h=min(scaled('win_h',sc), screen_h)
        r.geometry(f"{init_w}x{init_h}")
        r.minsize(min(scaled('min_w',sc), screen_w), min(scaled('min_h',sc), screen_h))

        # ── top: RF waterfall + spectrum strip ────────────────────────────────
        top=tk.Frame(r,bg=C["win_bg"])
        top.pack(side="top",fill="both",expand=True)
        self._top=top

        self.rf_wf=WFCanvas(top)
        self.rf_wf._app=self
        self.rf_wf.pack(side="top",fill="both",expand=True)

        spec_fr=tk.Frame(top,bg=C["spec_bg"],height=scaled('spec_h',sc))
        spec_fr.pack(side="top",fill="x"); spec_fr.pack_propagate(False)
        self._spec_fr=spec_fr
        self.rf_spec=SpecCanvas(spec_fr,self,show_filter=True)
        self.rf_spec.pack(fill="both",expand=True)

        # ── toolbar between RF and bottom ─────────────────────────────────────
        self._toolbar1_parent=r
        self._toolbar1=_toolbar(r,rbw="23.4 Hz",avg="2",sc=sc,app=self,box_id="rf",
                                initial_view=self.state.get("toolbar_view_rf","Waterfall"),
                                spec_ref=self.state.get("spec_ref_rf",0),
                                spec_ave=self.state.get("spec_ave_rf",2))

        # ── bottom row: left control panel + right AF ─────────────────────────
        bot=tk.Frame(r,bg=C["win_bg"])
        bot.pack(side="top",fill="both",expand=False)
        self._bot=bot

        self._build_left(bot)
        self._build_right(bot)

        # ── Persistent HiDPI scale +/- control (built once, never destroyed) ──
        self._build_scale_ctrl()
        # Enforce minimum height so no GUI elements vanish
        self.root.after(100, self._update_minsize)
        self.root.after(120, self._sync_bot_height)
        # Second pass for any reflow (S-meter / clock row at high DPI)
        self.root.after(300, self._sync_bot_height)
        self.root.after(320, self._apply_top_heights)

        # ── Bind window resize so bottom panel is always fully visible ─────────
        self._resize_after_id = None
        self.root.bind("<Configure>", self._on_resize, add="+")

    # ── left control panel ────────────────────────────────────────────────────
    def _build_left(self,parent):
        sc=self._sc
        lp=tk.Frame(parent,bg=C["panel_bg"],width=scaled('left_w',sc))
        lp.pack(side="left",fill="y"); lp.pack_propagate(False)
        self._lp=lp

        # ── S-meter row ───────────────────────────────────────────────────────
        sm_row=tk.Frame(lp,bg=C["panel_bg"])
        sm_row.pack(fill="x",padx=max(1,int(round(2*sc))),pady=(max(1,int(round(3*sc))),0))
        self._sm_row=sm_row

        pk_col=tk.Frame(sm_row,bg=C["panel_bg"])
        pk_col.pack(side="left")
        fs_pk=max(6,int(round(8*sc)))
        fs_pk_sm=max(5,int(round(7*sc)))

        def _mk_sm_btn(parent, text, fg, cmd_name, font):
            def _cmd():
                self.net.send({"cmd": cmd_name, "name": text})
            return tk.Button(parent, text=text, bg=C["btn_gray"], fg=fg,
                             activebackground=C["btn_sel"],
                             activeforeground=C["btn_sel_fg"],
                             font=font, relief="flat", bd=1,
                             command=_cmd)

        _mk_sm_btn(pk_col,"Peak",C["btn_grn_fg"],"ui_smeter_btn",
                   _gui_font(fs_pk)).pack(anchor="nw",padx=max(1,int(round(2*sc))),pady=0,fill="x")
        _mk_sm_btn(pk_col,"S-units",C["text_dim"],"ui_smeter_btn",
                   _gui_font(fs_pk_sm)).pack(anchor="w",padx=max(1,int(round(2*sc))),pady=0,fill="x")
        _mk_sm_btn(pk_col,"Squelch",C["text_dim"],"ui_smeter_btn",
                   _gui_font(fs_pk_sm)).pack(anchor="w",padx=max(1,int(round(2*sc))),pady=0,fill="x")

        # ── PTT circular button ───────────────────────────────────────────────
        # Pack PTT *before* the smeter (side="right") so it is always anchored
        # to the right edge of sm_row and is never squeezed off-screen when the
        # smeter takes expand=True space at small scale values.
        ptt_size = max(36, int(round(54 * sc)))
        ptt_col = tk.Frame(sm_row, bg=C["panel_bg"],
                           width=ptt_size + max(4, int(round(8*sc))))
        ptt_col.pack_propagate(False)   # hold fixed width so smeter can't steal it
        ptt_col.pack(side="right", fill="y",
                     padx=(0, max(2, int(round(4*sc)))))
        self._ptt_canvas = tk.Canvas(ptt_col, width=ptt_size, height=ptt_size,
                                     bg=C["panel_bg"], highlightthickness=0)
        # expand=True + fill="both" + anchor="center" centres the square canvas
        # both horizontally and vertically inside ptt_col for every scale level.
        self._ptt_canvas.pack(expand=True, fill="both", anchor="center")

        sm_w=scaled('smeter_w',sc); sm_h=scaled('smeter_h',sc)
        self.smeter=SMeter(sm_row,width=sm_w,height=sm_h)
        self.smeter._sc=sc
        self.smeter.pack(side="left",fill="x",expand=True,
                         padx=(max(1,int(round(2*sc))),max(2,int(round(4*sc)))))
        fs_ptt = max(6, int(round(7*sc)))
        self._ptt_size = ptt_size

        def _draw_ptt_btn(active, enabled=None):
            if enabled is None:
                enabled = getattr(self, "_ptt_enabled", False)
            c = self._ptt_canvas
            c.delete("all")
            # Use the actual rendered canvas dimensions so the circle is always
            # centred even when the packer has resized the canvas via fill="both".
            cw = c.winfo_width()
            ch = c.winfo_height()
            # Fallback to stored size before the first layout pass
            if cw < 2:
                cw = self._ptt_size
            if ch < 2:
                ch = self._ptt_size
            # Draw in a square region centred inside (cw x ch)
            sz = min(cw, ch)
            ox = (cw - sz) // 2
            oy = (ch - sz) // 2
            margin = max(3, int(round(4*sc)))
            if not enabled:
                fill_color  = "#444444"
                rim_color   = "#666666"
                label_color = "#999999"
            else:
                fill_color = "#cc1111" if active else "#117711"
                rim_color  = "#ff4444" if active else "#22ee44"
                label_color = "#ffcccc" if active else "#ccffcc"
            c.create_oval(ox + margin, oy + margin,
                          ox + sz - margin, oy + sz - margin,
                          fill=fill_color, outline=rim_color,
                          width=max(2, int(round(3*sc))))
            # Subtle inner highlight
            hi = margin + max(3, int(round(5*sc)))
            inner_outline = "#777777" if not enabled else ("#cc4444" if active else "#44aa44")
            c.create_oval(ox + hi, oy + hi,
                          ox + sz - hi, oy + sz - hi,
                          fill="", outline=inner_outline,
                          width=max(1, int(round(2*sc))))
            c.create_text(cw // 2, ch // 2, text="PTT",
                          fill=label_color,
                          font=_gui_font(fs_ptt, "bold"))

        self._draw_ptt_btn = _draw_ptt_btn
        _draw_ptt_btn(False, enabled=False)
        self._ptt_canvas.config(cursor="arrow")
        # Redraw the circle centred whenever the canvas is resized (window
        # resize, scale change, etc.) so it never drifts off-centre.
        self._ptt_canvas.bind(
            "<Configure>",
            lambda _e: _draw_ptt_btn(bool(self.state.get("ptt", False)))
        )

        def _ptt_click(_evt=None):
            if not getattr(self, "_ptt_enabled", False):
                # Audio channel hasn't bound a local UDP port yet — ignore the
                # click rather than send a bogus {"udp_port": None} to the server.
                return
            new_state = not self.state.get("ptt", False)
            self.state["ptt"] = new_state
            _draw_ptt_btn(new_state)
            self.smeter.set_tx(new_state)   # freeze meter immediately on PTT press
            # Freeze / unfreeze the upper RF waterfall and spectrum immediately.
            # Data frames arriving while ptt=True are already suppressed in
            # _handle(), but calling set_tx() here shows the TX badge at once
            # rather than waiting for the next data frame to not arrive.
            self.rf_wf.set_tx(new_state)
            self.rf_spec.set_tx(new_state)
            self.af_wf.set_tx(new_state)    # show TX badge / clear on AF waterfall
            self.af_spec.set_tx(new_state)  # show TX badge / clear on AF spectrum
            self.net.send({"cmd": "set_ptt", "enabled": new_state,
                           "udp_port": self.rtp_audio.local_udp_port()})
            self.rtp_audio.set_ptt(new_state)

        self._ptt_canvas.bind("<Button-1>", _ptt_click)

        # ── Mode buttons + FreqMgr ────────────────────────────────────────────
        mode_row=tk.Frame(lp,bg=C["panel_bg"])
        mode_row.pack(fill="x",padx=max(2,int(round(4*sc))),
                      pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        # ── Modulation buttons (fully server-configured, max 4 chars) ──────────
        # 10 slots; only those with a non-empty label from the server are shown.
        # No mode name, label, or type is hardcoded in the GUI — everything
        # (label + type) is supplied by the server via user_mod_labels /
        # user_mod_types and may be reconfigured at any time.
        # Buttons use grid with equal column weights (10 fixed columns), the
        # same pattern as the user-button rows below, so every button keeps
        # the same static size no matter how many of the 10 slots currently
        # have a label. pack(fill="x", expand=True) was used previously, but
        # that resizes every visible button each time a sibling slot is
        # shown or hidden.
        fs_mode=max(6,int(round(8*sc)))
        self.mode_btns={}
        _px_mode=max(1,int(round(1*sc)))
        for col in range(10):
            mode_row.grid_columnconfigure(col,weight=1,uniform="modebtn")
        for _umi in range(10):
            _umidx=_umi+1
            _umb=tk.Button(mode_row,text="",width=5,
                           command=lambda i=_umi:None,  # updated in _refresh
                           bg=C["btn_gray"],fg=C["btn_sel_fg"],
                           activebackground=C["btn_sel"],
                           font=_gui_font(fs_mode),relief="flat",bd=1,
                           padx=max(1,int(round(2*sc))),pady=max(1,int(round(1*sc))))
            _umb.grid(row=0,column=_umi,padx=_px_mode,sticky="ew")
            # Slot's column is reserved even while hidden, so the fixed size
            # never shifts — _refresh shows/hides it with grid()/grid_remove().
            self.mode_btns[_umidx]=_umb


        # ── LO + Tune freq displays ───────────────────────────────────────────
        freq_box=tk.Frame(lp,bg=C["spec_bg"],bd=0)
        freq_box.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))

        # Track which LO is active (A or B) and last band selected per LO
        self._lo_active=tk.StringVar(value=self.state.get("lo_active","A"))
        self._lo_band={"A":None,"B":None}   # last selected band name per LO

        def _select_lo(which):
            self._lo_active.set(which)
            _refresh_lo_btns()
            # Restore the band highlight for this LO
            _refresh_band_highlight()
            # Immediately re-centre on the selected LO frequency, reading
            # directly from the display widget so any pending digit edits
            # are included without waiting for a server round-trip.
            if which=="A":
                hz=self.lo_disp.value if hasattr(self,'lo_disp') else self.state["lo_freq"]
            else:
                hz=self.lo_b_disp.value if hasattr(self,'lo_b_disp') else self.state["lo_b_freq"]
            self._update_rf_view(hz)
            self.root.update_idletasks()
            self.net.send({"cmd":"set_lo","lo":which})

        def _refresh_lo_btns():
            a=self._lo_active.get()
            for w,btn in [("A",self._lo_a_disp._row_lbl),
                          ("B",self._lo_b_disp._row_lbl)]:
                if a==w:
                    btn.config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
                else:
                    btn.config(bg=C["btn_gray"],fg=C["text_dim"])

        def _refresh_band_highlight():
            """Light up the band button that was last used for the current LO."""
            active=self._lo_active.get()
            cur=self._lo_band[active]
            for bname,_bw in self._band_btns.items():
                if bname==cur:
                    self._band_btns[bname].config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
                else:
                    self._band_btns[bname].config(bg=C["btn_gray"],fg=C["btn_sel_fg"])

        # Expose refresh helpers so _change_scale can call them after a rebuild
        # without having to re-enter _build_left's scope.
        self._refresh_lo_btns        = _refresh_lo_btns
        self._refresh_band_highlight = _refresh_band_highlight

        # ── freq_box: outer container ─────────────────────────────────────────
        # We use a grid: column 0 = LO/Tune rows (stacked, flexible width),
        # column 1 = memory ("M") buttons (one per LO/Tune row), column 2 =
        # TX/RX split-indicator labels (centered in the gap), column 3 =
        # band column spanning all rows but anchored to the top, so the
        # first band button aligns exactly with the LO A row.
        freq_box.grid_columnconfigure(0,weight=1)
        freq_box.grid_columnconfigure(1,weight=0)
        freq_box.grid_columnconfigure(2,weight=0)
        freq_box.grid_columnconfigure(3,weight=0)

        # ── Memory ("M") buttons — one per frequency row (LO A / LO B / Tune) ──
        # Grid columns 0/1/2/3 (digits / M-gap / TX-RX-gap / band buttons)
        # keep their original indices and contents untouched — nothing here
        # moves any other widget's column. The M buttons themselves are no
        # longer grid()'d into column 1 though: at small widths the digit
        # display (column 0) centers its content using the FreqDisp's own
        # internal weight=1 column, so its right edge can drift right and
        # collide with a button that's grid-pinned immediately next door.
        # Instead each M button is a fixed-size square placed with place(),
        # pinned every layout pass to the exact horizontal midpoint between
        # the live right edge of that row's last digit and the live left
        # edge of band_area (the button column at the right) — see
        # _position_mem_btns() below, called after all rows/band_area exist.
        fs_mem=max(7,int(round(8*sc)))
        mem_sq=max(16,int(round(20*sc)))   # fixed pixel side -> always square
        self._mem_btns={}   # position string ("LO A"/"LO B"/"Tune") -> Button
        def _mem_btn(position):
            btn=tk.Button(freq_box,text="M",anchor="center",
                          bg=C["btn_gray"],fg=C["btn_sel_fg"],
                          activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                          font=_gui_font(fs_mem,"bold"),relief="flat",bd=0,
                          highlightthickness=0,padx=0,pady=0,
                          command=lambda p=position:self._mem_btn_press(p))
            self._mem_btns[position]=btn
            return btn

        lo_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_row.grid(row=0,column=0,sticky="ew")
        _mem_btn("LO A")

        # Left side: LO A display
        self.lo_disp=FreqDisp(lo_row,self,label="LO A",
                              lo_select_cmd=lambda:_select_lo("A"))
        self.lo_disp._label_text="LO A"
        self._lo_a_disp=self.lo_disp
        self.lo_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_disp.set_value(self.state["lo_freq"],notify=False)

        # "TX" label — shown only while SPLIT is enabled — sits in its own
        # grid column centered in the gap between the LO A digits and the
        # band-buttons column. Text toggles in _refresh_split_ui(); the
        # column itself is always present so nothing else ever shifts.
        fs_split_lbl=max(7,int(round(BASE['freq_label_size']*sc)))
        self._split_tx_lbl=tk.Label(freq_box,text="",bg=C["spec_bg"],fg=C["btn_red_fg"],
                                     font=_gui_font(fs_split_lbl,"bold"),
                                     width=2,anchor="center")
        self._split_tx_lbl.grid(row=0,column=2,sticky="ns",
                                 padx=max(3,int(round(5*sc))))

        # ── Band buttons column — top-aligned to LO A row ─────────────────────
        # Two sub-columns: left = RF user buttons (col=1), right = band buttons (col=2)
        band_area=tk.Frame(freq_box,bg=C["spec_bg"])
        band_area.grid(row=0,column=3,rowspan=4,sticky="n",
                       padx=max(2,int(round(3*sc))),
                       pady=(max(1,int(round(2*sc))),0))
        fs_band=max(6,int(round(7*sc)))
        # Horizontal padding inside each button so a 5-char label never
        # touches the border — 3 px at scale=1, scales with sc.
        _bpx=max(3,int(round(3*sc)))
        self._band_btns={}   # name -> Button

        def _band_select(bname, bfreq):
            active=self._lo_active.get()
            self._lo_band[active]=bname
            _refresh_band_highlight()
            if active=="B":
                self.lo_b_disp.set_value(bfreq,notify=True)
            else:
                self.set_frequency(bfreq)

        # ── RF user buttons sub-column (left of band buttons) ──────────────────
        # No fixed width: button auto-sizes to its label + _bpx padding so any
        # label up to 5 chars fits without touching borders.
        rf_usr_col=tk.Frame(band_area,bg=C["spec_bg"])
        rf_usr_col.pack(side="left",anchor="n",padx=(0,max(4,int(round(6*sc)))))
        self._rf_usr_btns={}   # idx -> Button
        for _rui in range(11):
            _ruidx=_rui+1
            _rub=tk.Button(rf_usr_col,text="",anchor="center",
                           bg=C["btn_gray"],fg=C["btn_sel_fg"],
                           activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                           font=_gui_font(fs_band),relief="flat",bd=0,highlightthickness=0,
                           padx=_bpx,pady=0,
                           command=lambda i=_ruidx:self._rf_usr_btn_press(i))
            # Do not pack now — _refresh packs/forgets based on server labels
            self._rf_usr_btns[_ruidx]=_rub

        # ── Band buttons sub-column (right of RF user buttons) ─────────────────
        # No fixed width: auto-sizes to widest label ("160m" = 4 chars) + padding.
        band_col=tk.Frame(band_area,bg=C["spec_bg"])
        band_col.pack(side="left",anchor="n")

        for bname,bfreq in BANDS:
            b=tk.Button(band_col,text=bname,anchor="center",
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                        font=_gui_font(fs_band),relief="flat",bd=0,highlightthickness=0,
                        padx=_bpx,pady=0,
                        command=lambda n=bname,f=bfreq:_band_select(n,f))
            b.pack(fill="x",padx=0,pady=(0,max(0,int(round(1*sc)))))
            self._band_btns[bname]=b

        # ── SPLIT toggle — sits between LO A and LO B rows ─────────────────────
        split_row=tk.Frame(freq_box,bg=C["spec_bg"])
        split_row.grid(row=1,column=0,sticky="w",
                       padx=max(1,int(round(2*sc))),
                       pady=(0,max(0,int(round(1*sc)))))
        fs_split=max(6,int(round(7*sc)))
        self._split_btn=tk.Button(split_row,text="SPLIT",anchor="center",
                       bg=C["btn_gray"],fg=C["btn_sel_fg"],
                       activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                       font=_gui_font(fs_split,"bold"),relief="flat",bd=0,highlightthickness=0,
                       padx=max(4,int(round(6*sc))),pady=max(1,int(round(1*sc))),
                       command=lambda:self._toggle_split())
        self._split_btn.pack(side="left")

        self._swap_btn=tk.Button(split_row,text="SWAP",anchor="center",
                       bg=C["btn_gray"],fg=C["btn_sel_fg"],
                       activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                       font=_gui_font(fs_split,"bold"),relief="flat",bd=0,highlightthickness=0,
                       padx=max(4,int(round(6*sc))),pady=max(1,int(round(1*sc))),
                       command=lambda:self._swap_lo_a_b())
        self._swap_btn.pack(side="left",padx=(max(2,int(round(3*sc))),0))

        lo_b_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_b_row.grid(row=2,column=0,sticky="ew")
        _mem_btn("LO B")
        self.lo_b_disp=FreqDisp(lo_b_row,self,label="LO B",
                                on_change=self.on_lo_b_changed,
                                lo_select_cmd=lambda:_select_lo("B"))
        self.lo_b_disp._label_text="LO B"
        self._lo_b_disp=self.lo_b_disp
        self.lo_b_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_b_disp.set_value(self.state["lo_b_freq"],notify=False)

        # "RX" label — counterpart to the TX label above, centered in the
        # same gap column at the LO B row.
        self._split_rx_lbl=tk.Label(freq_box,text="",bg=C["spec_bg"],fg=C["btn_grn_fg"],
                                     font=_gui_font(fs_split_lbl,"bold"),
                                     width=2,anchor="center")
        self._split_rx_lbl.grid(row=2,column=2,sticky="ns",
                                 padx=max(3,int(round(5*sc))))

        # Apply initial LO button colours
        _refresh_lo_btns()
        # Apply initial SPLIT button/label state
        self._refresh_split_ui()

        tune_row=tk.Frame(freq_box,bg=C["spec_bg"])
        tune_row.grid(row=3,column=0,sticky="ew")
        _mem_btn("Tune")
        self.tune_disp=FreqDisp(tune_row,self,label="Tune",on_change=self.on_tune_changed)
        self.tune_disp._label_text="Tune"
        self.tune_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.tune_disp.set_value(self.state["tune_freq"],notify=False)

        # ── Position the M buttons ──────────────────────────────────────────
        # Square (mem_sq x mem_sq, fixed pixel size) and pinned every layout
        # pass to the exact horizontal midpoint between the live right edge
        # of that row's last digit and the live left edge of band_area (the
        # button column at the right). Uses place() purely for the M
        # buttons themselves — every other widget here keeps its original
        # grid column, so nothing else moves.
        _mem_rows={"LO A":self.lo_disp,"LO B":self.lo_b_disp,"Tune":self.tune_disp}
        def _position_mem_btns(event=None):
            try:
                freq_box.update_idletasks()
                fb_x=freq_box.winfo_rootx()
                band_left=band_area.winfo_rootx()-fb_x
                for position,btn in self._mem_btns.items():
                    disp=_mem_rows[position]
                    last_digit=disp._lbl[-1]
                    digit_right=last_digit.winfo_rootx()+last_digit.winfo_width()-fb_x
                    row_mid_y=disp.winfo_rooty()-freq_box.winfo_rooty()+disp.winfo_height()/2
                    mid_x=(digit_right+band_left)/2
                    btn.place(in_=freq_box,x=mid_x,y=row_mid_y,
                              width=mem_sq,height=mem_sq,anchor="center")
                    # The TX/RX labels (column 2) are created after these M
                    # buttons, so without this they'd stack on top of the M
                    # buttons near LO A / LO B (Tk z-orders later-created
                    # siblings above earlier ones) — covering both the
                    # button's label and its click target. Lifting here
                    # keeps the M buttons clickable and visible every pass.
                    btn.lift()
            except Exception:
                pass
        self._position_mem_btns=_position_mem_btns
        freq_box.bind("<Configure>",_position_mem_btns)
        freq_box.after(0,_position_mem_btns)
        freq_box.after(120,_position_mem_btns)

        # ── Volume / AGC Thresh sliders ───────────────────────────────────────
        sv=tk.Frame(lp,bg=C["panel_bg"])
        sv.pack(fill="x",padx=max(3,int(round(6*sc))),
                pady=(max(2,int(round(3*sc))),max(1,int(round(1*sc)))))
        fs_sl=max(6,int(round(8*sc)))
        sl_len=max(100,int(round(180*sc)))
        tk.Label(sv,text="Volume",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=0,column=0,sticky="w")
        self.vol_var=tk.DoubleVar(value=self.state["volume"])
        tk.Scale(sv,from_=0,to=100,orient="horizontal",variable=self.vol_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_volume","value":float(v)})
                 ).grid(row=0,column=1,sticky="ew",padx=max(2,int(round(4*sc))))
        tk.Label(sv,text="AGC Thresh.",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=1,column=0,sticky="w")
        self.agct_var=tk.DoubleVar(value=self.state.get("agc_thresh",-100))
        tk.Scale(sv,from_=-140,to=-20,orient="horizontal",variable=self.agct_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_agc_thresh","value":float(v)})
                 ).grid(row=1,column=1,sticky="ew",padx=max(2,int(round(4*sc))))
        tk.Label(sv,text="RF Gain",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=2,column=0,sticky="w")
        self.rfg_var=tk.DoubleVar(value=self.state.get("rf_gain",20.0))
        tk.Scale(sv,from_=0,to=60,orient="horizontal",variable=self.rfg_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_rf_gain","value":float(v)})
                 ).grid(row=2,column=1,sticky="ew",padx=max(2,int(round(4*sc))))
        tk.Label(sv,text="Squelch",bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(fs_sl)).grid(row=3,column=0,sticky="w")
        self.sql_var=tk.DoubleVar(value=self.state.get("squelch",-130.0))
        tk.Scale(sv,from_=-140,to=0,orient="horizontal",variable=self.sql_var,
                 bg=C["panel_bg"],fg=C["text"],troughcolor=C["btn_gray"],
                 highlightthickness=0,showvalue=0,length=sl_len,
                 command=lambda v:self.net.send({"cmd":"set_squelch","value":float(v)})
                 ).grid(row=3,column=1,sticky="ew",padx=max(2,int(round(4*sc))))

        sv.grid_columnconfigure(1, weight=1)


        # ── SDR-Device / Soundcard / Bandwidth / Sample Rate ──────────────────
        r1=tk.Frame(lp,bg=C["panel_bg"])
        r1.pack(fill="x",padx=max(2,int(round(4*sc))),pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        for t in ["Device","Bandwidth","Sample Rate"]:
            if t == "Device":
                _dcmd = self._request_device_list
            elif t == "Sample Rate":
                _dcmd = self._request_sample_rates
            else:
                _dcmd = lambda t=t: self.net.send({"cmd":"ui_button","name":t})
            _fbtn(r1,t,sc=sc,command=_dcmd
                  ).pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)
        if not _ARGS.disable_soundcard_select:
            _fbtn(r1,"Soundcard",sc=sc,
                  command=self._open_soundcard_dialog
                  ).pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)

        # ── transport bar ─────────────────────────────────────────────────────
        tb=tk.Frame(lp,bg=C["panel_bg"])
        tb.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        colors={"●":"#cc2020","▶":"#22aa22","⏸":"#aaaa20",
                "■":"#607090","◀◀":"#607090","▶▶":"#607090","∞":"#607090"}
        actions={"●":"rec","▶":"play","⏸":"pause","■":"stop",
                 "◀◀":"rw","▶▶":"ff","∞":"infinite"}
        fs_tp=max(8,int(round(BASE['btn_big_size']*sc)))
        for sym in ["●","▶","⏸","■","◀◀","▶▶","∞"]:
            tk.Button(tb,text=sym,bg=C["btn_gray"],fg=colors[sym],
                      font=_gui_font(fs_tp),relief="flat",bd=1,
                      width=2,pady=0,
                      command=lambda sym=sym:self.net.send({"cmd":"transport","action":actions[sym]})
                      ).pack(side="left",padx=max(1,int(round(1*sc))))

        # ── Start ─────────────────────────────────────────────────────────────
        r3=tk.Frame(lp,bg=C["panel_bg"])
        r3.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        self.start_btn=_fbtn(r3,"Start",sc=sc,command=self._toggle_run)
        self.start_btn.pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)

        # ── User-button rows (NR/NB RF/NB IF/AFC/Mute/AGC Med/Notch/ANotch
        #    removed — these frames now only hold the user-defined buttons
        #    below). ──────────────────────────────────────────────────────
        r4=tk.Frame(lp,bg=C["panel_bg"])
        r4.pack(fill="x",padx=max(2,int(round(4*sc))),
                pady=(max(2,int(round(4*sc))),max(1,int(round(1*sc)))))
        fs_dsp=max(6,int(round(8*sc)))

        r5=tk.Frame(lp,bg=C["panel_bg"])
        r5.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))

        # ── User-defined buttons (1-7 on row r4, 8-14 on row r5). Labels/
        #    types come from the server; can be "normal" (momentary press)
        #    or "push" (push-push/toggle). Buttons use grid with equal
        #    column weights so every button has the same static width and
        #    the two rows together fully span the panel width. ───────────
        self.user_btns={}
        _ubtn_px=max(1,int(round(1*sc)))
        for col in range(7):
            r4.grid_columnconfigure(col,weight=1,uniform="userbtn")
        for col in range(7):
            idx=col+1
            b=tk.Button(r4,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        disabledforeground=C["text_dim"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        anchor="center",
                        padx=max(2,int(round(2*sc))),pady=max(1,int(round(2*sc))))
            b.grid(row=0,column=col,padx=_ubtn_px,sticky="ew"); self.user_btns[idx]=b
        for col in range(7):
            r5.grid_columnconfigure(col,weight=1,uniform="userbtn")
        for col in range(7):
            idx=col+8
            b=tk.Button(r5,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        disabledforeground=C["text_dim"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        anchor="center",
                        padx=max(2,int(round(2*sc))),pady=max(1,int(round(2*sc))))
            b.grid(row=0,column=col,padx=_ubtn_px,sticky="ew"); self.user_btns[idx]=b

        # ── Date/time + connect controls (bottom of left panel) ──────────────
        bot_l=tk.Frame(lp,bg=C["panel_bg"])
        bot_l.pack(fill="x",padx=max(2,int(round(4*sc))),
                   pady=(max(4,int(round(8*sc))),max(2,int(round(3*sc)))),side="bottom")
        fs_clk=max(8,int(round(BASE['clock_size']*sc)))
        fs_cr=max(6,int(round(8*sc)))

        # ── Connect controls (host / port / connect / status dot) ────────────
        cr=tk.Frame(bot_l,bg=C["panel_bg"])
        # Determine if host/port were supplied via CLI flags
        _cli_host = _ARGS.host is not None
        # Always create the StringVars; pre-fill from flags if provided
        self.host_var=tk.StringVar(value=_ARGS.host if _cli_host else "127.0.0.1")
        self.port_var=tk.StringVar(value=str(_ARGS.port) if _cli_host else "50101")
        if _ARGS.autoconnect:
            # Autoconnect mode: the whole host/port/connect/status row is
            # erased from the GUI (cr is never packed). self.conn_btn and
            # self.conn_status still need to exist because _toggle_connect /
            # _on_connect_result / _on_disconnected reference them, so they
            # are created here but simply never packed/shown.
            self.conn_btn=tk.Button(cr,text="Connect",command=self._toggle_connect)
            self.conn_status=tk.Label(cr,text="●")
        else:
            cr.pack(fill="x",anchor="w")
            if not _cli_host:
                # Show editable host/port fields only when not supplied via CLI
                tk.Label(cr,text="Host:",bg=C["panel_bg"],fg=C["text_dim"],
                         font=_gui_font(fs_cr)).pack(side="left",padx=(0,max(1,int(round(2*sc)))))
                tk.Entry(cr,textvariable=self.host_var,width=13,
                         bg=C["btn_gray"],fg=C["text"],insertbackground=C["text"],
                         relief="flat",font=_gui_font(fs_cr)
                         ).pack(side="left",padx=(0,max(2,int(round(4*sc)))))
                tk.Label(cr,text="Port:",bg=C["panel_bg"],fg=C["text_dim"],
                         font=_gui_font(fs_cr)).pack(side="left",padx=(0,max(1,int(round(2*sc)))))
                tk.Entry(cr,textvariable=self.port_var,width=6,
                         bg=C["btn_gray"],fg=C["text"],insertbackground=C["text"],
                         relief="flat",font=_gui_font(fs_cr)
                         ).pack(side="left",padx=(0,max(2,int(round(4*sc)))))
            self.conn_btn=tk.Button(cr,text="Connect",
                                    command=self._toggle_connect,
                                    bg="#0e2a10",fg=C["btn_grn_fg"],
                                    activebackground=C["btn_sel"],
                                    font=_gui_font(fs_cr,"bold"),relief="flat",bd=1,
                                    padx=max(4,int(round(6*sc))),pady=max(1,int(round(2*sc))))
            self.conn_btn.pack(side="left",padx=max(1,int(round(1*sc))))
            fs_dot=max(9,int(round(BASE['conn_dot_size']*sc)))
            self.conn_status=tk.Label(cr,text="●",bg=C["panel_bg"],fg="#331111",
                                      font=_gui_font(fs_dot))
            self.conn_status.pack(side="left",padx=max(2,int(round(4*sc))))

        # ── Date / time — own row at very bottom of box ───────────────────────
        self.clock_var=tk.StringVar(value="")
        clk_row=tk.Frame(bot_l,bg=C["panel_bg"])
        clk_row.pack(fill="x",anchor="w",pady=(max(1,int(round(2*sc))),0))
        tk.Label(clk_row,textvariable=self.clock_var,bg=C["panel_bg"],
                 fg=C["text_grn"],font=_gui_font(fs_clk,"bold")
                 ).pack(side="left",padx=max(2,int(round(4*sc))))

        # small yellow battery/progress bar at very bottom
        prog=tk.Frame(lp,bg=C["panel_bg"],height=max(4,int(round(6*sc))))
        prog.pack(fill="x",side="bottom")
        tk.Frame(prog,bg="#aaaa00",width=max(8,int(round(12*sc))),
                 height=max(3,int(round(5*sc)))).pack(side="left",pady=1,padx=2)

    # ── right: AF waterfall + spectrum (optionally split with a text panel) ──
    def _build_right(self,parent):
        sc=self._sc
        rp=tk.Frame(parent,bg=C["spec_bg"])
        rp.pack(side="left",fill="both",expand=True)
        self._rp=rp

        # Horizontal split container: left = waterfall/spectrum (always),
        # right = text/chat panel (only packed when a "text"/"text_input"
        # user-mod button is the active mode).
        split=tk.Frame(rp,bg=C["spec_bg"])
        split.pack(side="top",fill="both",expand=True)
        self._audio_split=split

        left=tk.Frame(split,bg=C["spec_bg"])
        left.pack(side="left",fill="both",expand=True)
        self._audio_left=left

        self.af_wf=WFCanvas(left,af=True)
        self.af_wf._app=self
        self.af_wf.pack(side="top",fill="both",expand=True)

        af_sf=tk.Frame(left,bg=C["spec_bg"],height=scaled('af_spec_h',sc))
        af_sf.pack(side="top",fill="x"); af_sf.pack_propagate(False)
        self._af_sf=af_sf
        self.af_spec=SpecCanvas(af_sf,self,show_filter=False,af=True)
        self.af_spec.pack(fill="both",expand=True)

        self._toolbar2=_toolbar(left,rbw="5.9 Hz",avg="1",sc=sc,app=self,box_id="af",
                                initial_view=self.state.get("toolbar_view_af","Waterfall"),
                                spec_ref=self.state.get("spec_ref_af",0),
                                spec_ave=self.state.get("spec_ave_af",1))

        # Right-hand text/chat pane — built once here, hidden until a
        # text/text_input user-mod mode is selected (see _update_af_text_split).
        self._build_text_pane(split)
        self._audio_text_pane_visible=False
        # Re-apply the split state immediately (handles rebuilds at a new
        # scale level while a text mode is already active).
        self._update_af_text_split()

    def _build_text_pane(self,parent):
        """Build the right-hand text/chat panel used by 'text' and
        'text_input' user-mod modes. Built once per _build_right() call;
        contents are repopulated per-slot by _update_af_text_split().

        Each user-mod slot has its own independent text history stored in
        self._text_buf (dict keyed by 1-based slot index).  Switching
        between buttons saves the current widget contents to the outgoing
        slot's buffer and restores the incoming slot's buffer into the
        widget, so no text is ever lost or bleed across slots."""
        # Per-slot receive buffers survive _build_text_pane rebuilds
        # (e.g. HiDPI scale changes) because we only initialise the dict
        # when it does not already exist on self.
        if not hasattr(self,"_text_buf"):
            self._text_buf={}   # {slot_idx: [line, ...]}
        sc=self._sc
        fs=max(7,int(round(9*sc)))
        pane=tk.Frame(parent,bg=C["spec_bg"])
        self._text_pane=pane
        # Not packed here — _update_af_text_split() packs/forgets it.

        # Header showing which user-mod slot is active (e.g. "RTTY")
        hdr=tk.Frame(pane,bg=C["panel_mid"])
        hdr.pack(side="top",fill="x")
        self._text_hdr_lbl=tk.Label(hdr,text="",bg=C["panel_mid"],fg=C["text_grn"],
                                    font=_gui_font(fs,"bold"),anchor="w")
        self._text_hdr_lbl.pack(side="left",fill="x",expand=True,
                                padx=max(2,int(round(4*sc))),pady=max(1,int(round(2*sc))))

        # Upper read-only area: text received from the server.
        rx_fr=tk.Frame(pane,bg=C["spec_bg"])
        rx_fr.pack(side="top",fill="both",expand=True)
        rx_scroll=tk.Scrollbar(rx_fr,orient="vertical")
        rx_scroll.pack(side="right",fill="y")
        self._text_rx=tk.Text(rx_fr,bg=C["spec_bg"],fg=C["text"],
                              font=_gui_font(fs),wrap="word",
                              insertbackground=C["text"],
                              relief="flat",bd=0,
                              state="disabled",
                              yscrollcommand=rx_scroll.set)
        self._text_rx.pack(side="left",fill="both",expand=True,
                           padx=max(2,int(round(3*sc))),pady=max(1,int(round(2*sc))))
        rx_scroll.config(command=self._text_rx.yview)

        # Lower editable input area (only used/packed for "text_input" type):
        # max 3 visible lines, auto-scrolling, Enter sends to server.
        tx_fr=tk.Frame(pane,bg=C["panel_mid"])
        self._text_tx_fr=tx_fr
        # Not packed here — packed only for "text_input" slots.
        sep=tk.Frame(tx_fr,bg=C["sep"],height=max(1,int(round(1*sc))))
        sep.pack(side="top",fill="x")
        tx_inner=tk.Frame(tx_fr,bg=C["panel_mid"])
        tx_inner.pack(side="top",fill="both",expand=True,
                      padx=max(2,int(round(3*sc))),pady=max(2,int(round(3*sc))))
        tx_scroll=tk.Scrollbar(tx_inner,orient="vertical")
        tx_scroll.pack(side="right",fill="y")
        self._text_tx=tk.Text(tx_inner,bg=C["panel_bg"],fg=C["text"],
                              font=_gui_font(fs),wrap="word",height=3,
                              insertbackground=C["text_grn"],
                              relief="flat",bd=0,
                              yscrollcommand=tx_scroll.set)
        self._text_tx.pack(side="left",fill="both",expand=True)
        tx_scroll.config(command=self._text_tx.yview)

        def _send_text(event=None):
            idx=getattr(self,"_text_pane_idx",None)
            if idx is None:
                return "break"
            text=self._text_tx.get("1.0","end").rstrip("\n")
            if text:
                self.net.send({"cmd":"user_text","index":idx,"text":text})
                self._append_text_rx(f"> {text}")
            self._text_tx.delete("1.0","end")
            return "break"   # swallow the newline Enter would otherwise insert

        def _limit_lines(event=None):
            # Enforce a 3-line maximum by trimming any extra trailing lines
            # (e.g. pasted multi-line text), keeping auto-scroll at the end.
            content=self._text_tx.get("1.0","end-1c")
            lines=content.split("\n")
            if len(lines)>3:
                self._text_tx.delete("1.0","end")
                self._text_tx.insert("1.0","\n".join(lines[:3]))
            self._text_tx.see("end")

        self._text_tx.bind("<Return>",_send_text)
        self._text_tx.bind("<KeyRelease>",_limit_lines)

    def _append_text_rx(self,line):
        """Append one line to the read-only upper text area, auto-scroll to
        the bottom, and persist it in the per-slot buffer so the text is
        restored when the user switches back to this slot later."""
        if not hasattr(self,"_text_rx"):
            return
        # Store in the per-slot buffer (keyed by the 1-based slot index that
        # is active at the moment of the append).
        idx=getattr(self,"_text_pane_idx",None)
        if idx is not None:
            buf=self._text_buf.setdefault(idx,[])
            buf.append(line)
            # Limit buffer depth to keep memory bounded (keep last 500 lines)
            if len(buf)>500:
                del buf[:-500]
        self._text_rx.config(state="normal")
        self._text_rx.insert("end",line+"\n")
        self._text_rx.see("end")
        self._text_rx.config(state="disabled")

    def _update_af_text_split(self):
        """Show/hide the right-hand text panel in the AF/audio box based on
        whether the currently active mode is a 'text' or 'text_input'
        user-mod slot. Safe to call any time _build_right() has already run
        (including repeatedly from _refresh())."""
        if not hasattr(self,"_text_pane"):
            return
        idx,mtype=self._active_text_mod()
        want_visible = idx is not None
        if want_visible:
            uml=self.state.get("user_mod_labels") or []
            label=(uml[idx-1].strip()[:4] if idx-1<len(uml) else "") or f"MOD{idx}"
            self._text_hdr_lbl.config(text=label)
            prev_idx=getattr(self,"_text_pane_idx",None)
            self._text_pane_idx=idx
            # Repopulate the rx widget whenever the active slot changes so each
            # button has its own independent, isolated text history.
            if idx!=prev_idx:
                self._text_rx.config(state="normal")
                self._text_rx.delete("1.0","end")
                for buffered_line in self._text_buf.get(idx,[]):
                    self._text_rx.insert("end",buffered_line+"\n")
                self._text_rx.see("end")
                self._text_rx.config(state="disabled")
                # Also clear the tx entry box so the user starts fresh
                self._text_tx.delete("1.0","end")
            if not self._audio_text_pane_visible:
                self._text_pane.pack(side="left",fill="both",expand=True,
                                     padx=(max(2,int(round(2*self._sc))),0))
                self._audio_text_pane_visible=True
            if mtype=="text_input":
                try:
                    self._text_tx_fr.pack_info()
                except tk.TclError:
                    self._text_tx_fr.pack(side="bottom",fill="x")
            else:
                self._text_tx_fr.pack_forget()
        else:
            if self._audio_text_pane_visible:
                self._text_pane.pack_forget()
                self._audio_text_pane_visible=False
            self._text_pane_idx=None

    # ── HiDPI scale change ────────────────────────────────────────────────────
    def _build_scale_ctrl(self):
        """Persistent HiDPI +/- scale control.

        Built exactly once and never destroyed, so it can never 'disappear'
        even though _change_scale() destroys/rebuilds most of the rest of
        the GUI. It floats as an overlay in the bottom-right corner of the
        window. Range: -5 .. +5, default 0 (shown centered between the two
        buttons).

        If --disable-scale was passed, this control (buttons and level
        number) is not created at all.
        """
        if _ARGS.disable_scale:
            self._scale_ctrl_fr=None
            self._scale_lbl=None
            self._scale_minus_btn=None
            self._scale_plus_btn=None
            return

        sc=self._sc
        fs=max(7,int(round(BASE['scale_btn_size']*sc)))

        fr=tk.Frame(self.root,bg=C["btn_gray"],bd=1,relief="raised")
        fr.place(relx=1.0,rely=1.0,x=-4,y=-4,anchor="se")
        self._scale_ctrl_fr=fr

        self._scale_minus_btn=tk.Button(
            fr,text="−",bg=C["btn_gray"],fg=C["btn_red_fg"],
            font=_gui_font(fs,"bold"),relief="flat",bd=1,
            width=2,pady=0,command=lambda:self._change_scale(-1))
        self._scale_minus_btn.pack(side="left")

        self._scale_lbl=tk.Label(
            fr,text=str(self._scale_level),bg=C["panel_bg"],
            fg=C["text_dim"],font=_gui_font(fs,"bold"),
            width=3,anchor="center")
        self._scale_lbl.pack(side="left")

        self._scale_plus_btn=tk.Button(
            fr,text="+",bg=C["btn_gray"],fg=C["btn_grn_fg"],
            font=_gui_font(fs,"bold"),relief="flat",bd=1,
            width=2,pady=0,command=lambda:self._change_scale(1))
        self._scale_plus_btn.pack(side="left")

    def _rescale_scale_ctrl(self):
        """Update the font size of the persistent +/- scale control to match sc."""
        if _ARGS.disable_scale: return
        sc=self._sc
        fs=max(7,int(round(BASE['scale_btn_size']*sc)))
        f=_gui_font(fs,"bold")
        self._scale_minus_btn.config(font=f)
        self._scale_lbl.config(font=f)
        self._scale_plus_btn.config(font=f)

    def _fit_top_heights(self):
        """Compute the RF spectrum-strip / waterfall heights for the top of
        the window, shrinking them if necessary so that the bottom control
        panel — which holds the S-meter row down through the date/time row —
        is ALWAYS fully visible on screen, no matter how short the display
        is. The bottom panel's own height is never reduced; only the upper
        waterfall/spectrum area (and, indirectly, the AF waterfall/spectrum
        on the right, which simply fills whatever height _bot ends up with)
        gives way first.
        """
        sc = self._sc
        screen_h = self.root.winfo_screenheight()
        # Leave a little headroom for window-manager chrome / taskbars.
        avail_h  = max(240, screen_h - 90)
        tb_h     = max(16, int(round(BASE['toolbar_h'] * sc)))
        # Use real lp child-sum for bot_h so pack_propagate(False) doesn't hide content
        lp = self._lp
        lp_h = 0
        for child in lp.pack_slaves():
            try:
                lp_h += max(child.winfo_reqheight(), 1)
                info = child.pack_info()
                pady = info.get('pady', 0)
                if isinstance(pady, (list, tuple)):
                    lp_h += int(pady[0]) + int(pady[1])
                else:
                    lp_h += int(pady) * 2
            except Exception:
                pass
        bot_h = max(lp_h, self._bot.winfo_reqheight(), 60)

        spec_h_full = scaled('spec_h', sc)
        wf_min_full = max(40, int(round(60 * sc)))
        top_budget  = avail_h - tb_h - bot_h - 4

        min_wf   = 24   # absolute floors — small but still usable/visible
        min_spec = 24
        if top_budget >= spec_h_full + wf_min_full:
            spec_h, wf_h = spec_h_full, wf_min_full
        else:
            top_budget = max(top_budget, min_wf + min_spec)
            extra = top_budget - min_wf - min_spec
            # Spectrum strip degrades first (it's secondary to the
            # waterfall); waterfall keeps the larger share of any room.
            spec_h = min_spec + int(extra * 0.3)
            wf_h   = top_budget - spec_h
        return spec_h, wf_h, tb_h, bot_h

    def _update_minsize(self):
        """Compute minimum window size so the bottom control panel is always
        fully visible. The waterfall/spectrum top area is allowed to shrink
        freely, so min_h only includes the fixed-height content (toolbar +
        bottom panel). This ensures vertical resize is never blocked.
        """
        self.root.update_idletasks()
        sc = self._sc
        # Measure the real required height of lp (left panel) by summing
        # its packed children, bypassing any pack_propagate(False) suppression.
        lp = self._lp
        lp_h = 0
        for child in lp.pack_slaves():
            try:
                lp_h += max(child.winfo_reqheight(), 1)
                info = child.pack_info()
                pady = info.get('pady', 0)
                if isinstance(pady, (list, tuple)):
                    lp_h += int(pady[0]) + int(pady[1])
                else:
                    lp_h += int(pady) * 2
            except Exception:
                pass
        bot_h = max(lp_h, self._bot.winfo_reqheight(), 60)
        spec_h, wf_h, tb_h, _ = self._fit_top_heights()
        bot_w    = self._bot.winfo_reqwidth()
        # min_h = only the parts that must always be visible
        min_h    = tb_h + bot_h + 4
        min_w    = max(scaled('min_w', sc), bot_w)
        self.root.minsize(min_w, max(60, min_h))
        return min_w, min_h

    def _sync_bot_height(self):
        """Set _bot's height to the left panel's true required content height.

        lp uses pack_propagate(False) to enforce a fixed width, but that also
        suppresses height reporting to _bot, causing the bottom control area to
        be clipped at higher scale levels.  We work around this by summing the
        requisite heights of ALL of lp's packed children — regardless of whether
        they are packed side='top' or side='bottom' — and applying that total as
        _bot's explicit height, so the S-meter row, clock/date line, and connect
        controls are never clipped off-screen at any resolution.
        """
        self.root.update_idletasks()
        lp = self._lp
        total_h = 0
        for child in lp.pack_slaves():
            try:
                ch = child.winfo_reqheight()
                if ch < 1:
                    # Widget hasn't been measured yet; ask Tk directly
                    child.update_idletasks()
                    ch = child.winfo_reqheight()
                total_h += max(ch, 1)
                info = child.pack_info()
                pady = info.get('pady', 0)
                if isinstance(pady, (list, tuple)):
                    total_h += int(pady[0]) + int(pady[1])
                else:
                    total_h += int(pady) * 2
            except Exception:
                pass
        if total_h > 0:
            self._bot.pack_propagate(False)
            self._bot.config(height=total_h)
            self._update_minsize()
            self._apply_top_heights()

    def _on_resize(self, event=None):
        """Debounced handler for window <Configure> events.

        Fires whenever the window is resized (including maximise/restore).
        Schedules _apply_top_heights() 80 ms after the last resize event so
        that repeated rapid events collapse into a single layout pass rather
        than flooding the Tk event queue.
        """
        # Only react to root-window resize events, not child-widget configures.
        if event is not None and event.widget is not self.root:
            return
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.root.after(80, self._apply_top_heights)

    def _apply_top_heights(self):
        """Shrink the RF waterfall/spectrum so the bottom control panel is
        always fully visible inside the window, no matter the current window
        height.  Called both on first build (via _sync_bot_height) and on
        every window resize via the debounced _on_resize handler.

        Algorithm:
          1. Measure the natural height of _bot — fixed content, never clipped.
             When _bot has pack_propagate(False) its winfo_reqheight() may be
             stale; instead we sum lp's packed children directly.
          2. Measure the toolbar strip height (also fixed).
          3. Whatever height remains is split between the waterfall (expand,
             gets the lion's share) and the RF spectrum strip (fixed, shrinks first).
          4. Apply heights by configuring _spec_fr; the waterfall canvas keeps
             expand=True so it fills any remaining slack automatically.

        minsize is set to ONLY the fixed content (bot + toolbar) so the user
        can freely drag the window smaller — the top area simply vanishes
        rather than blocking the resize.
        """
        try:
            self.root.update_idletasks()
            win_h   = self.root.winfo_height()
            tb_h    = max(16, int(round(BASE['toolbar_h'] * self._sc)))
            sc      = self._sc

            # Compute the true required height of the left panel (lp).
            # _bot may have pack_propagate(False) so winfo_reqheight() can be
            # stale — sum lp's children instead for an accurate measurement.
            lp = self._lp
            lp_h = 0
            for child in lp.pack_slaves():
                try:
                    lp_h += max(child.winfo_reqheight(), 1)
                    info = child.pack_info()
                    pady = info.get('pady', 0)
                    if isinstance(pady, (list, tuple)):
                        lp_h += int(pady[0]) + int(pady[1])
                    else:
                        lp_h += int(pady) * 2
                except Exception:
                    pass
            # Fall back to winfo_reqheight if we couldn't measure children
            bot_h = max(lp_h, self._bot.winfo_reqheight(), 60)

            # Available pixels for the entire top area (waterfall + spec strip)
            avail_top = win_h - bot_h - tb_h - 4
            if avail_top < 0:
                avail_top = 0

            spec_h_full = scaled('spec_h', sc)
            min_spec    = 0   # spec strip can disappear entirely
            min_wf      = 0   # waterfall can disappear entirely

            if avail_top >= spec_h_full:
                spec_h = spec_h_full
            else:
                # Spec strip shrinks first; waterfall gets whatever is left
                spec_h = max(min_spec, min(avail_top, spec_h_full))
                # If there is truly no room, spec goes to zero
                if avail_top <= 0:
                    spec_h = 0

            if self._spec_fr.winfo_reqheight() != max(1, spec_h):
                self._spec_fr.config(height=max(1, spec_h))

            # Minimum window height = just enough to show the bottom panel +
            # toolbar. The top waterfall/spectrum area is allowed to shrink to
            # nothing, so we do NOT add any waterfall floor to min_h.
            min_h  = bot_h + tb_h + 4
            bot_w  = self._bot.winfo_reqwidth()
            min_w  = max(scaled('min_w', sc), bot_w)
            self.root.minsize(min_w, max(60, min_h))
            if hasattr(self, '_position_mem_btns'):
                self._position_mem_btns()
        except Exception:
            import traceback; traceback.print_exc()

    def _change_scale(self,delta):
        """Rebuild the GUI at the new scale factor.

        The +/- buttons themselves live in a persistent overlay
        (see _build_scale_ctrl) that is never destroyed, so they remain
        usable indefinitely. Scale level range is -5..+5, default 0,
        and the current level (not a percentage) is shown in the label
        between the two buttons.
        """
        self._scale_level=max(-5,min(5,self._scale_level+delta))
        self._sc=1.25**self._scale_level
        sc=self._sc

        # Save LO selection state before widgets are destroyed; _build_left
        # unconditionally re-creates _lo_active and _lo_band, so without this
        # the user's LO-B / band selection would silently reset to defaults.
        _saved_lo_active = self._lo_active.get() if hasattr(self, '_lo_active') else "A"
        _saved_lo_band   = dict(self._lo_band)    if hasattr(self, '_lo_band')   else {"A": None, "B": None}

        # Destroy and rebuild left panel and right panel inside _bot
        for child in self._bot.winfo_children():
            child.destroy()

        # Also rebuild top-area fixed-height frames (spec strip)
        self._spec_fr.config(height=scaled('spec_h',sc))

        # Rebuild left and right panels
        self._build_left(self._bot)
        self._build_right(self._bot)

        # Restore LO state that _build_left just reset to defaults, then
        # re-sync the visual highlights so the UI matches.
        self._lo_active.set(_saved_lo_active)
        self._lo_band.update(_saved_lo_band)
        self._refresh_lo_btns()
        self._refresh_band_highlight()

        # Rebuild toolbar1 (between RF strip and bot)
        self._toolbar1.destroy()
        self._toolbar1=_toolbar(self._toolbar1_parent,rbw="23.4 Hz",avg="2",sc=sc,app=self,
                                box_id="rf",
                                initial_view=self.state.get("toolbar_view_rf","Waterfall"),
                                spec_ref=self.state.get("spec_ref_rf",0),
                                spec_ave=self.state.get("spec_ave_rf",2))
        # Re-pack toolbar1 before _bot by temporarily removing _bot from the
        # geometry manager, letting _toolbar() pack itself in the correct slot,
        # then re-packing _bot with its original options.  This avoids the
        # fragile pack(before=...) call which requires both widgets to share
        # the same geometry manager — a constraint that silently breaks if
        # either widget is ever re-parented during a future refactor.
        self._bot.pack_forget()
        # _toolbar() calls bar.pack(side="top", fill="x") internally; no
        # additional pack call is needed here.
        self._bot.pack(side="top", fill="both", expand=False)

        # Update the persistent scale label/buttons to show & match the
        # current scale value/size
        if not _ARGS.disable_scale:
            self._scale_lbl.config(text=str(self._scale_level))
            self._rescale_scale_ctrl()
            # Keep the overlay control on top and re-bring it to front
            self._scale_ctrl_fr.lift()

        # Refresh state colours
        self._refresh()

        # Compute the minimum size required at this scale (this also
        # accounts for everything in the left panel, including the
        # transport buttons and "Full Screen" row, so they can never be
        # clipped off-screen).
        self.root.update_idletasks()
        min_w, min_h = self._update_minsize()

        # Clamp the requested window size to both the natural minimum
        # (so nothing is squeezed/hidden) and the available screen size
        # (so the window manager doesn't crop the bottom rows off-screen).
        # When --resolution was given, the user pinned the window size; only
        # enforce the minimum so nothing is clipped, but never override their
        # chosen dimensions with the scale-derived ideal size.
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if _ARGS.resolution:
            cur_w = self.root.winfo_width()
            cur_h = self.root.winfo_height()
            new_w = max(min_w, cur_w)
            new_h = max(min_h, cur_h)
        else:
            new_w = max(min_w, min(scaled('win_w', sc), screen_w))
            new_h = max(min_h, min(scaled('win_h', sc), screen_h))
        self.root.geometry(f"{new_w}x{new_h}")

        # Re-apply minsize once more after geometry settles, in case
        # widget reflow slightly changed the natural sizes.
        self.root.after(100, self._update_minsize)
        self.root.after(120, self._sync_bot_height)
        self.root.after(140, self._apply_top_heights)
        # A second sync pass catches any layout changes from the first pass
        # (e.g. the S-meter / clock row repacking at high scale levels).
        self.root.after(300, self._sync_bot_height)
        self.root.after(320, self._apply_top_heights)

    # ── control logic ──────────────────────────────────────────────────────────
    def _refresh(self):
        # ── Modulation buttons ──────────────────────────────────────────────
        # Show/hide based on whether the server has provided a label for
        # that slot. Label, type, and selection state all come from the
        # server (user_mod_labels / user_mod_types / state["mode"]) — no
        # mode name is hardcoded in the GUI. Visibility is toggled with
        # grid()/grid_remove() rather than pack(fill="x", expand=True)/
        # pack_forget() — each slot keeps its own fixed grid column, so a
        # button's size never changes as other slots are shown or hidden.
        _uml=self.state.get("user_mod_labels") or []
        for _umidx,_umb in self.mode_btns.items():
            _lbl=((_uml[_umidx-1].strip() if _umidx-1<len(_uml) else ""))[:4]
            if _lbl:
                _umb.config(text=_lbl,
                            command=lambda lbl=_lbl,i=_umidx:self._set_mode(lbl,i),
                            bg=C["btn_sel"] if self.state["mode"]==_lbl else C["btn_gray"],
                            fg=C["btn_sel_fg"])
                _umb.grid()
            else:
                _umb.grid_remove()
        # Apply/clear the AF-box text-panel split for the active mode (if any)
        self._update_af_text_split()
        # User-defined buttons: refresh label and (for push-push type) the
        # pressed/released highlight. A button with no label configured on
        # the server (empty string) is shown disabled/greyed-out and cannot
        # be pressed.
        for idx,b in self.user_btns.items():
            label=self._user_btn_label(idx)
            b.config(text=label)
            if not label:
                b.config(state="disabled",bg=C["panel_mid"],fg=C["text_dim"])
                continue
            cfg=self._user_btn_cfg(idx)
            if cfg.get("type")=="push":
                on=self._user_btn_state(idx)
                b.config(state="normal",
                         bg=C["btn_sel"] if on else C["btn_gray"],
                         fg=C["btn_sel_fg"])
            else:
                b.config(state="normal",bg=C["btn_gray"],fg=C["btn_sel_fg"])
        # RF user buttons: pack/unpack based on server label; update push highlight
        _sc=self._sc
        _px_rf=max(0,int(round(1*_sc)))
        for idx,b in self._rf_usr_btns.items():
            lbl=self._rf_usr_btn_label(idx)
            if lbl:
                b.config(text=lbl)
                cfg=self._rf_usr_btn_cfg(idx)
                if cfg.get("type")=="push":
                    on=self._rf_usr_btn_state(idx)
                    b.config(bg=C["btn_sel"] if on else C["btn_gray"],fg=C["btn_sel_fg"])
                else:
                    b.config(bg=C["btn_gray"],fg=C["btn_sel_fg"])
                try:
                    b.pack_info()
                except tk.TclError:
                    b.pack(fill="x",padx=0,pady=(0,_px_rf))
            else:
                b.pack_forget()
        # Toolbar toggle buttons (Waterfall / Spectrum)
        for _tb_attr, _tb_key, _box in (
                ("_toolbar1","toolbar_view_rf","rf"),
                ("_toolbar2","toolbar_view_af","af")):
            _tb = getattr(self, _tb_attr, None)
            if _tb and hasattr(_tb, "set_view"):
                _tb.set_view(self.state.get(_tb_key, "Waterfall"))
            # Sync SCALE and AVE controls from state (survives reconnect /
            # server-pushed state updates).
            if _tb and hasattr(_tb, "set_ref"):
                _tb.set_ref(self.state.get(f"spec_ref_{_box}", 0))
            if _tb and hasattr(_tb, "set_ave"):
                _tb.set_ave(self.state.get(f"spec_ave_{_box}", 2 if _box=="rf" else 1))
            if _tb and hasattr(_tb, "set_zoom"):
                _tb.set_zoom(self.state.get("zoom", 1))
            if _tb and hasattr(_tb, "set_speed"):
                _tb.set_speed(self.state.get(f"wf_speed_{_box}", 10))
        # PTT button
        if hasattr(self, '_draw_ptt_btn'):
            self._draw_ptt_btn(bool(self.state.get("ptt", False)), self._ptt_enabled)
        # SPLIT toggle / TX-RX labels
        self._refresh_split_ui()


    # ── Device selection dialog (populated from server) ───────────────────────
    def _request_device_list(self):
        """Send get_devices to the server; reply opens the Device dialog."""
        if not self.net.connected:
            messagebox.showinfo("Device", "Not connected to server.", parent=self.root)
            return
        self.net.send({"cmd": "get_devices"})

    def _open_device_dialog(self, devices):
        """Open a modal window listing up to 20 server-provided device profiles.
        Clicking a device sends select_device to the server, which reloads its
        configuration from the associated TOML file and tells the GUI to resync."""
        sc  = self._sc
        fs  = max(7, int(round(8 * sc)))
        fs_h= max(8, int(round(9 * sc)))
        pad = max(4, int(round(6 * sc)))

        top = tk.Toplevel(self.root)
        top.title("Select Device")
        top.configure(bg=C["panel_bg"])
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        tk.Label(top, text="Select a device:", bg=C["panel_bg"], fg=C["btn_grn_fg"],
                 font=_gui_font(fs_h, "bold")).pack(padx=pad, pady=(pad, 2), anchor="w")

        if not devices:
            tk.Label(top, text="No devices configured on server.",
                     bg=C["panel_bg"], fg=C["text_dim"],
                     font=_gui_font(fs)).pack(padx=pad, pady=(2, pad))
            tk.Button(top, text="Close", command=top.destroy,
                      bg=C["btn_gray"], fg=C["btn_sel_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(6, int(round(8*sc)))
                      ).pack(pady=(0, pad))
        else:
            devices = devices[:20]   # hard cap at 20
            lst_fr = tk.Frame(top, bg=C["panel_bg"])
            lst_fr.pack(fill="both", expand=True,
                        padx=pad, pady=(2, pad))

            def _select(idx):
                top.destroy()
                self.net.send({"cmd": "select_device", "index": idx})

            for dev in devices:
                didx  = dev.get("index", 0)
                label = dev.get("label", f"Device {didx}")
                btn = tk.Button(
                    lst_fr, text=label, anchor="w",
                    bg=C["btn_gray"], fg=C["btn_sel_fg"],
                    activebackground=C["btn_sel"], activeforeground=C["btn_sel_fg"],
                    font=_gui_font(fs), relief="flat", bd=1,
                    padx=max(6, int(round(8*sc))),
                    pady=max(1, int(round(2*sc))),
                    command=lambda i=didx: _select(i))
                btn.pack(fill="x", pady=(0, max(1, int(round(1*sc)))))

            sep_line = tk.Frame(lst_fr, bg=C["sep"],
                                height=max(1, int(round(1*sc))))
            sep_line.pack(fill="x", pady=(max(2, int(round(3*sc))), 0))
            tk.Button(lst_fr, text="Cancel", command=top.destroy,
                      bg=C["btn_gray"], fg=C["btn_red_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(6, int(round(8*sc))),
                      pady=max(1, int(round(2*sc)))
                      ).pack(fill="x", pady=(max(2, int(round(3*sc))), 0))

        top.update_idletasks()
        rw = self.root.winfo_x() + self.root.winfo_width()  // 2
        rh = self.root.winfo_y() + self.root.winfo_height() // 2
        tw = top.winfo_reqwidth()
        th = top.winfo_reqheight()
        top.geometry(f"+{rw - tw // 2}+{rh - th // 2}")

    # ── Sample rate selection dialog ──────────────────────────────────────────
    def _request_sample_rates(self):
        """Send get_sample_rates to the server; reply opens the Sample Rate
        dialog. The choices come from the active device's per-device TOML
        file ([sdr].sample_rates) -- they are not hard-coded in the GUI."""
        if not self.net.connected:
            messagebox.showinfo("Sample Rate", "Not connected to server.", parent=self.root)
            return
        self.net.send({"cmd": "get_sample_rates"})

    @staticmethod
    def _fmt_sample_rate(hz):
        """Render a Hz value as a short human-readable string (kHz/MHz)."""
        try:
            hz = float(hz)
        except (TypeError, ValueError):
            return str(hz)
        if hz >= 1_000_000:
            return f"{hz/1_000_000:g} MHz"
        if hz >= 1000:
            return f"{hz/1000:g} kHz"
        return f"{hz:g} Hz"

    def _open_sample_rate_dialog(self, rates, current=None):
        """Open a modal window listing the sample rates configured for the
        active device (server-provided, sourced from that device's TOML
        file). Clicking a rate sends set_sample_rate to the server."""
        sc  = self._sc
        fs  = max(7, int(round(8 * sc)))
        fs_h= max(8, int(round(9 * sc)))
        pad = max(4, int(round(6 * sc)))

        top = tk.Toplevel(self.root)
        top.title("Select Sample Rate")
        top.configure(bg=C["panel_bg"])
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        tk.Label(top, text="Select a sample rate:", bg=C["panel_bg"], fg=C["btn_grn_fg"],
                 font=_gui_font(fs_h, "bold")).pack(padx=pad, pady=(pad, 2), anchor="w")

        if not rates:
            tk.Label(top, text="No sample rates configured for this device.",
                     bg=C["panel_bg"], fg=C["text_dim"],
                     font=_gui_font(fs)).pack(padx=pad, pady=(2, pad))
            tk.Button(top, text="Close", command=top.destroy,
                      bg=C["btn_gray"], fg=C["btn_sel_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(6, int(round(8*sc)))
                      ).pack(pady=(0, pad))
        else:
            lst_fr = tk.Frame(top, bg=C["panel_bg"])
            lst_fr.pack(fill="both", expand=True,
                        padx=pad, pady=(2, pad))

            def _select(val):
                top.destroy()
                self.net.send({"cmd": "set_sample_rate", "value": val})

            for rate in rates:
                label = self._fmt_sample_rate(rate)
                is_cur = current is not None and float(rate) == float(current)
                if is_cur:
                    label += "  \u2713"   # checkmark on the active rate
                btn = tk.Button(
                    lst_fr, text=label, anchor="w",
                    bg=C["btn_sel"] if is_cur else C["btn_gray"],
                    fg=C["btn_sel_fg"],
                    activebackground=C["btn_sel"], activeforeground=C["btn_sel_fg"],
                    font=_gui_font(fs), relief="flat", bd=1,
                    padx=max(6, int(round(8*sc))),
                    pady=max(1, int(round(2*sc))),
                    command=lambda r=rate: _select(r))
                btn.pack(fill="x", pady=(0, max(1, int(round(1*sc)))))

            sep_line = tk.Frame(lst_fr, bg=C["sep"],
                                height=max(1, int(round(1*sc))))
            sep_line.pack(fill="x", pady=(max(2, int(round(3*sc))), 0))
            tk.Button(lst_fr, text="Cancel", command=top.destroy,
                      bg=C["btn_gray"], fg=C["btn_red_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(6, int(round(8*sc))),
                      pady=max(1, int(round(2*sc)))
                      ).pack(fill="x", pady=(max(2, int(round(3*sc))), 0))

        top.update_idletasks()
        rw = self.root.winfo_x() + self.root.winfo_width()  // 2
        rh = self.root.winfo_y() + self.root.winfo_height() // 2
        tw = top.winfo_reqwidth()
        th = top.winfo_reqheight()
        top.geometry(f"+{rw - tw // 2}+{rh - th // 2}")

    # ── Soundcard device selection dialog ─────────────────────────────────────
    def _open_soundcard_dialog(self):
        """Open a modal window listing all PyAudio devices.
        The user picks an input device (microphone) and an output device
        (speaker) independently; confirming applies them immediately to the
        RTP audio client without requiring a reconnect."""

        devices = self.rtp_audio.get_devices()

        sc = self._sc
        fs = max(7, int(round(8 * sc)))
        fs_h = max(8, int(round(9 * sc)))
        pad = max(4, int(round(6 * sc)))
        row_h = max(22, int(round(26 * sc)))

        top = tk.Toplevel(self.root)
        top.title("Soundcard / Audio Device Selection")
        top.configure(bg=C["panel_bg"])
        top.transient(self.root)
        top.grab_set()
        top.resizable(False, False)

        # ── helper: build one device-list panel ──────────────────────────────
        def _make_panel(parent, title, filter_key, current_idx):
            """Return (frame, get_selection_fn).
            filter_key: "max_input_channels" or "max_output_channels"
            """
            fr = tk.Frame(parent, bg=C["panel_bg"])

            tk.Label(fr, text=title, bg=C["panel_bg"], fg=C["btn_grn_fg"],
                     font=_gui_font(fs_h, "bold")).pack(anchor="w", padx=pad, pady=(pad, 2))

            # Scrollable listbox
            lb_fr = tk.Frame(fr, bg=C["panel_bg"])
            lb_fr.pack(fill="both", expand=True, padx=pad, pady=(0, pad))

            sb = tk.Scrollbar(lb_fr, orient="vertical", bg=C["btn_gray"],
                              troughcolor=C["win_bg"])
            lb = tk.Listbox(lb_fr, yscrollcommand=sb.set,
                            bg=C["btn_gray"], fg=C["text"],
                            selectbackground=C["btn_sel"], selectforeground=C["btn_sel_fg"],
                            font=_gui_font(fs), relief="flat", bd=0,
                            height=10,
                            width=40,
                            activestyle="none",
                            exportselection=False)
            sb.config(command=lb.yview)
            sb.pack(side="right", fill="y")
            lb.pack(side="left", fill="both", expand=True)

            # Populate: first entry is always "System default"
            entries = [{"index": None, "label": "(System default)"}]
            for d in devices:
                if d[filter_key] > 0:
                    ch = d[filter_key]
                    sr = d["default_sample_rate"]
                    label = f"[{d['index']:2d}]  {d['name']}  ({ch}ch  {sr//1000}kHz)"
                    entries.append({"index": d["index"], "label": label})

            for e in entries:
                lb.insert("end", e["label"])

            # Pre-select current device
            sel = 0
            for i, e in enumerate(entries):
                if e["index"] == current_idx:
                    sel = i
                    break
            lb.selection_set(sel)
            lb.see(sel)

            def get_selection():
                idxs = lb.curselection()
                if not idxs:
                    return current_idx
                return entries[idxs[0]]["index"]

            return fr, get_selection

        # ── layout: two panels side by side ──────────────────────────────────
        panels_fr = tk.Frame(top, bg=C["panel_bg"])
        panels_fr.pack(fill="both", expand=True, padx=pad, pady=(pad, 0))

        _cur_in, _cur_out = self.rtp_audio.get_selected_devices()

        in_fr, get_in = _make_panel(
            panels_fr, "Microphone (input)",
            "max_input_channels", _cur_in)
        in_fr.pack(side="left", fill="both", expand=True, padx=(0, pad // 2))

        out_fr, get_out = _make_panel(
            panels_fr, "Speaker / Headphones (output)",
            "max_output_channels", _cur_out)
        out_fr.pack(side="left", fill="both", expand=True, padx=(pad // 2, 0))

        # Status label
        self._sc_status_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._sc_status_var,
                 bg=C["panel_bg"], fg=C["text_grn"],
                 font=_gui_font(fs)).pack(padx=pad, pady=(2, 0))

        # ── no pyaudio warning ────────────────────────────────────────────────
        if not devices:
            tk.Label(top,
                     text="pyaudio not installed - no devices available. pip install pyaudio",
                     bg=C["panel_bg"], fg=C["btn_red_fg"],
                     font=_gui_font(fs), justify="left"
                     ).pack(padx=pad, pady=(0, pad))

        # ── buttons ───────────────────────────────────────────────────────────
        btn_fr = tk.Frame(top, bg=C["panel_bg"])
        btn_fr.pack(fill="x", padx=pad, pady=pad)

        def _apply():
            in_idx  = get_in()
            out_idx = get_out()
            self.rtp_audio.set_devices(in_idx, out_idx)
            in_name  = next((d["name"] for d in devices if d["index"] == in_idx),
                            "System default")
            out_name = next((d["name"] for d in devices if d["index"] == out_idx),
                            "System default")
            self._sc_status_var.set(
                f"✓  In: {in_name[:28]}   Out: {out_name[:28]}")
            print(f"[audio] devices set — input={in_idx} ({in_name})"
                  f"  output={out_idx} ({out_name})")

        def _ok():
            _apply()
            top.destroy()

        _fbtn(btn_fr, "Apply", sc=sc, command=_apply,
              bg=C["btn_gray"], fg=C["btn_sel_fg"]
              ).pack(side="left", padx=(0, max(2, int(round(4 * sc)))))
        _fbtn(btn_fr, "OK", sc=sc, command=_ok,
              bg=C["btn_grn"], fg=C["btn_grn_fg"]
              ).pack(side="left", padx=(0, max(2, int(round(4 * sc)))))
        tk.Button(btn_fr, text="Cancel", command=top.destroy,
                  bg=C["btn_gray"], fg=C["btn_red_fg"],
                  font=_gui_font(fs), relief="flat", bd=1
                  ).pack(side="left")

        # ── centre over parent ────────────────────────────────────────────────
        top.update_idletasks()
        rw = self.root.winfo_x() + self.root.winfo_width() // 2
        rh = self.root.winfo_y() + self.root.winfo_height() // 2
        tw = top.winfo_reqwidth()
        th = top.winfo_reqheight()
        top.geometry(f"+{rw - tw // 2}+{rh - th // 2}")

    def _toggle_connect(self):
        if self.net.connected:
            if self.state["running"]:
                self.net.send({"cmd":"stop"})
            self.net.disconnect()
            self._on_disconnected()
        else:
            host=self.host_var.get().strip()
            try: port=int(self.port_var.get().strip())
            except ValueError:
                messagebox.showerror("Connect","Invalid port number"); return
            self.conn_btn.config(text="Connecting…",state="disabled")
            self.root.update_idletasks()
            # Run the blocking socket.create_connection() in a background thread
            # so the GUI remains responsive during the 3-second timeout window.
            # The result is posted back via self.q and handled in poll()/_handle().
            def _do_connect():
                ok, msg = self.net.connect(host, port)
                self.q.put({"type": "_connect_result",
                            "ok": ok, "msg": msg, "host": host, "port": port})
            threading.Thread(target=_do_connect, daemon=True).start()

    def _on_connect_result(self, ok, msg, host, port):
        """Called on the GUI thread after the background connect attempt finishes."""
        if not ok:
            self.conn_btn.config(text="Connect", state="normal")
            messagebox.showerror("Connect", f"Cannot connect to {host}:{port}\n{msg}")
            return
        # PTT and SPLIT are always inactive on a fresh connection — these are
        # session-only transients that the server also resets on new connections.
        self.state["ptt"] = False
        self.state["split"] = False
        self._refresh_split_ui()
        # Send hello so the server returns its full saved state for the active
        # device in the resp:ok.  That state arrives via the queue and is merged
        # into self.state by the normal "state" in msg branch, then the
        # reload_state message that follows resyncs every widget.
        # We do NOT push local GUI values (freq, mode, …) to the server here —
        # the server is the source of truth; we read from it, not the reverse.
        # PTT and SPLIT resets are sent explicitly because they are transient
        # and the server must clear any stale TX state from a previous session.
        def _send_hello_burst():
            self.net.send({"cmd": "hello"})
            self.net.send({"cmd": "set_ptt",   "enabled": False})
            self.net.send({"cmd": "set_split",  "enabled": False})
            if not self._user_stopped:
                self.net.send({"cmd": "start"})
        _auto_start = not self._user_stopped
        self.state["running"] = _auto_start
        threading.Thread(target=_send_hello_burst, daemon=True).start()
        self.conn_btn.config(text="Disconnect", state="normal",
                             bg="#2a0e0e", fg=C["btn_red_fg"])
        self.conn_status.config(fg=C["btn_grn_fg"])
        if _auto_start:
            self.start_btn.config(text="Stop", bg="#6a1414", fg=C["btn_red_fg"])
        else:
            self.start_btn.config(text="Start", bg=C["btn_grn"], fg=C["btn_grn_fg"])

    def _on_disconnected(self, reason=None):
        self.state["running"]=False
        self.state["ptt"]=False
        self.state["split"]=False
        self._refresh_split_ui()
        self.rtp_audio.close()
        self._ptt_enabled = False
        self.smeter.set_tx(False)   # unfreeze meter on disconnect
        if hasattr(self, 'rf_wf'):    self.rf_wf.set_tx(False)
        if hasattr(self, 'rf_spec'):  self.rf_spec.set_tx(False)
        if hasattr(self, '_draw_ptt_btn'):
            self._draw_ptt_btn(False, False)
        if hasattr(self, '_ptt_canvas'):
            self._ptt_canvas.config(cursor="arrow")
        self.conn_btn.config(text="Connect",state="normal",
                             bg="#0e2a10",fg=C["btn_grn_fg"])
        self.conn_status.config(fg="#331111")
        self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])
        if reason:
            messagebox.showerror("Disconnected", reason, parent=self.root)

    def _set_mode(self,label,idx=None):
        """Select a modulation mode (exclusive across all 10 server-defined
        slots). Label/type come entirely from the server; the GUI holds no
        per-mode defaults (e.g. filter passband), so filter_lo/filter_hi are
        left as-is — the server is free to push its own filter defaults for
        the new mode via the next state update."""
        self.state["mode"]=label
        self._refresh()
        self.net.send({"cmd":"set_mode","mode":label})

    # ── user-defined buttons (server-configured, indices 1..6) ─────────────
    def _active_text_mod(self):
        """If the currently selected mode (state['mode']) matches a
        user-defined modulation button whose type is 'text' or 'text_input',
        return (idx, mtype) with idx in 1..10. Otherwise return (None, None).
        Derived directly from state so it stays correct across reconnects,
        server-initiated mode changes, and scale-change rebuilds — no
        separate "active index" needs to be tracked."""
        mode=self.state.get("mode")
        uml=self.state.get("user_mod_labels") or []
        umt=self.state.get("user_mod_types") or []
        for i,lbl in enumerate(uml):
            lbl=(lbl or "").strip()[:4]
            if lbl and lbl==mode:
                mtype=umt[i] if i<len(umt) else "normal"
                if mtype in ("text","text_input"):
                    return i+1,mtype
                return None,None
        return None,None

    def _user_btn_cfg(self,idx):
        """Return {"label":..., "type":...} for user button idx (1..14),
        falling back to a default if the server hasn't provided one yet."""
        ub=self.state.get("user_buttons") or []
        if 1<=idx<=len(ub) and ub[idx-1]:
            cfg=ub[idx-1]
            return {"label":cfg.get("label",""),"type":cfg.get("type","normal")}
        return {"label":"","type":"normal"}

    def _user_btn_label(self,idx):
        label=self._user_btn_cfg(idx).get("label","").strip()
        # Show empty string when server has not provided a label
        return label[:7]

    def _user_btn_state(self,idx):
        st=self.state.get("user_btn_state") or []
        if 1<=idx<=len(st):
            return bool(st[idx-1])
        return False

    def _user_btn_press(self,idx):
        cfg=self._user_btn_cfg(idx)
        if cfg.get("type")=="push":
            new_on=not self._user_btn_state(idx)
            st=self.state.get("user_btn_state")
            if not st:
                st=[False]*14
            elif len(st)<14:
                st=list(st)+[False]*(14-len(st))
            st[idx-1]=new_on
            self.state["user_btn_state"]=st
            self.net.send({"cmd":"user_button","index":idx,"enabled":new_on})
        else:
            self.net.send({"cmd":"user_button","index":idx})
        self._refresh()

    # ── Memory ("M") buttons — one per LO A / LO B / Tune row ──────────────
    def _mem_btn_press(self,position):
        """Open the memory dialog for this frequency row ("LO A", "LO B", or
        "Tune") and ask the server for that row's 20 memory slots. Memories
        are per-device on the server side, so this always reflects whatever
        device is currently selected there."""
        self._open_memory_dialog(position)
        self.net.send({"cmd":"get_memories","position":position})

    def _memory_disp_for(self,position):
        """Return the FreqDisp widget that owns the actual on-air frequency
        for a given memory row position, or None if it doesn't exist yet."""
        return {"LO A":getattr(self,'lo_disp',None),
                "LO B":getattr(self,'lo_b_disp',None),
                "Tune":getattr(self,'tune_disp',None)}.get(position)

    def _memory_state_key_for(self,position):
        return {"LO A":"lo_freq","LO B":"lo_b_freq","Tune":"tune_freq"}.get(position)

    def _open_memory_dialog(self,position):
        """Build (or re-raise) the modal memory-list window for one
        frequency row. Rows are populated once the server's "memory_list"
        reply arrives (see _on_memory_list / _handle); until then the list
        just shows a one-line "Loading..." placeholder."""
        # Only one memory dialog at a time — reuse it if already open for
        # the same position, otherwise tear down the old one first.
        if getattr(self,'_mem_dialog',None) is not None:
            try:
                self._mem_dialog.destroy()
            except Exception:
                pass
            self._mem_dialog=None

        self._mem_dialog_position=position
        self._mem_dialog_data=[{"label":"","freq":0.0} for _ in range(20)]
        self._mem_dialog_selected=None

        sc=self._sc
        fs=max(7,int(round(8*sc)))
        fs_h=max(8,int(round(9*sc)))
        pad=max(4,int(round(6*sc)))

        top=tk.Toplevel(self.root)
        top.title(f"Memory — {position}")
        top.configure(bg=C["panel_bg"])
        top.transient(self.root)
        top.grab_set()
        top.resizable(False,False)
        self._mem_dialog=top
        def _on_close():
            self._mem_dialog=None
            self._mem_dialog_position=None
            top.destroy()
        top.protocol("WM_DELETE_WINDOW",_on_close)

        tk.Label(top,text=f"{position} memories:",bg=C["panel_bg"],
                 fg=C["btn_grn_fg"],font=_gui_font(fs_h,"bold")
                 ).pack(padx=pad,pady=(pad,2),anchor="w")

        list_fr=tk.Frame(top,bg=C["panel_bg"])
        list_fr.pack(padx=pad,pady=(0,4),fill="both",expand=True)
        scrollbar=tk.Scrollbar(list_fr,orient="vertical")
        lb=tk.Listbox(list_fr,height=20,width=34,
                      bg=C["btn_gray"],fg=C["text"],
                      selectbackground=C["btn_sel"],selectforeground=C["btn_sel_fg"],
                      font=("Courier",fs),relief="flat",bd=0,
                      activestyle="none",exportselection=False,
                      yscrollcommand=scrollbar.set)
        scrollbar.config(command=lb.yview)
        lb.pack(side="left",fill="both",expand=True)
        scrollbar.pack(side="right",fill="y")
        self._mem_dialog_listbox=lb
        lb.insert("end","Loading...")

        # ── Editable label + frequency (read-only) of the current selection ──
        edit_fr=tk.Frame(top,bg=C["panel_bg"])
        edit_fr.pack(padx=pad,pady=(2,0),fill="x")
        tk.Label(edit_fr,text="Edit label:",bg=C["panel_bg"],fg=C["text"],
                 font=_gui_font(fs)).pack(side="left")
        label_var=tk.StringVar(value="")
        self._mem_dialog_label_var=label_var
        lbl_ent=tk.Entry(edit_fr,textvariable=label_var,width=14,
                         bg=C["spec_bg"],fg=C["text"],
                         insertbackground=C["text"],relief="flat",
                         highlightthickness=1,highlightbackground=C["sep"],
                         highlightcolor=C["btn_sel"])
        lbl_ent.pack(side="left",padx=(4,0),fill="x",expand=True)
        # Keep labels within the server's MEMORY_LABEL_MAXLEN (10 chars).
        def _cap_label(*_a):
            v=label_var.get()
            if len(v)>10: label_var.set(v[:10])
        label_var.trace_add("write",_cap_label)
        tk.Label(top,text="Select a slot, type a label, then Rename (label only) "
                          "or Save (label + current frequency).",
                 bg=C["panel_bg"],fg=C["text_dim"],
                 font=_gui_font(max(6,fs-1)),wraplength=240,justify="left"
                 ).pack(padx=pad,pady=(2,4),anchor="w")

        def _select(evt=None):
            sel=lb.curselection()
            if not sel: return
            idx=sel[0]
            self._mem_dialog_selected=idx
            entry=self._mem_dialog_data[idx] if idx<len(self._mem_dialog_data) else {"label":"","freq":0.0}
            label_var.set(entry.get("label",""))
            lbl_ent.focus_set(); lbl_ent.select_range(0,"end")
        lb.bind("<<ListboxSelect>>",_select)
        # Double-click a row: select it and jump straight into the label
        # box ready to type, for people who expect double-click-to-rename.
        lb.bind("<Double-Button-1>",lambda e:(_select(),lbl_ent.focus_set(),
                                               lbl_ent.select_range(0,"end")))

        # ── Load / Rename / Save / Close buttons ────────────────────────────
        btn_fr=tk.Frame(top,bg=C["panel_bg"])
        btn_fr.pack(padx=pad,pady=(0,pad),fill="x")

        def _load():
            idx=self._mem_dialog_selected
            if idx is None:
                messagebox.showinfo("Memory","Select a memory slot first.",parent=top)
                return
            entry=self._mem_dialog_data[idx] if idx<len(self._mem_dialog_data) else None
            if not entry or (not entry.get("label") and not entry.get("freq")):
                messagebox.showinfo("Memory","That memory slot is empty.",parent=top)
                return
            freq=entry.get("freq",0) or 0
            disp=self._memory_disp_for(position)
            if disp is not None:
                disp.set_value(int(freq),notify=True)

        def _commit(idx,label,freq):
            if idx<len(self._mem_dialog_data):
                self._mem_dialog_data[idx]={"label":label,"freq":freq}
            self._refresh_memory_listbox()
            lb.selection_clear(0,"end"); lb.selection_set(idx); lb.see(idx)
            self.net.send({"cmd":"save_memory","position":position,
                           "index":idx,"label":label,"freq":freq})

        def _rename():
            """Edit just the label of the selected slot — its stored
            frequency is left exactly as it was (does NOT pull in the
            current actual frequency)."""
            idx=self._mem_dialog_selected
            if idx is None:
                messagebox.showinfo("Memory","Select a memory slot first.",parent=top)
                return
            entry=self._mem_dialog_data[idx] if idx<len(self._mem_dialog_data) else {"label":"","freq":0.0}
            label=label_var.get()[:10]
            freq=entry.get("freq",0) or 0
            _commit(idx,label,freq)

        def _save():
            """Save the row's *current actual frequency*, plus whatever
            label is in the box, into the selected slot."""
            idx=self._mem_dialog_selected
            if idx is None:
                messagebox.showinfo("Memory","Select a memory slot first.",parent=top)
                return
            key=self._memory_state_key_for(position)
            freq=self.state.get(key,0) or 0
            label=label_var.get()[:10]
            _commit(idx,label,freq)

        lbl_ent.bind("<Return>",lambda e:_rename())

        bpad=max(6,int(round(8*sc)))
        tk.Button(btn_fr,text="Load",command=_load,
                  bg=C["btn_grn"],fg=C["btn_grn_fg"],
                  font=_gui_font(fs,"bold"),relief="flat",bd=1,
                  padx=bpad).pack(side="left",fill="x",expand=True,padx=(0,2))
        tk.Button(btn_fr,text="Rename",command=_rename,
                  bg=C["btn_gray"],fg=C["text"],
                  font=_gui_font(fs,"bold"),relief="flat",bd=1,
                  padx=bpad).pack(side="left",fill="x",expand=True,padx=2)
        tk.Button(btn_fr,text="Save",command=_save,
                  bg=C["btn_sel"],fg=C["btn_sel_fg"],
                  font=_gui_font(fs,"bold"),relief="flat",bd=1,
                  padx=bpad).pack(side="left",fill="x",expand=True,padx=2)
        tk.Button(btn_fr,text="Close",command=_on_close,
                  bg=C["btn_gray"],fg=C["text"],
                  font=_gui_font(fs),relief="flat",bd=1,
                  padx=bpad).pack(side="left",fill="x",expand=True,padx=(2,0))

        top.update_idletasks()
        rw=self.root.winfo_x()+self.root.winfo_width()//2
        rh=self.root.winfo_y()+self.root.winfo_height()//2
        tw=top.winfo_reqwidth(); th=top.winfo_reqheight()
        top.geometry(f"+{rw-tw//2}+{rh-th//2}")

    def _refresh_memory_listbox(self):
        lb=getattr(self,'_mem_dialog_listbox',None)
        if lb is None: return
        sel=self._mem_dialog_selected
        lb.delete(0,"end")
        for i,entry in enumerate(self._mem_dialog_data):
            label=str(entry.get("label",""))[:10]
            freq=entry.get("freq",0) or 0
            lb.insert("end",f"{i+1:2d}  {label:<10}  {freq:>11,.0f} Hz")
        if sel is not None and 0<=sel<lb.size():
            lb.selection_set(sel)

    def _on_memory_list(self,msg):
        """Handle the server's reply to get_memories / save_memory: refresh
        the open memory dialog's list, but only if it's still showing the
        same position this reply is for (the user may have closed it or
        opened a different row's dialog in the meantime)."""
        position=msg.get("position")
        if getattr(self,'_mem_dialog_position',None)!=position:
            return
        memories=msg.get("memories") or []
        data=[]
        for i in range(20):
            if i<len(memories) and isinstance(memories[i],dict):
                data.append({"label":memories[i].get("label",""),
                             "freq":memories[i].get("freq",0)})
            else:
                data.append({"label":"","freq":0.0})
        self._mem_dialog_data=data
        first_load=(self._mem_dialog_selected is None)
        self._refresh_memory_listbox()
        if first_load:
            lb=getattr(self,'_mem_dialog_listbox',None)
            lvar=getattr(self,'_mem_dialog_label_var',None)
            if lb is not None and lvar is not None and lb.size()>0:
                self._mem_dialog_selected=0
                lb.selection_clear(0,"end"); lb.selection_set(0)
                lvar.set(data[0].get("label",""))

    # ── SPLIT toggle (between LO A and LO B) ────────────────────────────────
    def _toggle_split(self):
        new_on=not bool(self.state.get("split",False))
        self.state["split"]=new_on
        self.net.send({"cmd":"set_split","enabled":new_on})
        self._refresh_split_ui()

    def _refresh_split_ui(self):
        on=bool(self.state.get("split",False))
        if hasattr(self,'_split_btn'):
            self._split_btn.config(bg=C["btn_sel"] if on else C["btn_gray"],
                                    fg=C["btn_sel_fg"])
        # Keep the gap-column TX/RX labels always empty — TX/RX is shown
        # directly on the LO A / LO B row-label buttons instead.
        if hasattr(self,'_split_tx_lbl'):
            self._split_tx_lbl.config(text="")
        if hasattr(self,'_split_rx_lbl'):
            self._split_rx_lbl.config(text="")
        # When SPLIT is on: rename LO A → TX and LO B → RX on their row buttons.
        # When SPLIT is off: restore original LO A / LO B labels.
        # The buttons are also disabled while SPLIT is enabled (active LO
        # can't be changed mid-split).
        for disp, lbl_normal, lbl_split in (
                (getattr(self,'_lo_a_disp',None), "LO A", "TX"),
                (getattr(self,'_lo_b_disp',None), "LO B", "RX")):
            btn=getattr(disp,'_row_lbl',None) if disp is not None else None
            if btn is None:
                continue
            if on:
                btn.config(text=lbl_split,width=4,state="disabled",bg=C["btn_gray"],
                           fg=C["text_dim"],disabledforeground=C["text_dim"])
            else:
                btn.config(text=lbl_normal,width=4,state="normal")
        if not on and hasattr(self,'_refresh_lo_btns'):
            # Restore the normal active/inactive LO highlight colours.
            self._refresh_lo_btns()

    # ── RF user buttons (server-configured, indices 1..11, left of band btns) ─
    def _rf_usr_btn_cfg(self,idx):
        """Return {"label":..., "type":...} for RF user button idx (1..11)."""
        ub=self.state.get("rf_usr_btns") or []
        if 1<=idx<=len(ub) and ub[idx-1]:
            cfg=ub[idx-1]
            return {"label":cfg.get("label",""),"type":cfg.get("type","normal")}
        return {"label":"","type":"normal"}

    def _rf_usr_btn_label(self,idx):
        return self._rf_usr_btn_cfg(idx).get("label","").strip()[:7]

    def _rf_usr_btn_state(self,idx):
        st=self.state.get("rf_usr_btn_state") or []
        if 1<=idx<=len(st):
            return bool(st[idx-1])
        return False

    def _rf_usr_btn_press(self,idx):
        cfg=self._rf_usr_btn_cfg(idx)
        if cfg.get("type")=="push":
            new_on=not self._rf_usr_btn_state(idx)
            st=self.state.get("rf_usr_btn_state")
            if not st:
                st=[False]*11
            elif len(st)<11:
                st=list(st)+[False]*(11-len(st))
            st[idx-1]=new_on
            self.state["rf_usr_btn_state"]=st
            self.net.send({"cmd":"rf_usr_button","index":idx,"enabled":new_on})
        else:
            self.net.send({"cmd":"rf_usr_button","index":idx})
        self._refresh()

    def _toggle_run(self):
        if not self.net.connected: return
        if self.state["running"]:
            self.net.send({"cmd":"stop"}); self.state["running"]=False
            self._user_stopped = True   # remember the operator chose to stop
            self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])
        else:
            self.net.send({"cmd":"start"}); self.state["running"]=True
            self._user_stopped = False  # operator restarted — clear the flag
            self.start_btn.config(text="Stop",bg="#6a1414",fg=C["btn_red_fg"])

    def adj_zoom(self,d):
        z=int(self.state["zoom"])
        z=min(32,z*2) if d>0 else max(1,z//2)
        self.state["zoom"]=z; self.net.send({"cmd":"set_zoom","value":z})
        # Keep the RF toolbar's Zoom readout in sync even when zoom is
        # changed via mouse-wheel over the spectrum rather than the
        # toolbar's own +/- buttons.
        _tb=getattr(self,"_toolbar1",None)
        if _tb and hasattr(_tb,"set_zoom"):
            _tb.set_zoom(z)

    def _update_rf_view(self,hz):
        """Re-centre the upper spectrum/waterfall frequency scale on hz."""
        sr = self.state.get("sample_rate", 192_000.0)
        half = sr / 2.0
        f0=hz-half; f1=hz+half
        self.rf_spec.f0=f0; self.rf_spec.f1=f1; self.rf_spec.draw()
        self.rf_wf.set_freq_range(f0,f1)

    def on_freq_changed(self,hz):
        self.state["lo_freq"]=hz
        # Re-centre upper spectrum/waterfall only if LO A is the active LO
        if self._lo_active.get()=="A":
            self._update_rf_view(hz)
        if not self._sup: self.net.send({"cmd":"set_lo_a_freq","hz":hz})

    def _swap_lo_a_b(self):
        """Swap the LO A and LO B frequencies and push both changes to the server."""
        a_hz=self.lo_disp.value
        b_hz=self.lo_b_disp.value
        if a_hz==b_hz:
            return
        # Update on-screen digits without notify — state and server sends are
        # driven explicitly below so both messages are always sent regardless
        # of FreqDisp on_change wiring or any _sup suppression flag.
        self.lo_disp.set_value(b_hz,notify=False)
        self.lo_b_disp.set_value(a_hz,notify=False)
        # Update internal state for both LOs.
        self.state["lo_freq"]=b_hz
        self.state["lo_b_freq"]=a_hz
        # Re-centre RF view for whichever LO is currently active.
        active=self._lo_active.get()
        if active=="A":
            self._update_rf_view(b_hz)
        elif active=="B":
            self._update_rf_view(a_hz)
        # Send both frequency changes to the server unconditionally.
        self.net.send({"cmd":"set_lo_a_freq","hz":b_hz})
        self.net.send({"cmd":"set_lo_b_freq","hz":a_hz})

    def on_lo_b_changed(self,hz):
        self.state["lo_b_freq"]=hz
        # Re-centre upper spectrum/waterfall only if LO B is the active LO
        if self._lo_active.get()=="B":
            self._update_rf_view(hz)
        if not self._sup: self.net.send({"cmd":"set_lo_b_freq","hz":hz})

    def on_tune_changed(self,hz):
        self.state["tune_freq"]=hz
        if not self._sup: self.net.send({"cmd":"set_tune_freq","hz":hz})

    def set_frequency(self,hz):
        hz=int(max(0,hz))
        self.lo_disp.set_value(hz,notify=False); self.on_freq_changed(hz)

    def _clock(self):
        now=datetime.datetime.now()
        # Portable 12-hour hour: no strftime directives (%-I is Linux-only,
        # %#I is Windows-only; other POSIX platforms may support neither).
        h12=str(now.hour % 12 or 12)
        ampm="a.m." if now.hour<12 else "p.m."
        self.clock_var.set(
            f"{now.day}/{now.month}/{now.year}  {h12}:{now.strftime('%M:%S')} {ampm}"
        )
        self.root.after(1000,self._clock)

    # ── network poll ──────────────────────────────────────────────────────────
    # When the incoming queue exceeds this depth, stale spectrum "data" frames
    # are dropped so the GUI always catches up to the latest frame rather than
    # lagging further behind with each tick.
    _POLL_DROP_THRESHOLD = 50

    def poll(self):
        # IMPORTANT: self.root.after(30, self.poll) must run no matter what
        # happens above, or this loop stops rescheduling itself forever.
        # Every GUI update (spectrum, waterfall, S-meter, state refresh)
        # flows through this queue; the RTP audio threads do not. So if an
        # unexpected exception ever escaped poll() uncaught, audio would
        # keep playing fine (it's driven by independent PyAudio/UDP
        # threads) while the rest of the GUI silently froze in place.
        # The try/finally below makes that failure mode impossible.
        try:
            while True:
                if self.q.qsize() > self._POLL_DROP_THRESHOLD:
                    msg = self.q.get_nowait()
                    if msg.get("type") == "data":
                        # Still update the S-meter even when dropping the spectrum frame
                        # so it doesn't freeze while the queue is backed up.
                        # set_value() is a no-op during TX (smeter.set_tx blocks it).
                        try:
                            self.smeter.set_value(
                                msg.get("smeter_dbm", -127.0),
                                msg.get("smeter_text", ""))
                        except Exception:
                            traceback.print_exc()
                        continue      # discard stale spectrum frame; grab next
                    elif msg.get("type") == "af_local":
                        continue      # discard stale AF frame; grab next
                else:
                    msg = self.q.get_nowait()
                try:
                    self._handle(msg)
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        except Exception:
            # Belt-and-suspenders: anything else unexpected (e.g. q.get_nowait()
            # itself misbehaving) must not stop the chain from rescheduling.
            traceback.print_exc()
        finally:
            self.root.after(30, self.poll)

    def _handle(self,msg):
        t=msg.get("type")
        if t=="_connect_result":
            self._on_connect_result(msg["ok"], msg["msg"], msg["host"], msg["port"])
            return
        if t=="_audio_open_result":
            local_udp = msg.get("local_udp")
            if local_udp:
                # Only now is it safe to let the user press PTT — the local
                # socket is bound, so local_udp_port() will never return None.
                self._ptt_enabled = True
                if hasattr(self, '_draw_ptt_btn'):
                    self._draw_ptt_btn(bool(self.state.get("ptt", False)), True)
                if hasattr(self, '_ptt_canvas'):
                    self._ptt_canvas.config(cursor="hand2")
            else:
                print("[audio] WARNING: RTP socket failed to bind a local UDP "
                      "port — PTT remains disabled.")
            return
        if t=="disconnected": self._on_disconnected(msg.get("reason"))
        elif t=="audio_port":
            # Server is advertising its UDP RTP port — open the audio channel.
            # RTPAudioClient.open() calls pyaudio.PyAudio(), which on some
            # systems (PulseAudio/ALSA/JACK device enumeration issues) can
            # block for several seconds or longer. It also does a blocking
            # net.send() afterward. Both used to run directly on the GUI
            # thread here, which froze the whole window the instant the
            # server replied with audio_port — audio would still eventually
            # play because PyAudio's stream callback runs on its own thread,
            # completely independent of Tk's main loop. Do the open() call
            # (and the follow-up send) on a background thread instead, and
            # post the result back through the queue so widget updates still
            # happen safely on the GUI thread.
            server_host = self.net.sock.getpeername()[0] if self.net.sock else "127.0.0.1"
            udp_port    = int(msg.get("port", 5004))
            sr          = int(msg.get("sample_rate", AUDIO_SAMPLE_RATE))
            fm          = int(msg.get("frame_ms", AUDIO_FRAME_MS))
            def _open_audio():
                self.rtp_audio.open(server_host, udp_port, sample_rate=sr, frame_ms=fm)
                local_udp = self.rtp_audio.local_udp_port()
                if local_udp:
                    self.net.send({"cmd": "audio_hello", "udp_port": local_udp})
                self.q.put({"type": "_audio_open_result", "local_udp": local_udp})
            threading.Thread(target=_open_audio, daemon=True).start()
        elif t=="data":
            # Waterfall/spectrum only update on RX. S-meter set_value() is a
            # no-op during TX because set_tx(True) guards it in SMeter.
            if not self.state.get("ptt", False):
                f0=msg.get("f_start"); f1=msg.get("f_stop")
                spec=msg.get("spectrum",[])
                if f0 is not None and f1 is not None and spec:
                    self.rf_spec.update_data(f0,f1,spec)
                    self.rf_wf.set_freq_range(f0,f1)
                    self.rf_wf.add_row(spec)
            # AF spectrum/waterfall is updated separately via "af_local"
            # messages computed from the real decoded RTP audio (see
            # RTPAudioClient), not from this server-reported message, so it
            # always reflects the actual received signal.
            self.smeter.set_value(msg.get("smeter_dbm",-127.0),msg.get("smeter_text",""))
        elif t=="af_local":
            # Suppress AF waterfall/spectrum while transmitting.
            if not self.state.get("ptt", False):
                ar=msg.get("af_range",_AF_DISPLAY_RANGE_HZ)
                spec=msg.get("af_spectrum",[])
                if spec:
                    self.af_spec.update_data(0,ar,spec)
                    self.af_wf.set_freq_range(0,ar)
                    self.af_wf.add_row(spec)
        elif t=="user_text":
            # Server-pushed text for a "text"/"text_input" user-mod slot.
            # Only render it if that slot's panel is the one currently shown
            # (the GUI may have switched to a different mode in the meantime).
            idx=msg.get("index")
            text=msg.get("text","")
            if idx is not None and getattr(self,"_text_pane_idx",None)==idx and text:
                self._append_text_rx(text)
        elif t == "device_list":
            # Server replied to get_devices — open the selection popup on the
            # GUI thread (we are already on the GUI thread inside poll/_handle).
            self._open_device_dialog(msg.get("devices", []))
        elif t == "sample_rate_list":
            # Server replied to get_sample_rates — open the selection popup
            # with the choices configured for the active device's TOML file.
            # Prefer the server's "current" field: it is read under the
            # server's lock at reply time and is always accurate, including
            # after a device change where self.state["sample_rate"] may still
            # hold a value from the previous device or the pre-change state.
            # Fall back to self.state only when the server omits "current"
            # (older server versions).
            _cur_sr = msg.get("current") or self.state.get("sample_rate")
            self._open_sample_rate_dialog(msg.get("rates", []), _cur_sr)
        elif t == "memory_list":
            # Server replied to get_memories / save_memory — refresh the
            # memory dialog (if still open on the matching position).
            self._on_memory_list(msg)
        elif t == "reload_state":
            # Server has pushed a new device state (via select_device or on
            # initial hello).  self.state was already fully updated by the
            # preceding resp:ok message.  Now resync every widget from
            # self.state, suppressing round-trip sends so we don't echo the
            # server's own values back to it.
            #
            # PTT is always forced OFF on connect and device change — it is a
            # session-only transient and must never be inherited from a
            # previous session or a different device.
            self.state["ptt"] = False
            self.rtp_audio.set_ptt(False)
            # Unfreeze every display component that set_tx(True) may have
            # locked while PTT was active — identical to _on_disconnected,
            # so nothing stays blocked after a device switch or reconnect.
            self.smeter.set_tx(False)
            if hasattr(self, 'rf_wf'):   self.rf_wf.set_tx(False)
            if hasattr(self, 'rf_spec'): self.rf_spec.set_tx(False)
            if hasattr(self, 'af_wf'):   self.af_wf.set_tx(False)
            if hasattr(self, 'af_spec'): self.af_spec.set_tx(False)
            if hasattr(self, '_draw_ptt_btn'):
                self._draw_ptt_btn(False, self._ptt_enabled)
            self._sup = True
            try:
                # Frequency displays
                if hasattr(self, 'lo_disp'):
                    self.lo_disp.set_value(
                        int(self.state.get("lo_freq", 0)), notify=False)
                if hasattr(self, 'lo_b_disp'):
                    self.lo_b_disp.set_value(
                        int(self.state.get("lo_b_freq", 0)), notify=False)
                if hasattr(self, 'tune_disp'):
                    self.tune_disp.set_value(
                        int(self.state.get("tune_freq", 0)), notify=False)
                # Sliders / scale variables
                if hasattr(self, 'vol_var'):
                    self.vol_var.set(self.state.get("volume", 80.0))
                if hasattr(self, 'agct_var'):
                    self.agct_var.set(self.state.get("agc_thresh", -100.0))
                if hasattr(self, 'rfg_var'):
                    self.rfg_var.set(self.state.get("rf_gain", 20.0))
                if hasattr(self, 'sql_var'):
                    self.sql_var.set(self.state.get("squelch", -130.0))
                # LO A/B selector
                if hasattr(self, '_lo_active'):
                    self._lo_active.set(self.state.get("lo_active", "A"))
                    self._refresh_lo_btns()
                # Re-centre the upper spectrum/waterfall span for the
                # (possibly new) device's sample rate. _update_rf_view is
                # normally only triggered by on_freq_changed/on_lo_b_changed
                # on manual retune -- without this call here, switching to a
                # device with a different sample_rate (restored above into
                # self.state by the preceding resp:ok) left the RF view
                # showing the *previous* device's span/zoom until the
                # operator next touched a frequency dial.
                if hasattr(self, 'rf_spec'):
                    _active_lo = self.state.get("lo_active", "A")
                    _view_hz = self.state.get("lo_b_freq", 0) if _active_lo == "B" \
                        else self.state.get("lo_freq", 0)
                    self._update_rf_view(int(_view_hz))
            finally:
                self._sup = False
            # _refresh() redraws mode buttons, user buttons, RF user buttons,
            # AGC, filter, NB/NR/AFC/ANF/notch/mute toggles, zoom, PTT, SPLIT
            # — everything that reads directly from self.state.
            self._refresh()
            # If a memory dialog is open, the active device (and therefore
            # its memory bank) may have just changed — refresh it.
            if getattr(self, '_mem_dialog_position', None):
                self.net.send({"cmd": "get_memories",
                               "position": self._mem_dialog_position})
        elif "state" in msg:
            incoming = msg["state"]
            # Print the persistent values as retrieved from the server,
            # before any local mutation (e.g. the ptt pop below) touches them.
            print("[state] Retrieved persistent values from server:")
            for _k in sorted(incoming.keys()):
                print(f"[state]   {_k} = {incoming[_k]!r}")
            # PTT is owned by the GUI button — never let the server's reflected
            # state overwrite it.  Any other field is safe to merge normally.
            incoming.pop("ptt", None)
            _old_sr = self.state.get("sample_rate")
            self.state.update(incoming)
            # Sync all widget values from the newly merged state, suppressing
            # round-trip sends (same approach as reload_state).  This ensures
            # that after a hello/resp:ok the frequency displays, sliders, and
            # LO selector all reflect the server's persisted values immediately,
            # without waiting for a subsequent reload_state message.
            self._sup = True
            try:
                if hasattr(self, 'lo_disp'):
                    self.lo_disp.set_value(
                        int(self.state.get("lo_freq", 0)), notify=False)
                if hasattr(self, 'lo_b_disp'):
                    self.lo_b_disp.set_value(
                        int(self.state.get("lo_b_freq", 0)), notify=False)
                if hasattr(self, 'tune_disp'):
                    self.tune_disp.set_value(
                        int(self.state.get("tune_freq", 0)), notify=False)
                if hasattr(self, 'vol_var'):
                    self.vol_var.set(self.state.get("volume", 80.0))
                if hasattr(self, 'agct_var'):
                    self.agct_var.set(self.state.get("agc_thresh", -100.0))
                if hasattr(self, 'rfg_var'):
                    self.rfg_var.set(self.state.get("rf_gain", 20.0))
                if hasattr(self, 'sql_var'):
                    self.sql_var.set(self.state.get("squelch", -130.0))
                if hasattr(self, '_lo_active'):
                    self._lo_active.set(self.state.get("lo_active", "A"))
                    self._refresh_lo_btns()
            finally:
                self._sup = False
            self._refresh()
            # If the server reports a new sample_rate (e.g. after set_sample_rate
            # or a device switch whose reload_state hasn't arrived yet), immediately
            # re-centre the RF spectrum/waterfall so its frequency span reflects
            # the new bandwidth.  reload_state does this too, but set_sample_rate
            # only produces a resp:ok — no reload_state follows — so without this
            # the span stays wrong until the operator next touches a frequency dial.
            _new_sr = self.state.get("sample_rate")
            if _new_sr != _old_sr and hasattr(self, "rf_spec"):
                _active_lo = self.state.get("lo_active", "A")
                _view_hz = self.state.get("lo_b_freq", 0) if _active_lo == "B" \
                    else self.state.get("lo_freq", 0)
                self._update_rf_view(int(_view_hz))

# ── entry point ───────────────────────────────────────────────────────────────

def main():
    global _ARGS
    _ARGS = _parse_args()

    # ── --bg theme override (must happen before App() reads C) ────────────────
    if _ARGS.bg == 'light':
        for _k in ("win_bg", "panel_bg", "panel_mid", "spec_bg", "btn_gray"):
            C[_k] = "#FFECD6"

    if _ARGS.audio_list:
        _print_audio_devices()
        return
    root=tk.Tk()
    _load_custom_fonts(root)
    app=App(root)
    # Show initial scale level in the overlay label
    if not _ARGS.disable_scale:
        app._scale_lbl.config(text=str(app._scale_level))
    # Apply --full-screen flag
    if _ARGS.full_screen:
        root.attributes("-fullscreen", True)

    # Apply --resolution WxH flag (ignored when --full-screen is also set)
    if _ARGS.resolution and not _ARGS.full_screen:
        _rw, _rh = _ARGS.resolution
        root.geometry(f"{_rw}x{_rh}")

    # Triple-Esc toggles fullscreen (3 presses within 1 second)
    _esc_times = []
    def _on_esc(event=None):
        import time as _time
        now = _time.monotonic()
        _esc_times.append(now)
        # Keep only presses within the last 1 second
        while _esc_times and now - _esc_times[0] > 1.0:
            _esc_times.pop(0)
        if len(_esc_times) >= 3:
            _esc_times.clear()
            current = bool(root.attributes("-fullscreen"))
            root.attributes("-fullscreen", not current)
    root.bind("<Escape>", _on_esc)

    root.protocol("WM_DELETE_WINDOW",
                  lambda:(app.net.disconnect(), app.rtp_audio.close(), root.destroy()))
    root.mainloop()

if __name__=="__main__":
    main()
