# CAT Server ↔ Hamlib API Translation Map

> **Purpose:** Full mapping of every `cat_server.py` JSON protocol message to the
> equivalent Hamlib C API call, with all data transformations required for a
> translator layer. Cells marked **❌ Impossible** have no standard Hamlib
> counterpart. Cells marked **⚠️ Partial** require significant assumptions or
> lose fidelity. Cells marked **✅ Direct** translate with simple data conversion.
>
> **Hamlib references:** `rig_set_freq`, `rig_set_mode`, `rig_set_level`,
> `rig_set_func`, `rig_set_ptt`, `rig_set_split_vfo`, `rig_set_ant`,
> `rig_set_channel`, `rig_get_channel`, `rig_open`, `rig_close`.

---

## 1. Frequency Control

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_freq` / `set_lo_a_freq` | `hz: int` | `rig_set_freq(rig, RIG_VFO_A, freq)` | `freq = (freq_t) hz` — pass Hz directly | ✅ Direct |
| `set_tune_freq` | `hz: int` | `rig_set_freq(rig, RIG_VFO_B, freq)` | `freq = (freq_t) hz`; VFO B is the closest semantic match for a secondary/tune VFO | ✅ Direct |
| `set_lo_b_freq` | `hz: int` | `rig_set_freq(rig, RIG_VFO_B, freq)` | `freq = (freq_t) hz`; equivalent to setting VFO B | ✅ Direct |
| `set_lo` | `lo: "A"` \| `"B"` | `rig_set_vfo(rig, vfo)` | `"A"` → `RIG_VFO_A`, `"B"` → `RIG_VFO_B` | ✅ Direct |

---

## 2. Mode & Passband Filter

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_mode` | `mode: str` | `rig_set_mode(rig, RIG_VFO_CURR, mode, RIG_PASSBAND_NORMAL)` | String→enum: `"USB"`→`RIG_MODE_USB`, `"LSB"`→`RIG_MODE_LSB`, `"AM"`→`RIG_MODE_AM`, `"FM"`→`RIG_MODE_FM`, `"CW"`→`RIG_MODE_CW`, `"CWR"`→`RIG_MODE_CWR`, `"RTTY"`→`RIG_MODE_RTTY`, `"RTTYR"`→`RIG_MODE_RTTYR`, `"DSB"`→`RIG_MODE_DSB`, `"PKTUSB"`→`RIG_MODE_PKTUSB`. Unknown modes: pass `RIG_MODE_NONE` or ignore. | ✅ Direct |
| `set_filter` | `lo: int` (Hz offset), `hi: int` (Hz offset) | `rig_set_mode(rig, RIG_VFO_CURR, curr_mode, width)` | `width = abs(hi - lo)`. **Fidelity loss:** Hamlib encodes passband as a single width, not independent lo/hi offsets. The lower edge asymmetry (e.g. `lo=100, hi=2800` → 2700 Hz, centered differently than the carrier) is lost. Requires reading current mode first via `rig_get_mode`. | ⚠️ Partial |
| `set_selected_bw` | `value: str` (Hz as string) | `rig_set_mode(rig, RIG_VFO_CURR, curr_mode, width)` | `width = (pbwidth_t) int(value)`. Requires reading current mode first. Same asymmetry loss as `set_filter`. | ⚠️ Partial |

---

## 3. Gain & Level Controls

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_rf_gain` | `value: float` (dB, e.g. `20.0`) | `rig_set_level(rig, RIG_VFO_CURR, RIG_LEVEL_RF, val)` | Hamlib uses normalized `0.0–1.0`. Conversion depends on the rig's RF gain range; for a ±20 dB range: `val.f = (value + 20.0) / 40.0`. Must be clamped to `[0.0, 1.0]`. Range is rig-specific — query `rig->caps->level_gran[RIG_LEVEL_RF]`. | ⚠️ Partial |
| `set_volume` | `value: float` (0–100%) | `rig_set_level(rig, RIG_VFO_CURR, RIG_LEVEL_AF, val)` | `val.f = value / 100.0`. Hamlib uses `0.0–1.0`. | ✅ Direct |
| `set_squelch` | `value: float` (dBm, e.g. `−130.0`) | `rig_set_level(rig, RIG_VFO_CURR, RIG_LEVEL_SQL, val)` | Hamlib uses `0.0–1.0`; real rig squelch range is rig-specific and not in dBm. A generic mapping: `val.f = clamp((value + 130.0) / 80.0, 0.0, 1.0)` (assumes −130 dBm = 0, −50 dBm = 1). Actual calibration requires rig manufacturer data. | ⚠️ Partial |

---

## 4. AGC

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_agc` | `mode: str` (`"off"`, `"slow"`, `"Med"`, `"fast"`, `"auto"`) | `rig_set_level(rig, RIG_VFO_CURR, RIG_LEVEL_AGC, val)` | `val.i` enum: `"off"`→`RIG_AGC_OFF(0)`, `"slow"`→`RIG_AGC_SLOW(1)`, `"Med"`/`"medium"`→`RIG_AGC_MEDIUM(2)`, `"fast"`→`RIG_AGC_FAST(3)`, `"auto"`→`RIG_AGC_AUTO(5)`. | ✅ Direct |
| `set_agc_thresh` | `value: float` (dBm, e.g. `−100.0`) | *(none)* | Hamlib has no standard AGC threshold parameter in dBm. `RIG_LEVEL_AGC` is an enum, not a dBm threshold. Some rigs expose a custom `RIG_LEVEL_AGC_TIME` (decay time constant) but this is not equivalent. | ❌ Impossible |

---

## 5. DSP / Signal Processing Functions

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_nb` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_NB, status)` | `status = (int) enabled` (1 = on, 0 = off). Maps to the single generic NB function. | ✅ Direct |
| `set_nr` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_NR, status)` | `status = (int) enabled`. NR level (depth) is a separate `rig_set_level(…RIG_LEVEL_NR…)` call not exposed in this protocol. | ✅ Direct |
| `set_nbrf` | `enabled: bool` | *(none)* | Hamlib defines only a single `RIG_FUNC_NB`. RF-domain vs IF-domain NB distinction is not present in the Hamlib API. Cannot be translated without a rig-specific custom extension. | ❌ Impossible |
| `set_nbif` | `enabled: bool` | *(none)* | Same reason as `set_nbrf`. Hamlib has no IF-specific NB function. | ❌ Impossible |
| `set_afc` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_AFC, status)` | `status = (int) enabled`. | ✅ Direct |
| `set_anf` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_ANF, status)` | `status = (int) enabled`. | ✅ Direct |
| `set_notch` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_NOTCH, status)` | `status = (int) enabled`. Notch frequency is a separate `rig_set_level(…RIG_LEVEL_NOTCHF…)` call not modelled in this protocol. | ✅ Direct |
| `set_mute` | `enabled: bool` | `rig_set_func(rig, RIG_VFO_CURR, RIG_FUNC_MUTE, status)` | `status = (int) enabled`. | ✅ Direct |

---

## 6. TX Control

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `set_ptt` | `enabled: bool` | `rig_set_ptt(rig, RIG_VFO_CURR, ptt)` | `enabled=true` → `RIG_PTT_ON`, `enabled=false` → `RIG_PTT_OFF`. Choose `RIG_PTT_ON_MIC`, `RIG_PTT_ON_DATA` for specific TX sources if needed. | ✅ Direct |
| `set_split` | `enabled: bool` | `rig_set_split_vfo(rig, RIG_VFO_A, split, RIG_VFO_B)` | `enabled=true` → `RIG_SPLIT_ON`, `enabled=false` → `RIG_SPLIT_OFF`. TX VFO fixed to `RIG_VFO_B` (matches server's LO B as TX frequency). | ✅ Direct |

---

## 7. TX Power

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `get_power_levels` | *(none)* | *(none)* | Server returns an app-level list of watt values defined in TOML `[sdr].power_levels`. Hamlib has no concept of a "list of power steps" — it exposes a continuous `RIG_LEVEL_RFPOWER` range. The list must be built from rig capabilities (`rig->caps->level_gran[RIG_LEVEL_RFPOWER]`). | ❌ Impossible |
| `set_power` | `index: int` (0-based into `power_levels` list) | `rig_set_level(rig, RIG_VFO_CURR, RIG_LEVEL_RFPOWER, val)` | Map index to watt value: `watts = power_levels[index]`. Normalize: `val.f = watts / max_power_watts` where `max_power_watts` comes from `rig->caps->level_gran[RIG_LEVEL_RFPOWER].max.f` converted via `rig_power2mW / 1000`. | ⚠️ Partial |

---

## 8. Antenna Selection

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `get_antennas` | *(none)* | `rig_get_ant(rig, RIG_VFO_CURR, RIG_ANT_CURR, &option, &curr_ant, &tx_ant, &rx_ant)` | Server returns a labelled list with per-antenna band restrictions from TOML. Hamlib returns only the selected antenna index bitmask; no label or band restriction metadata exists in the API. The list must be built from static rig capability data. | ⚠️ Partial |
| `select_antenna` | `index: int` (1-based) | `rig_set_ant(rig, RIG_VFO_CURR, ant, option)` | `ant = (ant_t)(1 << (index - 1))` (Hamlib uses bitmask: ANT_1=1, ANT_2=2, ANT_3=4, …). `option.i = 0`. | ✅ Direct |

---

## 9. SDR-Specific Controls

> These commands are SDR/software-radio specific and have **no equivalent** in the Hamlib API,
> which models traditional hardware transceivers.

| GUI→Server Command | JSON Fields | Hamlib API Call | Notes | Status |
|---|---|---|---|---|
| `get_sample_rates` | *(none)* | *(none)* | Sample rate is an SDR hardware parameter. Hamlib has no concept of IF/ADC sample rates. | ❌ Impossible |
| `set_sample_rate` | `value: int` (Hz) | *(none)* | Same as above. The closest analog is IF bandwidth (`RIG_LEVEL_IF`) but that is not the ADC sample rate. | ❌ Impossible |
| `set_zoom` | `value: int` (1–N) | *(none)* | Spectrum display zoom factor. Pure GUI/display concept; no RF parameter. | ❌ Impossible |
| `set_spec_ref` | `box: "rf"\|"af"`, `value: float` (dBm) | *(none)* | Spectrum display reference level. Display-only setting. | ❌ Impossible |
| `set_spec_ave` | `box: "rf"\|"af"`, `value: int` (1–10) | *(none)* | FFT averaging count. Display-only setting. | ❌ Impossible |

---

## 10. Session / Lifecycle Control

| GUI→Server Command | JSON Fields | Hamlib API Call | Notes | Status |
|---|---|---|---|---|
| `hello` | *(none)* | *(none)* | Protocol-level handshake; server replies with full state. No Hamlib equivalent. The translator would synthesise this by calling `rig_get_freq`, `rig_get_mode`, `rig_get_level` (multiple), etc. to build an initial state snapshot. | ❌ Impossible |
| `start` | *(none)* | `rig_open(rig)` | Semantically different: `rig_open` initialises the hardware connection once; `start` means "begin SDR streaming/spectrum updates". The translator can use `rig_open` on first `start`, but periodic streaming must be implemented separately (polling loop). | ⚠️ Partial |
| `stop` | *(none)* | `rig_close(rig)` | Same caveat as `start`. `rig_close` tears down the hardware link entirely; `stop` only pauses SDR streaming. Do not call `rig_close` if the session should remain alive. | ⚠️ Partial |

---

## 11. Device Profile Management

> Device profiles are a higher-level management concept above individual rig control.
> Hamlib models a single rig instance and has no multi-profile concept.

| GUI→Server Command | JSON Fields | Hamlib API Call | Notes | Status |
|---|---|---|---|---|
| `get_devices` | *(none)* | *(none)* | Returns the list of TOML-configured device profiles. Hamlib does not have a device-list concept; it opens one rig model at a time via `rig_init(rig_model)`. | ❌ Impossible |
| `select_device` | `index: int` | *(none)* | Reloads buttons, sample rates, allowed bands, and memories for the chosen device profile. Would require closing the current `rig` instance and calling `rig_init` + `rig_open` with a new model, which is destructive and not a standard runtime operation. | ❌ Impossible |

---

## 12. Frequency Memories

| GUI→Server Command | JSON Fields | Hamlib API Call | Data Transformation | Status |
|---|---|---|---|---|
| `get_memories` | `position: "LO A"\|"LO B"\|"Tune"` | `rig_get_channel(rig, RIG_VFO_CURR, &ch, read_only=1)` | Server has 3 banks × 20 slots. Map to Hamlib channel numbers: `ch.channel_num = bank_offset + index` where `bank_offset` is e.g. `LO A`→0, `LO B`→20, `Tune`→40. Must call `rig_get_channel` 20 times per bank. Only `freq` and `channel_desc` (label) fields survive the mapping; server stores only freq+label per slot. | ⚠️ Partial |
| `save_memory` | `position`, `index: int`, `label: str`, `freq: int` | `rig_set_channel(rig, RIG_VFO_CURR, &ch)` | Populate `channel_t`: `ch.channel_num = bank_offset + index`, `ch.freq = (freq_t) freq`, `strncpy(ch.channel_desc, label, …)`. Mode and width fields in `channel_t` must be filled from current rig state or left at defaults. | ⚠️ Partial |
| `memory` (legacy) | `position: str` | *(treat as `get_memories`)* | Legacy no-op in current server; accept and ignore, or map same as `get_memories`. | ⚠️ Partial |

---

## 13. User-Defined Buttons

> These are application-level macro buttons with no transceiver radio function.

| GUI→Server Command | JSON Fields | Hamlib API Call | Notes | Status |
|---|---|---|---|---|
| `user_button` | `index: int`, `enabled: bool` (push type), `choice: int` (list type) | *(none)* | User-defined macro buttons. The server application decides what they do. No Hamlib call exists; the translator must maintain a user-configurable mapping table (e.g. button N → `rig_set_level(…)` or `rig_vfo_op(…)`). | ❌ Impossible |
| `rf_usr_button` | `index: int`, `enabled: bool` (push type) | *(none)* | Same as `user_button` — RF-area variant. Application-defined action; no standard Hamlib binding. | ❌ Impossible |
| `rf_usr_btn_config_set` | `index: int`, `values: dict` | *(none)* | Stores per-button configuration dialog values (slide/list/check/radio widgets). Pure application state; no Hamlib equivalent. | ❌ Impossible |

---

## 14. Text / Chat Modes (User Mod Buttons)

| GUI→Server Command | JSON Fields | Hamlib API Call | Notes | Status |
|---|---|---|---|---|
| `user_text` | `index: int`, `text: str` | *(none)* | Text sent from a `text_input` mode panel (RTTY-like chat). No Hamlib concept. A real implementation would feed this into a TNC or digital mode engine, not Hamlib. | ❌ Impossible |

---

## 15. Pure UI Events (No Radio State)

> These commands carry no radio-control information and exist only to drive the GUI.

| GUI→Server Command | JSON Fields | Notes | Status |
|---|---|---|---|
| `ui_button` | `name: str` | GUI actions: Full Screen, Minimize, Exit, Device dialog, FreqMgr, etc. No Hamlib binding. | ❌ Impossible |
| `ui_toolbar` | *(varies)* | Waterfall/Spectrum toolbar button clicks. Display-only. | ❌ Impossible |
| `ui_display` | `box: str`, `view: str` | Toggle waterfall vs spectrum view. Display-only. | ❌ Impossible |
| `ui_smeter_btn` | *(varies)* | S-meter Peak/S-units/Squelch mode clicks. Display-only. | ❌ Impossible |
| `transport` | `action: str` | Record/Play/Pause/Stop transport bar. Recording application concept; no Hamlib equivalent. | ❌ Impossible |

---

## 16. Server → GUI Push Messages (Responses & Async)

These messages flow from the **server to the GUI**. The translator would need to
*generate* them by polling Hamlib.

| Server Push Message | Key Fields | Hamlib Source | Data Transformation | Status |
|---|---|---|---|---|
| `{"resp": "ok", "state": {...}}` | Full radio state dict | Multiple `rig_get_*` calls | Assemble state by polling: `rig_get_freq` (VFO A/B), `rig_get_mode`, `rig_get_level` (RF, AF, SQL, AGC), `rig_get_func` (NB, NR, ANF, NOTCH, AFC, MUTE), `rig_get_ptt`, `rig_get_split_vfo`, `rig_get_ant`. Many state keys (buttons, zoom, spec_ref, etc.) are app-local and must be maintained in the translator. | ⚠️ Partial |
| `{"type": "data", ...}` | `spectrum`, `af_spectrum`, `smeter_dbm`, `smeter_text`, `squelch_open`, `swr` | `rig_get_level(…RIG_LEVEL_STRENGTH…)` for S-meter only | **Spectrum arrays have no Hamlib equivalent.** `smeter_dbm` ≈ `rig_get_level(…RIG_LEVEL_STRENGTH…)` (returns S-unit value in dB relative to S9, needs offset); `squelch_open` must be derived from signal vs SQL threshold. SWR: `rig_get_level(…RIG_LEVEL_SWR…)`. | ⚠️ Partial |
| `{"type": "reload_state"}` | *(none)* | N/A | Signals the GUI to resync all widgets. Translator emits this after `hello` or `select_device`. No Hamlib source needed — translator-generated. | ✅ Direct |
| `{"type": "memory_list", ...}` | `position`, `memories` | `rig_get_channel` × 20 per bank | See §12. Channel label and freq can be recovered; mode is extra data. | ⚠️ Partial |
| `{"type": "sample_rate_list", ...}` | `rates`, `current` | *(none)* | SDR-only concept. Cannot be sourced from Hamlib. | ❌ Impossible |
| `{"type": "antenna_list", ...}` | `antennas`, `current`, `device_allowed_bands` | `rig_get_ant` | Hamlib returns selected antenna bitmask only. Labels and band restrictions must come from static config. | ⚠️ Partial |
| `{"type": "power_level_list", ...}` | `levels`, `current` | *(none)* | Hamlib exposes a continuous power range, not a discrete step list. | ❌ Impossible |
| `{"type": "device_list", ...}` | `devices` | *(none)* | Multi-profile device list is application-level only. | ❌ Impossible |
| `{"type": "user_text", ...}` | `index`, `text` | *(none)* | Application-level text/RTTY chat. No Hamlib source. | ❌ Impossible |

---

## Summary

| Category | Total Commands | ✅ Direct | ⚠️ Partial | ❌ Impossible |
|---|---|---|---|---|
| Frequency control | 4 | 4 | 0 | 0 |
| Mode & filter | 3 | 1 | 2 | 0 |
| Gain & levels | 3 | 1 | 2 | 0 |
| AGC | 2 | 1 | 0 | 1 |
| DSP functions | 8 | 6 | 0 | 2 (`set_nbrf`, `set_nbif`) |
| TX control | 2 | 2 | 0 | 0 |
| TX power | 2 | 0 | 1 | 1 |
| Antenna | 2 | 1 | 1 | 0 |
| SDR-specific | 5 | 0 | 0 | 5 |
| Session / lifecycle | 3 | 0 | 2 | 1 |
| Device management | 2 | 0 | 0 | 2 |
| Memories | 3 | 0 | 3 | 0 |
| User buttons | 3 | 0 | 0 | 3 |
| Text / chat | 1 | 0 | 0 | 1 |
| Pure UI events | 5 | 0 | 0 | 5 |
| Server→GUI push | 9 | 1 | 4 | 4 |
| **Total** | **57** | **17 (30%)** | **15 (26%)** | **25 (44%)** |

---

## Key Design Notes for the Translator

1. **Hamlib level normalization.** `RIG_LEVEL_RF`, `RIG_LEVEL_AF`, `RIG_LEVEL_SQL`,
   and `RIG_LEVEL_RFPOWER` all use a `0.0–1.0` float. The server uses physical
   units (dB, %, dBm, watts). A rig-specific calibration table is required for
   squelch and RF gain; AF volume is a clean `/100.0` conversion.

2. **Filter passband asymmetry.** Hamlib `rig_set_mode` accepts a single `width`
   (in Hz). The server's `set_filter` passes independent `lo` / `hi` offsets from
   carrier (e.g. `lo=100, hi=2800`). The translator can only send `width = hi - lo`
   (2700 Hz here), losing the 100 Hz low-frequency cutoff asymmetry.

3. **AGC threshold.** `set_agc_thresh` (a dBm float) has no Hamlib mapping.
   If the target rig supports a vendor-specific Hamlib extension level, it must be
   handled as a rig-model-specific special case.

4. **RF vs IF noise blanker.** `set_nbrf` and `set_nbif` distinguish two NB domains
   that Hamlib collapses into one `RIG_FUNC_NB`. A possible workaround: map one to
   `RIG_FUNC_NB` and the other to `RIG_FUNC_NB2` if supported by the rig model.

5. **Spectrum data.** The 600-bin RF spectrum and 256-bin AF spectrum arrays in the
   `data` push message have **no Hamlib source**. Hamlib is a CAT control library, not
   a DSP/panadapter API. Real spectrum data requires a separate SDR pipeline
   (e.g. SoapySDR, rtl-sdr, librtlsdr).

6. **Memory bank layout.** The server uses 3 named banks (`LO A`, `LO B`, `Tune`)
   × 20 slots. Hamlib channel numbers are rig-specific. A recommended convention:
   `LO A` → channels 0–19, `LO B` → 20–39, `Tune` → 40–59. Verify the target
   rig's memory count via `rig->caps->chan_list`.

7. **Device profiles.** `select_device` / `get_devices` are entirely above the
   Hamlib abstraction layer. The translator must implement its own profile manager
   that calls `rig_cleanup` + `rig_init(new_model)` + `rig_open` on device switch,
   which is a reconnect, not a soft switch.

8. **`hello` resync.** On `hello`, the translator must poll all relevant Hamlib
   getters to build a synthetic `state` dict and send `reload_state`. This requires
   sequential calls to `rig_get_freq`, `rig_get_mode`, `rig_get_level` (×6),
   `rig_get_func` (×8), `rig_get_ptt`, `rig_get_split_vfo`, and `rig_get_ant`.
