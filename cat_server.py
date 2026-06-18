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
        {"cmd": "user_text", "index": 1, "text": "CQ CQ DE TEST"}
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

User-defined modulation buttons
--------------------------------
Up to 5 user-defined modulation buttons (N = 1..5) can be configured via CLI
flags and are advertised to the GUI in "user_mod_labels" / "user_mod_types"
lists inside every "state" dict:

    --user_mod_N      LABEL  Label for user-mod button N (max 4 chars)
    --user_mod_type_N  TYPE  "normal", "text", or "text_input". Default: "normal"

  * "normal"     behaves like a standard mode button (e.g. AM/USB/...).
  * "text"       when selected, the GUI splits its AF/audio box in two: the
                 left side keeps the AF waterfall/spectrum, the right side
                 shows a read-only text panel with text sent by the server.
  * "text_input" same split, but the right-hand panel itself is split into
                 an upper read-only area (text sent by the server) and a
                 bottom editable box (max 3 lines, auto-scroll) that sends
                 its contents to the server when the user presses Enter,
                 like an RTTY chat session.

Text sent by the GUI for a text/text_input mode button arrives as:

    {"cmd": "user_text", "index": N, "text": "..."}

The server replies immediately as usual ({"resp": "ok", "state": {...}}) and
also pushes its own text to the GUI asynchronously as:

    {"type": "user_text", "index": N, "text": "..."}

This demo server echoes back anything received on a "text_input" slot
(prefixed so it's clearly distinguishable in the chat panel) and, for any
"text"/"text_input" slot, periodically pushes a simulated status line so the
read-only panel has something to display even with no user input.

Real IQ recordings (--iq_wav)
------------------------------
By default the RF spectrum/waterfall is synthetic (a handful of fake
carriers). Pass --iq_wav PATH to a wav file of IQ samples in SDRplay IQ
wav format (stereo PCM/float, I = left channel, Q = right channel,
optionally with an 'auxi' chunk carrying the recorded centre frequency)
and the server will FFT real samples from that file instead, looping the
file forever so playback never runs out. The file's sample rate becomes
the radio's sample rate, and its recorded centre frequency (if present)
seeds the initial tuned frequency.

Real receive audio (--audio_wav)
---------------------------------
By default the downlink "received audio" sent to the GUI over RTP is just
a fake 440 Hz demo tone. Pass --audio_wav PATH to a normal mono/stereo PCM
(or float) wav file and the server will transmit that file's audio to the
GUI instead, looping it forever (so a short recording becomes an endless
"on air" audio source). Stereo files are downmixed to mono and the audio
is resampled to the RTP audio sample rate (8 kHz) if its native sample
rate differs. This only affects the simulated receive audio; it is sent
whenever the radio is running and PTT is off, same as the demo tone it
replaces.
"""

import argparse
import json
import math
import os
import random
import socket
import struct
import sys
import threading
import time

# numpy is only required when --iq_wav is used (FFT of recorded IQ samples).
# The rest of the server works fine without it.
try:
    import numpy as np
except ImportError:
    np = None

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
    "user_mods": {
        **{f"label_{n}": "" for n in range(1, 6)},
        **{f"type_{n}":  "normal" for n in range(1, 6)},
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

[user_mods]
# label: max 4 characters; user-defined modulation button labels shown in the
# mode row of the GUI. Fill slots in order: 1, 2, 3, 4, 5 (no skipping).
# type: "normal" (acts like a regular mode button), "text" (splits the AF/
#       audio box so a read-only text panel shows text sent by the server),
#       or "text_input" (same split, but the text panel itself is split into
#       an upper read-only area and a bottom 3-line editable input box that
#       sends text to the server on Enter, like an RTTY chat).
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
"""

def _parse_simple_toml_srv(text):
    """Minimal TOML parser for simple key=value with [sections]."""
    result = {}
    section = result
    for raw in text.splitlines():
        # Strip comments only when the '#' is outside of a quoted region.
        line = raw
        in_quote = False
        for ci, ch in enumerate(raw):
            if ch == '"':
                in_quote = not in_quote
            elif ch == '#' and not in_quote:
                line = raw[:ci]
                break
        line = line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            sec_name = line[1:-1].strip()
            # NOTE: This minimal fallback parser does NOT support dotted
            # section headers (e.g. [server.tls]) or inline tables.
            # The bundled config template never uses them.  If tomllib /
            # tomli is available it is used instead (see _load_server_config).
            if '.' in sec_name:
                raise ValueError(
                    f"_parse_simple_toml_srv: nested section [{sec_name}] is "
                    "not supported by the built-in fallback parser. "
                    "Install 'tomli' (pip install tomli) for full TOML support."
                )
            section = result.setdefault(sec_name, {})
            continue
        if '=' in line:
            k, _, v = line.partition('=')
            k = k.strip(); v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or \
               (v.startswith("'") and v.endswith("'")):
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

NUM_BINS = 600          # RF spectrum / waterfall bins
AF_BINS = 256           # AF spectrum / waterfall bins
AF_RANGE = 3000.0       # Hz shown on the AF display
UPDATE_HZ = 10.0        # data pushes per second
NUM_USER_BUTTONS = 6    # number of user-defined buttons (N = 1..6)
NUM_USER_MODS    = 5    # number of user-defined modulation buttons (N = 1..5)
IQ_FFT_SIZE = 4096      # FFT size used to turn --iq_wav samples into a spectrum

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
    if (hdr[0] >> 6) != 2:          # RTP version must be 2
        return None
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
        exp = 0  # defensive default; loop below will override for all valid s
        for e in range(7, -1, -1):
            if s >= (1 << (e + 5)):
                exp = e
                break
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


# ── SDRplay IQ .wav playback (--iq_wav) ────────────────────────────────────────
#
# SDRplay-family tools (SDRuno, SDR-Console, etc.) record raw IQ captures as
# ordinary RIFF/WAVE files: a stereo (2-channel) PCM or IEEE-float stream
# where the left channel is "I" and the right channel is "Q", at the radio's
# actual IQ sample rate. Some recorders additionally write a non-standard
# "auxi" chunk holding the centre frequency the capture was made at. This
# reader understands plain "fmt "/"data" wav files (16/24/32-bit int or
# 32-bit float, mono or stereo) and will opportunistically pull the centre
# frequency out of an "auxi" chunk if one is present; everything else about
# the chunk layout varies between vendors, so unknown/extra chunks are just
# skipped.

class IQWavSource:
    """Serves looping blocks of complex IQ samples read from a wav file.

    The file is read like a tape loop: once the data chunk is exhausted,
    reading simply wraps back around to the start, so a finite recording
    can feed an unlimited stream of spectrum/waterfall updates.
    """

    def __init__(self, path):
        if np is None:
            raise RuntimeError(
                "--iq_wav requires numpy. Install it with: pip install numpy"
            )
        self.path = path
        self.channels = 2
        self.sample_rate = 192000
        self.bits_per_sample = 16
        self.is_float = False
        self.data_offset = 0
        self.data_size = 0
        self.center_freq = None     # populated from 'auxi' chunk, if present
        self._pos = 0                # read offset (bytes) within the data chunk
        self._lock = threading.Lock()
        self._parse_header()
        try:
            self._fh = open(self.path, "rb")
        except Exception:
            raise

    # -- header parsing -------------------------------------------------------
    def _parse_header(self):
        with open(self.path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
                raise ValueError(f"{self.path}: not a RIFF/WAVE file")
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                chunk_id, chunk_size = struct.unpack("<4sI", hdr)
                chunk_start = f.tell()
                if chunk_id == b"fmt ":
                    self._parse_fmt(f.read(chunk_size))
                elif chunk_id == b"auxi":
                    self._parse_auxi(f.read(chunk_size))
                elif chunk_id == b"data":
                    self.data_offset = chunk_start
                    self.data_size = chunk_size
                    # do NOT break; 'auxi' may appear after 'data' in some recorders
                # RIFF chunks are word (2-byte) aligned
                f.seek(chunk_start + chunk_size + (chunk_size & 1))
        if self.data_size == 0:
            raise ValueError(f"{self.path}: no 'data' chunk found")

    def _parse_fmt(self, fmt):
        if len(fmt) < 16:
            raise ValueError("fmt chunk too short")
        (audio_fmt, channels, sample_rate, _byte_rate,
         _block_align, bits_per_sample) = struct.unpack("<HHIIHH", fmt[:16])
        self.channels = channels
        self.sample_rate = sample_rate
        self.bits_per_sample = bits_per_sample
        if audio_fmt == 0xFFFE and len(fmt) >= 40:
            # WAVE_FORMAT_EXTENSIBLE: sub-format tag lives 8 bytes into the
            # trailing GUID, right after the 22-byte fixed extensible header.
            sub_tag = struct.unpack_from("<H", fmt, 24)[0]
            self.is_float = (sub_tag == 3)
        else:
            self.is_float = (audio_fmt == 3)

    def _parse_auxi(self, aux):
        """Best-effort extraction of the centre frequency from an 'auxi'
        chunk. SDRuno's layout (confirmed against SDRplay's own
        examine_wav_iq_recordings.py reference tool) is:

            8x WORD  start time (year, month, dow, day, h, m, s, ms)
            8x WORD  stop time  (same fields)
            DWORD    centerFreq   <- this is what we want
            DWORD    ADFrequency
            DWORD    IFFrequency
            ... (bandwidth, IQ offset, etc.)

        i.e. the two 16-byte timestamps (32 bytes total) come BEFORE the
        centre frequency, not just one. This is true both for the full
        164-byte SDRuno chunk and the shorter 68-byte variant some other
        recorders write, since they share this same 36-byte prefix."""
        try:
            if len(aux) >= 36:
                center = struct.unpack_from("<I", aux, 32)[0]
                if 0 < center < 20_000_000_000:
                    self.center_freq = float(center)
        except struct.error:
            pass

    # -- sample access ---------------------------------------------------------
    @property
    def bytes_per_frame(self):
        return max(1, self.channels) * (self.bits_per_sample // 8)

    def read_iq_block(self, num_samples):
        """Return a complex64 numpy array of `num_samples` IQ samples,
        looping back to the start of the data chunk on EOF (infinite
        playback from a finite file)."""
        frame_size = self.bytes_per_frame
        need = num_samples * frame_size
        chunks = []
        got = 0
        with self._lock:
            while got < need:
                remaining = self.data_size - self._pos
                if remaining <= 0:
                    self._pos = 0          # loop back to the start of the file
                    remaining = self.data_size
                self._fh.seek(self.data_offset + self._pos)
                to_read = min(need - got, remaining)
                raw = self._fh.read(to_read)
                if not raw:
                    self._pos = 0           # defensive: avoid spinning forever
                    continue
                chunks.append(raw)
                got += len(raw)
                self._pos += len(raw)
                if self._pos >= self.data_size:
                    self._pos = 0           # wrap for next call too
        return self._to_iq(b"".join(chunks))

    def _to_iq(self, raw):
        if self.is_float and self.bits_per_sample == 32:
            samples = np.frombuffer(raw, dtype="<f4")
        elif self.bits_per_sample == 8:
            samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif self.bits_per_sample == 16:
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif self.bits_per_sample == 32:
            samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"unsupported bits_per_sample: {self.bits_per_sample}")
        if self.channels >= 2:
            n_frames = len(samples) // self.channels
            samples = samples[: n_frames * self.channels].reshape(n_frames, self.channels)
            i_ch = samples[:, 0]
            q_ch = samples[:, 1]
        else:
            i_ch = samples
            q_ch = np.zeros_like(samples)
        n = min(len(i_ch), len(q_ch))
        return (i_ch[:n] + 1j * q_ch[:n]).astype(np.complex64)

    def close(self):
        if hasattr(self, '_fh'):
            try:
                self._fh.close()
            except OSError:
                pass


# ── WAV downlink-audio playback (--audio_wav) ──────────────────────────────
#
# Plays back an ordinary mono/stereo PCM (or IEEE-float) wav file as the
# simulated "received audio" stream sent to the GUI over RTP, in place of
# the built-in demo sine tone. The whole file is decoded once at startup,
# downmixed to mono and resampled (simple linear interpolation) to the RTP
# audio sample rate (AUDIO_SAMPLE_RATE, 8 kHz) if needed, then served back
# frame-by-frame, wrapping around to the start forever.

class AudioWavSource:
    """Decodes a wav file fully to mono 16-bit PCM at AUDIO_SAMPLE_RATE and
    serves it back in fixed-size frames, looping forever."""

    def __init__(self, path):
        if np is None:
            raise RuntimeError(
                "--audio_wav requires numpy. Install it with: pip install numpy"
            )
        self.path = path
        channels, sample_rate, bits_per_sample, is_float, data = self._read_wav(path)
        self.source_channels = channels
        self.source_sample_rate = sample_rate

        samples = self._to_float(data, bits_per_sample, is_float)
        if channels >= 2:
            n_frames = len(samples) // channels
            samples = samples[: n_frames * channels].reshape(n_frames, channels)
            mono = samples.mean(axis=1)
        else:
            mono = samples

        if sample_rate != AUDIO_SAMPLE_RATE and len(mono) > 1:
            duration = len(mono) / float(sample_rate)
            n_out = max(1, int(round(duration * AUDIO_SAMPLE_RATE)))
            x_src = np.linspace(0.0, 1.0, num=len(mono))
            x_dst = np.linspace(0.0, 1.0, num=n_out)
            mono = np.interp(x_dst, x_src, mono)

        if len(mono) == 0:
            raise ValueError(f"{path}: contains no audio samples")

        self.pcm = np.clip(mono * 32767.0, -32768, 32767).astype("<i2")
        self.num_samples = len(self.pcm)
        self._pos = 0
        self._lock = threading.Lock()

    # -- header + data parsing -------------------------------------------------
    @staticmethod
    def _read_wav(path):
        with open(path, "rb") as f:
            riff = f.read(12)
            if len(riff) < 12 or riff[0:4] != b"RIFF" or riff[8:12] != b"WAVE":
                raise ValueError(f"{path}: not a RIFF/WAVE file")
            channels = None
            sample_rate = None
            bits_per_sample = None
            is_float = False
            data = b""
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                chunk_id, chunk_size = struct.unpack("<4sI", hdr)
                chunk_start = f.tell()
                if chunk_id == b"fmt ":
                    fmt = f.read(chunk_size)
                    if len(fmt) < 16:
                        raise ValueError("fmt chunk too short")
                    (audio_fmt, channels, sample_rate, _byte_rate,
                     _block_align, bits_per_sample) = struct.unpack("<HHIIHH", fmt[:16])
                    if audio_fmt == 0xFFFE and len(fmt) >= 40:
                        sub_tag = struct.unpack_from("<H", fmt, 24)[0]
                        is_float = (sub_tag == 3)
                    else:
                        is_float = (audio_fmt == 3)
                elif chunk_id == b"data":
                    data = f.read(chunk_size)
                # RIFF chunks are word (2-byte) aligned
                f.seek(chunk_start + chunk_size + (chunk_size & 1))
            if not data:
                raise ValueError(f"{path}: no 'data' chunk found")
            if sample_rate is None:
                raise ValueError(f"{path}: no 'fmt' chunk found")
            return channels, sample_rate, bits_per_sample, is_float, data

    @staticmethod
    def _to_float(raw, bits_per_sample, is_float):
        if is_float and bits_per_sample == 32:
            return np.frombuffer(raw, dtype="<f4").astype(np.float32)
        elif bits_per_sample == 8:
            return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif bits_per_sample == 16:
            return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        elif bits_per_sample == 32:
            return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"unsupported bits_per_sample: {bits_per_sample}")

    # -- playback ----------------------------------------------------------
    def read_frame(self, num_samples):
        """Return `num_samples` of little-endian 16-bit PCM bytes, wrapping
        back to the start of the file forever (infinite loop playback)."""
        with self._lock:
            idx = (np.arange(num_samples) + self._pos) % self.num_samples
            frame = self.pcm[idx]
            self._pos = (self._pos + num_samples) % self.num_samples
        return frame.tobytes()


def _iq_fft_spectrum_db(iq_block, rf_gain):
    """FFT a block of complex IQ samples into a dBm-ish power spectrum,
    DC-centred (index 0 = -sample_rate/2, last index = +sample_rate/2)."""
    n = len(iq_block)
    window = np.hanning(n)
    spec = np.fft.fftshift(np.fft.fft(iq_block * window))
    mag = np.abs(spec) / (np.sum(window) / 2.0 + 1e-12)
    mag = np.maximum(mag, 1e-12)
    # Recorded IQ files carry no absolute power reference (that depends on
    # the original RF/IF gain settings, not stored in the wav), so this is
    # a reasonable-looking approximation rather than a calibrated dBm value.
    db = 20.0 * np.log10(mag) - 30.0 + rf_gain * 0.4
    return np.clip(db, -135.0, -5.0)


def _crop_and_resample(full_db, num_bins, zoom):
    """Crop the full-bandwidth spectrum down to the span implied by `zoom`
    (centered on 0 Hz / DC) and resample it to exactly `num_bins` points."""
    n = len(full_db)
    half = max(1, int(round(n / (2.0 * max(1, zoom)))))
    center = n // 2
    lo = max(0, center - half)
    hi = min(n, center + half)
    seg = full_db[lo:hi]
    if len(seg) < 2:
        seg = full_db
    x_src = np.linspace(0.0, 1.0, num=len(seg))
    x_dst = np.linspace(0.0, 1.0, num=num_bins)
    return np.interp(x_dst, x_src, seg)


class RadioState:
    """Holds the simulated 'radio' settings and produces spectrum data."""

    def __init__(self, user_buttons=None, user_mod_labels=None, user_mod_types=None,
                 iq_source=None):
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

        # User-defined modulation buttons: list of up to NUM_USER_MODS labels
        # (max 4 chars each). Empty string means the slot is unused.
        self.user_mod_labels = list(user_mod_labels) if user_mod_labels else \
                               [""] * NUM_USER_MODS
        # Parallel list of types: "normal" | "text" | "text_input"
        self.user_mod_types = list(user_mod_types) if user_mod_types else \
                              ["normal"] * NUM_USER_MODS
        # Simulated periodic status-line counter per text/text_input slot
        self._text_tick = [0] * NUM_USER_MODS

        # AGC smoothing state for the S-meter / AF level
        self._smoothed_signal_db = NOISE_FLOOR_DBM
        self._t0 = time.time()

        # A handful of fixed "stations" relative to 0 Hz (absolute freq).
        # They become visible whenever they fall inside the current span.
        self.signals = self._make_signals()

        # Optional IQWavSource: when set, the RF spectrum/waterfall is
        # computed from real recorded IQ samples (looped forever) instead
        # of the synthetic signal generator above.
        self.iq_source = iq_source
        if self.iq_source is not None:
            self.sample_rate = float(self.iq_source.sample_rate)
            if self.iq_source.center_freq is not None:
                self.center_freq = self.iq_source.center_freq

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
                "user_buttons": [dict(b) for b in self.user_buttons],
                "user_btn_state": self.user_btn_state,
                "user_mod_labels": list(self.user_mod_labels),
                "user_mod_types": list(self.user_mod_types),
            }

    # ----------------------------------------------------------- commands ----
    def apply(self, cmd):
        c = cmd.get("cmd")
        outgoing = None
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
                self.lo_b_freq = float(cmd.get("hz", self.lo_b_freq))
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
            elif c == "user_text":
                # Text sent from a "text_input" user-mod chat panel.
                # {"cmd": "user_text", "index": N, "text": "..."}
                idx = int(cmd.get("index", 0)) - 1
                text = str(cmd.get("text", ""))
                if 0 <= idx < NUM_USER_MODS:
                    mtype = self.user_mod_types[idx] if idx < len(self.user_mod_types) else "normal"
                    if mtype == "text_input" and text:
                        # Demo behaviour: echo the line back so the chat panel
                        # shows a round-trip, like a simple RTTY echo test.
                        outgoing = {"type": "user_text", "index": idx + 1,
                                    "text": f"ECHO: {text}"}
            # unknown commands are simply ignored (still get an "ok" reply)

        # Show every change received from the GUI on the server console.
        self._log_cmd(cmd)
        return outgoing

    def make_user_text_messages(self):
        """Return a list of simulated {"type":"user_text",...} messages, one
        for each "text"/"text_input" user-mod slot, advancing a periodic
        counter. Called from the streaming loop so panels that are showing
        but receiving no user input still display something."""
        msgs = []
        with self.lock:
            for idx in range(NUM_USER_MODS):
                mtype = self.user_mod_types[idx] if idx < len(self.user_mod_types) else "normal"
                if mtype in ("text", "text_input"):
                    self._text_tick[idx] += 1
                    label = self.user_mod_labels[idx] or f"MOD{idx+1}"
                    msgs.append({
                        "type": "user_text",
                        "index": idx + 1,
                        "text": f"[{label}] status update #{self._text_tick[idx]}",
                    })
        return msgs

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
            center = self.lo_b_freq if self.lo_active == "B" else self.center_freq
            sample_rate = self.sample_rate
            zoom = max(1, self.zoom)
            rf_gain = self.rf_gain
            filter_lo = self.filter_lo
            filter_hi = self.filter_hi
            squelch = self.squelch
            mute = self.mute
            mode = self.mode
            t0 = self._t0
            iq_source = self.iq_source

        span = sample_rate / zoom
        f_start = center - span / 2.0
        f_stop = center + span / 2.0
        t = time.time() - t0

        lo_f = center + filter_lo
        hi_f = center + filter_hi
        if hi_f < lo_f:
            lo_f, hi_f = hi_f, lo_f

        if iq_source is not None:
            spectrum, signal_db = self._iq_spectrum_and_signal(
                iq_source, center, sample_rate, zoom, rf_gain, lo_f, hi_f
            )
        else:
            spectrum, signal_db = self._synthetic_spectrum_and_signal(
                f_start, span, t, rf_gain, lo_f, hi_f
            )

        # simple smoothing so the meter doesn't jitter wildly
        alpha = 0.35
        with self.lock:
            self._smoothed_signal_db = (
                (1 - alpha) * self._smoothed_signal_db + alpha * signal_db
            )
            smoothed = self._smoothed_signal_db
            # Re-read squelch and mute under the same lock so squelch_open is
            # consistent with the smoothed value we just wrote (BUG-10 fix).
            squelch = self.squelch
            mute = self.mute
        smeter_dbm = max(-135.0, min(10.0, smoothed))
        smeter_text = dbm_to_s_text(smeter_dbm)

        squelch_open = (smeter_dbm >= squelch) and not mute

        af_spectrum = self._make_af_spectrum(
            smeter_dbm, lo_f, hi_f, rf_gain, mute, squelch_open
        )

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

    # ---- RF spectrum: synthetic signal generator -------------------------
    def _synthetic_spectrum_and_signal(self, f_start, span, t, rf_gain, lo_f, hi_f):
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

        # signal level inside the IF passband (drives S-meter & AF)
        in_band = []
        for sig in self.signals:
            if lo_f - sig.width_hz <= sig.offset_hz <= hi_f + sig.width_hz:
                in_band.append(sig.level_at((lo_f + hi_f) / 2.0, t))
        if in_band:
            signal_db = max(in_band)
        else:
            signal_db = NOISE_FLOOR_DBM + random.uniform(-2.0, 2.0)
        signal_db += rf_gain * 0.4
        return spectrum, signal_db

    # ---- RF spectrum: real samples from --iq_wav (looped forever) --------
    def _iq_spectrum_and_signal(self, iq_source, center, sample_rate, zoom,
                                 rf_gain, lo_f, hi_f):
        iq_block = iq_source.read_iq_block(IQ_FFT_SIZE)
        full_db = _iq_fft_spectrum_db(iq_block, rf_gain)
        spectrum = _crop_and_resample(full_db, NUM_BINS, zoom).tolist()

        # Map the IF passband (lo_f..hi_f, absolute Hz) onto bins of the
        # full-bandwidth FFT (which spans center +/- sample_rate/2) so the
        # S-meter reacts to whatever the recording actually contains there.
        f_start_full = center - sample_rate / 2.0
        f_stop_full = center + sample_rate / 2.0
        span_full = max(1.0, f_stop_full - f_start_full)

        def freq_to_bin(f):
            frac = (f - f_start_full) / span_full
            frac = min(1.0, max(0.0, frac))
            return int(frac * (len(full_db) - 1))

        b_lo, b_hi = sorted((freq_to_bin(lo_f), freq_to_bin(hi_f)))
        if b_hi > b_lo:
            signal_db = float(np.max(full_db[b_lo:b_hi + 1]))
        else:
            signal_db = float(full_db[b_lo])
        return spectrum, signal_db

    # ---- AF (audio) spectrum, shared by both RF spectrum sources ---------
    def _make_af_spectrum(self, smeter_dbm, lo_f, hi_f, rf_gain, mute, squelch_open):
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
        return af_spectrum



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

    def __init__(self, radio: "RadioState", udp_port: int, audio_source=None):
        self.radio    = radio
        self.port     = udp_port
        self.audio_source = audio_source  # optional AudioWavSource (--audio_wav)
        self._sock    = None
        self._alive   = False
        self._seq     = 0
        self._ts      = 0
        self._phase   = [0.0]   # sine generator phase accumulator (demo tone fallback)
        self._cli_addr = None   # (ip, port) of GUI's UDP endpoint
        self._addr_lock = threading.Lock()  # guards _cli_addr + radio.ptt_client_addr

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
        with self._addr_lock:
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
            with self._addr_lock:
                cli_addr = self._cli_addr
            if not state["running"] or state["ptt"] or not cli_addr:
                continue  # nothing to send

            if self.audio_source is not None:
                raw_pcm = self.audio_source.read_frame(AUDIO_FRAME_SAMPS)
                payload = _linear16_to_ulaw(raw_pcm)
            else:
                payload = _gen_sine_frame(
                    _AUDIO_TONE_HZ, AUDIO_SAMPLE_RATE,
                    AUDIO_FRAME_SAMPS, self._phase
                )
            pkt = _rtp_pack(payload, self._seq, self._ts)
            self._seq = (self._seq + 1) & 0xFFFF
            self._ts  = (self._ts + AUDIO_FRAME_SAMPS) & 0xFFFFFFFF
            try:
                self._sock.sendto(pkt, cli_addr)
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
            with self._addr_lock:
                if self._cli_addr is None or self._cli_addr != addr:
                    self._cli_addr = addr
                    self.radio.ptt_client_addr = addr
            # Log outside the lock to avoid holding it during I/O
            # (set_client_addr's print is intentionally skipped here to keep
            #  the hot RX path lean; the TCP path still logs via set_client_addr)

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
        # A new client connection always starts with PTT off.  If the previous
        # client disconnected while transmitting, radio.ptt would still be True,
        # which would make the new GUI appear to start in TX mode.
        with self.radio.lock:
            self.radio.ptt = False
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

        self.sock.settimeout(30.0)   # avoid blocking forever on a stalled client
        buf = b""
        try:
            while self.alive:
                try:
                    data = self.sock.recv(65536)
                except socket.timeout:
                    continue
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
                    outgoing = self.radio.apply(cmd)
                    # When GUI sends its UDP address alongside set_ptt or
                    # audio_hello, register it so the TX loop can reach it.
                    if cmd.get("cmd") in ("set_ptt", "audio_hello"):
                        udp_port = cmd.get("udp_port")
                        if udp_port and self.audio_channel:
                            gui_ip = self.addr[0]
                            self.audio_channel.set_client_addr((gui_ip, int(udp_port)))
                    self.send_json({"resp": "ok", "state": self.radio.as_dict()})
                    if outgoing:
                        self.send_json(outgoing)
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
        next_tick = time.monotonic()
        # Simulated text panel updates are much slower than the ~10 Hz
        # spectrum stream so the chat/status panel doesn't scroll too fast.
        text_period = 3.0
        next_text_tick = time.monotonic() + text_period
        while self.alive:
            # BUG-11 fix: check running with a single lock-protected read
            # before calling as_dict() (which acquires the lock and copies all
            # state) to avoid redundant work while the radio is stopped.
            with self.radio.lock:
                is_running = self.radio.running
            if is_running:
                state = self.radio.as_dict()
                msg = self.radio.make_data_message()
                msg["state"] = state
                if not self.send_json(msg):
                    break
            now = time.monotonic()
            if now >= next_text_tick:
                next_text_tick = now + text_period
                for tmsg in self.radio.make_user_text_messages():
                    if not self.send_json(tmsg):
                        return   # socket dead — exit _stream_loop entirely
            next_tick += period
            time.sleep(max(0.0, next_tick - time.monotonic()))


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
    _umods= _cfg.get("user_mods",    {})
    _D    = _SERVER_CONFIG_DEFAULTS

    _def_host       = _srv.get("host",       _D["server"]["host"])
    _def_port       = int(_srv.get("port",   _D["server"]["port"]))
    _def_audio_port = int(_aud.get("audio_port", _D["audio"]["audio_port"]))
    _def_no_audio   = bool(_aud.get("no_audio",  _D["audio"]["no_audio"]))

    # Determine which positional args (host / port) were explicitly on the CLI,
    # ignoring every flag that takes a value (and its value) below.
    # NOTE: boolean store_true flags (e.g. --no-audio) must NOT be added here;
    # they consume no following argument and the scanner already skips them
    # correctly because they start with '-'.  Adding them would cause the
    # token *after* the flag to be silently dropped from _positionals.
    # IMPORTANT: host and port positionals must appear before any flags on the
    # command line to be detected reliably (e.g. `cat_server.py 0.0.0.0 50101
    # --no-audio`).  Passing them after flags risks ambiguous tokenisation.
    _value_flags = {'--config', '--audio-port', '--iq_wav', '--audio_wav'}
    for _n in range(1, NUM_USER_BUTTONS + 1):
        _value_flags.add(f'--user-button-label-{_n}')
        _value_flags.add(f'--user-button-type-{_n}')
    for _n in range(1, NUM_USER_MODS + 1):
        _value_flags.add(f'--user_mod_{_n}')
        _value_flags.add(f'--user_mod_type_{_n}')
    _skip = False
    _positionals = []
    for _a in sys.argv[1:]:
        if _skip:
            _skip = False
            continue
        if _a in _value_flags:
            _skip = True
            continue
        if any(_a.startswith(_vf + '=') for _vf in _value_flags):
            continue
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
    ap.add_argument("--iq_wav", metavar="PATH", default=None,
                    help="Path to a wav file of IQ samples in SDRplay IQ wav "
                         "format (stereo I/Q PCM or float). When given, the "
                         "RF spectrum/waterfall sent to the GUI is computed "
                         "from these real samples (looped forever) instead "
                         "of the built-in synthetic signal generator.")
    ap.add_argument("--audio_wav", metavar="PATH", default=None,
                    help="Path to a mono/stereo PCM (or float) wav file to "
                         "transmit to the GUI as the simulated received "
                         "audio, looped forever, instead of the built-in "
                         "demo sine tone. Resampled to the RTP audio sample "
                         "rate (8 kHz) if its native rate differs.")
    for n in range(1, NUM_USER_BUTTONS + 1):
        ap.add_argument(f"--user-button-label-{n}", metavar="TEXT",
                        default=argparse.SUPPRESS,
                        help=f"Label for user button {n} (max 7 characters)")
        ap.add_argument(f"--user-button-type-{n}", choices=["normal", "push"],
                        default=argparse.SUPPRESS,
                        help=f"Type of user button {n}: 'normal' (momentary) "
                             f"or 'push' (push-push/toggle). Default: normal")
    for n in range(1, NUM_USER_MODS + 1):
        ap.add_argument(f"--user_mod_{n}", metavar="LABEL",
                        default=argparse.SUPPRESS,
                        help=f"Label for user-defined modulation button {n} "
                             f"(max 4 characters). Slots must be filled in order: "
                             f"1, 2, 3 — no skipping.")
        ap.add_argument(f"--user_mod_type_{n}", choices=["normal", "text", "text_input"],
                        default=argparse.SUPPRESS,
                        help=f"Type of user-defined modulation button {n}: "
                             f"'normal' (acts like a standard mode button), "
                             f"'text' (splits the GUI's AF/audio box to show a "
                             f"read-only text panel), or 'text_input' (same "
                             f"split, but with an editable RTTY-chat-style input "
                             f"box below the read-only text). Default: normal. "
                             f"Requires --user_mod_{n} to also be set.")
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

    # User mods: CLI beats config, config beats built-in default
    for n in range(1, NUM_USER_MODS + 1):
        _mattr = f"user_mod_{n}"
        _tattr2 = f"user_mod_type_{n}"
        _cfg_mod_label = _umods.get(f"label_{n}", _D["user_mods"][f"label_{n}"])
        _cfg_mod_type  = _umods.get(f"type_{n}",  _D["user_mods"][f"type_{n}"])
        if not hasattr(_raw, _mattr):
            setattr(_raw, _mattr, _cfg_mod_label)
        if not hasattr(_raw, _tattr2):
            setattr(_raw, _tattr2, _cfg_mod_type)

    # ── Validations ───────────────────────────────────────────────────────────
    # Length checks
    for n in range(1, NUM_USER_BUTTONS + 1):
        label = getattr(_raw, f"user_button_label_{n}")
        if len(label) > 7:
            ap.error(f"--user-button-label-{n}: label must be at most 7 "
                     f"characters (got {len(label)!r}: {label!r})")
    for n in range(1, NUM_USER_MODS + 1):
        label = getattr(_raw, f"user_mod_{n}")
        if len(label) > 4:
            ap.error(f"--user_mod_{n}: label must be at most 4 "
                     f"characters (got {len(label)!r}: {label!r})")
    # Each user_mod_type_N belongs to its own user_mod_N — an empty label
    # slot cannot carry a non-default type.
    for n in range(1, NUM_USER_MODS + 1):
        label = getattr(_raw, f"user_mod_{n}")
        mtype = getattr(_raw, f"user_mod_type_{n}")
        if not label and mtype != "normal":
            ap.error(f"--user_mod_type_{n} requires --user_mod_{n} to also "
                     f"be set (a type cannot be set on an empty slot)")

    # Sequential checks: no gaps allowed — must fill 1, 2, 3… in order
    _btn_empty = False
    for n in range(1, NUM_USER_BUTTONS + 1):
        _lbl = getattr(_raw, f"user_button_label_{n}")
        if not _lbl:
            _btn_empty = True
        elif _btn_empty:
            ap.error(f"--user-button-label/type flags must be specified "
                     f"sequentially (1, 2, 3…); cannot set slot {n} while "
                     f"a preceding slot is empty")
    _mod_empty = False
    for n in range(1, NUM_USER_MODS + 1):
        _lbl = getattr(_raw, f"user_mod_{n}")
        if not _lbl:
            _mod_empty = True
        elif _mod_empty:
            ap.error(f"--user_mod flags must be specified sequentially "
                     f"(1, 2, 3); cannot set --user_mod_{n} without "
                     f"filling the preceding slots")
    return _raw


def _build_user_buttons(args):
    buttons = []
    for n in range(1, NUM_USER_BUTTONS + 1):
        buttons.append({
            "label": getattr(args, f"user_button_label_{n}"),
            "type": getattr(args, f"user_button_type_{n}"),
        })
    return buttons


def _build_user_mods(args):
    """Return a list of NUM_USER_MODS label strings for user-defined mod buttons."""
    return [getattr(args, f"user_mod_{n}", "") for n in range(1, NUM_USER_MODS + 1)]


def _build_user_mod_types(args):
    """Return a list of NUM_USER_MODS type strings for user-defined mod buttons."""
    return [getattr(args, f"user_mod_type_{n}", "normal") for n in range(1, NUM_USER_MODS + 1)]


def main():
    args = _parse_args()
    host = args.host
    port = args.port

    # ── Optional: load a recorded IQ wav file to drive the RF spectrum ────────
    iq_source = None
    if args.iq_wav:
        try:
            iq_source = IQWavSource(args.iq_wav)
        except Exception as e:
            print(f"[cat_server] ERROR: could not load --iq_wav {args.iq_wav!r}: {e}")
            sys.exit(1)
        cf = f"{iq_source.center_freq / 1e6:.6f} MHz" if iq_source.center_freq else "unknown (use GUI to set)"
        print(f"[cat_server] IQ wav loaded: {args.iq_wav}")
        print(f"[cat_server]   sample_rate={iq_source.sample_rate} Hz, "
              f"channels={iq_source.channels}, bits={iq_source.bits_per_sample}"
              f"{' float' if iq_source.is_float else ''}, center_freq={cf}")
        print("[cat_server]   -> looping this file forever for spectrum/waterfall")

    radio = RadioState(user_buttons=_build_user_buttons(args),
                       user_mod_labels=_build_user_mods(args),
                       user_mod_types=_build_user_mod_types(args),
                       iq_source=iq_source)

    # ── Optional: load a wav file to transmit as the downlink audio ──────────
    audio_source = None
    if args.audio_wav:
        try:
            audio_source = AudioWavSource(args.audio_wav)
        except Exception as e:
            print(f"[cat_server] ERROR: could not load --audio_wav {args.audio_wav!r}: {e}")
            sys.exit(1)
        print(f"[cat_server] audio wav loaded: {args.audio_wav}")
        print(f"[cat_server]   source sample_rate={audio_source.source_sample_rate} Hz, "
              f"channels={audio_source.source_channels} "
              f"-> resampled to {AUDIO_SAMPLE_RATE} Hz mono")
        print("[cat_server]   -> looping this file forever as the RX audio "
              "stream sent to the GUI")

    # ── Start the UDP audio channel ──────────────────────────────────────────
    audio_ch = None
    if not args.no_audio:
        audio_ch = UDPAudioChannel(radio, args.audio_port, audio_source=audio_source)
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
        if iq_source:
            iq_source.close()
        srv.close()


if __name__ == "__main__":
    main()
