#!/usr/bin/env python3
"""
cat_server.py
================

A small simulated-SDR backend for `cat_gui.py`.

It listens on a TCP socket and speaks a simple newline-delimited JSON
protocol:

  * The GUI sends one JSON object per line, each with a "cmd" field, e.g.

        {"cmd": "set_freq", "hz": 14195000}
        {"cmd": "set_tune_freq", "hz": 14205000}
        {"cmd": "set_mode", "mode": "USB"}
        {"cmd": "set_agc",  "mode": "medium"}
        {"cmd": "set_agc_thresh", "value": -100.0}
        {"cmd": "set_filter", "lo": 100, "hi": 2800}
        {"cmd": "set_rf_gain", "value": 20.0}
        {"cmd": "set_volume",  "value": 80.0}
        {"cmd": "set_squelch", "value": -130.0}
        {"cmd": "set_nb",  "enabled": true}
        {"cmd": "set_nr",  "enabled": true}
        {"cmd": "set_nbrf","enabled": true}
        {"cmd": "set_nbif","enabled": true}
        {"cmd": "set_afc", "enabled": true}
        {"cmd": "set_anf", "enabled": true}
        {"cmd": "set_notch","enabled": true}
        {"cmd": "set_mute","enabled": true}
        {"cmd": "set_zoom","value": 2}
        {"cmd": "ui_button","name": "Full Screen"}
        {"cmd": "transport","action": "\u25b6"}
        {"cmd": "start"}
        {"cmd": "stop"}
        {"cmd": "hello"}

    Every command gets an immediate reply:

        {"resp": "ok", "state": {...full radio state...}}

  * While "running", the server pushes ~10 updates/second of the form:

        {
          "type": "data",
          "f_start": <Hz>, "f_stop": <Hz>, "spectrum": [dBm, ...],
          "af_range": 3000, "af_spectrum": [dBm, ...],
          "smeter_dbm": <float>, "smeter_text": "S7",
          "squelch_open": <bool>,
          "state": {...}
        }

This is enough for the GUI to draw the RF/AF spectra + waterfalls, move the
S-meter needle, light the squelch LED, and keep every control (frequency,
mode, AGC, filter, sliders, zoom, start/stop) in sync.

User-defined buttons
--------------------
Up to 6 user-defined buttons (N = 1..6) can be configured via CLI flags and
are advertised to the GUI in the "hello" response and in every "state" dict
as a "user_buttons" list:

    --user-button-label-N TEXT   Label for user button N (max 7 chars)
    --user-button-type-N  TYPE   "normal" (momentary) or "push" (push-push /
                                  toggle). Default: "normal"

A button the GUI sends becomes:

    {"cmd": "user_button", "index": N}                 (normal button press)
    {"cmd": "user_button", "index": N, "enabled": true} (push-push toggle)
"""

import argparse
import json
import math
import random
import socket
import struct
import threading
import time

# ── TOML config support ───────────────────────────────────────────────────────
try:
    import tomllib as _tomllib          # Python 3.11+
except ImportError:
    try:
        import tomli as _tomllib        # pip install tomli
    except ImportError:
        _tomllib = None

_SERVER_CONFIG_NAME = "cat_server.toml"

_SERVER_CONFIG_DEFAULTS = {
    "server": {
        "host": "0.0.0.0",
        "port": 50101,
    },
    "audio": {
        "audio_port": 5004,
        "no_audio":   False,
    },
    "user_buttons": {
        **{f"label_{n}": "" for n in range(1, 7)},
        **{f"type_{n}":  "normal" for n in range(1, 7)},
    },
}

_SERVER_CONFIG_TEMPLATE = """\
# CAT Server configuration
# CLI flags override these values at runtime without modifying this file.
# Use --config PATH to load a file from a non-default location.

[server]
host = "0.0.0.0"
port = 50101

[audio]
audio_port = 5004
no_audio = false

[user_buttons]
# label: max 7 characters; type: "normal" (momentary) or "push" (toggle)
label_1 = ""
type_1 = "normal"
label_2 = ""
type_2 = "normal"
label_3 = ""
type_3 = "normal"
label_4 = ""
type_4 = "normal"
label_5 = ""
type_5 = "normal"
label_6 = ""
type_6 = "normal"
"""

def _parse_simple_toml_srv(text):
    """Minimal TOML parser for simple key=value with [sections]."""
    result = {}
    section = result
    for raw in text.splitlines():
        line = raw.split('#')[0].strip()
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
                section[k] = v[1:-1]
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

def _load_server_config(path):
    """Return the parsed TOML dict, or {} on any error."""
    try:
        if _tomllib is not None:
            with open(path, "rb") as f:
                return _tomllib.load(f)
        else:
            with open(path, "r", encoding="utf-8") as f:
                return _parse_simple_toml_srv(f.read())
    except Exception as e:
        print(f"[config] WARNING: could not read {path}: {e}")
        return {}

def _ensure_server_config(path):
    """Create the config file with defaults if it does not exist, then load it."""
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_SERVER_CONFIG_TEMPLATE)
            print(f"[config] Created default config: {path}")
        except Exception as e:
            print(f"[config] WARNING: could not write default config: {e}")
    return _load_server_config(path)

import os

NUM_BINS = 600          # RF spectrum / waterfall bins
AF_BINS = 256           # AF spectrum / waterfall bins
AF_RANGE = 3000.0       # Hz shown on the AF display
UPDATE_HZ = 10.0        # data pushes per second
NUM_USER_BUTTONS = 6    # number of user-defined buttons (N = 1..6)

# ── RTP / UDP audio ──────────────────────────────────────────────────────────
AUDIO_SAMPLE_RATE  = 8000       # Hz
AUDIO_FRAME_MS     = 20         # milliseconds per RTP packet
AUDIO_FRAME_SAMPS  = int(AUDIO_SAMPLE_RATE * AUDIO_FRAME_MS / 1000)  # 160
AUDIO_RTP_TYPE     = 0          # PCM μ-law payload type (RTP PT 0 = PCMU)
AUDIO_UDP_PORT     = 5004       # default; overridable via --audio-port
# Simple sine-wave beep sent while running and PTT is off (receive side demo)
_AUDIO_TONE_HZ     = 440        # Hz of the demo tone the server sends

NOISE_FLOOR_DBM = -120.0
DB_S9 = -73.0           # dBm that corresponds to "S9" on the meter
DB_PER_S_UNIT = 6.0     # 6 dB per S-unit below S9


def dbm_to_s_text(dbm):
    """Convert a dBm reading into an 'S' string like the CAT GUI meter."""
    if dbm >= DB_S9:
        over = dbm - DB_S9
        if over < 0.5:
            return "S9"
        return f"S9 +{over:0.0f}dB"
    s = 9 - (DB_S9 - dbm) / DB_PER_S_UNIT
    s = max(0.0, s)
    return f"S{s:0.0f}"



# ── RTP helpers ───────────────────────────────────────────────────────────────

def _rtp_pack(payload: bytes, seq: int, ts: int, ssrc: int = 0x1234ABCD) -> bytes:
    """Pack a minimal 12-byte RTP header + payload."""
    # V=2, P=0, X=0, CC=0, M=0, PT=AUDIO_RTP_TYPE
    byte0 = 0x80
    byte1 = AUDIO_RTP_TYPE & 0x7F
    return struct.pack("!BBHII", byte0, byte1, seq & 0xFFFF, ts, ssrc) + payload


def _rtp_unpack(data: bytes):
    """Return (payload, seq, ts) from a raw RTP datagram, or None on error."""
    if len(data) < 12:
        return None
    hdr = struct.unpack("!BBHII", data[:12])
    seq = hdr[2]
    ts  = hdr[3]
    return data[12:], seq, ts


def _linear16_to_ulaw(samples: bytes) -> bytes:
    """Convert raw 16-bit little-endian PCM to 8-bit μ-law bytes."""
    out = bytearray(len(samples) // 2)
    for i in range(len(out)):
        s = struct.unpack_from("<h", samples, i * 2)[0]
        # μ-law encoding
        sign = 0 if s >= 0 else 0x80
        if s < 0:
            s = -s
        s = min(s, 32767)
        s += 33
        exp = 7
        for e in range(7, -1, -1):
            if s >= (1 << (e + 5)):
                exp = e
                break
        else:
            exp = 0
        mantissa = (s >> (exp + 1)) & 0x0F
        ulaw = ~(sign | (exp << 4) | mantissa) & 0xFF
        out[i] = ulaw
    return bytes(out)


def _ulaw_to_linear16(ulaw_bytes: bytes) -> bytes:
    """Convert 8-bit μ-law bytes to raw 16-bit little-endian PCM."""
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


def _gen_sine_frame(freq: float, sample_rate: int, frame_samps: int,
                    phase_ref: list) -> bytes:
    """Generate one frame of a sine tone as μ-law RTP payload."""
    samples = bytearray(frame_samps * 2)
    phase = phase_ref[0]
    for i in range(frame_samps):
        val = int(32000 * math.sin(phase))
        struct.pack_into("<h", samples, i * 2, val)
        phase += 2 * math.pi * freq / sample_rate
    phase_ref[0] = phase % (2 * math.pi)
    return _linear16_to_ulaw(bytes(samples))


class Signal:
    """A synthetic 'on air' carrier sitting at a fixed offset from a
    reference frequency, with a slowly wandering amplitude so the display
    looks alive."""

    def __init__(self, offset_hz, base_db, width_hz, drift=6.0):
        self.offset_hz = offset_hz
        self.base_db = base_db
        self.width_hz = width_hz
        self.drift = drift
        self.phase = random.uniform(0, 2 * math.pi)
        self.speed = random.uniform(0.15, 0.6)

    def level_at(self, f, t):
        amp = self.base_db + self.drift * math.sin(self.phase + t * self.speed)
        d = (f - self.offset_hz) / max(1.0, self.width_hz)
        # smooth bump (Gaussian-ish)
        return amp - 18.0 * d * d


class RadioState:
    """Holds the simulated 'radio' settings and produces spectrum data."""

    def __init__(self, user_buttons=None):
        self.lock = threading.Lock()
        self.center_freq = 14_195_000.0
        self.sample_rate = 192_000.0
        self.zoom = 1
        self.mode = "USB"
        self.filter_lo = 100
        self.filter_hi = 2800
        self.agc = "Med"
        self.rf_gain = 20.0
        self.volume = 80.0
        self.squelch = -130.0
        self.nb = False
        self.nr = False
        self.nbrf = False
        self.nbif = False
        self.afc = False
        self.anf = False
        self.notch = False
        self.agc_thresh = -100.0
        self.tune_freq = 14_205_000.0
        self.mute = False
        self.ptt = False
        self.ptt_client_addr = None   # (ip, port) of the GUI's UDP endpoint
        self.running = False
        self.lo_active = "A"
        self.lo_b_freq = self.center_freq

        # User-defined buttons: list of {"label": str, "type": "normal"|"push"}
        # for N = 1..NUM_USER_BUTTONS, plus per-button push-push (toggle) state.
        self.user_buttons = user_buttons or [
            {"label": "", "type": "normal"} for _ in range(NUM_USER_BUTTONS)
        ]
        self.user_btn_state = [False] * NUM_USER_BUTTONS

        # AGC smoothing state for the S-meter / AF level
        self._smoothed_signal_db = NOISE_FLOOR_DBM
        self._t0 = time.time()

        # A handful of fixed "stations" relative to 0 Hz (absolute freq).
        # They become visible whenever they fall inside the current span.
        self.signals = self._make_signals()

    # ------------------------------------------------------------ setup ----
    def _make_signals(self):
        sigs = []
        rng = random.Random(1234)
        # spread a bunch of carriers across the HF spectrum
        f = 1_800_000
        while f < 30_000_000:
            amp = rng.uniform(-95, -35)
            width = rng.uniform(150, 3000)
            sigs.append(Signal(float(f), amp, width))
            f += int(rng.uniform(60_000, 400_000))
        return sigs

    # ------------------------------------------------------------- state ----
    def as_dict(self):
        with self.lock:
            return {
                "center_freq": self.center_freq,
                "sample_rate": self.sample_rate,
                "zoom": self.zoom,
                "mode": self.mode,
                "filter_lo": self.filter_lo,
                "filter_hi": self.filter_hi,
                "agc": self.agc,
                "rf_gain": self.rf_gain,
                "volume": self.volume,
                "squelch": self.squelch,
                "nb": self.nb,
                "nr": self.nr,
                "nbrf": self.nbrf,
                "nbif": self.nbif,
                "afc": self.afc,
                "anf": self.anf,
                "notch": self.notch,
                "agc_thresh": self.agc_thresh,
                "tune_freq": self.tune_freq,
                "mute": self.mute,
                "ptt": self.ptt,
                "running": self.running,
                "lo_active": self.lo_active,
                "lo_b_freq": self.lo_b_freq,
                "user_buttons": self.user_buttons,
                "user_btn_state": self.user_btn_state,
            }

    # ----------------------------------------------------------- commands ----
    def apply(self, cmd):
        c = cmd.get("cmd")
        with self.lock:
            if c == "hello":
                pass
            elif c == "set_freq":
                self.center_freq = float(cmd.get("hz", self.center_freq))
            elif c == "set_tune_freq":
                self.tune_freq = float(cmd.get("hz", self.tune_freq))
            elif c == "set_mode":
                self.mode = cmd.get("mode", self.mode)
            elif c == "set_agc":
                self.agc = cmd.get("mode", self.agc)
            elif c == "set_agc_thresh":
                self.agc_thresh = float(cmd.get("value", self.agc_thresh))
            elif c == "set_filter":
                self.filter_lo = int(cmd.get("lo", self.filter_lo))
                self.filter_hi = int(cmd.get("hi", self.filter_hi))
            elif c == "set_rf_gain":
                self.rf_gain = float(cmd.get("value", self.rf_gain))
            elif c == "set_volume":
                self.volume = float(cmd.get("value", self.volume))
            elif c == "set_squelch":
                self.squelch = float(cmd.get("value", self.squelch))
            elif c == "set_nb":
                self.nb = bool(cmd.get("enabled", self.nb))
            elif c == "set_nr":
                self.nr = bool(cmd.get("enabled", self.nr))
            elif c == "set_nbrf":
                self.nbrf = bool(cmd.get("enabled", self.nbrf))
            elif c == "set_nbif":
                self.nbif = bool(cmd.get("enabled", self.nbif))
            elif c == "set_afc":
                self.afc = bool(cmd.get("enabled", self.afc))
            elif c == "set_anf":
                self.anf = bool(cmd.get("enabled", self.anf))
            elif c == "set_notch":
                self.notch = bool(cmd.get("enabled", self.notch))
            elif c == "set_mute":
                self.mute = bool(cmd.get("enabled", self.mute))
            elif c == "set_ptt":
                self.ptt = bool(cmd.get("enabled", self.ptt))
            elif c == "set_ptt":
                self.ptt = bool(cmd.get("enabled", self.ptt))
            elif c == "set_zoom":
                self.zoom = max(1, int(cmd.get("value", self.zoom)))
            elif c == "start":
                self.running = True
            elif c == "stop":
                self.running = False
            elif c == "ui_button":
                # Generic UI button presses (Full Screen, SDR-Device, FreqMgr,
                # Minimize, Exit, ...) - nothing to simulate, but still logged
                # below so they're visible on the server console.
                pass
            elif c == "ui_toolbar":
                # Waterfall / Spectrum toolbar button clicks
                pass
            elif c == "ui_display":
                # Waterfall / Spectrum view toggle sent by toolbar buttons
                # {"box": "rf"|"af", "view": "waterfall"|"spectrum"}
                pass
            elif c == "ui_smeter_btn":
                # Peak / S-units / Squelch button clicks from S-meter column
                pass
            elif c == "set_lo":
                # LO A / LO B selection
                self.lo_active = cmd.get("lo", "A")
            elif c == "set_lo_b_freq":
                self.lo_b_freq = float(cmd.get("hz", getattr(self,"lo_b_freq",self.center_freq)))
            elif c == "transport":
                # Transport-bar button presses (record/play/pause/etc.) -
                # nothing to simulate, but still logged below.
                pass
            elif c == "user_button":
                # User-defined button N (1..NUM_USER_BUTTONS).
                idx = int(cmd.get("index", 0)) - 1
                if 0 <= idx < NUM_USER_BUTTONS:
                    btype = self.user_buttons[idx].get("type", "normal")
                    if btype == "push":
                        if "enabled" in cmd:
                            self.user_btn_state[idx] = bool(cmd["enabled"])
                        else:
                            self.user_btn_state[idx] = not self.user_btn_state[idx]
                    # "normal" buttons are momentary - nothing to store
            # unknown commands are simply ignored (still get an "ok" reply)

        # Show every change received from the GUI on the server console.
        self._log_cmd(cmd)

    def _log_cmd(self, cmd):
        c = cmd.get("cmd")
        extra = {k: v for k, v in cmd.items() if k != "cmd"}
        if extra:
            print(f"[cat_server] <- {c} {extra}")
        else:
            print(f"[cat_server] <- {c}")

    # --------------------------------------------------------- simulation ----
    def make_data_message(self):
        """Build one {"type": "data", ...} update from the current state."""
        with self.lock:
            center = self.center_freq
            sample_rate = self.sample_rate
            zoom = max(1, self.zoom)
            rf_gain = self.rf_gain
            filter_lo = self.filter_lo
            filter_hi = self.filter_hi
            squelch = self.squelch
            mute = self.mute
            mode = self.mode

        span = sample_rate / zoom
        f_start = center - span / 2.0
        f_stop = center + span / 2.0
        t = time.time() - self._t0

        # ---- RF spectrum --------------------------------------------------
        spectrum = [0.0] * NUM_BINS
        for i in range(NUM_BINS):
            f = f_start + (i / (NUM_BINS - 1)) * span
            level = NOISE_FLOOR_DBM + random.uniform(-2.0, 2.0)
            for sig in self.signals:
                # only bother with signals reasonably close to this bin
                if abs(sig.offset_hz - f) < sig.width_hz * 6 + span:
                    lvl = sig.level_at(f, t)
                    if lvl > level:
                        level = lvl
            level += rf_gain * 0.4  # RF gain brightens the displayed trace a bit
            spectrum[i] = max(-135.0, min(-5.0, level))

        # ---- signal level inside the IF passband (drives S-meter & AF) ----
        lo_f = center + filter_lo
        hi_f = center + filter_hi
        if hi_f < lo_f:
            lo_f, hi_f = hi_f, lo_f
        in_band = []
        for sig in self.signals:
            if lo_f - sig.width_hz <= sig.offset_hz <= hi_f + sig.width_hz:
                # power contributed at band centre
                in_band.append(sig.level_at((lo_f + hi_f) / 2.0, t))
        if in_band:
            signal_db = max(in_band)
        else:
            signal_db = NOISE_FLOOR_DBM + random.uniform(-2.0, 2.0)
        signal_db += rf_gain * 0.4

        # simple smoothing so the meter doesn't jitter wildly
        alpha = 0.35
        self._smoothed_signal_db = (
            (1 - alpha) * self._smoothed_signal_db + alpha * signal_db
        )
        smeter_dbm = max(-135.0, min(10.0, self._smoothed_signal_db))
        smeter_text = dbm_to_s_text(smeter_dbm)

        squelch_open = (smeter_dbm >= squelch) and not mute

        # ---- AF (audio) spectrum ------------------------------------------
        af_spectrum = [0.0] * AF_BINS
        bw = max(50, hi_f - lo_f)
        carrier_present = squelch_open
        for i in range(AF_BINS):
            af = i / (AF_BINS - 1) * AF_RANGE
            level = NOISE_FLOOR_DBM + 25 + rf_gain * 0.2 + random.uniform(-3, 3)
            if carrier_present and af <= bw:
                # roughly shape it like the demodulated passband
                shape = 1.0 - abs((af / bw) - 0.5) * 1.2
                shape = max(0.0, shape)
                level = smeter_dbm + 25 + shape * 25 + random.uniform(-3, 3)
            if mute:
                level = NOISE_FLOOR_DBM
            af_spectrum[i] = max(-135.0, min(-5.0, level))

        msg = {
            "type": "data",
            "f_start": f_start,
            "f_stop": f_stop,
            "spectrum": spectrum,
            "af_range": AF_RANGE,
            "af_spectrum": af_spectrum,
            "smeter_dbm": smeter_dbm,
            "smeter_text": smeter_text,
            "squelch_open": squelch_open,
        }
        return msg



# ── UDP Audio Channel ─────────────────────────────────────────────────────────

class UDPAudioChannel:
    """
    Manages one UDP socket for bidirectional RTP audio.

    Behaviour:
      • PTT OFF (radio.ptt == False):
            Server → GUI  (server generates/re-streams audio, GUI plays it)
      • PTT ON  (radio.ptt == True):
            GUI → Server  (GUI sends mic audio, server receives it)

    The GUI's UDP address is learned from the first incoming datagram
    (STUN-less hole-punch: GUI sends a small "hello" RTP packet on
    channel open so the server learns (ip, port)).
    """

    def __init__(self, radio: "RadioState", udp_port: int):
        self.radio    = radio
        self.port     = udp_port
        self._sock    = None
        self._alive   = False
        self._seq     = 0
        self._ts      = 0
        self._phase   = [0.0]   # sine generator phase accumulator
        self._cli_addr = None   # (ip, port) of GUI's UDP endpoint

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(0.05)
        self._alive = True
        threading.Thread(target=self._rx_loop, daemon=True).start()
        threading.Thread(target=self._tx_loop, daemon=True).start()
        print(f"[audio] UDP RTP channel open on port {self.port}")

    def stop(self):
        self._alive = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        print("[audio] UDP RTP channel closed")

    def set_client_addr(self, addr):
        """Called by ClientHandler when the GUI's UDP endpoint is known."""
        self._cli_addr = addr
        self.radio.ptt_client_addr = addr
        print(f"[audio] GUI UDP endpoint registered: {addr}")

    # ── TX loop: server → GUI (PTT OFF) ──────────────────────────────────────
    def _tx_loop(self):
        """Push one RTP frame every AUDIO_FRAME_MS ms while PTT is OFF."""
        interval = AUDIO_FRAME_MS / 1000.0
        next_tick = time.monotonic()
        while self._alive:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(max(0.0, next_tick - now))
            next_tick += interval

            state = self.radio.as_dict()
            if not state["running"] or state["ptt"] or not self._cli_addr:
                continue  # nothing to send

            payload = _gen_sine_frame(
                _AUDIO_TONE_HZ, AUDIO_SAMPLE_RATE,
                AUDIO_FRAME_SAMPS, self._phase
            )
            pkt = _rtp_pack(payload, self._seq, self._ts)
            self._seq = (self._seq + 1) & 0xFFFF
            self._ts  = (self._ts + AUDIO_FRAME_SAMPS) & 0xFFFFFFFF
            try:
                self._sock.sendto(pkt, self._cli_addr)
            except OSError:
                pass

    # ── RX loop: GUI → server (PTT ON) ────────────────────────────────────────
    def _rx_loop(self):
        """Receive RTP datagrams from the GUI while PTT is ON."""
        while self._alive:
            try:
                data, addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            # Auto-register the GUI's UDP address from any incoming packet
            if self._cli_addr is None or self._cli_addr != addr:
                self.set_client_addr(addr)

            result = _rtp_unpack(data)
            if result is None:
                continue
            payload, seq, ts = result

            state = self.radio.as_dict()
            if not state["ptt"]:
                # PTT is off — GUI shouldn't be sending, but discard gracefully
                continue

            # ── Here you would route payload (μ-law PCM) to SDR TX / playback
            # For this reference implementation we just log occasionally.
            # Replace this stub with your real audio sink (soundcard / SDR TX):
            #   pcm = _ulaw_to_linear16(payload)
            #   audio_sink.write(pcm)
            _ = _ulaw_to_linear16(payload)   # decode (result discarded in demo)


# ── TCP server ────────────────────────────────────────────────────────────────

class ClientHandler(threading.Thread):
    def __init__(self, sock, addr, radio, audio_channel=None):
        super().__init__(daemon=True)
        self.sock = sock
        self.addr = addr
        self.radio = radio
        self.audio_channel = audio_channel
        self.send_lock = threading.Lock()
        self.alive = True

    def send_json(self, obj):
        try:
            data = (json.dumps(obj) + "\n").encode("utf-8")
            with self.send_lock:
                self.sock.sendall(data)
            return True
        except OSError:
            self.alive = False
            return False

    def run(self):
        print(f"[cat_server] client connected: {self.addr}")
        # Announce the UDP audio port immediately so the GUI can open the channel
        if self.audio_channel:
            self.send_json({
                "type": "audio_port",
                "port": self.audio_channel.port,
                "sample_rate": AUDIO_SAMPLE_RATE,
                "frame_ms": AUDIO_FRAME_MS,
                "codec": "pcmu",   # G.711 μ-law
            })
        streamer = threading.Thread(target=self._stream_loop, daemon=True)
        streamer.start()

        buf = b""
        try:
            while self.alive:
                data = self.sock.recv(65536)
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        cmd = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    self.radio.apply(cmd)
                    # When GUI sends its UDP address alongside set_ptt or
                    # audio_hello, register it so the TX loop can reach it.
                    if cmd.get("cmd") in ("set_ptt", "audio_hello"):
                        udp_port = cmd.get("udp_port")
                        if udp_port and self.audio_channel:
                            gui_ip = self.addr[0]
                            self.audio_channel.set_client_addr((gui_ip, int(udp_port)))
                    self.send_json({"resp": "ok", "state": self.radio.as_dict()})
        except OSError:
            pass
        finally:
            self.alive = False
            try:
                self.sock.close()
            except OSError:
                pass
            print(f"[cat_server] client disconnected: {self.addr}")

    def _stream_loop(self):
        period = 1.0 / UPDATE_HZ
        while self.alive:
            if self.radio.as_dict()["running"]:
                msg = self.radio.make_data_message()
                msg["state"] = self.radio.as_dict()
                if not self.send_json(msg):
                    break
            time.sleep(period)


def _parse_args():
    import sys

    # ── Phase 1: extract --config before full parsing ─────────────────────────
    _pre = argparse.ArgumentParser(add_help=False)
    _pre.add_argument('--config', default=None)
    _pre_args, _ = _pre.parse_known_args()
    _config_path = _pre_args.config or os.path.join(os.getcwd(), _SERVER_CONFIG_NAME)

    # ── Load / create TOML config ─────────────────────────────────────────────
    _cfg  = _ensure_server_config(_config_path)
    _srv  = _cfg.get("server",       {})
    _aud  = _cfg.get("audio",        {})
    _ubtn = _cfg.get("user_buttons", {})
    _D    = _SERVER_CONFIG_DEFAULTS

    _def_host       = _srv.get("host",       _D["server"]["host"])
    _def_port       = int(_srv.get("port",   _D["server"]["port"]))
    _def_audio_port = int(_aud.get("audio_port", _D["audio"]["audio_port"]))
    _def_no_audio   = bool(_aud.get("no_audio",  _D["audio"]["no_audio"]))

    # Determine which positional args (host / port) were explicitly on the CLI,
    # ignoring --config and its value.
    _skip = False
    _positionals = []
    for _a in sys.argv[1:]:
        if _skip:            _skip = False; continue
        if _a == '--config': _skip = True;  continue
        if _a.startswith('--config='): continue
        if not _a.startswith('-'):
            _positionals.append(_a)
    _cli_host_given = len(_positionals) >= 1
    _cli_port_given = len(_positionals) >= 2

    # ── Full argument parse ───────────────────────────────────────────────────
    ap = argparse.ArgumentParser(description="cat_server")
    ap.add_argument('--config', metavar='PATH', default=None,
                    help=f'Path to TOML config file (default: ./{_SERVER_CONFIG_NAME})')
    ap.add_argument("host", nargs="?",
                    default=_def_host if not _cli_host_given else None,
                    help=f"Host/IP to listen on (default: {_def_host})")
    ap.add_argument("port", nargs="?", type=int,
                    default=_def_port if not _cli_port_given else None,
                    help=f"TCP port to listen on (default: {_def_port})")
    ap.add_argument("--audio-port", metavar="PORT", type=int, default=argparse.SUPPRESS,
                    help=f"UDP port for RTP audio (default: {_def_audio_port})")
    ap.add_argument("--no-audio", action="store_true", default=argparse.SUPPRESS,
                    help="Disable the RTP/UDP audio channel")
    for n in range(1, NUM_USER_BUTTONS + 1):
        ap.add_argument(f"--user-button-label-{n}", metavar="TEXT",
                        default=argparse.SUPPRESS,
                        help=f"Label for user button {n} (max 7 characters)")
        ap.add_argument(f"--user-button-type-{n}", choices=["normal", "push"],
                        default=argparse.SUPPRESS,
                        help=f"Type of user button {n}: 'normal' (momentary) "
                             f"or 'push' (push-push/toggle). Default: normal")
    _raw = ap.parse_args()

    # ── Merge: CLI beats config, config beats built-in default ───────────────
    _raw.config     = _config_path
    _raw.audio_port = _raw.audio_port if hasattr(_raw, 'audio_port') else _def_audio_port
    _raw.no_audio   = _raw.no_audio   if hasattr(_raw, 'no_audio')   else _def_no_audio

    # Host/port: use CLI value if explicitly given, else config/default
    if not _cli_host_given:
        _raw.host = _def_host
    if not _cli_port_given:
        _raw.port = _def_port

    # User buttons: CLI beats config, config beats built-in default
    for n in range(1, NUM_USER_BUTTONS + 1):
        _lattr = f"user_button_label_{n}"
        _tattr = f"user_button_type_{n}"
        _cfg_label = _ubtn.get(f"label_{n}", _D["user_buttons"][f"label_{n}"])
        _cfg_type  = _ubtn.get(f"type_{n}",  _D["user_buttons"][f"type_{n}"])
        if not hasattr(_raw, _lattr):
            setattr(_raw, _lattr, _cfg_label)
        if not hasattr(_raw, _tattr):
            setattr(_raw, _tattr, _cfg_type)

    # ── Validations ───────────────────────────────────────────────────────────
    for n in range(1, NUM_USER_BUTTONS + 1):
        label = getattr(_raw, f"user_button_label_{n}")
        if len(label) > 7:
            ap.error(f"--user-button-label-{n}: label must be at most 7 "
                     f"characters (got {len(label)!r}: {label!r})")
    return _raw


def _build_user_buttons(args):
    buttons = []
    for n in range(1, NUM_USER_BUTTONS + 1):
        buttons.append({
            "label": getattr(args, f"user_button_label_{n}"),
            "type": getattr(args, f"user_button_type_{n}"),
        })
    return buttons


def main():
    args = _parse_args()
    host = args.host
    port = args.port

    radio = RadioState(user_buttons=_build_user_buttons(args))

    # ── Start the UDP audio channel ──────────────────────────────────────────
    audio_ch = None
    if not args.no_audio:
        audio_ch = UDPAudioChannel(radio, args.audio_port)
        audio_ch.start()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    print(f"[cat_server] listening on {host}:{port}")

    try:
        while True:
            sock, addr = srv.accept()
            ClientHandler(sock, addr, radio, audio_channel=audio_ch).start()
    except KeyboardInterrupt:
        print("\n[cat_server] shutting down")
    finally:
        if audio_ch:
            audio_ch.stop()
        srv.close()


if __name__ == "__main__":
    main()
