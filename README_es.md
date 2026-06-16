# Interfaz GUI CAT (simulación por TCP)

<div align="center">
  <a href="https://github.com/hiperiondev/RadioCAT_GUI">
    <img src="images/full_gui.png" alt="captura de pantalla">
  </a>
</div>

Este proyecto es una **Interfaz GUI CAT** en Python/Tkinter — un front-end SDR
simulado en el que cada control está conectado a un pequeño backend de "radio"
simulado a través de un socket TCP plano.

Consta de dos archivos:

- `cat_server.py` — un servidor TCP que actúa como capa de hardware/backend.
  Gestiona todo el "estado de la radio" y transmite un entorno RF simulado.
- `cat_gui.py` — un cliente Tkinter que proporciona la ventana principal de la
  Interfaz GUI CAT y envía cada interacción del usuario al servidor,
  redibujando a partir de los datos que el servidor retransmite.

---

## 1. Descripción general de la interfaz

La Interfaz GUI CAT es una aplicación Python/Tkinter para el control de Radio
Definida por Software. Puntos clave:

- **Sin acceso directo al hardware.** La GUI se comunica con su backend a
  través de `cat_server.py`, que abstrae cualquier dispositivo SDR específico
  y expone una API TCP común para configurar la frecuencia, la tasa de muestreo,
  la ganancia e iniciar/detener el flujo IQ.
- **Disposición de la ventana principal** centrada en:
  - Grandes pantallas de frecuencia de 9 dígitos estilo LCD ámbar para
    **LO A**, **LO B** y **Sintonía**, cada una ajustable desplazando el
    ratón o haciendo clic en dígitos individuales, o bien haciendo doble clic
    para escribir una frecuencia. LO A y LO B son seleccionables; el LO activo
    determina la frecuencia central del cascada/espectro RF.
  - Una pantalla de espectro RF (FFT) y una cascada RF sobre ella, centradas
    en la frecuencia del LO activo y abarcando la tasa de muestreo del
    receptor (más estrecha si está "ampliada").
  - Una superposición de banda de paso IF/filtro arrastrable dibujada
    directamente sobre el espectro, cuyos bordes definen el ancho de banda
    del demodulador.
  - Botones de modo: **AM, ECSS, FM, LSB, USB, CW, DIG**, cada uno con una
    banda de paso de filtro predeterminada razonable.
  - Un único botón de alternancia **AGC Med** (en la segunda fila DSP), más
    las alternativas **Notch** y **ANotch**.
  - Botones de alternancia DSP: **NR** (reducción de ruido), **NB RF**
    (cancelador de ruido RF), **NB IF** (cancelador de ruido IF) y **AFC**
    (control automático de frecuencia) en la primera fila; **Silencio**,
    **AGC Med**, **Notch** y **ANotch** en la segunda fila.
  - Hasta 6 **botones definidos por el usuario** (3 por fila DSP, alineados
    a la derecha), cuyos etiquetas y tipos (momentáneo o pulsador/alternancia)
    se configuran en el lado del servidor.
  - Un S-Meter que muestra la intensidad de señal en unidades S
    (S1–S9, S9+20 dB, S9+40 dB) y una lectura digital en dBm, derivada
    de la potencia dentro de la banda de paso del filtro actual.
  - Controles deslizantes de **Volumen** y **Umbral AGC** en el panel
    de control.
  - Control de zoom (rueda del ratón sobre el espectro, o etiquetas de la
    barra de herramientas) para el espectro RF y la cascada.
  - Un panel AF (audio) más pequeño de espectro + cascada que muestra
    la banda de paso de audio demodulado.
  - Una columna de **selección rápida de banda** (160m, 80m, 60m, 40m, 30m,
    20m, 17m, 15m, 12m, 10m, 6m) que sintoniza el LO activo.
  - Botones de la **barra de transporte**: Grabar (●), Reproducir (▶),
    Pausar (⏸), Detener (■), Rebobinar (◀◀), Avance rápido (▶▶) e Infinito (∞).
  - Control **Iniciar/Detener** sobre el flujo del receptor.
  - Botones auxiliares del S-meter: **Pico**, **Unidades S**, **Squelch**.
  - Botones de función: **SDR-Device**, **Soundcard**, **Bandwidth**,
    **Options**, **FreqMgr**.
  - Un **reloj de fecha/hora** en vivo y un botón TCP **Conectar/Desconectar**
    con un indicador de estado de color.
  - Dos barras de herramientas (una entre la cascada RF y el panel de control,
    otra en el panel AF), cada una con botones de alternancia **Cascada** /
    **Espectro**, lectura RBW, etiquetas de Prom., Zoom y Velocidad.
  - Una superposición persistente **HiDPI +/−** en la esquina inferior derecha
    para ajuste de escala en tiempo real desde el nivel −5 hasta +5
    (factor 1,25 por paso).
- **Protocolo de control TCP personalizado.** La Interfaz GUI CAT define su
  propio protocolo JSON simple delimitado por saltos de línea entre
  `cat_gui.py` y `cat_server.py` (descrito a continuación).

## 2. Mapa de funcionalidades

| Función de la GUI CAT | Implementación |
| --- | --- |
| Backend | `cat_server.py` — gestiona todo el estado de la radio, genera un espectro RF simulado |
| Pantallas de dígitos VFO (LO A, LO B, Sintonía) | `FreqDisp` — desplazar/clic en cada dígito, doble clic para escribir una frecuencia; clic en la etiqueta LO A o LO B cambia el LO activo y recentra la cascada inmediatamente |
| Espectro RF + superposición de filtro | `SpecCanvas` — bordes de banda de paso arrastrables, clic para sintonizar, desplazamiento para zoom |
| Cascada RF | `WFCanvas` (resolución interna de 900 bins) |
| Espectro AF + cascada | segundo par `SpecCanvas` / `WFCanvas`, banda base 0..3000 Hz |
| Botones de modo (AM/ECSS/FM/LSB/USB/CW/DIG) | Fila de botones de modo, establece la banda de paso del filtro predeterminada por modo |
| Alternativas DSP (NR / NB RF / NB IF / AFC / Silencio / Notch / ANotch) | Dos filas de botones DSP |
| AGC | Único botón de alternancia **AGC Med** |
| Botones definidos por el usuario (×6) | Alineados a la derecha en las dos filas DSP; etiquetas y tipos provienen del servidor |
| S-Meter | Lienzo `SMeter`, escala S1–S9 + S9+20 dB / S9+40 dB de sobrecarga, lectura digital en dBm |
| Volumen / Umbral AGC | Controles deslizantes en el panel de control izquierdo |
| Zoom / span | Rueda del ratón en el lienzo del espectro RF |
| Selección rápida de banda | Columna de botones de banda (160m–6m) junto a las pantallas de frecuencia |
| Barra de transporte | Botones ● ▶ ⏸ ■ ◀◀ ▶▶ ∞, cada uno envía un comando `transport` |
| Iniciar/Detener | Botón Iniciar/Detener, controla la transmisión del servidor |
| PTT | Botón de lienzo circular en la fila del S-meter; envía comando `set_ptt` |
| Escala HiDPI | Superposición persistente −/+; niveles de escala −5..+5 (×1,25 por paso) |
| Pantalla completa | Opción `--full-screen`; triple Esc (3 pulsaciones en 1 s) activa/desactiva la pantalla completa |
| Tema | `--bg dark` (predeterminado) o `--bg light` (fondos #FFECD6) |

Todo lo que aparece en la tabla anterior se controla en vivo mediante TCP —
nada es estático ni prerenderizado.

## 3. Protocolo TCP

Cada mensaje es un objeto JSON terminado con `\n`.

**Cliente → Servidor (comandos):**

```
{"cmd": "hello"}
{"cmd": "set_freq",       "hz": 14195000}
{"cmd": "set_lo_b_freq",  "hz": 14195000}
{"cmd": "set_tune_freq",  "hz": 14205000}
{"cmd": "set_lo",         "lo": "A"}               # "A" o "B" — LO activo
{"cmd": "set_mode",       "mode": "USB"}            # AM|ECSS|FM|LSB|USB|CW|DIG
{"cmd": "set_filter",     "lo": 100, "hi": 2800}   # Desplazamientos en Hz desde la portadora
{"cmd": "set_agc",        "mode": "Med"}            # Off|Med
{"cmd": "set_agc_thresh", "value": -100.0}          # dBm
{"cmd": "set_rf_gain",    "value": 20}              # 0..40 dB
{"cmd": "set_volume",     "value": 80}              # 0..100
{"cmd": "set_squelch",    "value": -130}            # umbral en dBm
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
{"cmd": "user_button",    "index": 1}              # pulsación momentánea (tipo normal)
{"cmd": "user_button",    "index": 2, "enabled": true}  # estado de alternancia pulsador
```

**Servidor → Cliente:**

Respuesta a cada comando:
```
{"resp": "ok", "state": {...estado actual de la radio...}}
```

Transmitido (solo mientras está "en ejecución"), aproximadamente 10 veces por segundo:
```
{
  "type": "data",
  "f_start": <Hz>, "f_stop": <Hz>,
  "spectrum": [dBm, dBm, ...],       # Espectro RF, 600 puntos
  "af_spectrum": [dBm, ...],         # Espectro AF, 256 puntos
  "af_range": 3000,
  "smeter_dbm": -73.4,
  "smeter_text": "S9 +3dB",
  "squelch_open": true,
  "state": {...estado actual de la radio...}
}
```

El diccionario `state` incluido en cada respuesta y envío de datos contiene
el estado completo de la radio: `center_freq`, `lo_b_freq`, `lo_active`
(`"A"` o `"B"`), `tune_freq`, `sample_rate`, `zoom`, `mode`, `filter_lo`,
`filter_hi`, `agc` (`"Med"` u `"Off"`), `agc_thresh`, `rf_gain`, `volume`,
`squelch`, `nb`, `nr`, `nbrf`, `nbif`, `afc`, `anf`, `notch`, `mute`,
`ptt`, `running`, `user_buttons` y `user_btn_state`.

El entorno RF simulado se genera de forma determinista a partir de la
frecuencia (piso de ruido + portadoras HF sintéticas distribuidas entre
1,8–30 MHz con amplitudes que derivan lentamente), de modo que diferentes
partes del espectro tienen un aspecto realista y variado, y la sintonización,
el zoom y el filtrado afectan visiblemente al S-meter, al espectro AF y a
las cascadas.

## 4. Ejecución

Requiere Python 3 con Tkinter (`python3-tk` en Debian/Ubuntu).

```bash
# Terminal 1 — iniciar el backend SDR simulado
python3 cat_server.py            # escucha en 0.0.0.0:50101 por defecto
python3 cat_server.py 0.0.0.0 50101   # host y puerto explícitos

# Configurar botones definidos por el usuario (opcional)
python3 cat_server.py \
    --user-button-label-1 "Gain+" --user-button-type-1 normal \
    --user-button-label-2 "Record" --user-button-type-2 push

# Terminal 2 — iniciar la GUI
python3 cat_gui.py
```

### Opciones de línea de comandos de la GUI

| Opción | Descripción |
| --- | --- |
| `--host HOST --port PORT` | Prerrellena y bloquea la dirección del servidor (ambas requeridas juntas); oculta los campos de entrada de host/puerto en la GUI |
| `--bg dark\|light` | Tema de color (`dark` es el predeterminado; `light` establece fondos de panel en #FFECD6) |
| `--scale INT` | Nivel de escala HiDPI inicial, −5..+5 (predeterminado 0; el factor es 1,25^nivel) |
| `--disable-scale` | Oculta la superposición de escala +/− (requiere que `--scale` también esté definido) |
| `--full-screen` | Inicia en modo de pantalla completa |
| `--freq-font PATH` | Archivo TTF/OTF para las pantallas de dígitos de frecuencia LO/Sintonía |
| `--gui-font PATH` | Archivo TTF/OTF para todo el resto del texto de la GUI |

En la GUI, haga clic en **Conectar** (host predeterminado `127.0.0.1`, puerto
`50101`), luego en **Iniciar** para comenzar la transmisión. Desde ahí:

- Desplace o haga clic en los dígitos de frecuencia (o doble clic para
  escribir una frecuencia) para sintonizar LO A, LO B o Sintonía de
  forma independiente.
- Haga clic en el botón-etiqueta **LO A** o **LO B** para cambiar qué LO
  controla la cascada/espectro RF; la pantalla se recentra inmediatamente.
- Haga clic en los botones de banda (160m–6m) para hacer QSY del LO activo.
- Haga clic en cualquier lugar del espectro RF para sintonizar el LO activo
  a esa frecuencia.
- Arrastre los bordes de la superposición de filtro sombreada para cambiar
  la banda de paso.
- Haga clic en los botones de modo (AM/ECSS/FM/LSB/USB/CW/DIG) para cambiar
  el modo de demodulación; cada uno establece una banda de paso predeterminada.
- Active o desactive **NR**, **NB RF**, **NB IF**, **AFC**, **Silencio**,
  **AGC Med**, **Notch** y **ANotch** según sea necesario.
- Use los controles deslizantes de **Volumen** y **Umbral AGC**.
- Gire la rueda del ratón sobre el espectro RF para ampliar o reducir el zoom.
- Use los botones de alternancia **Cascada** / **Espectro** en cada barra de
  herramientas para cambiar el modo de visualización de ese panel.
- Pulse Escape tres veces en un segundo para activar o desactivar el modo
  de pantalla completa.
- Use la superposición **+/−** en la esquina inferior derecha para ajustar
  la escala HiDPI en vivo sin reiniciar.

## 5. Limitaciones

Esta es una simulación con fines de demostración/educación:

- No hay hardware RF real ni salida de audio — las "señales" son un modelo
  sintético determinista de portadoras HF entre 1,8–30 MHz, y los controles
  DSP (NR/NB/ANF/Silencio/Volumen/AGC) afectan a los números mostrados pero
  no procesan audio real.
- El sistema de menús, la base de datos de mapeo de bandas, la grabación,
  la decodificación DRM y la integración OmniRig/CAT no están reproducidos
  — este proyecto se centra en el flujo de trabajo básico de sintonización/
  espectro/cascada/medidor descrito anteriormente.
- El servidor acepta solo un cliente a la vez por puerto; múltiples
  conexiones simultáneas son atendidas por hilos `ClientHandler` separados
  pero comparten la misma instancia de `RadioState`.
