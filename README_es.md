# Interfaz CAT GUI

<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="screenshot">
  </a>
</div>

Este proyecto es una **Interfaz CAT GUI** en Python/Tkinter — un frontend de
SDR cuyos controles están conectados a un pequeño backend de radio a través
de un simple socket TCP.

Consta de dos archivos:

- `cat_server.py` — un servidor TCP que actúa como la capa de
  hardware/backend. Posee todo el "estado de la radio", transmite un
  entorno de RF simulado y gestiona un canal de audio RTP/UDP bidireccional.
- `cat_gui.py` — un cliente Tkinter que proporciona la ventana principal de
  la Interfaz CAT GUI y envía cada interacción del usuario al servidor,
  redibujando a partir de los datos que el servidor retransmite. También
  reproduce el audio RTP recibido y envía audio del micrófono durante el PTT.

---

## 1. Descripción general de la interfaz

La Interfaz CAT GUI es una aplicación Python/Tkinter para el control de
Radio Definida por Software (SDR). Puntos clave:

- **Sin acceso directo al hardware.** La GUI se comunica con su backend a
  través de `cat_server.py`, que abstrae cualquier dispositivo SDR
  específico y expone una API TCP común para establecer frecuencia, tasa de
  muestreo, ganancia y para iniciar/detener el flujo I/Q.
- **El diseño de la ventana principal** se centra en:
  - Grandes pantallas de frecuencia de 9 dígitos estilo LCD ámbar para
    **LO A**, **LO B** y **Tune**, cada una sintonizable desplazando el
    cursor o haciendo clic en dígitos individuales, o haciendo doble clic
    para escribir una frecuencia. LO A y LO B son seleccionables; el LO
    activo determina la frecuencia central de la cascada/espectro de RF.
  - Una pantalla de espectro de RF (FFT) y una cascada de RF encima de
    esta, centradas en la frecuencia del LO activo y abarcando la tasa de
    muestreo del receptor (más estrecha si está "ampliada").
  - Una superposición de paso de banda de FI/filtro arrastrable, dibujada
    directamente sobre el espectro, cuyos bordes establecen el ancho de
    banda del demodulador.
  - No hay filas fijas de botones de Modo o de conmutación de DSP — la
    selección de modo y las conmutaciones de DSP se implementan
    completamente a través de los bancos de botones genéricos definidos por
    el servidor que se describen más abajo; la GUI no contiene valores
    predeterminados por modo (p. ej., el paso de banda del filtro).
  - Hasta 14 **botones definidos por el usuario** (7 por fila, ocupando
    todo el ancho del panel en dos filas con columnas de cuadrícula de
    peso igual — no alineados a la derecha), cuyas etiquetas y tipos
    (momentáneo o push-push/conmutador) se configuran del lado del
    servidor.
  - Hasta 11 **botones de usuario de RF**, mostrados a la izquierda de la
    columna de selección de banda, con el mismo comportamiento
    momentáneo/push-push que los botones definidos por el usuario
    anteriores; configurados del lado del servidor.
  - Un S-Meter que muestra la intensidad de la señal en unidades S
    (S1–S9, S9+20 dB, S9+40 dB) y una lectura digital en dBm, derivada de
    la potencia dentro del paso de banda del filtro actual.
  - Deslizadores de **Volumen** y **Umbral de AGC** en el panel de
    control.
  - Control de zoom (rueda del ratón sobre el espectro, o etiquetas de la
    barra de herramientas) para el espectro y la cascada de RF.
  - Un panel más pequeño de espectro + cascada de AF (audio) que muestra
    el paso de banda de audio demodulado.
  - Una columna de **selección rápida de banda** (160m, 80m, 60m, 40m,
    30m, 20m, 17m, 15m, 12m, 10m, 6m) que sintoniza el LO actualmente
    activo.
  - Botones de la **barra de transporte**: Grabar (●), Reproducir (▶),
    Pausa (⏸), Detener (■), Rebobinar (◀◀), Avance rápido (▶▶) y Bucle (∞).
  - Control de **Inicio/Detener** sobre el flujo del receptor.
  - Botones auxiliares del S-meter: **Pico**, **Unidades S**, **Squelch**.
  - Botones de función: **Dispositivo**, **Tarjeta de sonido**, **Ancho de
    banda**, **Tasa de muestreo**. Nota: **Tarjeta de sonido** abre un
    cuadro de diálogo local de selección de dispositivo de audio y **no**
    envía ningún comando al servidor.
  - **Selector de dispositivo.** El servidor puede contener varios
    perfiles de dispositivo (cada uno con sus propios botones de usuario,
    botones de usuario de RF, botones user-mod y lista de tasas de
    muestreo). `get_devices`/`select_device` permiten que la GUI los liste
    y cambie entre ellos; cambiar de dispositivo recarga los botones y
    tasas de muestreo de ese dispositivo y restaura su último estado de
    GUI guardado.
  - **Selector de tasa de muestreo.** `get_sample_rates`/`set_sample_rate`
    permiten que la GUI consulte y cambie la tasa de muestreo SDR del
    dispositivo activo a partir de su lista configurada de opciones.
  - **Memorias de frecuencia.** Cada uno de LO A, LO B y Tune tiene 20
    espacios de memoria almacenables (etiqueta + frecuencia), guardados
    por dispositivo mediante `get_memories`/`save_memory`.
  - **Nivel de referencia / promediado del espectro.** `set_spec_ref` y
    `set_spec_ave` controlan de forma independiente el nivel de
    referencia (límite superior de la escala) y el conteo de promediado
    de FFT de las pantallas de espectro de RF y AF.
  - El modo **Split** se alterna mediante `set_split` y se mantiene en el
    estado de la radio.
  - Un **reloj de fecha/hora** en vivo y un botón TCP de
    **Conectar/Desconectar** con un punto indicador de estado coloreado.
  - Dos franjas de barra de herramientas (una entre la cascada de RF y el
    panel de control, otra en el panel de AF), cada una con botones de
    conmutación **Cascada** / **Espectro**, lectura de RBW, y etiquetas de
    Promedio, Zoom y Velocidad.
  - Una superposición persistente de **HiDPI +/−** en la esquina inferior
    derecha para escalado en tiempo real desde el nivel −5 hasta +5
    (factor 1,25 por paso).
  - Un botón circular **PTT** (en la fila del S-meter) que alterna el modo
    de transmisión; mientras el PTT está activo, la GUI envía el audio del
    micrófono al servidor vía RTP/UDP y deja de reproducir el audio
    recibido.
- **Canal de audio RTP/UDP.** Además de la conexión de control TCP, el
  servidor abre un puerto UDP (5004 por defecto) para audio G.711 µ-law
  (PCMU) bidireccional. Mientras el PTT está apagado, el servidor transmite
  un tono sinusoidal de demostración a la GUI para su reproducción;
  mientras el PTT está encendido, la GUI captura el audio del micrófono y
  lo transmite al servidor. La reproducción y captura de audio usan
  PyAudio (opcional; la GUI funciona sin él, pero el audio queda
  silenciosamente deshabilitado).
- **Archivos de configuración TOML.** `cat_gui.py` crea automáticamente un
  único `cat_gui.toml` en el directorio actual la primera vez que se
  ejecuta y lo usa como fuente persistente de valores predeterminados.
  `cat_server.py` usa **dos** archivos TOML: `cat_server.toml`
  (configuración de transporte más la lista `[devices]` de perfiles de
  dispositivo seleccionables) y un archivo de estilo `cat_device.toml` por
  cada perfil de dispositivo (los botones de usuario, botones de usuario
  de RF, botones user-mod y tasas de muestreo SDR de ese dispositivo).
  Tanto `cat_server.toml` como el `cat_device.toml` del dispositivo
  predeterminado se crean automáticamente la primera vez que se ejecuta si
  no existen. Cada dispositivo también obtiene su propio archivo de
  memoria y archivo de estado de GUI creados automáticamente. Los
  indicadores de línea de comandos (CLI) siempre tienen prioridad sobre
  los valores del archivo de configuración.
- **Protocolo de control TCP personalizado.** La Interfaz CAT GUI define
  su propio protocolo simple basado en JSON delimitado por saltos de línea
  entre `cat_gui.py` y `cat_server.py` (descrito más abajo).

## 2. Mapa de funciones

| Función de la CAT GUI | Implementación |
| --- | --- |
| Backend | `cat_server.py` — posee todo el estado de la radio, genera un espectro de RF simulado |
| Pantallas de dígitos del VFO (LO A, LO B, Tune) | `FreqDisp` — desplazar/hacer clic en cada dígito, doble clic para escribir una frecuencia; hacer clic en la etiqueta LO A o LO B cambia el LO activo y recentra inmediatamente la cascada |
| Espectro de RF + superposición de filtro | `SpecCanvas` — bordes de paso de banda arrastrables, clic para sintonizar, desplazamiento para hacer zoom |
| Cascada de RF | `WFCanvas` (resolución de renderizado interno de 900 bins; el servidor transmite 600 puntos) |
| Espectro + cascada de AF | segundo par `SpecCanvas` / `WFCanvas`, banda base 0..3000 Hz; calculado localmente por `RTPAudioClient._af_worker` a partir del audio RTP decodificado (FFT de 512 puntos, ventana Hamming con 50% de solapamiento) — no se transmite desde el servidor |
| Selección de modo | No hay una fila fija de botones de modo; se realiza mediante los botones de modulación definidos por el usuario (ver más abajo). La GUI no tiene un paso de banda predeterminado por modo |
| Conmutaciones DSP (NR / NB RF / NB IF / AFC / Mute / AGC Med / Notch / ANotch) | No hay una fila fija de conmutación DSP — eliminada de la GUI. Estas funciones, si se exponen, se implementan mediante los botones genéricos definidos por el usuario que se describen más abajo. No existe un botón NB independiente; el indicador de estado `nb` del servidor no tiene control en la GUI |
| Botones definidos por el usuario (×14) | 7 por fila, ocupando todo el ancho del panel en dos filas con columnas de cuadrícula de peso igual; las etiquetas y tipos provienen del servidor |
| Botones de usuario de RF (×11) | Mostrados a la izquierda de la columna de selección de banda; las etiquetas y tipos provienen del servidor; momentáneo o push-push, igual que los botones definidos por el usuario |
| Botones de modulación definidos por el usuario (×10) | Configurables mediante `--user_mod_1`…`--user_mod_10` / `--user_mod_type_1`…`--user_mod_type_10` (etiquetas de máximo 4 caracteres); las etiquetas y tipos están en los campos de estado `user_mod_labels` / `user_mod_types` |
| Reproducción de IQ wav / audio wav | `IQWavSource` (`--iq_wav`) alimenta un archivo IQ wav real al espectro/cascada de RF; `AudioWavSource` (`--audio_wav`) reemplaza el tono sinusoidal de demostración por un archivo de audio real |
| S-Meter | Lienzo `SMeter`, escala S1–S9 + sobrecarga S9+20 dB / S9+40 dB, lectura digital en dBm |
| Volumen / Umbral de AGC | Deslizadores en el panel de control izquierdo |
| Zoom / span | Rueda del ratón sobre el lienzo de espectro de RF |
| Selección rápida de banda | Columna de botones de banda (160m–6m) junto a las pantallas de frecuencia |
| Barra de transporte | Botones ● ▶ ⏸ ■ ◀◀ ▶▶ ∞, cada uno envía un comando `transport` |
| Inicio/Detener | Botón Inicio/Detener, controla la transmisión del servidor |
| PTT | Botón circular de lienzo en la fila del S-meter; envía el comando `set_ptt` y conmuta el canal de audio RTP entre RX y TX |
| Audio RTP/UDP | `RTPAudioClient` (GUI) / `UDPAudioChannel` (servidor) — audio G.711 µ-law bidireccional en un puerto UDP; requiere PyAudio |
| Diálogo de tarjeta de sonido | Cuadro de diálogo local de selección de dispositivo de audio (micrófono y altavoz de forma independiente); abierto por el botón Tarjeta de sonido, **no** envía un comando `ui_button` al servidor |
| Escalado HiDPI | Superposición persistente −/+; niveles de escala −5..+5 (×1,25 por paso) |
| Pantalla completa | Indicador `--full-screen`; triple-Esc (3 pulsaciones en 1 s) alterna la pantalla completa |
| Tema | `--bg dark` (predeterminado) o `--bg light` (fondos #FFECD6) |
| Configuración TOML | `cat_server.toml` / `cat_gui.toml` creados automáticamente en la primera ejecución; `--config PATH` anula la ubicación |
| Perfiles de dispositivo | La sección `[devices]` de `cat_server.toml` enumera hasta 20 perfiles de dispositivo, cada uno apuntando a su propio archivo de configuración estilo `cat_device.toml`; `get_devices` los lista, `select_device` cambia el activo (recarga sus botones de usuario, botones de usuario de RF, botones user-mod, lista de tasas de muestreo, memorias y el último estado de GUI guardado) |
| Configuración de dispositivo | `cat_device.toml` (por dispositivo; creado automáticamente en la primera ejecución) — contiene `[user_buttons]`, `[user_mods]`, `[rf_usr_btns]` y `[sdr]`; `--device-config PATH` anula la ubicación de configuración del dispositivo predeterminado |
| Selección de tasa de muestreo | `get_sample_rates` / `set_sample_rate` — consulta/cambia la tasa de muestreo SDR del dispositivo activo a partir de su lista de opciones configurada en `[sdr]` |
| Memorias de frecuencia | 20 espacios almacenables (etiqueta + frecuencia) por fila (LO A, LO B, Tune), guardados por dispositivo; `get_memories` / `save_memory` |
| Nivel de referencia / promediado del espectro | `set_spec_ref` (−50..10 dBm, pasos de 5 dBm) y `set_spec_ave` (1–10 promedios), de forma independiente para los paneles de RF y AF |
| Split | `set_split` alterna el indicador de estado `split` |

Todo lo que aparece en la tabla anterior se controla en vivo por TCP —
nada es estático ni está pre-renderizado.

## 3. Protocolo TCP

Cada mensaje es un objeto JSON terminado en `\n`.

**Cliente → Servidor (comandos):**

```json
{"cmd": "hello"}
{"cmd": "set_lo_a_freq",  "hz": 14195000}
{"cmd": "set_lo_b_freq",  "hz": 14195000}
{"cmd": "set_tune_freq",  "hz": 14205000}
{"cmd": "set_lo",         "lo": "A"}               # "A" o "B" — LO activo
{"cmd": "set_mode",       "mode": "USB"}            # AM|FM|LSB|USB|CW
{"cmd": "set_filter",     "lo": 100, "hi": 2800}   # desplazamientos en Hz respecto a la portadora
{"cmd": "set_agc",        "mode": "Med"}            # Off|Med
{"cmd": "set_agc_thresh", "value": -100.0}          # dBm
{"cmd": "set_rf_gain",    "value": 20}              # 0..40 dB
{"cmd": "set_volume",     "value": 80}              # 0..100
{"cmd": "set_squelch",    "value": -130}            # umbral en dBm
{"cmd": "set_nb",         "enabled": true}          # indicador NB independiente (sin botón en la GUI; solo del lado del servidor)
{"cmd": "set_nr",         "enabled": true}
{"cmd": "set_nbrf",       "enabled": true}
{"cmd": "set_nbif",       "enabled": true}
{"cmd": "set_afc",        "enabled": true}
{"cmd": "set_anf",        "enabled": true}
{"cmd": "set_notch",      "enabled": true}
{"cmd": "set_mute",       "enabled": true}
{"cmd": "set_ptt",        "enabled": true, "udp_port": 5010}  # udp_port = puerto UDP RTP de la GUI
{"cmd": "set_zoom",       "value": 2}              # 1..32
{"cmd": "set_spec_ref",   "box": "rf", "value": -10}  # nivel de referencia, -50..10 dBm (pasos de 5 dBm); box: rf|af
{"cmd": "set_spec_ave",   "box": "rf", "value": 4}    # conteo de promediado FFT, 1..10; box: rf|af
{"cmd": "set_split",      "enabled": true}
{"cmd": "get_sample_rates"}                         # solicita las opciones de tasa de muestreo del dispositivo activo
{"cmd": "set_sample_rate","value": 192000}          # debe ser una de las tasas configuradas del dispositivo activo
{"cmd": "get_devices"}                              # solicita la lista de perfiles de dispositivo configurados
{"cmd": "select_device",  "index": 1}               # cambia el perfil de dispositivo activo (base 1)
{"cmd": "get_memories",   "position": "LO A"}       # position: "LO A"|"LO B"|"Tune"
{"cmd": "save_memory",    "position": "LO A", "index": 0, "label": "40M SSB", "freq": 7185000}
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "transport",      "action": "rec"}         # rec|play|pause|stop|ff|rw|infinite
{"cmd": "ui_button",      "name": "Bandwidth"}     # solo "Bandwidth" se sigue enviando vía ui_button; Device y Sample Rate usan sus propios comandos dedicados (get_devices, get_sample_rates); Options/FreqMgr ya no existen (Soundcard excluido — solo abre un diálogo local)
{"cmd": "ui_toolbar"}                              # clics en la barra de herramientas Waterfall/Spectrum (solo se registran)
{"cmd": "ui_display",     "box": "rf", "view": "waterfall"}  # box: rf|af  view: waterfall|spectrum
{"cmd": "ui_smeter_btn",  "name": "Peak"}          # Peak|S-units|Squelch
{"cmd": "user_button",    "index": 1}              # pulsación momentánea (tipo normal)
{"cmd": "user_button",    "index": 2, "enabled": true}  # estado de conmutador push-push
{"cmd": "rf_usr_button",  "index": 1}              # botón de usuario de RF, misma semántica que user_button
{"cmd": "audio_hello",    "udp_port": 5010}        # la GUI registra su puerto UDP RTP en el servidor
{"cmd": "user_text",     "index": 1, "text": "CQ CQ DE TEST"}  # escribe una cadena de texto en el slot index (base 1)
```

> **Nota:** `set_freq` se acepta como alias heredado de `set_lo_a_freq`
> (ambos establecen la frecuencia de LO A); las compilaciones actuales de
> la GUI siempre envían `set_lo_a_freq`.

> **Nota:** `memory` (un simple `{"cmd": "memory", "position": "LO A"}`
> sin `index`/`label`/`freq`) se acepta como alias heredado/sin efecto,
> mantenido para compilaciones antiguas de la GUI; las GUI actuales usan
> `get_memories` / `save_memory` en su lugar.

> **Nota:** El botón **Tarjeta de sonido** abre un cuadro de diálogo local
> de dispositivo de audio y **no** envía un comando `ui_button` al
> servidor.

> **Nota:** `set_nb` es gestionado por el servidor y se rastrea en el
> diccionario de estado, pero la GUI actualmente no tiene ningún botón que
> lo envíe. Úselo desde clientes externos o extienda la GUI para agregar
> una conmutación "NB".

> **Nota:** `audio_hello` debe ser enviado por cualquier cliente de
> terceros después de conectarse, para registrar el puerto UDP RTP del
> cliente en el servidor antes de que el audio pueda fluir.

**Servidor → Cliente:**

Enviado una vez al conectar (antes de que comience la transmisión), cuando
el canal de audio está habilitado:
```json
{"type": "audio_port", "port": 5004, "sample_rate": 8000, "frame_ms": 20, "codec": "pcmu"}
```

> **Nota sobre puertos UDP:** `5004` es el puerto de escucha RTP del
> servidor (el puerto que el servidor abre y al que la GUI envía audio).
> El campo `udp_port` en los comandos `set_ptt` / `audio_hello` (p. ej.,
> `5010`) es el puerto de envío RTP de la *GUI* — el puerto al que el
> servidor debe devolver el audio. Estos son dos lados diferentes del
> canal bidireccional.

Respuesta a cada comando:
```json
{"resp": "ok", "state": {...estado actual de la radio...}}
```

Envío asíncrono iniciado por el servidor (enviado cada vez que se
actualiza un slot `user_text`):
```json
{"type": "user_text", "index": 1, "text": "CQ CQ DE TEST"}
```

Transmitido (solo mientras está "en ejecución"), unas 10 veces por
segundo:
```json
{
  "type": "data",
  "f_start": <Hz>, "f_stop": <Hz>,
  "spectrum": [dBm, dBm, ...],       # espectro de RF, 600 puntos
  "af_range": 3000.0,                # ancho en Hz de la pantalla AF (siempre 3000)
  "af_spectrum": [dBm, dBm, ...],    # espectro AF, 256 puntos (se envía pero no lo usa la GUI — ver nota abajo)
  "smeter_dbm": -73.4,
  "smeter_text": "S9",
  "squelch_open": true,
  "state": {...estado actual de la radio...}
}
```

> **Nota:** Los campos `af_spectrum` / `af_range` que pueden estar
> presentes en los cuadros de datos del servidor **no son usados por la
> GUI**. El espectro y la cascada de AF se calculan completamente del
> lado del cliente mediante `RTPAudioClient._af_worker`, que ejecuta una
> FFT de 512 puntos con ventana Hamming sobre el audio RTP decodificado y
> publica el resultado como un mensaje `"af_local"` en la cola de la GUI.
> Esto significa que la pantalla de AF siempre refleja el audio real que
> se está recibiendo, independientemente del procesamiento del lado del
> servidor.

El diccionario `state` incluido en cada respuesta y envío de datos
contiene el estado completo de la radio: `lo_freq` (el nombre de campo
local del cliente para la frecuencia de LO A; `center_freq` no aparece en
el espejo de estado de la GUI), `lo_b_freq`, `lo_active` (`"A"` o `"B"`),
`tune_freq`, `sample_rate`, `zoom`, `mode`, `filter_lo`, `filter_hi`,
`agc` (`"Med"` o `"Off"`), `agc_thresh`, `rf_gain`, `volume`, `squelch`,
`nb`, `nr`, `nbrf`, `nbif`, `afc`, `anf`, `notch`, `mute`, `ptt`, `split`,
`running`, `user_buttons`, `user_btn_state`, `rf_usr_btns`,
`rf_usr_btn_state`, `user_mod_labels`, `user_mod_types`, `spec_ref_rf`,
`spec_ave_rf`, `spec_ref_af`, y `spec_ave_af`.

> **Nota:** `smeter_text` es una cadena en el formato `"S1"` a `"S9"`, o
> `"S9 +NdB"` (p. ej., `"S9 +20dB"`) para niveles por encima de S9. El
> comando `set_zoom` controla el **zoom del espectro de RF** (factor
> entero 1–32) y es completamente independiente del indicador CLI
> `--scale`, que controla la **escala de UI HiDPI** (niveles −5 a +5,
> factor 1,25 por paso).

El entorno de RF simulado se genera de forma determinista a partir de la
frecuencia (piso de ruido + portadoras HF sintéticas distribuidas entre
1,8–30 MHz con amplitudes que varían lentamente), por lo que distintas
partes del espectro tienen un aspecto realista y variado, y la
sintonización/zoom/filtrado afectan visiblemente al S-meter, el espectro
de AF y las cascadas.

## 4. Ejecutarlo

Requiere Python 3 con Tkinter (`python3-tk` en Debian/Ubuntu).

**Paquetes Python opcionales** (instalados por separado; las aplicaciones
funcionan sin ellos pero con funcionalidad reducida):

```bash
pip install pyaudio       # reproducción/captura de audio RTP (micrófono/altavoz); deshabilitado silenciosamente si no está presente
pip install tomli         # soporte de archivos de configuración TOML en Python < 3.11 (3.11+ lo incluye integrado)
pip install fonttools     # extracción precisa del nombre de familia PostScript para fuentes personalizadas
pip install numpy         # cálculo de FFT más rápido; recurre a Python puro si no está presente
```

```bash
# Terminal 1 — iniciar el backend SDR simulado
python3 cat_server.py            # escucha en 0.0.0.0:50101 por defecto
python3 cat_server.py 0.0.0.0 50101   # host y puerto explícitos

# Configurar botones definidos por el usuario (opcional)
python3 cat_server.py \
    --user-button-label-1 "Gain+" --user-button-type-1 normal \
    --user-button-label-2 "Record" --user-button-type-2 push

# Usar un archivo wav de IQ real para el espectro/cascada de RF en lugar del modelo sintético
python3 cat_server.py --iq_wav /path/to/iq_recording.wav

# Usar un archivo wav de audio real para la reproducción RTP en lugar del tono de demostración de 440 Hz
python3 cat_server.py --audio_wav /path/to/audio.wav

# Terminal 2 — iniciar la GUI
python3 cat_gui.py
```

### Opciones de línea de comandos del servidor

| Indicador | Descripción |
| --- | --- |
| `host [port]` | Posicional: host/IP y puerto TCP en el que escuchar (predeterminados: `0.0.0.0` `50101`) |
| `--config PATH` | Carga la configuración TOML del servidor (transporte + lista `[devices]`) desde PATH (predeterminado: `./cat_server.toml`, creado automáticamente en la primera ejecución) |
| `--device-config PATH` | Carga la configuración TOML del dispositivo (los botones del perfil de dispositivo predeterminado/inicial + ajustes SDR) desde PATH (predeterminado: `./cat_device.toml`, creado automáticamente en la primera ejecución) |
| `--audio-port PORT` | Puerto UDP para el canal de audio RTP (predeterminado: `5004`) |
| `--no-audio` | Deshabilita por completo el canal de audio RTP/UDP |
| `--iq_wav PATH` | Alimenta un archivo wav de IQ real como fuente del espectro/cascada de RF en lugar del modelo sintético |
| `--audio_wav PATH` | Reemplaza el tono sinusoidal de demostración de 440 Hz por un archivo wav de audio real para la reproducción RTP |
| `--user-button-label-N TEXT` | Etiqueta del botón de usuario N (1–14, máximo 7 caracteres); los espacios deben llenarse secuencialmente (1, 2, 3…, sin huecos) |
| `--user-button-type-N TYPE` | Tipo del botón de usuario N: `normal` (momentáneo) o `push` (push-push/conmutador) |
| `--user_mod_N TEXT` | Etiqueta del botón de modulación definido por el usuario N (1–10, máximo 4 caracteres); los espacios deben llenarse secuencialmente |
| `--user_mod_type_N TYPE` | Tipo del botón de modulación de usuario N: `normal` (actúa como un botón de modo estándar), `text` (divide la caja de AF/audio para mostrar un panel de texto de solo lectura), o `text_input` (la misma división con un cuadro de entrada de chat RTTY editable debajo). Requiere que `--user_mod_N` también esté establecido. |
| `--rf_usr_btn_N TEXT` | Etiqueta del botón de usuario de RF N (1–11, máximo 7 caracteres), mostrado a la izquierda de los botones de banda; oculto cuando está vacío |
| `--rf_usr_btn_mode_N TYPE` | Modo del botón de usuario de RF N: `normal` (momentáneo) o `push` (push-push/conmutador). Requiere que `--rf_usr_btn_N` también esté establecido. |

> **Nota:** La lista de perfiles de dispositivo en sí (etiquetas + rutas
> de archivos de configuración por dispositivo) se configura únicamente a
> través de la sección `[devices]` de `cat_server.toml` (hasta 20
> entradas) — no existen indicadores CLI para ella.

### Opciones de línea de comandos de la GUI

| Indicador | Descripción |
| --- | --- |
| `--host HOST --port PORT` | Prerrellena y bloquea la dirección del servidor (ambos requeridos juntos); oculta los campos de entrada de host/puerto en la GUI |
| `--config PATH` | Carga la configuración TOML desde PATH (predeterminado: `./cat_gui.toml`, creado automáticamente en la primera ejecución) |
| `--bg dark\|light` | Tema de color (`dark` es el predeterminado; `light` establece los fondos de los paneles en #FFECD6) |
| `--scale INT` | Nivel de escala HiDPI inicial, −5..+5 (predeterminado 0; el factor es 1,25^nivel) |
| `--disable-scale` | Oculta la superposición de escala +/− (requiere que `--scale` también esté establecido) |
| `--full-screen` | Inicia en modo de pantalla completa |
| `--resolution WxH` | Establece el tamaño inicial de la ventana en píxeles (p. ej., `1280x720`); se ignora si también se da `--full-screen` |
| `--autoconnect` | Se conecta automáticamente al servidor al iniciar; oculta toda la fila de host/puerto/conectar de la GUI |
| `--freq-font PATH` | Archivo TTF/OTF para las pantallas de dígitos de frecuencia de LO/Tune |
| `--gui-font PATH` | Archivo TTF/OTF para el resto del texto de la GUI |
| `--audio-list` | Lista todos los dispositivos de entrada/salida de audio con sus números de índice, y luego sale |
| `--audio-mic INDEX` | Selecciona el dispositivo de micrófono por índice (debe ir junto con `--audio-speaker`) |
| `--audio-speaker INDEX` | Selecciona el dispositivo de altavoz/auriculares por índice (debe ir junto con `--audio-mic`) |
| `--disable-soundcard-select` | Oculta el botón Tarjeta de sonido en la GUI |

En la GUI, haga clic en **Conectar** (host predeterminado `127.0.0.1`,
puerto `50101`), luego en **Inicio** para comenzar la transmisión. A
partir de ahí:

- Desplace el cursor o haga clic en los dígitos de frecuencia (o haga
  doble clic para escribir una frecuencia) para sintonizar LO A, LO B o
  Tune de forma independiente.
- Haga clic en la etiqueta-botón **LO A** o **LO B** para cambiar qué LO
  controla la cascada/espectro de RF; la pantalla se recentra
  inmediatamente.
- Haga clic en los botones de banda (160m–6m) para cambiar de frecuencia
  el LO actualmente activo.
- Haga clic en cualquier punto del espectro de RF para sintonizar el LO
  activo a esa frecuencia.
- Arrastre los bordes de la superposición de filtro sombreada para
  cambiar el paso de banda.
- Use los **botones definidos por el usuario** configurados en el
  servidor para cambiar el modo de demodulación y activar funciones de
  estilo DSP (no existen filas fijas de botones de Modo o conmutación DSP
  en la GUI; las etiquetas y el comportamiento se definen en el
  servidor).
- Use los deslizadores de **Volumen** y **Umbral de AGC**.
- Desplace la rueda del ratón sobre el espectro de RF para acercar o
  alejar el zoom.
- Use los botones de conmutación **Cascada** / **Espectro** en cada franja
  de la barra de herramientas para cambiar el modo de visualización de
  ese panel.
- Pulse Escape tres veces en un segundo para alternar el modo de pantalla
  completa.
- Use la superposición **+/−** en la esquina inferior derecha para
  ajustar la escala HiDPI en vivo sin reiniciar.
- Haga clic en el botón **Tarjeta de sonido** para abrir el cuadro de
  diálogo local de selección de dispositivo de audio y elegir los
  dispositivos de micrófono y altavoz de forma independiente.
- Haga clic en el botón **PTT** para alternar la transmisión; el audio se
  transmite al servidor mientras el PTT está activo (requiere PyAudio).

## 5. Limitaciones

Esto es una simulación con fines de demostración/educativos:

- No hay hardware de RF ni salida de audio real — las "señales" son un
  modelo sintético determinista de portadoras HF entre 1,8–30 MHz, y los
  controles DSP (NR/NB/ANF/Mute/Volumen/AGC) afectan a los números
  mostrados pero no procesan audio real.
- El canal de audio RTP transmite un tono sinusoidal de 440 Hz desde el
  servidor (PTT apagado) y descarta el audio del micrófono recibido (PTT
  encendido). El enrutamiento de audio real hacia hardware SDR de
  transmisión queda como un stub en `UDPAudioChannel._rx_loop`.
- Las funciones de audio requieren `pyaudio`. Si no está instalado, el
  canal de audio se deshabilita silenciosamente; el resto de las
  funciones de la GUI siguen funcionando.
- El indicador de estado `nb` (silenciador de ruido independiente) es
  gestionado por el servidor y se incluye en el diccionario de estado,
  pero ningún botón de la GUI envía `set_nb`. Actívelo desde un cliente
  externo o agregue un botón "NB" dedicado.
- El estado `rf_gain` es rastreado por el servidor y se incluye en el
  diccionario de estado (20,0 dB por defecto), pero la GUI no tiene
  ningún deslizador o control que envíe `set_rf_gain`. Solo puede
  establecerse desde clientes externos o ampliarse con un control
  dedicado.
- El umbral `squelch` es rastreado por el servidor (−130,0 dBm por
  defecto) y controla el indicador `squelch_open` en cada cuadro de
  datos, pero la GUI no tiene ningún deslizador para `set_squelch`. El
  botón "Squelch" en la columna del S-meter solo envía una notificación
  `ui_smeter_btn`; no cambia el nivel de squelch.
- El espectro de RF siempre se calcula a partir de la frecuencia de LO A
  (`lo_freq`), sin importar cuál LO esté activo. Cambiar a LO B recentra
  la pantalla del lado del cliente, pero los cuadros de datos posteriores
  del servidor seguirán reflejando la posición de LO A, no la de LO B.
- El sistema de menús, la base de datos de mapeo de bandas, la grabación,
  la decodificación DRM y la integración OmniRig/CAT no están reproducidos
  — esto se enfoca en el flujo de trabajo principal de
  sintonización/espectro/cascada/medidor descrito anteriormente.
- El servidor acepta múltiples conexiones simultáneas, cada una atendida
  por un hilo `ClientHandler` separado, pero todos los hilos comparten la
  misma instancia de `RadioState`.
