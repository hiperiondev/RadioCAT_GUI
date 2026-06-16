#!/usr/bin/env python3
"""
cat_gui.py
"""
import argparse, collections, json, math, os, queue, socket, struct, sys, threading, time, datetime
import tkinter as tk
from tkinter import messagebox, ttk

# ── CLI argument parsing ─────────────────────────────────────────────────────
def _parse_args():
    ap = argparse.ArgumentParser(description='CAT GUI Interface', add_help=True)
    ap.add_argument('--freq-font', metavar='PATH', default=None,
                    help='TTF/OTF font file for LO/Tune frequency digit displays')
    ap.add_argument('--gui-font',  metavar='PATH', default=None,
                    help='TTF/OTF font file for all other GUI elements')
    ap.add_argument('--scale', metavar='INT', type=int, default=0,
                    help='Initial scale level (-5..5, default 0)')
    ap.add_argument('--bg', choices=['light','dark'], default='dark',
                    help='Background theme: "light" sets all interface '
                         'backgrounds to #FFECD6, "dark" keeps the default colours')
    ap.add_argument('--full-screen', action='store_true', default=False,
                    help='Start in full-screen mode')
    ap.add_argument('--disable-scale', action='store_true', default=False,
                    help='Hide the HiDPI scale +/- controls and scale level number '
                         '(requires --scale to also be specified)')
    ap.add_argument('--host', metavar='HOST', default=None,
                    help='Server hostname or IP to connect to (must be used together with --port)')
    ap.add_argument('--port', metavar='PORT', type=int, default=None,
                    help='Server port to connect to (must be used together with --host)')
    ap.add_argument('--audio-list', action='store_true', default=False,
                    help='List all audio input/output devices on this system, with the '
                         'same index numbers shown in the GUI Soundcard dialog, then exit. '
                         'Use the indices with --audio-mic / --audio-speaker.')
    ap.add_argument('--audio-mic', metavar='INDEX', type=int, default=None,
                    help='Select the microphone (input) device by index (see --audio-list). '
                         'Default: system default device.')
    ap.add_argument('--audio-speaker', metavar='INDEX', type=int, default=None,
                    help='Select the speaker/headphone (output) device by index (see --audio-list). '
                         'Default: system default device.')
    args=ap.parse_args()
    if args.audio_list and len(sys.argv) > 2:
        ap.error('--audio-list must be used alone, without other flags')
    if args.disable_scale:
        scale_given=any(a=='--scale' or a.startswith('--scale=') for a in sys.argv[1:])
        if not scale_given:
            ap.error('--disable-scale requires --scale to also be specified')
    # --host and --port must be used together
    if (args.host is None) != (args.port is None):
        ap.error('--host and --port must be specified together')
    return args

_ARGS = _parse_args()

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

    def _wait_for_family(root, family, retries=6, delay_ms=120):
        """Return True once family appears in tkfont.families()."""
        fams = set(tkfont.families(root))
        if family in fams:
            return True
        # Poll: give Tk a moment to ingest the new fontconfig cache
        for _ in range(retries):
            root.update()
            import time; time.sleep(delay_ms / 1000)
            fams = set(tkfont.families(root))
            if family in fams:
                return True
        return False

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
    win_bg      = "#060d1e",   # outer window / waterfall background
    panel_bg    = "#0c1525",   # left control panel
    panel_mid   = "#0e1a2e",   # toolbar / dividers
    spec_bg     = "#020810",   # spectrum/AF canvas bg
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
    grid        = "#121e30",   # grid lines
    grid_text   = "#3a5878",   # grid labels
    trace       = "#18e840",   # spectrum trace
    trace_fill  = "#030d06",   # trace fill
    filter_fill = "#142850",   # IF passband
    filter_edge = "#3060e0",   # IF passband edge
    vfo_line    = "#ff2828",   # VFO line
    smeter_grn  = "#28ee50",
    smeter_red  = "#ff3830",
    peak_bar    = "#22ee44",   # bright green peak bar
    toolbar_wf  = "#ff3030",   # "Waterfall" label red
    toolbar_sp  = "#c8d8f0",   # "Spectrum" label
    sep         = "#1a3050",
)

# ── --bg theme override ──────────────────────────────────────────────────────
if _ARGS.bg == 'light':
    _LIGHT_BG = "#FFECD6"
    for _k in ("win_bg","panel_bg","panel_mid","spec_bg","btn_gray"):
        C[_k] = _LIGHT_BG

MODES    = ["AM","ECSS","FM","LSB","USB","CW","DIG"]
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

def db_to_rgb(db, dmin=-150.0, dmax=0.0):
    t = max(0.0, min(1.0, (db-dmin)/(dmax-dmin)))
    stops = [(0.00,(4,8,22)),(0.18,(0,0,140)),(0.38,(0,120,200)),
             (0.55,(0,200,0)),(0.73,(230,200,0)),(1.00,(255,20,0))]
    for i in range(len(stops)-1):
        t0,c0 = stops[i]; t1,c1 = stops[i+1]
        if t<=t1 or i==len(stops)-2:
            f=max(0.0,min(1.0,(t-t0)/(t1-t0) if t1>t0 else 0.0))
            return (int(c0[0]+(c1[0]-c0[0])*f),
                    int(c0[1]+(c1[1]-c0[1])*f),
                    int(c0[2]+(c1[2]-c0[2])*f))
    return stops[-1][1]

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

# ── RTP helpers (GUI side) ────────────────────────────────────────────────────

def _rtp_pack_gui(payload: bytes, seq: int, ts: int, ssrc: int = 0xABCD1234) -> bytes:
    byte0 = 0x80
    byte1 = 0 & 0x7F   # PT 0 = PCMU
    return struct.pack("!BBHII", byte0, byte1, seq & 0xFFFF, ts, ssrc) + payload

def _rtp_unpack_gui(data: bytes):
    if len(data) < 12:
        return None
    hdr = struct.unpack("!BBHII", data[:12])
    return data[12:], hdr[2], hdr[3]

def _ulaw_to_linear16_gui(ulaw_bytes: bytes) -> bytes:
    out = bytearray(len(ulaw_bytes) * 2)
    for i, b in enumerate(ulaw_bytes):
        b = ~b & 0xFF
        sign = b & 0x80
        exp  = (b >> 4) & 0x07
        mantissa = b & 0x0F
        s = ((mantissa << 1) | 0x21) << exp
        s -= 33
        if sign:
            s = -s
        s = max(-32768, min(32767, s))
        struct.pack_into("<h", out, i * 2, s)
    return bytes(out)

def _linear16_to_ulaw_gui(samples: bytes) -> bytes:
    out = bytearray(len(samples) // 2)
    for i in range(len(out)):
        s = struct.unpack_from("<h", samples, i * 2)[0]
        sign = 0 if s >= 0 else 0x80
        if s < 0:
            s = -s
        s = min(s, 32767)
        s += 33
        exp = 0
        for e in range(7, -1, -1):
            if s >= (1 << (e + 5)):
                exp = e
                break
        mantissa = (s >> (exp + 1)) & 0x0F
        ulaw = ~(sign | (exp << 4) | mantissa) & 0xFF
        out[i] = ulaw
    return bytes(out)


class RTPAudioClient:
    """
    Manages the GUI side of the RTP/UDP audio channel.

    Behaviour driven by PTT state:
      PTT OFF → open speaker stream, receive RTP from server and play
      PTT ON  → mute speaker, open mic stream, send RTP to server

    PyAudio is imported lazily so the GUI still runs on machines without it
    (audio features silently disabled with a console warning).
    """

    def __init__(self, server_host: str, server_port: int):
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
        self._sample_rate  = AUDIO_SAMPLE_RATE
        self._frame_ms     = AUDIO_FRAME_MS
        self._frame_samps  = AUDIO_FRAME_SAMPS

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

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def open(self, server_host: str, server_udp_port: int,
             sample_rate: int = AUDIO_SAMPLE_RATE,
             frame_ms: int = AUDIO_FRAME_MS):
        """Call this when the server sends audio_port."""
        self._host        = server_host
        self._port        = server_udp_port
        self._sample_rate = sample_rate
        self._frame_ms    = frame_ms
        self._frame_samps = int(sample_rate * frame_ms / 1000)

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
                **kw,
            )
        except Exception as e:
            print(f"[audio] speaker stream error: {e}")

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
        import pyaudio
        payload = _linear16_to_ulaw_gui(in_data)
        pkt = _rtp_pack_gui(payload, self._seq, self._ts)
        self._seq = (self._seq + 1) & 0xFFFF
        self._ts  = (self._ts + frame_count) & 0xFFFFFFFF
        try:
            self._sock.sendto(pkt, (self._host, self._port))
        except OSError:
            pass
        return (None, pyaudio.paContinue)

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
                try:
                    self._rx_stream.write(pcm)
                except Exception:
                    pass


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
        s.settimeout(None); self.sock=s; self.connected=True
        threading.Thread(target=self._rx,daemon=True).start()
        return True,"ok"

    def disconnect(self):
        self.connected=False
        if self.sock:
            try: self.sock.close()
            except: pass
            self.sock=None

    def send(self,obj):
        if not self.connected or not self.sock: return False
        d=(json.dumps(obj)+"\n").encode()
        try:
            with self._lk: self.sock.sendall(d)
            return True
        except OSError:
            self.connected=False
            self.app.q.put({"type":"disconnected"})
            return False

    def _rx(self):
        buf=b""
        while self.connected:
            try: data=self.sock.recv(65536)
            except: break
            if not data: break
            buf+=data
            while b"\n" in buf:
                line,buf=buf.split(b"\n",1)
                line=line.strip()
                if not line: continue
                try: self.app.q.put(json.loads(line.decode()))
                except: pass
        self.connected=False
        self.app.q.put({"type":"disconnected"})

# ── Waterfall canvas ──────────────────────────────────────────────────────────

class WFCanvas(tk.Canvas):
    def __init__(self,master,img_w,af=False,**kw):
        kw.setdefault("bg",C["win_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.img_w=img_w; self.rows=collections.deque(); self._img=None
        self.af=af
        self.f0=28_490_000.0; self.f1=28_510_000.0  # updated externally
        self._app=None   # set by App after construction
        # Image item placed at top-left; grid overlay items drawn after (on top)
        self._iid=self.create_image(0,0,anchor="nw")
        self.bind("<Configure>",lambda e:(self._render(),self._draw_overlay()))

    def set_freq_range(self,f0,f1):
        self.f0=f0; self.f1=f1; self._draw_overlay()

    def add_row(self,spectrum,dmin=-150,dmax=0):
        n=len(spectrum)
        if n==0: return
        w=self.img_w; row=bytearray(w*3)
        for x in range(w):
            si=min(int(x*n/w),n-1)
            r,g,b=db_to_rgb(spectrum[si],dmin,dmax)
            row[x*3]=r; row[x*3+1]=g; row[x*3+2]=b
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        lbl_h=max(10,int(round(12*sc)))
        ch=max(self.winfo_height()-lbl_h,1)
        self.rows.appendleft(bytes(row))
        # Keep at most canvas-height rows so history fills exactly the widget
        while len(self.rows)>ch: self.rows.pop()
        self._render()
        self._draw_overlay()

    def _render(self):
        nrows=len(self.rows)
        if nrows==0: return
        cw=max(self.winfo_width(),1)
        ch=max(self.winfo_height(),1)
        src_w=self.img_w

        # Reserve a bottom strip for the frequency axis line/labels so the
        # waterfall image stops above it instead of being drawn underneath
        # (and thus overlapped by) the axis overlay.
        sc=getattr(self._app,'_sc',1.0) if self._app else 1.0
        lbl_h=max(10,int(round(12*sc)))
        avail_h=max(1,ch-lbl_h)

        # Build PPM at native row width, native row count
        hdr=f"P6\n{src_w} {nrows}\n255\n".encode()
        body=b"".join(self.rows)
        try:
            src=tk.PhotoImage(width=src_w,height=nrows,data=hdr+body,format="PPM")
        except tk.TclError: return

        # Scale to canvas width using zoom/subsample (integer ratios only in Tk)
        zx=max(1,round(cw/src_w)) if cw>=src_w else 1
        sx=max(1,round(src_w/cw)) if src_w>cw else 1
        if zx>1: src=src.zoom(zx,1)
        if sx>1: src=src.subsample(sx,1)

        # Position image so its bottom aligns to the top of the reserved
        # axis strip; empty space at top remains canvas bg (black) while
        # filling up.
        y_off=max(0,avail_h-nrows)
        self.coords(self._iid,0,y_off)
        self._img=src
        self.itemconfig(self._iid,image=self._img)

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
            # Label drawn in the reserved bottom strip, below the image
            self.create_text(x+2,ch-2,text=lbl,fill=C["grid_text"],
                             anchor="sw",font=gfont,tags="wf_overlay")
            f+=step
        # Horizontal bottom axis line
        self.create_line(0,ch-lbl_h,cw,ch-lbl_h,fill=C["sep"],tags="wf_overlay")

# ── Spectrum canvas ───────────────────────────────────────────────────────────

class SpecCanvas(tk.Canvas):
    DB_MIN=-150.0; DB_MAX=0.0; GRAB=6

    def __init__(self,master,app,show_filter=False,af=False,**kw):
        kw.setdefault("bg",C["spec_bg"]); kw.setdefault("highlightthickness",0)
        super().__init__(master,**kw)
        self.app=app; self.show_filter=show_filter; self.af=af
        self.f0=28_490_000.0; self.f1=28_510_000.0; self.data=[]
        self.drag=None; self._last=0.0
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
        self.f0=f0; self.f1=f1; self.data=spec; self.draw()

    def draw(self):
        self.delete("all")
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
            pts=[]
            for i,db in enumerate(self.data):
                pts.extend([i/(n-1)*w,self._dy(db, draw_h)])
            self.create_polygon(pts+[w,draw_h,0,draw_h],fill=C["trace_fill"],outline="")
            self.create_line(pts,fill=C["trace"],width=1)

        # ── 2. IF filter overlay (behind grid, over trace) ────────────────────
        if self.show_filter:
            ctr=(self.f0+self.f1)/2
            fl=self.app.state["filter_lo"]; fh=self.app.state["filter_hi"]
            x1=self._fx(ctr+fl); x2=self._fx(ctr+fh)
            self.create_rectangle(x1,0,x2,draw_h,fill=C["filter_fill"],
                                  outline="",stipple="gray50")
            self.create_line(x1,0,x1,draw_h,fill=C["filter_edge"],width=1)
            self.create_line(x2,0,x2,draw_h,fill=C["filter_edge"],width=1)
            xc=self._fx(ctr)
            self.create_line(xc,0,xc,draw_h,fill=C["vfo_line"],width=1,dash=(4,3))

        # ── 3. dB grid lines + labels (ON TOP of trace) ───────────────────────
        db_labels=[0,-25,-50,-75,-100,-125,-150]
        for db in db_labels:
            y=self._dy(db, draw_h)
            self.create_line(0,y,w,y,fill=C["grid"])
            self.create_text(2,y+1,text=f"{db} dB" if db==0 else str(db),
                             fill=C["grid_text"],anchor="nw",font=gfont)

        # ── 4. Frequency grid lines + labels (ON TOP of trace) ────────────────
        # Estimate pixel width of widest dB label ("-150", 4 chars) so that
        # X-axis frequency labels don't overlap the Y-axis dB labels on the left.
        _db_lbl_w = max(28, int(round(30 * sc)))
        span=self.f1-self.f0
        if span>0:
            step=nice_step(span/12)
            f=math.ceil(self.f0/step)*step
            while f<self.f1:
                x=self._fx(f)
                self.create_line(x,0,x,draw_h,fill=C["grid"])
                lbl=f"{f:.0f}" if self.af else f"{f/1000:.0f}"
                # Label in the reserved bottom strip — skip labels that would
                # land on top of the dB labels in the left margin.
                if x >= _db_lbl_w:
                    self.create_text(x+2,draw_h+lbl_h-1,text=lbl,fill=C["grid_text"],
                                     anchor="sw",font=gfont)
                f+=step

        # ── 5. Separator line between trace area and label strip ──────────────
        self.create_line(0,draw_h,w,draw_h,fill=C["sep"])

        # ── 6. Green peak/hold line at top (always on top) ───────────────────
        self.create_line(0,2,w,2,fill=C["peak_bar"],width=2)

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
        now=time.time()
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
        self._sc=1.0   # current scale factor, updated by App
        self.bind("<Configure>",lambda e:self._draw())

    def set_value(self,dbm,txt): self.dbm=dbm; self.txt=txt; self._draw()

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
        self.create_text(max(3,int(round(5*sc))),h-max(2,int(round(4*sc))),
                         text=f"{self.dbm:.1f} dBm",
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
            self._row_lbl=tk.Button(self,text=lbl_text,
                     bg=C["btn_sel"],fg=C["btn_sel_fg"],
                     font=_gui_font(lbl_fs,"bold"),relief="flat",bd=0,
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
        tk.Label(top,text="Frequency (Hz):",bg=C["panel_bg"],
                 fg=C["text"]).pack(padx=12,pady=(12,4))
        var=tk.StringVar(value=str(self.value))
        ent=tk.Entry(top,textvariable=var,width=16,justify="right")
        ent.pack(padx=12,pady=4); ent.select_range(0,"end"); ent.focus_set()
        def apply(_=None):
            try: v=int(float(var.get()))
            except: top.destroy(); return
            self.set_value(v,notify=True); top.destroy()
        ent.bind("<Return>",apply)
        tk.Button(top,text="Set",command=apply,bg=C["btn_gray"],
                  fg=C["text"]).pack(pady=(4,12))

# ── toolbar strip (between RF waterfall and AF area) ─────────────────────────

def _toolbar(parent,rbw="23.4 Hz",avg="2",bg=None,sc=1.0,app=None,box_id="rf"):
    if bg is None: bg=C["panel_mid"]
    h=max(16,int(round(BASE['toolbar_h']*sc)))
    fs=max(6,int(round(8*sc)))
    bar=tk.Frame(parent,bg=bg,height=h)
    bar.pack(side="top",fill="x"); bar.pack_propagate(False)

    def lbl(txt,fg,font=None):
        if font is None: font=_gui_font(fs)
        tk.Label(bar,text=txt,bg=bg,fg=fg,font=font).pack(side="left",padx=max(1,int(round(2*sc))))

    def sep():
        tk.Label(bar,text="──",bg=bg,fg=C["text_dim"],
                 font=_gui_font(max(5,int(round(7*sc))))).pack(side="left")

    # ── Mutually exclusive Waterfall / Spectrum toggle buttons ──────────────
    _wf_state = {"sel": "Waterfall"}   # one mutable cell shared by both closures

    def _make_toggle(name, btn_ref_key):
        def _cmd():
            _wf_state["sel"] = name
            _update_toggle_colors()
            if app:
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
    for t in ["◀◀","◀"]: lbl(t,C["text_dim"])
    sep()
    for name, fg in [("Waterfall", C["toolbar_wf"]), ("Spectrum", C["toolbar_sp"])]:
        b = tk.Button(bar, text=name, bg=bg, fg=fg,
                      activebackground=C["btn_sel"], activeforeground=C["btn_sel_fg"],
                      font=_gui_font(fs), relief="flat", bd=1,
                      padx=max(1,int(round(2*sc))), pady=0,
                      command=_make_toggle(name, name))
        b.pack(side="left", padx=max(1,int(round(2*sc))))
        _toggle_btns[name] = b
        sep()
    # Apply initial colours (Waterfall selected by default)
    _update_toggle_colors()

    for t in ["◀","◀◀"]: lbl(t,C["text_dim"])
    sep()
    lbl(f"RBW {rbw}",C["text_dim"])
    tk.Label(bar,text=avg,bg=C["btn_gray"],fg=C["text"],
             font=_gui_font(fs),width=2,relief="flat").pack(side="left",padx=max(1,int(round(2*sc))))
    lbl("Avg",C["text_dim"]); sep()
    lbl("Zoom",C["text_dim"]); sep()
    lbl("Speed",C["text_dim"])
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
        except: pass
        try:
            root.option_add("*Font","TkDefaultFont")
        except: pass
        try:
            # Disabled labels use the same dim color as the LO A label
            root.option_add("*Label.disabledForeground",C["text_dim"])
        except: pass

        self.net=Net(self); self.q=queue.Queue()
        self.rtp_audio = RTPAudioClient("", 0)   # configured when server sends audio_port

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
            agc="Med", mode="USB",
            rf_gain=20.0, volume=80.0, squelch=-130.0,
            agc_thresh=-100.0,
            zoom=1, sample_rate=192_000.0, running=False,
            nr=False, nbrf=False, nbif=False, afc=False,
            mute=False, notch=False, anotch=False,
            ptt=False,
            user_buttons=[{"label":"","type":"normal"} for _ in range(6)],
            user_btn_state=[False]*6,
        )
        self._sup=False
        # HiDPI / 4K scaling state
        self._scale_level = max(-5, min(5, _ARGS.scale))  # from --scale flag
        self._sc = 1.25 ** self._scale_level  # current visual scale factor
        self._build()
        self._refresh()
        self._clock()
        self.poll()

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
        r.minsize(scaled('min_w',sc), scaled('min_h',sc))

        # ── top: RF waterfall + spectrum strip ────────────────────────────────
        top=tk.Frame(r,bg=C["win_bg"])
        top.pack(side="top",fill="both",expand=True)

        self.rf_wf=WFCanvas(top,img_w=NUM_BINS)
        self.rf_wf._app=self
        self.rf_wf.pack(side="top",fill="both",expand=True)

        spec_fr=tk.Frame(top,bg=C["spec_bg"],height=scaled('spec_h',sc))
        spec_fr.pack(side="top",fill="x"); spec_fr.pack_propagate(False)
        self._spec_fr=spec_fr
        self.rf_spec=SpecCanvas(spec_fr,self,show_filter=True)
        self.rf_spec.pack(fill="both",expand=True)

        # ── toolbar between RF and bottom ─────────────────────────────────────
        self._toolbar1_parent=r
        self._toolbar1=_toolbar(r,rbw="23.4 Hz",avg="2",sc=sc,app=self,box_id="rf")

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

        sm_w=scaled('smeter_w',sc); sm_h=scaled('smeter_h',sc)
        self.smeter=SMeter(sm_row,width=sm_w,height=sm_h)
        self.smeter._sc=sc
        self.smeter.pack(side="left",fill="x",expand=True,
                         padx=(max(1,int(round(2*sc))),max(2,int(round(4*sc)))))

        # ── PTT circular button ───────────────────────────────────────────────
        ptt_size = max(36, int(round(54 * sc)))
        ptt_col = tk.Frame(sm_row, bg=C["panel_bg"])
        ptt_col.pack(side="left", padx=(0, max(2, int(round(4*sc)))))
        self._ptt_canvas = tk.Canvas(ptt_col, width=ptt_size, height=ptt_size,
                                     bg=C["panel_bg"], highlightthickness=0)
        self._ptt_canvas.pack()
        fs_ptt = max(6, int(round(7*sc)))
        self._ptt_size = ptt_size

        def _draw_ptt_btn(active):
            c = self._ptt_canvas
            c.delete("all")
            sz = self._ptt_size
            margin = max(3, int(round(4*sc)))
            fill_color = "#cc1111" if active else "#117711"
            rim_color  = "#ff4444" if active else "#22ee44"
            label_color = "#ffcccc" if active else "#ccffcc"
            c.create_oval(margin, margin, sz-margin, sz-margin,
                          fill=fill_color, outline=rim_color,
                          width=max(2, int(round(3*sc))))
            # Subtle inner highlight
            hi = margin + max(3, int(round(5*sc)))
            c.create_oval(hi, hi, sz-hi, sz-hi,
                          fill="", outline="#cc4444" if active else "#44aa44",
                          width=max(1, int(round(2*sc))))
            c.create_text(sz//2, sz//2, text="PTT",
                          fill=label_color,
                          font=_gui_font(fs_ptt, "bold"))

        self._draw_ptt_btn = _draw_ptt_btn
        _draw_ptt_btn(False)

        def _ptt_click(_evt=None):
            new_state = not self.state.get("ptt", False)
            self.state["ptt"] = new_state
            _draw_ptt_btn(new_state)
            self.net.send({"cmd": "set_ptt", "enabled": new_state,
                           "udp_port": self.rtp_audio.local_udp_port()})
            self.rtp_audio.set_ptt(new_state)

        self._ptt_canvas.bind("<Button-1>", _ptt_click)
        self._ptt_canvas.config(cursor="hand2")

        # ── Mode buttons + FreqMgr ────────────────────────────────────────────
        mode_row=tk.Frame(lp,bg=C["panel_bg"])
        mode_row.pack(fill="x",padx=max(2,int(round(4*sc))),
                      pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        self.mode_btns={}
        fs_mode=max(6,int(round(8*sc)))
        for m in MODES:
            b=tk.Button(mode_row,text=m,width=4,
                        command=lambda mm=m:self._set_mode(mm),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        activebackground=C["btn_sel"],
                        font=_gui_font(fs_mode),relief="flat",bd=1,
                        padx=max(1,int(round(2*sc))),pady=max(1,int(round(1*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.mode_btns[m]=b
        tk.Button(mode_row,text="FreqMgr",bg=C["btn_gray"],fg=C["btn_sel_fg"],
                  font=_gui_font(fs_mode),relief="flat",bd=1,
                  padx=max(2,int(round(3*sc))),pady=max(1,int(round(1*sc))),
                  command=lambda:self.net.send({"cmd":"ui_button","name":"FreqMgr"})
                  ).pack(side="right",padx=max(1,int(round(2*sc))))

        # ── LO + Tune freq displays ───────────────────────────────────────────
        freq_box=tk.Frame(lp,bg=C["spec_bg"],bd=0)
        freq_box.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))

        # Track which LO is active (A or B) and last band selected per LO
        self._lo_active=tk.StringVar(value="A")
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

        # ── freq_box: outer container ─────────────────────────────────────────
        # We use a grid: column 0 = LO/Tune rows (stacked), column 1 = band
        # column spanning all three rows but anchored to the top, so the
        # first band button aligns exactly with the LO A row.
        freq_box.grid_columnconfigure(0,weight=1)
        freq_box.grid_columnconfigure(1,weight=0)

        lo_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_row.grid(row=0,column=0,sticky="ew")

        # Left side: LO A display
        self.lo_disp=FreqDisp(lo_row,self,label="LO A",
                              lo_select_cmd=lambda:_select_lo("A"))
        self.lo_disp._label_text="LO A"
        self._lo_a_disp=self.lo_disp
        self.lo_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_disp.set_value(self.state["lo_freq"],notify=False)

        # ── Band buttons column — top-aligned to LO A row ─────────────────────
        band_col=tk.Frame(freq_box,bg=C["spec_bg"])
        band_col.grid(row=0,column=1,rowspan=3,sticky="n",
                       padx=max(2,int(round(3*sc))),
                       pady=(max(1,int(round(2*sc))),0))
        fs_band=max(6,int(round(7*sc)))
        btn_w=max(4,int(round(5*sc)))
        self._band_btns={}   # name -> Button

        def _band_select(bname, bfreq):
            active=self._lo_active.get()
            self._lo_band[active]=bname
            _refresh_band_highlight()
            if active=="B":
                self.lo_b_disp.set_value(bfreq,notify=True)
            else:
                self.set_frequency(bfreq)

        for bname,bfreq in BANDS:
            b=tk.Button(band_col,text=bname,width=btn_w,anchor="center",
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        activebackground=C["btn_sel"],activeforeground=C["btn_sel_fg"],
                        font=_gui_font(fs_band),relief="flat",bd=0,highlightthickness=0,
                        pady=0,
                        command=lambda n=bname,f=bfreq:_band_select(n,f))
            b.pack(fill="x",padx=0,pady=(0,max(0,int(round(1*sc)))))
            self._band_btns[bname]=b

        lo_b_row=tk.Frame(freq_box,bg=C["spec_bg"])
        lo_b_row.grid(row=1,column=0,sticky="ew")
        self.lo_b_disp=FreqDisp(lo_b_row,self,label="LO B",
                                on_change=self.on_lo_b_changed,
                                lo_select_cmd=lambda:_select_lo("B"))
        self.lo_b_disp._label_text="LO B"
        self._lo_b_disp=self.lo_b_disp
        self.lo_b_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.lo_b_disp.set_value(self.state["lo_b_freq"],notify=False)

        # Apply initial LO button colours
        _refresh_lo_btns()

        tune_row=tk.Frame(freq_box,bg=C["spec_bg"])
        tune_row.grid(row=2,column=0,sticky="ew")
        self.tune_disp=FreqDisp(tune_row,self,label="Tune",on_change=self.on_tune_changed)
        self.tune_disp._label_text="Tune"
        self.tune_disp.pack(side="left",fill="x",expand=True,padx=max(1,int(round(2*sc))),pady=max(1,int(round(2*sc))))
        self.tune_disp.set_value(self.state["tune_freq"],notify=False)

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


        # ── SDR-Device / Soundcard / Bandwidth / Options ──────────────────────
        r1=tk.Frame(lp,bg=C["panel_bg"])
        r1.pack(fill="x",padx=max(2,int(round(4*sc))),pady=(max(1,int(round(2*sc))),max(1,int(round(1*sc)))))
        for t in ["SDR-Device","Bandwidth","Options"]:
            _fbtn(r1,t,sc=sc,
                  command=lambda t=t:self.net.send({"cmd":"ui_button","name":t})
                  ).pack(side="left",padx=max(1,int(round(1*sc))),fill="x",expand=True)
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

        # ── NR / NB RF / NB IF / AFC ──────────────────────────────────────────
        r4=tk.Frame(lp,bg=C["panel_bg"])
        r4.pack(fill="x",padx=max(2,int(round(4*sc))),
                pady=(max(2,int(round(4*sc))),max(1,int(round(1*sc)))))
        self.dsp_btns={}
        fs_dsp=max(6,int(round(8*sc)))
        for t,k in [("NR","nr"),("NB RF","nbrf"),("NB IF","nbif"),("AFC","afc")]:
            b=tk.Button(r4,text=t,command=lambda k=k:self._toggle(k),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.dsp_btns[k]=b

        # ── Mute / AGC Med / Notch / ANotch ──────────────────────────────────
        r5=tk.Frame(lp,bg=C["panel_bg"])
        r5.pack(fill="x",padx=max(2,int(round(4*sc))),pady=max(1,int(round(1*sc))))
        self.agc_btns={}
        for t,k in [("Mute","mute"),("AGC Med","agcmed"),("Notch","notch"),("ANotch","anotch")]:
            b=tk.Button(r5,text=t,
                        command=lambda k=k,t=t:self._agc_tog(k,t),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="left",padx=max(1,int(round(1*sc)))); self.agc_btns[k]=b

        # ── User-defined buttons (1-3 on the AFC row, 4-6 on the ANotch row,
        #    right-aligned). Labels/types come from the server; can be
        #    "normal" (momentary press) or "push" (push-push/toggle). ──────
        self.user_btns={}
        for i in reversed(range(3)):
            idx=i+1
            b=tk.Button(r4,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        width=7,anchor="center",
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="right",padx=max(1,int(round(1*sc)))); self.user_btns[idx]=b
        for i in reversed(range(3)):
            idx=i+4
            b=tk.Button(r5,text=self._user_btn_label(idx),
                        command=lambda idx=idx:self._user_btn_press(idx),
                        bg=C["btn_gray"],fg=C["btn_sel_fg"],
                        font=_gui_font(fs_dsp),relief="flat",bd=1,
                        width=7,anchor="center",
                        padx=max(3,int(round(5*sc))),pady=max(1,int(round(2*sc))))
            b.pack(side="right",padx=max(1,int(round(1*sc)))); self.user_btns[idx]=b

        # ── Date/time + connect controls (bottom of left panel) ──────────────
        bot_l=tk.Frame(lp,bg=C["panel_bg"])
        bot_l.pack(fill="x",padx=max(2,int(round(4*sc))),
                   pady=(max(4,int(round(8*sc))),max(2,int(round(3*sc)))),side="bottom")
        fs_clk=max(8,int(round(BASE['clock_size']*sc)))
        fs_cr=max(6,int(round(8*sc)))

        # ── Connect controls (host / port / connect / status dot) ────────────
        cr=tk.Frame(bot_l,bg=C["panel_bg"])
        cr.pack(fill="x",anchor="w")
        # Determine if host/port were supplied via CLI flags
        _cli_host = _ARGS.host is not None
        # Always create the StringVars; pre-fill from flags if provided
        self.host_var=tk.StringVar(value=_ARGS.host if _cli_host else "127.0.0.1")
        self.port_var=tk.StringVar(value=str(_ARGS.port) if _cli_host else "50101")
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

    # ── right: AF waterfall + spectrum ────────────────────────────────────────
    def _build_right(self,parent):
        sc=self._sc
        rp=tk.Frame(parent,bg=C["spec_bg"])
        rp.pack(side="left",fill="both",expand=True)
        self._rp=rp

        self.af_wf=WFCanvas(rp,img_w=AF_BINS,af=True)
        self.af_wf._app=self
        self.af_wf.pack(side="top",fill="both",expand=True)

        af_sf=tk.Frame(rp,bg=C["spec_bg"],height=scaled('af_spec_h',sc))
        af_sf.pack(side="top",fill="x"); af_sf.pack_propagate(False)
        self._af_sf=af_sf
        self.af_spec=SpecCanvas(af_sf,self,show_filter=False,af=True)
        self.af_spec.pack(fill="both",expand=True)

        self._toolbar2=_toolbar(rp,rbw="5.9 Hz",avg="1",sc=sc,app=self,box_id="af")

    # ── HiDPI scale change ────────────────────────────────────────────────────
    def _build_scale_ctrl(self):
        """Persistent HiDPI +/- scale control.

        Built exactly once and never destroyed, so it can never 'disappear'
        even though _change_scale() destroys/rebuilds most of the rest of
        the GUI. It floats as an overlay in the bottom-right corner of the
        window. Range: -9 .. +9, default 0 (shown centered between the two
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

    def _update_minsize(self):
        """Compute minimum window size so no GUI element can disappear.

        The bottom panel (_bot) has a fixed natural height determined by its
        children. We measure it after the layout settles, add the toolbar and
        spec strip heights, and apply that as the window's minimum height so
        the waterfall (which uses expand=True) absorbs any spare space but
        never pushes the control rows off-screen.
        """
        self.root.update_idletasks()
        sc = self._sc
        # Fixed-height regions below the waterfall
        spec_h   = scaled('spec_h', sc)
        tb_h     = max(16, int(round(BASE['toolbar_h'] * sc)))
        bot_h    = self._bot.winfo_reqheight()
        bot_w    = self._bot.winfo_reqwidth()
        # Minimum waterfall height (keep it visible but can be small)
        wf_min   = max(40, int(round(60 * sc)))
        min_h    = wf_min + spec_h + tb_h + bot_h + 4
        min_w    = max(scaled('min_w', sc), bot_w)
        self.root.minsize(min_w, min_h)
        return min_w, min_h

    def _sync_bot_height(self):
        """Set _bot's height to the left panel's true required content height.

        lp uses pack_propagate(False) to enforce a fixed width, but that also
        suppresses height reporting to _bot, causing the bottom control area to
        be clipped at higher scale levels.  We work around this by summing the
        requisite heights of lp's packed children and applying that as _bot's
        explicit height, so all controls remain fully visible.
        """
        self.root.update_idletasks()
        lp=self._lp
        total_h=0
        for child in lp.pack_slaves():
            try:
                total_h+=child.winfo_reqheight()
                info=child.pack_info()
                pady=info.get('pady',0)
                if isinstance(pady,(list,tuple)):
                    total_h+=pady[0]+pady[1]
                else:
                    total_h+=int(pady)*2
            except Exception:
                pass
        if total_h>0:
            self._bot.pack_propagate(False)
            self._bot.config(height=total_h)
            self._update_minsize()

    def _change_scale(self,delta):
        """Rebuild the GUI at the new scale factor.

        The +/- buttons themselves live in a persistent overlay
        (see _build_scale_ctrl) that is never destroyed, so they remain
        usable indefinitely. Scale level range is -9..+9, default 0,
        and the current level (not a percentage) is shown in the label
        between the two buttons.
        """
        self._scale_level=max(-5,min(5,self._scale_level+delta))
        self._sc=1.25**self._scale_level
        sc=self._sc

        # Destroy and rebuild left panel and right panel inside _bot
        for child in self._bot.winfo_children():
            child.destroy()

        # Also rebuild top-area fixed-height frames (spec strip)
        self._spec_fr.config(height=scaled('spec_h',sc))

        # Rebuild left and right panels
        self._build_left(self._bot)
        self._build_right(self._bot)

        # Rebuild toolbar1 (between RF strip and bot)
        self._toolbar1.destroy()
        self._toolbar1=_toolbar(self._toolbar1_parent,rbw="23.4 Hz",avg="2",sc=sc,app=self,box_id="rf")
        # Re-pack toolbar1 before _bot
        self._toolbar1.pack(before=self._bot)

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
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        new_w = max(min_w, min(scaled('win_w', sc), screen_w))
        new_h = max(min_h, min(scaled('win_h', sc), screen_h))
        self.root.geometry(f"{new_w}x{new_h}")

        # Re-apply minsize once more after geometry settles, in case
        # widget reflow slightly changed the natural sizes.
        self.root.after(100, self._update_minsize)
        self.root.after(120, self._sync_bot_height)

    # ── control logic ──────────────────────────────────────────────────────────
    def _refresh(self):
        for m,b in self.mode_btns.items():
            if m==self.state["mode"]:
                b.config(bg=C["btn_sel"],fg=C["btn_sel_fg"])
            else:
                b.config(bg=C["btn_gray"],fg=C["btn_sel_fg"])
        for k,b in self.dsp_btns.items():
            on=self.state.get(k,False)
            b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                     fg=C["btn_sel_fg"])
        for k,b in self.agc_btns.items():
            on=(self.state["agc"]=="Med") if k=="agcmed" else self.state.get(k,False)
            b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                     fg=C["btn_sel_fg"])
        # User-defined buttons: refresh label and (for push-push type) the
        # pressed/released highlight.
        for idx,b in self.user_btns.items():
            b.config(text=self._user_btn_label(idx))
            cfg=self._user_btn_cfg(idx)
            if cfg.get("type")=="push":
                on=self._user_btn_state(idx)
                b.config(bg=C["btn_sel"] if on else C["btn_gray"],
                         fg=C["btn_sel_fg"])
            else:
                b.config(bg=C["btn_gray"],fg=C["btn_sel_fg"])
        # PTT button
        if hasattr(self, '_draw_ptt_btn'):
            self._draw_ptt_btn(bool(self.state.get("ptt", False)))


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

        in_fr, get_in = _make_panel(
            panels_fr, "Microphone (input)",
            "max_input_channels", self.rtp_audio._in_device)
        in_fr.pack(side="left", fill="both", expand=True, padx=(0, pad // 2))

        out_fr, get_out = _make_panel(
            panels_fr, "Speaker / Headphones (output)",
            "max_output_channels", self.rtp_audio._out_device)
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
            ok,msg=self.net.connect(host,port)
            if not ok:
                self.conn_btn.config(text="Connect",state="normal")
                messagebox.showerror("Connect",f"Cannot connect to {host}:{port}\n{msg}")
                return
            self.net.send({"cmd":"hello"})
            self.net.send({"cmd":"set_freq","hz":self.state["lo_freq"]})
            self.net.send({"cmd":"set_lo_b_freq","hz":self.state["lo_b_freq"]})
            self.net.send({"cmd":"set_tune_freq","hz":self.state["tune_freq"]})
            self.net.send({"cmd":"set_mode","mode":self.state["mode"]})
            self.net.send({"cmd":"start"})
            self.state["running"]=True
            self.conn_btn.config(text="Disconnect",state="normal",
                                 bg="#2a0e0e",fg=C["btn_red_fg"])
            self.conn_status.config(fg=C["btn_grn_fg"])
            self.start_btn.config(text="Stop",bg="#6a1414",fg=C["btn_red_fg"])

    def _on_disconnected(self):
        self.state["running"]=False
        self.rtp_audio.close()
        self.conn_btn.config(text="Connect",state="normal",
                             bg="#0e2a10",fg=C["btn_grn_fg"])
        self.conn_status.config(fg="#331111")
        self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])

    def _set_mode(self,m):
        self.state["mode"]=m
        defs={"LSB":(-2800,-100),"USB":(100,2800),"AM":(-4500,4500),
              "FM":(-8000,8000),"CW":(300,700)}
        lo,hi=defs.get(m,(self.state["filter_lo"],self.state["filter_hi"]))
        self.state["filter_lo"]=lo; self.state["filter_hi"]=hi
        self._refresh(); self.net.send({"cmd":"set_mode","mode":m})

    def _toggle(self,k):
        self.state[k]=not self.state.get(k,False); self._refresh()
        cmd={"nr":"set_nr","nbrf":"set_nbrf","nbif":"set_nbif","afc":"set_afc"}.get(k)
        if cmd:
            self.net.send({"cmd":cmd,"enabled":self.state[k]})

    def _agc_tog(self,k,t):
        if k=="agcmed":
            self.state["agc"]="Med" if self.state["agc"]!="Med" else "Off"
            self.net.send({"cmd":"set_agc","mode":self.state["agc"]})
        elif k in self.state:
            self.state[k]=not self.state[k]
            cmd={"mute":"set_mute","notch":"set_notch","anotch":"set_anf"}.get(k)
            if cmd:
                self.net.send({"cmd":cmd,"enabled":self.state[k]})
        self._refresh()

    # ── user-defined buttons (server-configured, indices 1..6) ─────────────
    def _user_btn_cfg(self,idx):
        """Return {"label":..., "type":...} for user button idx (1..6),
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
            if not st or len(st)<6:
                st=[False]*6
            st[idx-1]=new_on
            self.state["user_btn_state"]=st
            self.net.send({"cmd":"user_button","index":idx,"enabled":new_on})
        else:
            self.net.send({"cmd":"user_button","index":idx})
        self._refresh()

    def _toggle_run(self):
        if not self.net.connected: return
        if self.state["running"]:
            self.net.send({"cmd":"stop"}); self.state["running"]=False
            self.start_btn.config(text="Start",bg=C["btn_grn"],fg=C["btn_grn_fg"])
        else:
            self.net.send({"cmd":"start"}); self.state["running"]=True
            self.start_btn.config(text="Stop",bg="#6a1414",fg=C["btn_red_fg"])

    def adj_zoom(self,d):
        z=int(self.state["zoom"])
        z=min(32,z*2) if d>0 else max(1,z//2)
        self.state["zoom"]=z; self.net.send({"cmd":"set_zoom","value":z})

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
        if not self._sup: self.net.send({"cmd":"set_freq","hz":hz})

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
        h12=now.strftime("%-I") if os.name!="nt" else now.strftime("%#I")
        ampm="a.m." if now.hour<12 else "p.m."
        try:
            self.clock_var.set(
                now.strftime(f"%#d/%#m/%Y  {h12}:%M:%S {ampm}")
                if os.name=="nt"
                else f"{now.day}/{now.month}/{now.year}  {h12}:{now.strftime('%M:%S')} {ampm}"
            )
        except Exception:
            self.clock_var.set(now.strftime("%d/%m/%Y  %H:%M:%S"))
        self.root.after(1000,self._clock)

    # ── network poll ──────────────────────────────────────────────────────────
    def poll(self):
        try:
            for _ in range(100):
                msg=self.q.get_nowait(); self._handle(msg)
        except queue.Empty: pass
        self.root.after(30,self.poll)

    def _handle(self,msg):
        t=msg.get("type")
        if t=="disconnected": self._on_disconnected()
        elif t=="audio_port":
            # Server is advertising its UDP RTP port — open the audio channel
            server_host = self.net.sock.getpeername()[0] if self.net.sock else "127.0.0.1"
            udp_port    = int(msg.get("port", 5004))
            sr          = int(msg.get("sample_rate", AUDIO_SAMPLE_RATE))
            fm          = int(msg.get("frame_ms", AUDIO_FRAME_MS))
            self.rtp_audio.open(server_host, udp_port, sample_rate=sr, frame_ms=fm)
            # Tell the server our UDP port so TX can reach us
            local_udp = self.rtp_audio.local_udp_port()
            if local_udp:
                self.net.send({"cmd": "audio_hello", "udp_port": local_udp})
        elif t=="data":
            f0=msg["f_start"]; f1=msg["f_stop"]
            self.rf_spec.update_data(f0,f1,msg["spectrum"])
            self.rf_wf.set_freq_range(f0,f1)
            self.rf_wf.add_row(msg["spectrum"])
            ar=msg.get("af_range",3000)
            self.af_spec.update_data(0,ar,msg["af_spectrum"])
            self.af_wf.set_freq_range(0,ar)
            self.af_wf.add_row(msg["af_spectrum"])
            self.smeter.set_value(msg["smeter_dbm"],msg["smeter_text"])
        if "state" in msg:
            self.state.update(msg["state"]); self._refresh()

# ── entry point ───────────────────────────────────────────────────────────────

def main():
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
