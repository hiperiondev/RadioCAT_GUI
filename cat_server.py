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
import threading
import time

NUM_BINS = 600          # RF spectrum / waterfall bins
AF_BINS = 256           # AF spectrum / waterfall bins
AF_RANGE = 3000.0       # Hz shown on the AF display
UPDATE_HZ = 10.0        # data pushes per second
NUM_USER_BUTTONS = 6    # number of user-defined buttons (N = 1..6)

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


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

class ClientHandler(threading.Thread):
    def __init__(self, sock, addr, radio):
        super().__init__(daemon=True)
        self.sock = sock
        self.addr = addr
        self.radio = radio
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
    ap = argparse.ArgumentParser(description="cat_server")
    ap.add_argument("host", nargs="?", default="0.0.0.0",
                    help="Host/IP to listen on (default: 0.0.0.0)")
    ap.add_argument("port", nargs="?", type=int, default=50101,
                    help="TCP port to listen on (default: 50101)")
    for n in range(1, NUM_USER_BUTTONS + 1):
        ap.add_argument(f"--user-button-label-{n}", metavar="TEXT", default="",
                         help=f"Label for user button {n} (max 7 characters)")
        ap.add_argument(f"--user-button-type-{n}", choices=["normal", "push"],
                         default="normal",
                         help=f"Type of user button {n}: 'normal' (momentary) "
                              f"or 'push' (push-push/toggle). Default: normal")
    args = ap.parse_args()

    for n in range(1, NUM_USER_BUTTONS + 1):
        label = getattr(args, f"user_button_label_{n}")
        if len(label) > 7:
            ap.error(f"--user-button-label-{n}: label must be at most 7 "
                     f"characters (got {len(label)!r}: {label!r})")
    return args


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

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(8)
    print(f"[cat_server] listening on {host}:{port}")

    try:
        while True:
            sock, addr = srv.accept()
            ClientHandler(sock, addr, radio).start()
    except KeyboardInterrupt:
        print("\n[cat_server] shutting down")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
