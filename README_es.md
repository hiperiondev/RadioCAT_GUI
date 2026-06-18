# Interfaz GUI CAT

<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="captura de pantalla">
  </a>
</div>

Este proyecto es una **Interfaz GUI CAT** en Python/Tkinter — un front-end SDR simulado cuyo cada control está conectado a un pequeño "radio" de backend simulado a través de un socket TCP simple.

Consta de dos archivos:

- `cat_server.py` — un servidor TCP que actúa como la capa de hardware/backend.
  Posee todo el "estado del radio", transmite en streaming un entorno RF simulado y gestiona
  un canal de audio RTP/UDP bidireccional.
- `cat_gui.py` — un cliente Tkinter que provee la ventana principal de la Interfaz GUI CAT
  y envía cada interacción del usuario al servidor, redibujando a partir de los
  datos que el servidor devuelve en streaming. También reproduce el audio RTP recibido y envía
  audio del micrófono durante PTT.

---

## 1. Descripción general de la interfaz

La Interfaz GUI CAT es una aplicación Python/Tkinter para el control de Radio Definida por Software.
Puntos clave:

- **Sin acceso directo al hardware.** La GUI se comunica con su backend a través de
  `cat_server.py`, que abstrae cualquier dispositivo SDR específico y expone
  una API TCP común para configurar frecuencia, tasa de muestreo, ganancia, e
  iniciar/detener el stream I/Q.
- **Disposición de la ventana principal** centrada en:
  - Grandes pantallas de frecuencia de 9 dígitos estilo LCD ámbar para **LO A**, **LO B**
    y **Tune**, cada una sintonizable desplazando o haciendo clic en dígitos individuales o
    haciendo doble clic para escribir una frecuencia. LO A y LO B son seleccionables;
    el LO activo controla la frecuencia central del cascada RF/espectro.
  - Una pantalla de espectro RF (FFT) y una cascada RF encima, centradas en
    la frecuencia del LO activo y abarcando la tasa de muestreo del receptor
    (más estrecha si está "ampliada").
  - Una superposición de banda de paso IF/filtro arrastrable dibujada directamente en el espectro,
    cuyos bordes definen el ancho de banda del demodulador.
  - Botones de modo: **AM, FM, LSB, USB, CW**, cada uno con una banda de paso de filtro
    predeterminada al seleccionarlo.
  - Botones de palanca DSP: **NR** (reducción de ruido), **NB RF** (blanqueador de ruido
    RF), **NB IF** (blanqueador de ruido IF), y **AFC** (control automático de frecuencia)
    en la primera fila; **Silencio**, **AGC Med**, **Notch** y **ANotch** en la segunda fila.
  - Hasta 6 **botones definidos por el usuario** (3 por fila DSP, alineados a la derecha),
    cuyos etiquetas y tipos (momentáneo o push-push/palanca) se configuran del lado del servidor.
  - Un S-Metro que muestra la intensidad de señal en unidades S (S1–S9, S9+20 dB,
    S9+40 dB) y una lectura digital en dBm, derivada de la potencia dentro de la
    banda de paso del filtro actual.
  - Controles deslizantes de **Volumen** y **Umbral AGC** en el panel de control.
  - Control de zoom (rueda del ratón en el espectro, o etiquetas de la barra de herramientas) para el
    espectro RF y la cascada.
  - Un panel más pequeño de espectro AF (audio) + cascada que muestra la banda de paso de
    audio demodulado.
  - Una columna de **selección rápida de banda** (160m, 80m, 60m, 40m, 30m, 20m, 17m,
    15m, 12m, 10m, 6m) que sintoniza el LO actualmente activo.
  - Botones de la **barra de transporte**: Grabar (●), Reproducir (▶), Pausar (⏸), Detener (■),
    Rebobinar (◀◀), Avance rápido (▶▶) y Bucle (∞).
  - Control **Iniciar/Detener** sobre el stream del receptor.
  - Botones auxiliares del S-Metro: **Pico**, **Unidades S**, **Silenciador**.
  - Botones de función: **Dispositivo**, **Tarjeta de sonido**, **Ancho de banda**,
    **Opciones**, **GestorFrec**. Nota: **Tarjeta de sonido** abre un cuadro de diálogo
    local de selección de dispositivo de audio y **no** envía un comando al servidor.
  - Un **reloj de fecha/hora** en vivo y un botón TCP **Conectar/Desconectar** con
    un indicador de estado de punto de color.
  - Dos tiras de barra de herramientas (una entre la cascada RF y el panel de control,
    otra en el panel AF), cada una con botones de palanca **Cascada** / **Espectro**,
    lectura de RBW, etiquetas de Promedio, Zoom y Velocidad.
  - Una superposición **HiDPI +/−** persistente en la esquina inferior derecha para
    escala en tiempo real desde nivel −5 a +5 (factor 1,25 por paso).
  - Un botón circular canvas **PTT** (en la fila del S-Metro) que activa/desactiva
    el modo de transmisión; mientras PTT está activo, la GUI envía audio del micrófono al
    servidor vía RTP/UDP y deja de reproducir el audio recibido.
- **Canal de audio RTP/UDP.** Además de la conexión de control TCP, el
  servidor abre un puerto UDP (predeterminado 5004) para audio G.711 µ-law (PCMU)
  bidireccional. Con PTT desactivado, el servidor transmite un tono sinusoidal de demostración a la
  GUI para su reproducción; con PTT activo, la GUI captura audio del micrófono y
  lo transmite al servidor. La reproducción y captura de audio usan PyAudio (opcional;
  la GUI funciona sin él, pero el audio se desactiva silenciosamente).
- **Archivos de configuración TOML.** Ambas aplicaciones crean automáticamente un
  archivo `cat_server.toml` / `cat_gui.toml` en el directorio actual en el primer
  arranque y lo utilizan como fuente persistente de valores predeterminados. Las banderas CLI siempre anulan
  los valores del archivo de configuración.
- **Protocolo de control TCP personalizado.** La Interfaz GUI CAT define su propio
  protocolo JSON simple delimitado por saltos de línea entre `cat_gui.py` y
  `cat_server.py` (descrito a continuación).

## 2. Mapa de funciones

| Función GUI CAT | Implementación |
| --- | --- |
| Backend | `cat_server.py` — posee todo el estado del radio, genera un espectro RF simulado |
| Pantallas de dígitos VFO (LO A, LO B, Tune) | `FreqDisp` — desplazar/hacer clic en cada dígito, doble clic para escribir una frecuencia; hacer clic en la etiqueta LO A o LO B cambia el LO activo y recentra inmediatamente la cascada |
| Espectro RF + superposición de filtro | `SpecCanvas` — bordes de banda de paso arrastrables, clic para sintonizar, desplazamiento para zoom |
| Cascada RF | `WFCanvas` (resolución de renderizado interno de 900 bins; el servidor transmite 600 puntos) |
| Espectro AF + cascada | segundo par `SpecCanvas` / `WFCanvas`, banda base 0..3000 Hz; calculado localmente por `RTPAudioClient._af_worker` a partir del audio RTP decodificado (FFT de 512 puntos, ventana de Hamming con 50% de superposición) — no se transmite desde el servidor |
| Botones de modo (AM/FM/LSB/USB/CW) | Fila de botones de modo; establece la banda de paso de filtro predeterminada para cada modo |
| Palancas DSP (NR / NB RF / NB IF / AFC / Silencio / AGC Med / Notch / ANotch) | Dos filas de botones DSP. No hay botón NB independiente; el indicador de estado `nb` del servidor no tiene control en la GUI |
| Botones definidos por el usuario (×6) | Alineados a la derecha en las dos filas DSP; etiquetas y tipos provienen del servidor |
| Botones de modulación definidos por el usuario (×5) | Configurables mediante `--user_mod_1`…`--user_mod_5` / `--user_mod_type_1`…`--user_mod_type_5`; etiquetas y tipos en campos de estado `user_mod_labels` / `user_mod_types` |
| Reproducción de wav IQ / wav de audio | `IQWavSource` (`--iq_wav`) alimenta un archivo wav IQ real al espectro RF/cascada; `AudioWavSource` (`--audio_wav`) reemplaza el tono sinusoidal de demostración con un archivo de audio real |
| S-Metro | Canvas `SMeter`, escala de sobrecarga S1–S9 + S9+20 dB / S9+40 dB, lectura digital en dBm |
| Volumen / Umbral AGC | Controles deslizantes en el panel de control izquierdo |
| Zoom / span | Rueda del ratón en el canvas del espectro RF |
| Selección rápida de banda | Columna de botones de banda (160m–6m) junto a las pantallas de frecuencia |
| Barra de transporte | Botones ● ▶ ⏸ ■ ◀◀ ▶▶ ∞, cada uno envía un comando `transport` |
| Iniciar/Detener | Botón Iniciar/Detener, controla el streaming del servidor |
| PTT | Botón circular canvas en la fila del S-Metro; envía el comando `set_ptt` y cambia el canal de audio RTP entre RX y TX |
| Audio RTP/UDP | `RTPAudioClient` (GUI) / `UDPAudioChannel` (servidor) — audio G.711 µ-law bidireccional en un puerto UDP; requiere PyAudio |
| Cuadro de diálogo de tarjeta de sonido | Cuadro de diálogo de selección de dispositivo de audio local (micrófono + altavoz independientemente); abierto por el botón Tarjeta de sonido, **no** envía un comando `ui_button` al servidor |
| Escalado HiDPI | Superposición −/+ persistente; niveles de escala −5..+5 (×1,25 por paso) |
| Pantalla completa | Bandera `--full-screen`; triple Esc (3 pulsaciones en 1 s) activa/desactiva la pantalla completa |
| Tema | `--bg dark` (predeterminado) o `--bg light` (fondos #FFECD6) |
| Configuración TOML | `cat_server.toml` / `cat_gui.toml` creados automáticamente en el primer arranque; `--config PATH` anula la ubicación |

Todo en la tabla anterior se controla en vivo por TCP — nada es estático
ni pre-renderizado.

## 3. Protocolo TCP

Cada mensaje es un objeto JSON terminado por `\n`.

**Cliente → Servidor (comandos):**

```json
{"cmd": "hello"}
{"cmd": "set_freq",       "hz": 14195000}
{"cmd": "set_lo_b_freq",  "hz": 14195000}
{"cmd": "set_tune_freq",  "hz": 14205000}
{"cmd": "set_lo",         "lo": "A"}               # "A" o "B" — LO activo
{"cmd": "set_mode",       "mode": "USB"}            # AM|FM|LSB|USB|CW
{"cmd": "set_filter",     "lo": 100, "hi": 2800}   # desplazamientos en Hz desde la portadora
{"cmd": "set_agc",        "mode": "Med"}            # Off|Med
{"cmd": "set_agc_thresh", "value": -100.0}          # dBm
{"cmd": "set_rf_gain",    "value": 20}              # 0..40 dB
{"cmd": "set_volume",     "value": 80}              # 0..100
{"cmd": "set_squelch",    "value": -130}            # umbral en dBm
{"cmd": "set_nb",         "enabled": true}          # indicador NB independiente (sin botón GUI; solo del lado del servidor)
{"cmd": "set_nr",         "enabled": true}
{"cmd": "set_nbrf",       "enabled": true}
{"cmd": "set_nbif",       "enabled": true}
{"cmd": "set_afc",        "enabled": true}
{"cmd": "set_anf",        "enabled": true}
{"cmd": "set_notch",      "enabled": true}
{"cmd": "set_mute",       "enabled": true}
{"cmd": "set_ptt",        "enabled": true, "udp_port": 5010}  # udp_port = puerto UDP RTP de la GUI
{"cmd": "set_zoom",       "value": 2}              # 1..32
{"cmd": "start"}
{"cmd": "stop"}
{"cmd": "transport",      "action": "rec"}         # rec|play|pause|stop|ff|rw|infinite
{"cmd": "ui_button",      "name": "FreqMgr"}       # Device|Bandwidth|Options|FreqMgr (Soundcard excluido — abre solo el cuadro de diálogo local)
{"cmd": "ui_display",     "box": "rf", "view": "waterfall"}  # box: rf|af  view: waterfall|spectrum
{"cmd": "ui_smeter_btn",  "name": "Peak"}          # Peak|S-units|Squelch
{"cmd": "user_button",    "index": 1}              # pulsación momentánea (tipo normal)
{"cmd": "user_button",    "index": 2, "enabled": true}  # estado de palanca push-push
{"cmd": "audio_hello",    "udp_port": 5010}        # la GUI registra su puerto UDP RTP en el servidor
{"cmd": "user_text",     "index": 1, "text": "CQ CQ DE TEST"}  # escribe una cadena de texto en el slot índice (base 1)
```

> **Nota:** El botón **Tarjeta de sonido** abre un cuadro de diálogo local de dispositivo de audio y
> **no** envía un comando `ui_button` al servidor.

> **Nota:** `set_nb` es manejado por el servidor y registrado en el diccionario de estado,
> pero la GUI actualmente no tiene ningún botón que lo envíe. Úselo desde clientes externos
> o amplíe la GUI para agregar una palanca "NB".

> **Nota:** `audio_hello` debe ser enviado por cualquier cliente de terceros después de conectarse
> para registrar el puerto UDP RTP del cliente en el servidor antes de que fluya el audio.

**Servidor → Cliente:**

Enviado una vez al conectar (antes de que comience el streaming), cuando el canal de audio está habilitado:
```json
{"type": "audio_port", "port": 5004, "sample_rate": 8000, "frame_ms": 20, "codec": "pcmu"}
```

> **Nota sobre puertos UDP:** `5004` es el puerto de escucha RTP del servidor (el puerto que el
> servidor abre y al que la GUI envía audio). El campo `udp_port` en los comandos
> `set_ptt` / `audio_hello` (por ejemplo, `5010`) es el puerto de envío RTP de la GUI —
> el puerto al que el servidor debe enviar audio de vuelta. Estos son dos
> lados diferentes del canal bidireccional.

Respuesta a cada comando:
```json
{"resp": "ok", "state": {...estado actual del radio...}}
```

Envío asíncrono iniciado por el servidor (enviado cuando se actualiza un slot `user_text`):
```json
{"type": "user_text", "index": 1, "text": "CQ CQ DE TEST"}
```

Transmitido en streaming (solo mientras está "en ejecución"), aproximadamente 10 veces por segundo:
```json
{
  "type": "data",
  "f_start": <Hz>, "f_stop": <Hz>,
  "spectrum": [dBm, dBm, ...],       # espectro RF, 600 puntos
  "af_range": 3000.0,                # ancho en Hz de la pantalla AF (siempre 3000)
  "af_spectrum": [dBm, dBm, ...],    # espectro AF, 256 puntos (enviado pero no usado por la GUI — ver nota abajo)
  "smeter_dbm": -73.4,
  "smeter_text": "S9",
  "squelch_open": true,
  "state": {...estado actual del radio...}
}
```

> **Nota:** Los campos `af_spectrum` / `af_range` que pueden estar presentes en
> los frames de datos del servidor **no son utilizados por la GUI**. El espectro AF y
> la cascada se calculan enteramente del lado del cliente por
> `RTPAudioClient._af_worker`, que ejecuta una FFT de 512 puntos con ventana de Hamming
> sobre el audio RTP decodificado y publica el resultado como un mensaje `"af_local"` en la
> cola de la GUI. Esto significa que la pantalla AF siempre refleja el audio real que se está
> recibiendo, independientemente del procesamiento del lado del servidor.

El diccionario `state` incluido en cada respuesta y envío de datos contiene el estado completo del radio:
`center_freq`, `lo_b_freq`, `lo_active` (`"A"` o `"B"`), `tune_freq`,
`sample_rate`, `zoom`, `mode`, `filter_lo`, `filter_hi`, `agc` (`"Med"` o
`"Off"`), `agc_thresh`, `rf_gain`, `volume`, `squelch`, `nb`, `nr`, `nbrf`,
`nbif`, `afc`, `anf`, `notch`, `mute`, `ptt`, `running`, `user_buttons`,
`user_btn_state`, `user_mod_labels` y `user_mod_types`.

> **Nota:** `smeter_text` es una cadena en el formato `"S1"` a `"S9"`,
> o `"S9 +NdB"` (por ejemplo, `"S9 +20dB"`) para niveles por encima de S9. El comando `set_zoom`
> controla el **zoom del espectro RF** (factor entero 1–32) y es completamente
> independiente de la bandera CLI `--scale`, que controla la **escala de la interfaz HiDPI**
> (niveles −5 a +5, factor 1,25 por paso).

El entorno RF simulado se genera de manera determinista a partir de la frecuencia
(piso de ruido + portadoras HF sintéticas distribuidas por 1,8–30 MHz con amplitudes
que derivan lentamente), de modo que diferentes partes del espectro tienen un aspecto realista y
variado, y la sintonización/zoom/filtrado afectan visiblemente al S-Metro,
espectro AF y cascadas.

## 4. Ejecución

Requiere Python 3 con Tkinter (`python3-tk` en Debian/Ubuntu).

**Paquetes Python opcionales** (instalados por separado; las aplicaciones se ejecutan sin ellos
pero con funcionalidad reducida):

```bash
pip install pyaudio       # Reproducción/captura de audio RTP (micrófono/altavoz); desactivado silenciosamente si no está presente
pip install tomli         # Soporte de archivo de configuración TOML en Python < 3.11 (3.11+ lo tiene integrado)
pip install fonttools     # Extracción precisa de nombres de familia PostScript para fuentes personalizadas
pip install numpy         # Cálculo FFT más rápido; regresa a Python puro si no está presente
```

```bash
# Terminal 1 — iniciar el backend SDR simulado
python3 cat_server.py            # escucha en 0.0.0.0:50101 por defecto
python3 cat_server.py 0.0.0.0 50101   # host y puerto explícitos

# Configurar botones definidos por el usuario (opcional)
python3 cat_server.py \
    --user-button-label-1 "Gain+" --user-button-type-1 normal \
    --user-button-label-2 "Record" --user-button-type-2 push

# Usar un archivo wav IQ real para el espectro RF/cascada en lugar del modelo sintético
python3 cat_server.py --iq_wav /ruta/a/grabacion_iq.wav

# Usar un archivo wav de audio real para la reproducción RTP en lugar del tono de demostración de 440 Hz
python3 cat_server.py --audio_wav /ruta/a/audio.wav

# Terminal 2 — iniciar la GUI
python3 cat_gui.py
```

### Opciones de línea de comandos del servidor

| Bandera | Descripción |
| --- | --- |
| `host [puerto]` | Posicional: host/IP y puerto TCP en el que escuchar (predeterminados: `0.0.0.0` `50101`) |
| `--config RUTA` | Cargar configuración TOML desde RUTA (predeterminado: `./cat_server.toml`, creado automáticamente en el primer arranque) |
| `--audio-port PUERTO` | Puerto UDP para el canal de audio RTP (predeterminado: `5004`) |
| `--no-audio` | Deshabilitar completamente el canal de audio RTP/UDP |
| `--iq_wav RUTA` | Alimentar un archivo wav IQ real como fuente del espectro RF/cascada en lugar del modelo sintético |
| `--audio_wav RUTA` | Reemplazar el tono sinusoidal de demostración de 440 Hz con un archivo wav de audio real para la reproducción RTP |
| `--user-button-label-N TEXTO` | Etiqueta para el botón de usuario N (1–6, máximo 7 caracteres) |
| `--user-button-type-N TIPO` | Tipo del botón de usuario N: `normal` (momentáneo) o `push` (push-push/palanca) |
| `--user_mod_N TEXTO` | Etiqueta para el botón de modulación definido por el usuario N (1–5) |
| `--user_mod_type_N TIPO` | Tipo del botón de modulación de usuario N: `normal` (actúa como un botón de modo estándar), `text` (divide el cuadro AF/audio para mostrar un panel de texto de solo lectura), o `text_input` (misma división con un cuadro de entrada RTTY-chat editable debajo). Requiere que también se establezca `--user_mod_N`. |

### Opciones de línea de comandos de la GUI

| Bandera | Descripción |
| --- | --- |
| `--host HOST --port PUERTO` | Pre-rellenar y bloquear la dirección del servidor (ambos requeridos juntos); oculta los campos de entrada de host/puerto en la GUI |
| `--config RUTA` | Cargar configuración TOML desde RUTA (predeterminado: `./cat_gui.toml`, creado automáticamente en el primer arranque) |
| `--bg dark\|light` | Tema de color (`dark` es el predeterminado; `light` establece fondos del panel en #FFECD6) |
| `--scale INT` | Nivel de escala HiDPI inicial, −5..+5 (predeterminado 0; el factor es 1,25^nivel) |
| `--disable-scale` | Ocultar la superposición de escala +/− (requiere que también se establezca `--scale`) |
| `--full-screen` | Iniciar en modo de pantalla completa |
| `--freq-font RUTA` | Archivo TTF/OTF para las pantallas de dígitos de frecuencia LO/Tune |
| `--gui-font RUTA` | Archivo TTF/OTF para todo el texto de la GUI |
| `--audio-list` | Listar todos los dispositivos de entrada/salida de audio con sus números de índice, luego salir |
| `--audio-mic ÍNDICE` | Seleccionar el dispositivo de micrófono por índice (debe combinarse con `--audio-speaker`) |
| `--audio-speaker ÍNDICE` | Seleccionar el dispositivo de altavoz/auriculares por índice (debe combinarse con `--audio-mic`) |
| `--disable-soundcard-select` | Ocultar el botón Tarjeta de sonido en la GUI |

En la GUI, haga clic en **Conectar** (host predeterminado `127.0.0.1`, puerto `50101`),
luego en **Iniciar** para comenzar el streaming. Desde allí:

- Desplace o haga clic en los dígitos de frecuencia (o doble clic para escribir una
  frecuencia) para sintonizar LO A, LO B o Tune independientemente.
- Haga clic en el botón-etiqueta **LO A** o **LO B** para cambiar qué LO controla la
  cascada RF/espectro; la pantalla se recentra inmediatamente.
- Haga clic en los botones de banda (160m–6m) para hacer QSY al LO actualmente activo.
- Haga clic en cualquier lugar del espectro RF para sintonizar el LO activo a esa frecuencia.
- Arrastre los bordes de la superposición de filtro sombreada para cambiar la banda de paso.
- Haga clic en los botones de modo (AM/FM/LSB/USB/CW) para cambiar el modo de demodulación;
  cada uno establece una banda de paso predeterminada.
- Alterne **NR**, **NB RF**, **NB IF**, **AFC**, **Silencio**, **AGC Med**,
  **Notch** y **ANotch** según sea necesario.
- Use los controles deslizantes de **Volumen** y **Umbral AGC**.
- Desplace la rueda del ratón en el espectro RF para acercar o alejar el zoom.
- Use los botones de palanca **Cascada** / **Espectro** en cada tira de barra de herramientas
  para cambiar el modo de visualización de ese panel.
- Presione Escape tres veces en un segundo para activar/desactivar el modo de pantalla completa.
- Use la superposición **+/−** en la esquina inferior derecha para ajustar la escala HiDPI
  en vivo sin reiniciar.
- Haga clic en el botón **Tarjeta de sonido** para abrir el cuadro de diálogo de selección de dispositivo
  de audio local y elegir los dispositivos de micrófono y altavoz independientemente.
- Haga clic en el botón **PTT** para activar/desactivar la transmisión; el audio se transmite al servidor
  mientras PTT está activo (requiere PyAudio).

## 5. Limitaciones

Esta es una simulación con fines de demostración/educativos:

- No hay hardware RF real ni salida de audio real — las "señales" son un
  modelo sintético determinista de portadoras HF a lo largo de 1,8–30 MHz, y
  los controles DSP (NR/NB/ANF/Silencio/Volumen/AGC) afectan los números mostrados
  pero no procesan audio real.
- El canal de audio RTP transmite un tono sinusoidal de 440 Hz desde el servidor (PTT desactivado)
  y descarta el audio del micrófono recibido (PTT activado). El enrutamiento de audio real al hardware
  de TX SDR se deja como un stub en `UDPAudioChannel._rx_loop`.
- Las funciones de audio requieren `pyaudio`. Si no está instalado, el canal de audio
  se deshabilita silenciosamente; todas las demás funciones de la GUI siguen funcionando.
- El indicador de estado `nb` (blanqueador de ruido independiente) es manejado por el servidor e
  incluido en el diccionario de estado, pero ningún botón de la GUI envía `set_nb`. Actívelo
  desde un cliente externo o agregue un botón "NB" dedicado.
- El estado `rf_gain` es rastreado por el servidor e incluido en el diccionario de estado
  (predeterminado 20,0 dB), pero la GUI no tiene control deslizante ni control que envíe
  `set_rf_gain`. Solo puede establecerse desde clientes externos o extenderse con un
  control dedicado.
- El umbral de `squelch` es rastreado por el servidor (predeterminado −130,0 dBm) y
  controla el indicador `squelch_open` en cada frame de datos, pero la GUI no tiene control deslizante
  para `set_squelch`. El botón "Silenciador" en la columna del S-Metro envía solo una
  notificación `ui_smeter_btn`; no cambia el nivel del silenciador.
- El espectro RF siempre se calcula a partir de la frecuencia de LO A (`center_freq`)
  independientemente de qué LO esté activo. Cambiar a LO B recentra la pantalla
  del lado del cliente, pero los frames de datos posteriores del servidor reflejarán
  la posición de LO A, no la de LO B.
- El sistema de menús, la base de datos de mapeo de bandas, la grabación, la decodificación DRM y
  la integración OmniRig/CAT no están reproducidos — este proyecto se enfoca en el
  flujo de trabajo central de sintonización/espectro/cascada/medidor descrito anteriormente.
- El servidor acepta múltiples conexiones simultáneas, cada una atendida por un
  hilo `ClientHandler` separado, pero todos los hilos comparten la misma
  instancia de `RadioState`.
