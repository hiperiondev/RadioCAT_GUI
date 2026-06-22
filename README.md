# CAT GUI Interface

<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="screenshot">
  </a>
</div>

This project is a Python/Tkinter **CAT GUI Interface** — a SDR
front-end whose every control is wired to a small radio backend
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
  - No fixed Mode or DSP-toggle button rows — mode selection and DSP
    toggles are implemented entirely through the generic, server-labeled
    user-defined button banks below; the GUI holds no per-mode defaults
    (e.g. filter passband).
  - Up to 14 **user-defined buttons** (7 per row, filling the full panel
    width across two rows with equal-weight grid columns — not
    right-aligned), whose labels and types (momentary or push-push/toggle)
    are configured on the server side.
  - Up to 11 **RF user buttons**, shown left of the band-select column,
    with the same momentary/push-push behaviour as the user-defined
    buttons above; configured on the server side.
  - An S-Meter showing signal strength in S-units (S1–S9, S9 +20dB,
    S9 +40dB) and a digital dBm readout, derived from the power inside the
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
    **Sample Rate**. Note: **Soundcard** opens a local audio device
    selection dialog and does **not** send a command to the server.
  - **Device selector.** The server can hold multiple device profiles
    (each with its own user buttons, RF user buttons, user-mod buttons,
    sample-rate list, and antenna port definitions). `get_devices`/`select_device` let the GUI list
    and switch between them; switching reloads that device's buttons,
    sample rates, antenna ports, and restores its last-saved GUI state.
  - **Sample-rate selector.** `get_sample_rates`/`set_sample_rate` let the
    GUI query and change the active device's SDR sample rate from its
    configured list of choices.
  - **Frequency memories.** Each of LO A, LO B, and Tune has 20 storable
    memory slots (label + frequency), saved per device via
    `get_memories`/`save_memory`.
  - **Spectrum reference level / averaging.** `set_spec_ref` and
    `set_spec_ave` independently control the RF and AF spectrum displays'
    reference (top-of-scale) level and FFT averaging count.
  - **Split** mode, toggled via `set_split`, is tracked in the radio state.
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
- **TOML configuration files.** `cat_gui.py` auto-creates a single
  `cat_gui.toml` in the current directory on first run and uses it as a
  persistent source of defaults. The auto-generated file includes an `[audio]`
  section with `mic`, `speaker`, and `disable_soundcard_select` keys — the
  last of which hides the Soundcard button and is equivalent to the
  `--disable-soundcard-select` CLI flag. `cat_server.py` uses **two** TOML files:
  `cat_server.toml` (transport settings plus the `[devices]` list of
  selectable device profiles) and one `cat_device.toml`-style file per
  device profile (that device's user buttons, RF user buttons, user-mod
  buttons, SDR sample rates, and antenna port definitions). Both
  `cat_server.toml` and the default device's `cat_device.toml` are
  auto-created on first run if missing. Each device also gets its own
  auto-created memory file and GUI-state file. CLI flags always override
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
| RF waterfall | `WFCanvas` (900-bin internal render resolution; server streams 600 points — the GUI linearly interpolates the 600 server points to fill the 900 render bins) |
| AF spectrum + waterfall | second `SpecCanvas` / `WFCanvas` pair, baseband 0..3000 Hz; computed locally by `RTPAudioClient._af_worker` from decoded RTP audio (512-point FFT, 50% overlap Hamming window) — not streamed from the server |
| Mode selection | No fixed mode-button row; done via the user-defined modulation buttons (see below). The GUI holds no per-mode default passband |
| DSP toggles (NR / NB RF / NB IF / AFC / Mute / AGC Med / Notch / ANotch) | No fixed DSP toggle row — removed from the GUI. These functions, if exposed, are implemented via the generic user-defined buttons below. There is no standalone NB button; the server's `nb` state flag has no GUI control |
| User-defined buttons (×14) | 7 per row, filling the full panel width across two rows with equal-weight grid columns; labels and types come from the server |
| RF user buttons (×11) | Shown left of the band-select column; labels and types come from the server; momentary or push-push, same as user-defined buttons |
| User-defined modulation buttons (×10) | Configurable via `--user_mod_1`…`--user_mod_10` / `--user_mod_type_1`…`--user_mod_type_10` (labels max 4 characters); labels and types in `user_mod_labels` / `user_mod_types` state fields |
| IQ wav / audio wav playback | `IQWavSource` (`--iq_wav`) feeds a real IQ wav file to the RF spectrum/waterfall; `AudioWavSource` (`--audio_wav`) replaces the demo sine tone with a real audio file |
| S-Meter | `SMeter` canvas, S1–S9 + S9 +20dB / S9 +40dB overload scale, digital dBm readout |
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
| TOML config | `cat_server.toml` / `cat_gui.toml` auto-created on first run; `--config PATH` overrides server/GUI config location; `--device-config PATH` overrides the default device config location |
| Antenna selector | Per-device antenna port list defined in `[antenna]` section of `cat_device.toml`; `get_antennas` returns the list, `select_antenna` picks one (1-based index); per-antenna band restrictions narrow the allowed-band set independently of the device-level restriction |
| Device profiles | `cat_server.toml`'s `[devices]` section lists up to 20 device profiles, each pointing to its own `cat_device.toml`-like config file; `get_devices` lists them, `select_device` switches the active one (reloads its user buttons, RF user buttons, user-mod buttons, sample-rate list, antenna ports, memories, and last-saved GUI state) |
| Device config | `cat_device.toml` (per device; auto-created on first run) — holds `[user_buttons]`, `[user_mods]`, `[rf_usr_btns]`, `[sdr]`, and `[antenna]`; `--device-config PATH` overrides the default device's config location |
| Sample-rate selection | `get_sample_rates` / `set_sample_rate` — query/change the active device's SDR sample rate from its configured `[sdr]` choice list |
| Frequency memories | 20 storable slots (label + frequency) per row (LO A, LO B, Tune), saved per device; `get_memories` / `save_memory` |
| Spectrum ref level / averaging | `set_spec_ref` (−50..10 dBm, 5 dBm steps) and `set_spec_ave` (1–10 averages), independently for the RF and AF boxes |
| Split | `set_split` toggles the `split` state flag |

Everything in the table above is driven live over TCP — nothing is static
or pre-rendered.

## 3. TCP protocol

Each message is one JSON object terminated by `\n`.

**Client → Server (commands):**

```json
{"cmd": "hello"}
{"cmd": "set_lo_a_freq",  "hz": 14195000}
{"cmd": "set_lo_b_freq",  "hz": 14195000}
{"cmd": "set_tune_freq",  "hz": 14205000}
{"cmd": "set_lo",         "lo": "A"}               # "A" or "B" — active LO
{"cmd": "set_mode",       "mode": "USB"}            # AM|FM|LSB|USB|CW
{"cmd": "set_filter",     "lo": 100, "hi": 2800}   # Hz offsets from carrier
{"cmd": "set_agc",        "mode": "Med"}            # Med|Off
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
{"cmd": "set_spec_ref",   "box": "rf", "value": -10}  # ref level, -50..10 dBm (5 dBm steps); box: rf|af
{"cmd": "set_spec_ave",   "box": "rf", "value": 4}    # FFT averaging count, 1..10; box: rf|af
{"cmd": "set_split",      "enabled": true}
{"cmd": "get_sample_rates"}                         # request active device's sample-rate choices
{"cmd": "set_sample_rate","value": 192000}          # must be one of the active device's configured rates
{"cmd": "get_devices"}                              # request the list of configured device profiles
{"cmd": "select_device",  "index": 1}               # switch active device profile (1-based)
{"cmd": "get_memories",   "position": "LO A"}       # position: "LO A"|"LO B"|"Tune"
{"cmd": "save_memory",    "position": "LO A", "index": 0, "label": "40M SSB", "freq": 7185000}
{"cmd": "get_antennas"}                             # request the antenna port list for the active device
{"cmd": "select_antenna", "index": 1}               # select antenna port by 1-based index (0 = deselect)
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "transport",      "action": "rec"}         # rec|play|pause|stop|ff|rw|infinite
{"cmd": "ui_button",      "name": "Bandwidth"}     # valid names: "Bandwidth" only (see note below)
{"cmd": "ui_toolbar"}                              # Waterfall/Spectrum toolbar button clicks (logged only)
{"cmd": "ui_display",     "box": "rf", "view": "waterfall"}  # box: rf|af  view: waterfall|spectrum
{"cmd": "ui_smeter_btn",  "name": "Peak"}          # Peak|S-units|Squelch
{"cmd": "user_button",    "index": 1}              # momentary press (normal type)
{"cmd": "user_button",    "index": 2, "enabled": true}  # push-push toggle state
{"cmd": "rf_usr_button",  "index": 1}              # RF user button, same semantics as user_button
{"cmd": "audio_hello",    "udp_port": 5010}        # GUI registers its RTP UDP port with the server
{"cmd": "user_text",     "index": 1, "text": "CQ CQ DE TEST"}  # write a text string to slot index (1-based)
```

> **Note:** `set_freq` is accepted as a legacy alias for `set_lo_a_freq`
> (both set LO A's frequency); current GUI builds always send
> `set_lo_a_freq`.

> **Note:** `memory` (a bare `{"cmd": "memory", "position": "LO A"}` with no
> `index`/`label`/`freq`) is accepted as a legacy/no-op alias kept for older
> GUI builds; current GUIs use `get_memories` / `save_memory` instead.

> **Note:** The **Soundcard** button opens a local audio device dialog and does
> **not** send a `ui_button` command to the server.

> **Note:** The only valid `ui_button` name currently sent by the GUI is
> `"Bandwidth"`. The **Device** and **Sample Rate** buttons use their own
> dedicated commands (`get_devices`/`select_device` and
> `get_sample_rates`/`set_sample_rate` respectively). The **Options** and
> **FreqMgr** buttons have been removed from the GUI and no longer exist.
> Third-party clients should treat any `ui_button` name other than
> `"Bandwidth"` as unsupported.

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

Reply to `hello` and `select_device` (full state included):
```json
{"resp": "ok", "state": {...current radio state...}}
```

Reply to all other commands (no state payload):
```json
{"resp": "ok"}
```

> **Note:** Only `hello` and `select_device` receive the full `state` dict in
> their reply. Every other command (e.g. `set_freq`, `set_mode`, `user_button`)
> gets a bare `{"resp": "ok"}`. The streaming `data` frames (below) keep all
> controls in sync during normal operation.

Sent in addition to `resp:ok` for `hello` and `select_device`, telling the GUI
to resync all widgets from the state dict in the preceding response:
```json
{"type": "reload_state"}
```

Reply to `get_devices`:
```json
{"type": "device_list", "devices": [{"index": 1, "label": "SDRplay RSP1A"}, ...]}
```

Reply to `get_sample_rates`:
```json
{"type": "sample_rate_list", "rates": [192000, 250000, 500000], "current": 192000}
```

Reply to `get_memories` and `save_memory`:
```json
{"type": "memory_list", "position": "LO A", "memories": [{"label": "40M SSB", "freq": 7185000.0}, ...]}
```
> `memories` always contains exactly 20 slots; unused slots have `label: ""` and `freq: 0.0`.

Reply to `get_antennas`:
```json
{
  "type": "antenna_list",
  "antennas": [{"index": 1, "label": "HF Port", "allowed_bands": ["160m", "40m", "20m"]}, ...],
  "current": 1,
  "device_allowed_bands": ["160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m"]
}
```
> Only antenna slots with non-empty labels are included. `current` is the
> 1-based index of the selected antenna (0 = none selected).
> `allowed_bands` per entry is the per-antenna band restriction (empty list =
> inherits the device-level `device_allowed_bands`).

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
  "smeter_dbm": -73.4,
  "smeter_text": "S9",
  "squelch_open": true,
  "state": {...current radio state...}
}
```

> **Legacy / unused fields (third-party clients may ignore these):**
> ```json
> "af_range": 3000.0,             # Hz width of the AF display (always 3000) — not used by the GUI
> "af_spectrum": [dBm, dBm, ...], # AF spectrum, 256 points — not used by the GUI
> ```
> The AF spectrum and waterfall are computed entirely on the client side by
> `RTPAudioClient._af_worker`, which runs a 512-point Hamming-windowed FFT
> on decoded RTP audio and posts the result as an `"af_local"` message to the
> GUI queue. This means the AF display always reflects the actual audio being
> received, independent of server-side processing. Third-party clients do not
> need to implement `af_spectrum` parsing.

The `state` dict included in `hello`/`select_device` responses and in every
streaming `data` push contains the full radio state: `lo_freq` and
`center_freq` (both present and always equal — both carry LO A's frequency;
`lo_freq` is the key the GUI uses internally), `lo_b_freq`,
`lo_active` (`"A"` or `"B"`), `tune_freq`,
`sample_rate`, `zoom`, `mode`, `filter_lo`, `filter_hi`, `agc` (`"Med"` or
`"Off"`), `agc_thresh`, `rf_gain`, `volume`, `squelch`, `nb`, `nr`, `nbrf`,
`nbif`, `afc`, `anf`, `notch`, `mute`, `ptt`, `split`, `running`,
`user_buttons`, `user_btn_state`, `rf_usr_btns`, `rf_usr_btn_state`,
`user_mod_labels`, `user_mod_types`, `spec_ref_rf`, `spec_ave_rf`,
`spec_ref_af`, `spec_ave_af`, `squelch_open` (boolean; `true` when the received signal exceeds the squelch threshold), `allowed_bands` (sorted list of band name
strings permitted by the active device), `antenna_labels` (list of 10
antenna port label strings; empty string = unused slot), `antenna_index`
(1-based index of the selected antenna port; 0 = none), and
`antenna_allowed_bands` (list of 10 sorted band-name lists, one per antenna
slot; empty list at index N means that antenna inherits the device-level
`allowed_bands` restriction).

> **Note:** `smeter_text` is a string in the format `"S1"` through `"S9"`,
> or `"S9 +NdB"` (e.g. `"S9 +20dB"`) for levels above S9. The `set_zoom` command
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
| `--config PATH` | Load TOML server config (transport + `[devices]` list) from PATH (default: `./cat_server.toml`, auto-created on first run) |
| `--device-config PATH` | Load TOML device config (the default/starting device profile's buttons + SDR settings) from PATH (default: `./cat_device.toml`, auto-created on first run) |
| `--audio-port PORT` | UDP port for the RTP audio channel (default: `5004`) |
| `--no-audio` | Disable the RTP/UDP audio channel entirely |
| `--iq_wav PATH` | Feed a real IQ wav file as the RF spectrum/waterfall source instead of the synthetic model |
| `--audio_wav PATH` | Replace the demo 440 Hz sine tone with a real audio wav file for RTP playback |
| `--user-button-label-N TEXT` | Label for user button N (1–14, max 7 characters); slots must be filled sequentially (1, 2, 3…, no gaps) |
| `--user-button-type-N TYPE` | Type of user button N: `normal` (momentary) or `push` (push-push/toggle) |
| `--user_mod_N TEXT` | Label for user-defined modulation button N (1–10, max 4 characters); slots must be filled sequentially |
| `--user_mod_type_N TYPE` | Type of user modulation button N: `normal` (acts like a standard mode button), `text` (splits the AF/audio box to show a read-only text panel), or `text_input` (same split with an editable RTTY-chat input box below). Requires `--user_mod_N` to also be set. |
| `--rf_usr_btn_N TEXT` | Label for RF user button N (1–11, max 7 characters), shown left of the band buttons; hidden when empty |
| `--rf_usr_btn_mode_N TYPE` | Mode of RF user button N: `normal` (momentary) or `push` (push-push/toggle). Requires `--rf_usr_btn_N` to also be set. |

> **Note:** The list of device profiles itself (labels + per-device config
> file paths) is configured only via `cat_server.toml`'s `[devices]`
> section (up to 20 entries) — there are no CLI flags for it.

### GUI command-line options

| Flag | Description |
| --- | --- |
| `--host HOST --port PORT` | Pre-fill and lock the server address (both required together); hides the host/port entry fields in the GUI. Equivalent to setting `host` and `port` in the `[connection]` section of `cat_gui.toml`. |
| `--config PATH` | Load TOML config from PATH (default: `./cat_gui.toml`, auto-created on first run) |
| `--bg dark\|light` | Colour theme (`dark` is default; `light` sets panel backgrounds to #FFECD6) |
| `--scale INT` | Initial HiDPI scale level, −5..+5 (default 0; factor is 1.25^level) |
| `--disable-scale` | Hide the +/− scale overlay. Requires `--scale` to also be passed **on the command line**; setting `scale` only via `cat_gui.toml` does not satisfy this requirement. |
| `--full-screen` | Start in full-screen mode |
| `--resolution WxH` | Set the initial window size in pixels (e.g. `1280x720`); ignored if `--full-screen` is also given |
| `--autoconnect` | Connect to the server automatically on startup; hides the entire host/port/connect row from the GUI. Can also be set via `[connection] autoconnect = true` in `cat_gui.toml`. |
| `--freq-font PATH` | TTF/OTF file for the LO/Tune frequency digit displays |
| `--gui-font PATH` | TTF/OTF file for all other GUI text |
| `--audio-list` | List all audio input/output devices with their index numbers, then exit |
| `--audio-mic INDEX` | Select the microphone device by index (must be paired with `--audio-speaker`) |
| `--audio-speaker INDEX` | Select the speaker/headphone device by index (must be paired with `--audio-mic`) |
| `--disable-soundcard-select` | Hide the Soundcard button in the GUI |
| `--aspect-ratio W:H` | Lock the window to a fixed aspect ratio (e.g. `16:9`). The window width is kept and the height is recalculated. Ignored when `--full-screen` is also set. |
| `--restrict-band` | Prevent setting LO A or LO B to a frequency outside the currently selected amateur band. Frequencies that fall outside all standard amateur bands are always blocked. |
| `--debug` | Enable verbose debug output, including printing persistent state values recovered from the server on startup or device change. |

In the GUI, click **Connect** (default host `127.0.0.1`, port `50101`),
then **Start** to begin streaming. From there:

- Scroll or click on the frequency digits (or double-click to type a
  frequency) to tune LO A, LO B, or Tune independently.
- Click the **LO A** or **LO B** label-button to switch which LO drives the
  RF waterfall/spectrum; the display recentres immediately.
- Click the band buttons (160m–6m) to QSY the currently active LO.
- Click anywhere on the RF spectrum to tune the active LO to that frequency.
- Drag the edges of the shaded filter overlay to change the passband.
- Use the server-configured **user-defined buttons** to change demodulation
  mode and trigger DSP-style functions (no fixed Mode or DSP-toggle button
  rows exist in the GUI; labels and behavior are defined on the server).
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
  (default 20.0 dB). The GUI has a partial implementation (`rfg_var`) that
  reads and displays the current value from the state on every update, but no
  control that sends `set_rf_gain`. RF gain can only be changed from external
  clients; the GUI would need a dedicated slider wired to `set_rf_gain` to
  expose full control.
- The `squelch` threshold is tracked by the server (default −130.0 dBm) and
  drives the `squelch_open` flag in every data frame. The GUI has a partial
  implementation (`sql_var`) that reads and displays the current squelch value
  from the state on every update, but no control that sends `set_squelch`. The
  "Squelch" button in the S-meter column sends a `ui_smeter_btn` notification
  only; it does not change the squelch level. A dedicated slider wired to
  `set_squelch` would be needed for full control.
- The RF spectrum is computed from whichever LO is currently active: LO A's
  frequency (`center_freq`) when `lo_active` is `"A"`, or LO B's frequency
  (`lo_b_freq`) when `lo_active` is `"B"`. Both the GUI recentring and the
  server's subsequent data frames track the active LO correctly.
- Menu system, band-mapping database, recording, DRM decoding, and
  OmniRig/CAT integration are not reproduced — this focuses on the
  core tuning/spectrum/waterfall/meter workflow described above.
- The server accepts multiple simultaneous connections, each served by a
  separate `ClientHandler` thread, but all threads share the same
  `RadioState` instance.
