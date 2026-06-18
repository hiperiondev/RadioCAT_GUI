# CAT GUI Interface

<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="screenshot">
  </a>
</div>

This project is a Python/Tkinter **CAT GUI Interface** — a simulated SDR
front-end whose every control is wired to a small simulated "radio" backend
over a plain TCP socket.

It consists of two files:

- `cat_server.py` — a TCP server that acts as the hardware/backend layer.
  It owns all "radio state", streams a simulated RF environment, and manages
  a bidirectional RTP/UDP audio channel.
- `cat_gui.py` — a Tkinter client that provides the CAT GUI Interface main
  window and sends every user interaction to the server, redrawing from the
  data the server streams back. It also plays received RTP audio and sends
  microphone audio during PTT.

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
  - Mode buttons: **AM, ECSS, FM, LSB, USB, CW, DIG**, each with a default
    filter passband (note: ECSS and DIG do not change the filter on mode
    switch — only the mode label updates).
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
  - Function buttons: **Device**, **Soundcard**, **Bandwidth**,
    **Options**, **FreqMgr**. Note: **Soundcard** opens a local audio device
    selection dialog and does **not** send a command to the server.
  - A live **date/time clock** and a TCP **Connect/Disconnect** button with
    a coloured status indicator dot.
  - Two toolbar strips (one between the RF waterfall and the control panel,
    one in the AF pane), each with **Waterfall** / **Spectrum** toggle
    buttons, RBW readout, Avg, Zoom and Speed labels.
  - A persistent **HiDPI +/−** overlay in the bottom-right corner for
    real-time scaling from level −5 to +5 (factor 1.25 per step).
  - A **PTT** circular canvas button (in the S-meter row) that toggles
    transmit mode; while PTT is active the GUI sends microphone audio to the
    server via RTP/UDP and stops playing received audio.
- **RTP/UDP audio channel.** In addition to the TCP control connection, the
  server opens a UDP port (default 5004) for bidirectional G.711 µ-law
  (PCMU) audio. While PTT is off, the server streams a demo sine tone to the
  GUI for playback; while PTT is on, the GUI captures microphone audio and
  streams it to the server. Audio playback and capture use PyAudio (optional;
  the GUI runs without it but audio is silently disabled).
- **TOML configuration files.** Both applications auto-create a
  `cat_server.toml` / `cat_gui.toml` file in the current directory on first
  run and use it as a persistent source of defaults. CLI flags always override
  config file values.
- **Custom TCP control protocol.** The CAT GUI Interface defines its own
  simple newline-delimited JSON protocol between `cat_gui.py` and
  `cat_server.py` (described below).

## 2. Feature map

| CAT GUI feature | Implementation |
| --- | --- |
| Backend | `cat_server.py` — owns all radio state, generates a simulated RF spectrum |
| VFO digit displays (LO A, LO B, Tune) | `FreqDisp` — scroll/click each digit, double-click to type a frequency; clicking the LO A or LO B label switches the active LO and immediately recentres the waterfall |
| RF spectrum + filter overlay | `SpecCanvas` — draggable passband edges, click-to-tune, scroll-to-zoom |
| RF waterfall | `WFCanvas` (900-bin internal render resolution; server streams 600 points) |
| AF spectrum + waterfall | second `SpecCanvas` / `WFCanvas` pair, baseband 0..3000 Hz (server streams 256 points; waterfall renders at 600 bins internally) |
| Mode buttons (AM/ECSS/FM/LSB/USB/CW/DIG) | Mode button row; sets default filter passband for AM, FM, LSB, USB, CW. ECSS and DIG change the mode label only — filter is unchanged |
| DSP toggles (NR / NB RF / NB IF / AFC / Mute / AGC Med / Notch / ANotch) | Two DSP button rows. There is no standalone NB button; the server's `nb` state flag has no GUI control |
| User-defined buttons (×6) | Right-aligned in the two DSP rows; labels and types come from the server |
| User-defined modulation buttons (×5) | Configurable via `--user_mod_1`…`--user_mod_5` / `--user_mod_type_1`…`--user_mod_type_5`; labels and types in `user_mod_labels` / `user_mod_types` state fields |
| IQ wav / audio wav playback | `IQWavSource` (`--iq_wav`) feeds a real IQ wav file to the RF spectrum/waterfall; `AudioWavSource` (`--audio_wav`) replaces the demo sine tone with a real audio file |
| S-Meter | `SMeter` canvas, S1–S9 + S9+20 dB / S9+40 dB overload scale, digital dBm readout |
| Volume / AGC Thresh. | Sliders in the left control panel |
| Zoom / span | Mouse-wheel on the RF spectrum canvas |
| Band quick-select | Column of band buttons (160m–6m) beside the frequency displays |
| Transport bar | ● ▶ ⏸ ■ ◀◀ ▶▶ ∞ buttons, each sends a `transport` command |
| Start/Stop | Start/Stop button, controls server streaming |
| PTT | Circular canvas button in S-meter row; sends `set_ptt` command and switches the RTP audio channel between RX and TX |
| RTP/UDP audio | `RTPAudioClient` (GUI) / `UDPAudioChannel` (server) — bidirectional G.711 µ-law audio on a UDP port; requires PyAudio |
| Soundcard dialog | Local audio device selection dialog (microphone + speaker independently); opened by the Soundcard button, does **not** send a `ui_button` command to the server |
| HiDPI scaling | Persistent −/+ overlay; scale levels −5..+5 (×1.25 per step) |
| Fullscreen | `--full-screen` flag; triple-Esc (3 presses within 1 s) toggles fullscreen on/off |
| Theme | `--bg dark` (default) or `--bg light` (#FFECD6 backgrounds) |
| TOML config | `cat_server.toml` / `cat_gui.toml` auto-created on first run; `--config PATH` overrides location |

Everything in the table above is driven live over TCP — nothing is static
or pre-rendered.

## 3. TCP protocol

Each message is one JSON object terminated by `\n`.

**Client → Server (commands):**

```json
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
{"cmd": "set_nb",         "enabled": true}          # standalone NB flag (no GUI button; server-side only)
{"cmd": "set_nr",         "enabled": true}
{"cmd": "set_nbrf",       "enabled": true}
{"cmd": "set_nbif",       "enabled": true}
{"cmd": "set_afc",        "enabled": true}
{"cmd": "set_anf",        "enabled": true}
{"cmd": "set_notch",      "enabled": true}
{"cmd": "set_mute",       "enabled": true}
{"cmd": "set_ptt",        "enabled": true, "udp_port": 5010}  # udp_port = GUI's RTP UDP port
{"cmd": "set_zoom",       "value": 2}              # 1..32
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "transport",      "action": "rec"}         # rec|play|pause|stop|ff|rw|infinite
{"cmd": "ui_button",      "name": "FreqMgr"}       # Device|Bandwidth|Options|FreqMgr (Soundcard excluded — opens local dialog only)
{"cmd": "ui_display",     "box": "rf", "view": "waterfall"}  # box: rf|af  view: waterfall|spectrum
{"cmd": "ui_smeter_btn",  "name": "Peak"}          # Peak|S-units|Squelch
{"cmd": "user_button",    "index": 1}              # momentary press (normal type)
{"cmd": "user_button",    "index": 2, "enabled": true}  # push-push toggle state
{"cmd": "audio_hello",    "udp_port": 5010}        # GUI registers its RTP UDP port with the server
{"cmd": "user_text",     "index": 1, "text": "CQ CQ DE TEST"}  # write a text string to slot index (1-based)
```

> **Note:** The **Soundcard** button opens a local audio device dialog and does
> **not** send a `ui_button` command to the server.

> **Note:** `set_nb` is handled by the server and tracked in the state dict,
> but the GUI currently has no button that sends it. Use it from external
> clients or extend the GUI to add an "NB" toggle.

> **Note:** `audio_hello` must be sent by any third-party client after connecting
> to register the client's RTP UDP port with the server before audio will flow.

**Server → Client:**

Sent once on connect (before streaming starts), when the audio channel is
enabled:
```json
{"type": "audio_port", "port": 5004, "sample_rate": 8000, "frame_ms": 20, "codec": "pcmu"}
```

> **Note on UDP ports:** `5004` is the server's RTP listen port (the port the
> server opens and the GUI sends audio *to*). The `udp_port` field in
> `set_ptt` / `audio_hello` commands (e.g. `5010`) is the *GUI's* RTP send
> port — the port the server should send audio *back to*. These are two
> different sides of the bidirectional channel.

Reply to every command:
```json
{"resp": "ok", "state": {...current radio state...}}
```

Asynchronous server-initiated push (sent whenever a `user_text` slot is updated):
```json
{"type": "user_text", "index": 1, "text": "CQ CQ DE TEST"}
```

Streamed (only while "running"), about 10×/second:
```json
{
  "type": "data",
  "f_start": <Hz>, "f_stop": <Hz>,
  "spectrum": [dBm, dBm, ...],       # RF spectrum, 600 points
  "af_spectrum": [dBm, ...],         # AF spectrum, 256 points
  "af_range": 3000,
  "smeter_dbm": -73.4,
  "smeter_text": "S9",
  "squelch_open": true,
  "state": {...current radio state...}
}
```

The `state` dict included in every response and data push contains the full radio
state: `center_freq`, `lo_b_freq`, `lo_active` (`"A"` or `"B"`), `tune_freq`,
`sample_rate`, `zoom`, `mode`, `filter_lo`, `filter_hi`, `agc` (`"Med"` or
`"Off"`), `agc_thresh`, `rf_gain`, `volume`, `squelch`, `nb`, `nr`, `nbrf`,
`nbif`, `afc`, `anf`, `notch`, `mute`, `ptt`, `running`, `user_buttons`,
`user_btn_state`, `user_mod_labels`, and `user_mod_types`.

> **Note:** `smeter_text` is a string in the format `"S1"` through `"S9"`,
> `"S9+20dB"`, or `"S9+40dB"` for overload levels. The `set_zoom` command
> controls the **RF spectrum zoom** (integer factor 1–32) and is entirely
> separate from the `--scale` CLI flag, which controls the **HiDPI UI scale**
> (levels −5 to +5, factor 1.25 per step).

The simulated RF environment is generated deterministically from frequency
(noise floor + synthetic HF carriers spread across 1.8–30 MHz with slowly
drifting amplitudes), so different parts of the spectrum have a realistic,
varied look, and tuning/zooming/filtering all visibly affect the S-meter,
AF spectrum, and waterfalls.

## 4. Running it

Requires Python 3 with Tkinter (`python3-tk` on Debian/Ubuntu).

**Optional Python packages** (installed separately; the apps run without them
but with reduced functionality):

```bash
pip install pyaudio       # RTP audio playback/capture (mic/speaker); silently disabled if absent
pip install tomli         # TOML config file support on Python < 3.11 (3.11+ has it built in)
pip install fonttools     # Accurate PostScript family-name extraction for custom fonts
pip install numpy         # Faster FFT computation; falls back to pure-Python if absent
```

```bash
# Terminal 1 — start the simulated SDR backend
python3 cat_server.py            # listens on 0.0.0.0:50101 by default
python3 cat_server.py 0.0.0.0 50101   # explicit host and port

# Configure user-defined buttons (optional)
python3 cat_server.py \
    --user-button-label-1 "Gain+" --user-button-type-1 normal \
    --user-button-label-2 "Record" --user-button-type-2 push

# Use a real IQ wav file for the RF spectrum/waterfall instead of the synthetic model
python3 cat_server.py --iq_wav /path/to/iq_recording.wav

# Use a real audio wav file for RTP playback instead of the 440 Hz demo tone
python3 cat_server.py --audio_wav /path/to/audio.wav

# Terminal 2 — start the GUI
python3 cat_gui.py
```

### Server command-line options

| Flag | Description |
| --- | --- |
| `host [port]` | Positional: host/IP and TCP port to listen on (defaults: `0.0.0.0` `50101`) |
| `--config PATH` | Load TOML config from PATH (default: `./cat_server.toml`, auto-created on first run) |
| `--audio_port PORT` | UDP port for the RTP audio channel (default: `5004`) |
| `--no-audio` | Disable the RTP/UDP audio channel entirely |
| `--iq_wav PATH` | Feed a real IQ wav file as the RF spectrum/waterfall source instead of the synthetic model |
| `--audio_wav PATH` | Replace the demo 440 Hz sine tone with a real audio wav file for RTP playback |
| `--user-button-label-N TEXT` | Label for user button N (1–6, max 7 characters) |
| `--user-button-type-N TYPE` | Type of user button N: `normal` (momentary) or `push` (push-push/toggle) |
| `--user_mod_N TEXT` | Label for user-defined modulation button N (1–5) |
| `--user_mod_type_N TYPE` | Type of user modulation button N: `normal` or `push` |

### GUI command-line options

| Flag | Description |
| --- | --- |
| `--host HOST --port PORT` | Pre-fill and lock the server address (both required together); hides the host/port entry fields in the GUI |
| `--config PATH` | Load TOML config from PATH (default: `./cat_gui.toml`, auto-created on first run) |
| `--bg dark\|light` | Colour theme (`dark` is default; `light` sets panel backgrounds to #FFECD6) |
| `--scale INT` | Initial HiDPI scale level, −5..+5 (default 0; factor is 1.25^level) |
| `--disable-scale` | Hide the +/− scale overlay (requires `--scale` to also be set) |
| `--full-screen` | Start in full-screen mode |
| `--freq-font PATH` | TTF/OTF file for the LO/Tune frequency digit displays |
| `--gui-font PATH` | TTF/OTF file for all other GUI text |
| `--audio-list` | List all audio input/output devices with their index numbers, then exit |
| `--audio-mic INDEX` | Select the microphone device by index (must be paired with `--audio-speaker`) |
| `--audio-speaker INDEX` | Select the speaker/headphone device by index (must be paired with `--audio-mic`) |
| `--disable-soundcard-select` | Hide the Soundcard button in the GUI |

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
  mode; AM, FM, LSB, USB, and CW each set a default passband.
- Toggle **NR**, **NB RF**, **NB IF**, **AFC**, **Mute**, **AGC Med**,
  **Notch**, and **ANotch** as needed.
- Use the **Volume** and **AGC Thresh.** sliders.
- Scroll the mouse wheel on the RF spectrum to zoom in or out.
- Use the **Waterfall** / **Spectrum** toggle buttons in each toolbar strip
  to switch the display mode for that pane.
- Press Escape three times within one second to toggle fullscreen mode.
- Use the **+/−** overlay in the bottom-right corner to adjust the HiDPI
  scale live without restarting.
- Click the **Soundcard** button to open the local audio device selection
  dialog and choose microphone and speaker devices independently.
- Click the **PTT** button to toggle transmit; audio streams to the server
  while PTT is active (requires PyAudio).

## 5. Limitations

This is a simulation for demonstration/educational purposes:

- There is no real RF hardware or audio output — the "signals" are a
  deterministic synthetic model of HF carriers across 1.8–30 MHz, and
  DSP controls (NR/NB/ANF/Mute/Volume/AGC) affect the displayed numbers
  but don't process real audio.
- The RTP audio channel streams a 440 Hz sine tone from the server (PTT off)
  and discards received microphone audio (PTT on). Real audio routing to SDR
  TX hardware is left as a stub in `UDPAudioChannel._rx_loop`.
- Audio features require `pyaudio`. If it is not installed, the audio channel
  is silently disabled; all other GUI functions still work.
- The `nb` (standalone noise blanker) state flag is handled by the server and
  included in the state dict, but no GUI button sends `set_nb`. Toggle it
  from an external client or add a dedicated "NB" button.
- The `rf_gain` state is tracked by the server and included in the state dict
  (default 20.0 dB), but the GUI has no slider or control that sends
  `set_rf_gain`. It can only be set from external clients or extended with a
  dedicated control.
- The `squelch` threshold is tracked by the server (default −130.0 dBm) and
  drives the `squelch_open` flag in every data frame, but the GUI has no slider
  for `set_squelch`. The "Squelch" button in the S-meter column sends a
  `ui_smeter_btn` notification only; it does not change the squelch level.
- The RF spectrum is always computed from LO A's frequency (`center_freq`)
  regardless of which LO is active. Switching to LO B recentres the display
  on the client side, but subsequent data frames from the server will reflect
  LO A's position, not LO B's.
- ECSS and DIG modes have no default filter passband: selecting them updates
  the mode label but leaves the filter edges unchanged.
- Menu system, band-mapping database, recording, DRM decoding, and
  OmniRig/CAT integration are not reproduced — this focuses on the
  core tuning/spectrum/waterfall/meter workflow described above.
- The server accepts multiple simultaneous connections, each served by a
  separate `ClientHandler` thread, but all threads share the same
  `RadioState` instance.
