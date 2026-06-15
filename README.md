# CAT GUI Interface (TCP-driven simulation)

This project is a Python/Tkinter **CAT GUI Interface** — a simulated SDR
front-end whose every control is wired to a small simulated "radio" backend
over a plain TCP socket.

It consists of two files:

- `cat_server.py` — a TCP server that acts as the hardware/backend layer.
  It owns all "radio state" and streams a simulated RF environment.
- `cat_gui.py` — a Tkinter client that provides the CAT GUI Interface main
  window and sends every user interaction to the server, redrawing from the
  data the server streams back.

---

## 1. Interface overview

The CAT GUI Interface is a Python/Tkinter application for Software Defined
Radio control. Key points:

- **No direct hardware access.** The GUI talks to its backend through
  `cat_server.py`, which abstracts away any specific SDR device and exposes
  a common TCP API for setting frequency, sample rate, gain, and
  starting/stopping the I/Q stream.
- **Main window layout** centers on:
  - Large amber LCD-style 9-digit frequency displays for **LO A**, **LO B**,
    and **Tune**, each tunable by scrolling or clicking individual digits or
    by double-clicking to type a frequency. LO A and LO B are selectable;
    the active LO drives the RF waterfall/spectrum centre frequency.
  - An RF spectrum (FFT) display and an RF waterfall above it, centred on
    the active LO frequency and spanning the receiver's sample rate
    (narrower if "zoomed").
  - A draggable IF/filter passband overlay drawn directly on the spectrum,
    whose edges set the demodulator bandwidth.
  - Mode buttons: **AM, ECSS, FM, LSB, USB, CW, DIG**, each with a sensible
    default filter passband.
  - A single **AGC Med** toggle button (in the second DSP row), plus
    **Notch** and **ANotch** toggles.
  - DSP toggle buttons: **NR** (noise reduction), **NB RF** (noise blanker
    RF), **NB IF** (noise blanker IF), and **AFC** (automatic frequency
    control) on the first row; **Mute**, **AGC Med**, **Notch**, and
    **ANotch** on the second row.
  - Up to 6 **user-defined buttons** (3 per DSP row, right-aligned), whose
    labels and types (momentary or push-push/toggle) are configured on the
    server side.
  - An S-Meter showing signal strength in S-units (S1–S9, S9+20 dB,
    S9+40 dB) and a digital dBm readout, derived from the power inside the
    current filter passband.
  - **Volume** and **AGC Thresh.** sliders in the control panel.
  - Zoom control (mouse-wheel on the spectrum, or toolbar labels) for the
    RF spectrum and waterfall.
  - A smaller AF (audio) spectrum + waterfall pane showing the demodulated
    audio passband.
  - A **band quick-select** column (160m, 80m, 60m, 40m, 30m, 20m, 17m,
    15m, 12m, 10m, 6m) that tunes the currently active LO.
  - **Transport bar** buttons: Record (●), Play (▶), Pause (⏸), Stop (■),
    Rewind (◀◀), Fast-forward (▶▶), and Loop (∞).
  - **Start/Stop** control over the receiver stream.
  - S-meter auxiliary buttons: **Peak**, **S-units**, **Squelch**.
  - Function buttons: **SDR-Device**, **Soundcard**, **Bandwidth**,
    **Options**, **FreqMgr**.
  - A live **date/time clock** and a TCP **Connect/Disconnect** button with
    a coloured status indicator dot.
  - Two toolbar strips (one between the RF waterfall and the control panel,
    one in the AF pane), each with **Waterfall** / **Spectrum** toggle
    buttons, RBW readout, Avg, Zoom and Speed labels.
  - A persistent **HiDPI +/−** overlay in the bottom-right corner for
    real-time scaling from level −5 to +5 (factor 1.25 per step).
- **Custom TCP control protocol.** The CAT GUI Interface defines its own
  simple newline-delimited JSON protocol between `cat_gui.py` and
  `cat_server.py` (described below).

## 2. Feature map

| CAT GUI feature | Implementation |
| --- | --- |
| Backend | `cat_server.py` — owns all radio state, generates a simulated RF spectrum |
| VFO digit displays (LO A, LO B, Tune) | `FreqDisp` — scroll/click each digit, double-click to type a frequency; clicking the LO A or LO B label switches the active LO and immediately recentres the waterfall |
| RF spectrum + filter overlay | `SpecCanvas` — draggable passband edges, click-to-tune, scroll-to-zoom |
| RF waterfall | `WFCanvas` (900-bin internal resolution) |
| AF spectrum + waterfall | second `SpecCanvas` / `WFCanvas` pair, baseband 0..3000 Hz |
| Mode buttons (AM/ECSS/FM/LSB/USB/CW/DIG) | Mode button row, sets default filter passband per mode |
| DSP toggles (NR / NB RF / NB IF / AFC / Mute / Notch / ANotch) | Two DSP button rows |
| AGC | Single **AGC Med** toggle button |
| User-defined buttons (×6) | Right-aligned in the two DSP rows; labels and types come from the server |
| S-Meter | `SMeter` canvas, S1–S9 + S9+20 dB / S9+40 dB overload scale, digital dBm readout |
| Volume / AGC Thresh. | Sliders in the left control panel |
| Zoom / span | Mouse-wheel on the RF spectrum canvas |
| Band quick-select | Column of band buttons (160m–6m) beside the frequency displays |
| Transport bar | ● ▶ ⏸ ■ ◀◀ ▶▶ ∞ buttons, each sends a `transport` command |
| Start/Stop | Start/Stop button, controls server streaming |
| PTT | Circular canvas button in S-meter row; sends `set_ptt` command |
| HiDPI scaling | Persistent −/+ overlay; scale levels −5..+5 (×1.25 per step) |
| Fullscreen | `--full-screen` flag; triple-Esc (3 presses within 1 s) toggles fullscreen on/off |
| Theme | `--bg dark` (default) or `--bg light` (#FFECD6 backgrounds) |

Everything in the table above is driven live over TCP — nothing is static
or pre-rendered.

## 3. TCP protocol

Each message is one JSON object terminated by `\n`.

**Client → Server (commands):**

```
{"cmd": "hello"}
{"cmd": "set_freq",       "hz": 14195000}
{"cmd": "set_lo_b_freq",  "hz": 14195000}
{"cmd": "set_tune_freq",  "hz": 14205000}
{"cmd": "set_lo",         "lo": "A"}               # "A" or "B" — active LO
{"cmd": "set_mode",       "mode": "USB"}            # AM|ECSS|FM|LSB|USB|CW|DIG
{"cmd": "set_filter",     "lo": 100, "hi": 2800}   # Hz offsets from carrier
{"cmd": "set_agc",        "mode": "Med"}            # Off|Med
{"cmd": "set_agc_thresh", "value": -100.0}          # dBm
{"cmd": "set_rf_gain",    "value": 20}              # 0..40 dB
{"cmd": "set_volume",     "value": 80}              # 0..100
{"cmd": "set_squelch",    "value": -130}            # dBm threshold
{"cmd": "set_nb",         "enabled": true}
{"cmd": "set_nr",         "enabled": true}
{"cmd": "set_nbrf",       "enabled": true}
{"cmd": "set_nbif",       "enabled": true}
{"cmd": "set_afc",        "enabled": true}
{"cmd": "set_anf",        "enabled": true}
{"cmd": "set_notch",      "enabled": true}
{"cmd": "set_mute",       "enabled": true}
{"cmd": "set_ptt",        "enabled": true}
{"cmd": "set_zoom",       "value": 2}              # 1..32
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "transport",      "action": "rec"}         # rec|play|pause|stop|ff|rw|infinite
{"cmd": "ui_button",      "name": "FreqMgr"}       # SDR-Device|Soundcard|Bandwidth|Options|FreqMgr|…
{"cmd": "ui_display",     "box": "rf", "view": "waterfall"}  # box: rf|af  view: waterfall|spectrum
{"cmd": "ui_smeter_btn",  "name": "Peak"}          # Peak|S-units|Squelch
{"cmd": "user_button",    "index": 1}              # momentary press (normal type)
{"cmd": "user_button",    "index": 2, "enabled": true}  # push-push toggle state
```

**Server → Client:**

Reply to every command:
```
{"resp": "ok", "state": {...current radio state...}}
```

Streamed (only while "running"), about 10×/second:
```
{
  "type": "data",
  "f_start": <Hz>, "f_stop": <Hz>,
  "spectrum": [dBm, dBm, ...],       # RF spectrum, 600 points
  "af_spectrum": [dBm, ...],         # AF spectrum, 256 points
  "af_range": 3000,
  "smeter_dbm": -73.4,
  "smeter_text": "S9 +3dB",
  "squelch_open": true,
  "state": {...current radio state...}
}
```

The `state` dict included in every response and data push contains the full radio
state: `center_freq`, `lo_b_freq`, `lo_active` (`"A"` or `"B"`), `tune_freq`,
`sample_rate`, `zoom`, `mode`, `filter_lo`, `filter_hi`, `agc` (`"Med"` or
`"Off"`), `agc_thresh`, `rf_gain`, `volume`, `squelch`, `nb`, `nr`, `nbrf`,
`nbif`, `afc`, `anf`, `notch`, `mute`, `ptt`, `running`, `user_buttons`, and
`user_btn_state`.

The simulated RF environment is generated deterministically from frequency
(noise floor + synthetic HF carriers spread across 1.8–30 MHz with slowly
drifting amplitudes), so different parts of the spectrum have a realistic,
varied look, and tuning/zooming/filtering all visibly affect the S-meter,
AF spectrum, and waterfalls.

## 4. Running it

Requires Python 3 with Tkinter (`python3-tk` on Debian/Ubuntu).

```bash
# Terminal 1 — start the simulated SDR backend
python3 cat_server.py            # listens on 0.0.0.0:50101 by default
python3 cat_server.py 0.0.0.0 50101   # explicit host and port

# Configure user-defined buttons (optional)
python3 cat_server.py \
    --user-button-label-1 "Gain+" --user-button-type-1 normal \
    --user-button-label-2 "Record" --user-button-type-2 push

# Terminal 2 — start the GUI
python3 cat_gui.py
```

### GUI command-line options

| Flag | Description |
| --- | --- |
| `--host HOST --port PORT` | Pre-fill and lock the server address (both required together); hides the host/port entry fields in the GUI |
| `--bg dark\|light` | Colour theme (`dark` is default; `light` sets panel backgrounds to #FFECD6) |
| `--scale INT` | Initial HiDPI scale level, −5..+5 (default 0; factor is 1.25^level) |
| `--disable-scale` | Hide the +/− scale overlay (requires `--scale` to also be set) |
| `--full-screen` | Start in full-screen mode |
| `--freq-font PATH` | TTF/OTF file for the LO/Tune frequency digit displays |
| `--gui-font PATH` | TTF/OTF file for all other GUI text |

In the GUI, click **Connect** (default host `127.0.0.1`, port `50101`),
then **Start** to begin streaming. From there:

- Scroll or click on the frequency digits (or double-click to type a
  frequency) to tune LO A, LO B, or Tune independently.
- Click the **LO A** or **LO B** label-button to switch which LO drives the
  RF waterfall/spectrum; the display recentres immediately.
- Click the band buttons (160m–6m) to QSY the currently active LO.
- Click anywhere on the RF spectrum to tune the active LO to that frequency.
- Drag the edges of the shaded filter overlay to change the passband.
- Click mode buttons (AM/ECSS/FM/LSB/USB/CW/DIG) to change the demodulation
  mode; each sets a default passband.
- Toggle **NR**, **NB RF**, **NB IF**, **AFC**, **Mute**, **AGC Med**,
  **Notch**, and **ANotch** as needed.
- Use the **Volume** and **AGC Thresh.** sliders.
- Scroll the mouse wheel on the RF spectrum to zoom in or out.
- Use the **Waterfall** / **Spectrum** toggle buttons in each toolbar strip
  to switch the display mode for that pane.
- Press Escape three times within one second to toggle fullscreen mode.
- Use the **+/−** overlay in the bottom-right corner to adjust the HiDPI
  scale live without restarting.

## 5. Limitations

This is a simulation for demonstration/educational purposes:

- There is no real RF hardware or audio output — the "signals" are a
  deterministic synthetic model of HF carriers across 1.8–30 MHz, and
  DSP controls (NR/NB/ANF/Mute/Volume/AGC) affect the displayed numbers
  but don't process real audio.
- Menu system, band-mapping database, recording, DRM decoding, and
  OmniRig/CAT integration are not reproduced — this focuses on the
  core tuning/spectrum/waterfall/meter workflow described above.
- The server accepts only one client at a time per port; multiple
  simultaneous connections are served by separate `ClientHandler` threads
  but share the same `RadioState` instance.
