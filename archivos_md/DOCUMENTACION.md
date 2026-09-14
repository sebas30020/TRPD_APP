# Visor de Vacuolas — Documentación y reglas internas

Aplicación Dash (`app.py`) para explorar mediciones de osciloscopio Keysight y
analizar los impulsos y los peaks del canal trigger. Este documento recoge las
**reglas internas** que el programa debe respetar; actualízalo cada vez que se
añada o cambie una funcionalidad.

---

## 0. Ruta de los datos, de principio a fin

Este recorrido describe cómo fluye la información desde los archivos HDF5 crudos
hasta cada gráfico y tabla de la interfaz:

1. **HDF5 crudo → mV y µs (`cargar_segmento`):**
   Los datos binarios de osciloscopio se leen desde `Waveforms/<canal>/<canal> Seg<seg>Data`.
   Se convierten a unidades físicas:
   $v = (\text{raw} \cdot \text{YInc} + \text{YOrg}) \times 10^3 \text{ mV}$,
   $t = (\text{XOrg} + i \cdot \text{XInc}) \times 10^6 \text{ µs}$.
   A continuación se recortan a la ventana temporal `T_MIN..T_MAX` (`-5..30 µs`).
   Este es el **único punto de conversión** de unidades de toda la aplicación (regla **R-D1**).
2. **Selección de contexto en la interfaz:**
   El usuario elige en los controles superiores la **medición** (carpeta), el
   **segmento** a inspeccionar y el canal asignado como **trigger** (`ch2`, `ch3` o `ch4`).
   Cada segmento del canal trigger se procesa individualmente.
3. **Detección de peaks sobre el canal trigger (`find_peaks`):**
   Sobre la señal del canal trigger, recortada a $t \ge t_{\text{mín}}$, se ejecuta
   `scipy.signal.find_peaks` evaluando exclusivamente altura absoluta (`umbral` en mV)
   y separación mínima (`distancia` en µs convertida a muestras con `_muestras`).
   No se evalúa prominencia ni ancho.
4. **Clasificación: peak con ventana completa o "sin ventana" (`capturar`):**
   Para cada peak detectado en el índice $i$, se evalúa si se dispone de margen
   suficiente para extraer una ventana de $1 \text{ µs}$ ($0.2 \text{ µs}$ antes y
   $0.8 \text{ µs}$ después del peak).
   Si la ventana se sale del segmento recortado ($i - n_{\text{antes}} < 0$ o
   $i + n_{\text{desp}} + 1 > v.\text{size}$), el evento se clasifica como
   **peak sin ventana** (`t_peak_borde`, `v_peak_borde`, `seg_borde`).
   Estos peaks cuentan en las estadísticas de conteo y densidad, pero no poseen
   señal capturada (regla **R-P3**).
5. **Captura de ventanas de 1 µs (`capturar`):**
   Para los peaks completos se extrae el recorte temporal $[-0.2, +0.8] \text{ µs}$
   alineado al peak en $t = 0$. Esta matriz $W$ y sus vectores asociados
   (`t_peak`, `v_peak`, `seg`) conforman el **conjunto único y ordenado** que
   comparten de forma 1:1 el scatter de Peaks, el scatter de Vpp vs Energía, las
   ventanas temporales superpuestas, la FFT y la Transformada S de la ventana (regla **R-C2**).
6. **Selección de eventos por el usuario (store `seleccion`):**
   El usuario selecciona eventos individuales o grupos mediante clics o cajas de
   selección en cualquiera de los dos scatters (Peaks o Vpp vs Energía) o haciendo
   clic directo sobre las cruces negras del canal trigger en el gráfico principal.
   El store central `seleccion` almacena la lista de índices de ventana elegidos.
7. **Análisis derivados de la selección:**
   - **Ventanas temporales (`figura_ventanas`):** superpone en pantalla únicamente
     las formas de onda seleccionadas, alineadas en su peak ($t = 0$).
   - **FFT Welch (`figura_fft`):** calcula el espectro de potencia de cada ventana
     seleccionada y grafica el promedio entre ellas.
   - **Transformada S de la ventana (`figura_st_ventana`):** calcula la distribución
     tiempo-frecuencia de cada ventana de $1 \text{ µs}$ y promedia su magnitud $|S|$.
8. **Rama paralela independiente: Transformada S del segmento completo (`st_segmento`):**
   No depende de la detección de peaks ni de la captura o selección. Toma la señal
   cruda completa de cada canal ($[-5, 30] \text{ µs}$, incluido CH1 crudo sin filtrar)
   y calcula la Transformada S multicanal en la pestaña "Transformada S" del panel
   principal (`tabs_principal`).
9. **Rama paralela independiente: Impulso de referencia CH1 (`impulso_filtrado`):**
   Informativa y de referencia visual. Promedia la señal de CH1 de todos los segmentos
   de la medición, aplica un filtro pasa-bajos Butterworth de $20 \text{ MHz}$ (orden 4)
   y calcula los tiempos característicos ($t_{10}, t_{30}, t_{90}, t_{50}, t_0^{\text{lin}}, t_{\text{max}}^{\text{lin}}$).
   Se muestra en la fila de CH1 del gráfico principal y como curva de referencia
   en el scatter de Peaks; no alimenta la detección de peaks, la FFT ni la Transformada S.

### Diagrama de flujo de datos

```text
                                [ Archivos HDF5 crudos ]
                                (ch1.h5, ch2.h5, ch3.h5, ch4.h5)
                                           |
                                           v
                                   cargar_segmento()
                    (conversión a mV y µs, recorte a -5..30 µs [R-D1, R-D2])
                                           |
          +--------------------------------+-------------------------------+
          |                                |                               |
[ Rama Impulso CH1 ]             [ Rama Segmento Completo ]      [ Rama Peaks y Ventanas ]
          |                                |                               |
promedio_impulso()                         | (pestaña "Transformada S"     | (control canal trigger,
(promedio todos segmentos)                 |  en tabs_principal;           |  umbral, dist_us, tmin)
          |                                |  control st_fmax)             v
impulso_filtrado()                         v                     _detectar() / capturar()
(Butterworth pasa-bajos            st_segmento() /               (find_peaks en t >= tmin)
 20 MHz, orden 4)                  figura_st_segmento()                    |
          |                        (ST cruda de ch1..ch4,                  v
tiempos_impulso()                   cacheada por sesión)          Bifurcación en capturar()
(t10, t30, t90, t50,                                              (botón "Calcular peaks")
 t0_lin, tmax_lin)                                                +--------+--------+
          |                                                       |                 |
          v                                                       v                 v
_dibujar_impulso_ch1()                                     Peaks completos    Peaks sin ventana
(trazo fila CH1 en figura()                               (con margen 1 µs)   (muy cerca de borde/tmin)
 y trazo ref en figura_scatter())                                 |                 |
                                                          Ventana W (1 µs)          |
                                                          [t_peak, v_peak, seg]     | [t_peak_borde, seg_borde]
                                                                  |                 |
                                                           +------+------+          |
                                                           |             |          |
                                                           |       contar_peaks()   |
                                                           |       tabla_densidad() |
                                                           |       (barras y tabla) <
                                                           |       (cruces naranjas
                                                           |        en figura())
                                                           v
                                                figura_scatter() / figura_vpp_energia()
                                                (cruces negras en figura(); Scattergl)
                                                           |
                                                           | (clic/caja en scatters o
                                                           |  clic en cruces negras)
                                                           v
                                                    Store seleccion
                                                (lista de índices de ventana)
                                                           |
                                            +--------------+--------------+
                                            |                             |
                                    figura_ventanas()             figura_fft() / figura_st_ventana()
                                    (ventanas superpuestas,       (Welch espectro lineal / ST promedio |S|;
                                     alineadas en t=0)             pestañas tabs_espectro, control st_fmax)
```

---

## 1. Datos

- Carpeta de datos: `../mediciones/Mediciones/` (hermana del repo, fuera de
  `TRPD_APP`).
  - **Mediciones históricas:** Están clasificadas por cadencia de adquisición
    (ver `cadencia.py`, sección 13) en `Mediciones/<clase>/<experimento>/`, con
    `<clase>` ∈ `cada_1min`, `cada_30s`, `otros`, y archivos `ch1.h5 … ch4.h5`.
  - **Nuevas mediciones (estándar a partir de ahora):** Se organizan en 2 niveles
    agrupadas por probeta y ensayo fechado:
    `Mediciones/<ID_Probeta>/<YYYYMMDD>_<TensionDC>kV_rep<NN>/`
    - `<ID_Probeta>`: Código estándar de probeta (ej. `1V2`, `2V22`, `3V224`, `3V444H`, `4V4444`).
    - Subcarpeta fechada: Fecha (`YYYYMMDD`), tensión DC en el condensador de carga del circuito de impulso (ej. `30kV`) y réplica (ej. `rep01`).
    - Ejemplo: `Mediciones/3V224/20260915_30kV_rep01/`.
  - `listar_mediciones` en `app.py` busca automáticamente carpetas con `ch*.h5`
    a 1 o 2 niveles de profundidad, por lo que reconoce tanto las históricas como las nuevas
    sin requerir cambios de código.
- Archivos por carpeta de medición:
  - `ch1.h5`: Tensión de impulso LI (divisor capacitivo / sincronismo).
  - `ch2.h5`: Corriente de descarga (HFCT, atenuador 30 dB) o sensor reconfigurable.
  - `ch3.h5`: Radiación electromagnética (antena Vivaldi / UHF) o sensor reconfigurable.
  - `ch4.h5`: Monopolo plano bioinspirado (filtro pasa-altos 200 MHz) o sensor reconfigurable.
  - `metadata.yaml`: Metadatos del ensayo generados por `generate_metadata.py`.
  - `registro_disparos.csv`: Registro de los 50 disparos (Npd, detecciones por canal, observaciones).
- Cadencia: cada segmento tiene el atributo `SegmentedTimeTag` [s], instante
  de la descarga relativo al segmento 1 (idéntico en los 4 canales).
  `MEDICIONES` (en `app.py` y `generate_metadata.py`) se calcula por **ruta
  directa** desde `AQUI` (`os.path.join(AQUI, os.pardir, "mediciones",
  "Mediciones")`).
  Cada archivo es un canal con varios **segmentos** (~1.000.003 muestras `int16`).
- Conversión desde el HDF5: `v = raw * YInc + YOrg`, `t = XOrg + i * XInc`.
- Frecuencia de muestreo típica: **Fs = 5 GSa/s** (`XInc = 2e-10 s`).
- Roles de canal:
  - **CH1** = impulso de referencia (fijo, no es trigger).
  - **CH2 / CH3 / CH4** = canales seleccionables como **trigger** (`TRIGGERS`) y cuyos sensores pueden reconfigurarse según la instrumentación conectada.

### Reglas de datos
- **R-D1 · Unidades.** Todo el voltaje se maneja y se muestra en **mV**; el
  tiempo en **µs**. La conversión a mV se hace en un único punto,
  `cargar_segmento` (`… * 1e3`), para que detección, impulso, ventanas, FFT,
  Vpp y energía queden todos en mV automáticamente. Ejes/hover/etiquetas dicen
  `mV`, `µs`, `mV²`, `mV²·µs`.
- **R-D2 · Ventana temporal.** Todo se recorta a `T_MIN..T_MAX` (`-5..30 µs`).
- **R-D3 · Caché de metadatos.** `meta_medicion` cachea nombre de canal y
  escalas por experimento (`_META_CACHE`).

---

## 2. Impulso CH1

Sobre el gráfico principal, la fila de **CH1 muestra la señal promedio filtrada**
(no los segmentos crudos).

- **R-I1 · Señal.** `s_imp` = promedio de CH1 sobre todos los segmentos
  (`promedio_impulso`, `_IMPULSO_CACHE`), luego **pasa-bajos Butterworth de fase
  cero** (`sosfiltfilt`), con frecuencia de corte `IMP_FCORTE = 20e6` (20 MHz) y
  orden `IMP_ORDEN = 4`. Cacheado por experimento en `_IMPULSO_FILT_CACHE` (el
  filtro se aplica una sola vez por experimento; no se recalcula en cada render).
  > **Nota de discrepancia en el código:** Los comentarios y docstrings de
  > `app.py` (`figura`, `impulso_filtrado`, `_dibujar_impulso_ch1`) todavía
  > mencionan históricamente "50 MHz", pero el valor vigente de la constante en
  > el código es `IMP_FCORTE = 20e6` (20 MHz).
- **R-I2 · Tiempos característicos** (`tiempos_impulso`), interpolados a
  sub-muestra. `Vmax = max(s_imp)` en `t_pico`:
  - `t10`, `t30`, `t90`: cruce del 10/30/90 % de `Vmax` en el **flanco de subida**.
  - `t50`: cruce del 50 % en la **cola** (`t > t_pico`).
  - Recta por `(t30, 0.3·Vmax)` y `(t90, 0.9·Vmax)`; `t0_lin` = corte con 0,
    `tmax_lin` = corte con `Vmax`.
  - **T1 se omite** (por decisión del usuario).
- **R-I3 · Dibujo.** Líneas verticales de cada tiempo sobre la fila de CH1,
  valores en una caja estática anclada al dominio del subplot. Trazo del impulso
  decimado a `IMP_PUNTOS_PLOT` puntos (los tiempos se calculan a resolución
  completa). Sin cruces si el tiempo no existe (p. ej. `t50` en impulsos de cola
  larga).
- **R-I4 · Sin resta de baseline.** Los umbrales son fracciones de `max(s_imp)`
  sin restar continua (fiel a la especificación). Revisar si un experimento
  tiene offset relevante.
- **R-I5 · Umbral por defecto.** La función `umbral_defecto(carpeta, canal, seg=1)`
  calcula el 50 % de `max(|v|)` del canal trigger evaluado específicamente sobre el
  **segmento 1**.

---

## 3. Peaks del canal trigger

Toda la lógica de detección y filtrado de peaks se concentra bajo estas reglas
unificadas:

- **R-P1 · Detección con `scipy.signal.find_peaks`.**
  Tanto el conteo en vivo (`_detectar`) como la captura congelada (`capturar`)
  usan `find_peaks(v, height=umbral, distance=distancia)`:
  - `height = umbral`: valor absoluto en mV.
  - `distance`: distancia mínima requerida entre peaks, convertida de µs a número
    entero de muestras con `_muestras`: `max(1, int(round(dist_us / dt_us)))`. Si
    `dist_us` es 0 o vacío, pasa `None` (sin restricción de separación). Con
    $Fs = 5 \text{ GSa/s}$ ($dt = 2 \times 10^{-4} \text{ µs}$), $1 \text{ µs} = 5000 \text{ muestras}$.
  - **Solo máximos positivos:** `find_peaks` busca crestas donde $v[i] > v[i-1]$ y
    $v[i] > v[i+1]$; no detecta valles negativos.
  - **Sin parámetros adicionales:** No se utilizan `prominence`, `width` ni
    `threshold`. La detección depende únicamente de la altura absoluta y de la
    separación temporal.
  - **Filtro temporal previo:** La condición $t \ge t_{\text{mín}}$ se aplica
    **antes** de llamar a `find_peaks`, recortando los arrays `t` y `v` (`t = t[mask]`,
    `v = v[mask]`). Esto acota el inicio de la señal y desplaza el índice cero
    efectivo a $t_{\text{mín}}$.
- **R-P2 · Umbral (línea roja móvil).** El umbral es la posición de la línea
  arrastrable en el gráfico principal. Fuente de verdad: store `umbral`.
  Se inicializa al 50 % de `max(|v|)` del canal trigger en el **segmento 1**
  (`umbral_defecto`) y se reinicia automáticamente al cambiar de canal o de medición.
- **R-P3 · Clasificación: peaks completos vs. peaks "sin ventana".**
  Para cada peak detectado en la muestra $i$ de la señal recortada ($t \ge t_{\text{mín}}$),
  se verifica si la ventana de captura cabe dentro del segmento:
  $a = i - n_{\text{antes}} \ge 0$ y $b = i + n_{\text{desp}} + 1 \le v.\text{size}$.
  - **Peak completo:** Cumple ambas condiciones. Se guarda en `t_peak`, `v_peak`,
    `seg` y su señal se apila en la matriz $W$.
  - **Peak sin ventana:** Si $a < 0$ o $b > v.\text{size}$, se guarda en
    `t_peak_borde`, `v_peak_borde`, `seg_borde`.
    - **Sí cuenta** en el conteo total por segmento (`contar_peaks`), en el gráfico
      de barras y en la tabla de densidad de eventos.
    - En el gráfico principal se dibuja como una **cruz naranja** (`symbol="x", color="orange"`),
      sin `customdata` (no clicable).
    - **No entra** en la matriz $W$ de `capturar` ni en los scatters (Peaks,
      Vpp vs Energía), ni en el visor de ventanas, ni en la FFT ni en la Transformada S.
- **R-P4 · Snapshot de captura.** Al pulsar **"Calcular peaks"**, los parámetros
  se congelan en `captura_params`. Mientras no se pulse el botón, las cruces del
  gráfico principal corresponden a detección en vivo y no son clicables.

### Resumen de participación de peaks por análisis

| Análisis / Visualización | Peaks completos | Peaks sin ventana | Filtrado por selección (`seleccion`) |
|---|:---:|:---:|:---:|
| **Barras de peaks por segmento** (`figura_peaks`) | Sí | Sí | No (todos los del segmento) |
| **Tabla de densidad de eventos** (`tabla_densidad`) | Sí | Sí | No (todos los segmentos) |
| **Cruces negras en gráfico principal** (`figura`) | Sí | No | Clicables (alimentan `seleccion`) |
| **Cruces naranjas en gráfico principal** (`figura`) | No | Sí | No clicables (informativas) |
| **Scatter Peaks** (`figura_scatter`) | Sí | No | Resalta seleccionados en amarillo |
| **Scatter Vpp vs Energía** (`figura_vpp_energia`) | Sí | No | Resalta seleccionados en amarillo |
| **Ventanas temporales** (`figura_ventanas`) | Sí | No | **Solo los seleccionados** |
| **FFT Welch** (`figura_fft`) | Sí | No | **Solo los seleccionados** (promedio) |
| **Transformada S de la ventana** (`figura_st_ventana`) | Sí | No | **Solo los seleccionados** (promedio \|S\|) |

---

## 4. Captura (fuente única de análisis)

Al pulsar **"Calcular peaks"** se fija un *snapshot* de parámetros en el store
`captura_params` = `{carpeta, canal, umbral, dist, tmin}`. **Todos** los análisis
(barras, densidad, scatter Peaks, Vpp/Energía, ventanas, FFT, Transformada S y las
cruces del gráfico principal) derivan de ese snapshot vía `capturar`.

- **R-C1 · `capturar`** (cacheado en `_CAPTURA_CACHE`) detecta los peaks de
  todos los segmentos y extrae una **ventana de 1 µs por peak**: **20 % antes /
  80 % después** del peak (`antes_us = 0.2`, `desp_us = 0.8`), alineada al peak en $t = 0$. Devuelve:
  - `t_rel`: eje temporal relativo al peak (µs), común a todas las ventanas.
  - `W`: matriz ($n_{\text{ventanas}} \times n_{\text{muestras}}$) con las señales capturadas (mV).
  - `t_peak`, `v_peak`: instante (µs) y amplitud (mV) de cada peak con ventana completa.
  - `seg`: segmento de origen de cada ventana completa.
  - `t_peak_borde`, `v_peak_borde`, `seg_borde`: peaks detectados pero demasiado pegados al borde.
  - `dt_us`: paso de muestreo (µs).
- **R-C2 · Criterio de exclusión y borde efectivo.**
  El recorte se valida con $a = i - n_{\text{antes}} < 0$ o $b = i + n_{\text{desp}} + 1 > v.\text{size}$,
  donde $v$ es la señal **ya recortada a $t \ge t_{\text{mín}}$**.
  Como consecuencia directa, el borde izquierdo efectivo para la captura es
  $t_{\text{mín}}$ (y no $T_{\text{MIN}} = -5 \text{ µs}$). Cualquier peak situado
  en el intervalo $[t_{\text{mín}}, t_{\text{mín}} + 0.2 \text{ µs})$ o a menos de
  $0.8 \text{ µs}$ del final del segmento ($T_{\text{MAX}} = 30 \text{ µs}$) se
  clasifica como "sin ventana".
- **R-C3 · Conjunto único y ordenado.** Peaks completos y ventanas comparten
  **exactamente el mismo conjunto y orden**, de modo que el índice $i$ de una fila
  en la matriz $W$ mapea 1:1 al punto $i$ de los scatters.
- **R-C4 · Coherencia.** Mientras no se pulse el botón, los análisis mantienen el
  snapshot anterior aunque se muevan parámetros en la interfaz.

---

## 5. Política de recálculo

- **R-R1.** Cambios que **NO** recalculan automáticamente (son `State`, no `Input`):
  - mover la línea de **umbral**,
  - cambiar **"distancia entre peaks"**,
  - cambiar **"t mín"**.
- **R-R2.** El recálculo de peaks y ventanas ocurre **solo** al pulsar
  **"Calcular peaks"** (modifica el store `captura_params`).
- **R-R3.** El gráfico principal se redibuja al pulsar el botón o al cambiar de
  **segmento / canal / medición**. Al cambiar de canal o medición se fuerza el
  umbral por defecto (evita arrastrar el valor del canal anterior).

---

## 6. Selección de señales (modelo unificado)

Store central **`seleccion`** = lista de índices globales de ventana. Es la única
fuente para el gráfico temporal, la FFT y el resaltado amarillo.

- **R-S1 · Fuentes.** Alimentan la selección (`set_seleccion`):
  1. clic o caja en el scatter **Peaks**,
  2. clic o caja en el scatter **Vpp vs Energía**,
  3. **clic en las cruces negras** del canal trigger en el gráfico principal.
- **R-S2 · Mapeo por fuente** (crítico por fiabilidad de eventos WebGL):
  - Scatters (Peaks, Vpp/Energía): trazas **Scattergl**, la **curva 0** es 1:1
    con las ventanas → se usa **`pointNumber`** (siempre presente). `_idx_scatter`.
  - Cruces del trigger: traza **`go.Scatter` (SVG)** con **`customdata` = índice
    global**; SVG garantiza `customdata` en `clickData`. `_idx_cruces`.
  - **No** usar `customdata` en trazas Scattergl para selección (poco fiable).
  - **`customdata` debe pasarse como lista Python, no ndarray.** Plotly 7
    serializa los arrays numpy en binario (`{dtype, bdata}`) y entonces
    `customdata` **no llega** al `clickData`. Usar `.tolist()`.
- **R-S3 · Resaltado.** El punto seleccionado se marca en **amarillo** (`#FFD400`)
  en **ambos** scatters, venga la selección del scatter que sea o de las cruces.
- **R-S4 · Sin selección.** El gráfico temporal, la FFT y la Transformada S de
  la ventana quedan **vacíos con un aviso** (nunca "todas las señales"). Una
  **nueva captura limpia** la selección.
- **R-S5 · Anti-bucle.** Redibujar los scatters resetea su `selectedData`/
  `clickData` a `None`; `set_seleccion` devuelve `no_update` ante `None` para no
  borrar la selección. `uirevision` (estable por captura) preserva zoom/caja.

---

## 7. Gráficos derivados

- **Barras** (`figura_peaks`): nº de peaks por segmento.
- **Densidad de eventos** (`tabla_densidad`, `dash_table.DataTable` id="tabla_densidad"):
  Distribución de segmentos según la cantidad de peaks que contienen. Presenta filas
  explícitas para $0, 1, 2, \dots, \text{DENSIDAD\_MAX}$ (`DENSIDAD_MAX = 6`) y, si
  algún segmento supera ese valor, añade automáticamente una fila agregada `>6`
  para no perder eventos silenciosamente. Columnas:
  - `peaks`: "N° de peaks",
  - `n_segmentos`: "N° de segmentos",
  - `pct`: "% de segmentos".
- **Scatter Peaks** (`figura_scatter`): `t_peak` vs `v_peak` (+ CH1 promedio de ref.).
- **Vpp vs Energía** (`figura_vpp_energia`): por señal capturada,
  `Vpp = ptp(ventana)` [mV], `Energía = Σ v² · dt_us` [mV²·µs].
- **Ventanas** (`figura_ventanas`): señales seleccionadas superpuestas, alineadas
  al peak ($t = 0$). Decimadas a ~300 puntos para visualización ágil.
- **FFT** (`figura_fft`): `scipy.signal.welch(scaling="spectrum")`, **escala
  lineal** (mV²), promediando el espectro de las ventanas seleccionadas.
  `nperseg = min(len, 1024)`, eje en MHz (hasta Nyquist = Fs/2).

### Límites de cálculo de la FFT

A partir de las constantes y configuración vigentes ($XInc = 2 \times 10^{-10} \text{ s} \implies Fs = 5 \text{ GSa/s}$,
$dt = 2 \times 10^{-4} \text{ µs}$, `antes_us = 0.2`, `desp_us = 0.8`):

- **Longitud de la señal analizada:**
  $n_{\text{antes}} = \text{round}(0.2 / 2 \times 10^{-4}) = 1000$ muestras,
  $n_{\text{desp}} = \text{round}(0.8 / 2 \times 10^{-4}) = 4000$ muestras.
  La ventana temporal contiene $[-1000, 4000]$ muestras, es decir **5001 muestras** ($1 \text{ µs}$).
- **Parámetros de Welch:**
  - `nperseg = min(5001, 1024) = 1024`.
  - Welch utiliza por defecto una ventana Hann con 50 % de solapamiento (`noverlap = 512`),
    lo que da un salto de 512 muestras entre bloques.
  - Sub-segmentos promediados por ventana individual:
    $$\frac{5001 - 512}{512} = 8 \text{ sub-segmentos}$$
  - **Doble promediado:** Welch promedia los 8 sub-segmentos dentro de cada
    señal capturada para reducir varianza. Luego, `figura_fft` promedia esos
    espectros resultantes **entre todas las señales seleccionadas** en el store `seleccion`.
    Este doble promedio suaviza el espectro final.
- **Resolución en frecuencia:**
  $$\Delta f = \frac{Fs}{\text{nperseg}} = \frac{5 \times 10^9 \text{ Sa/s}}{1024} \approx 4.8828 \text{ MHz por bin}$$
  - Componentes espectrales separadas por menos de $\sim 10 \text{ MHz}$ (2 bins)
    no pueden resolverse de forma independiente.
  - Cualquier componente de frecuencia inferior a $\sim 5 \text{ MHz}$ cae en el
    bin 0 (continua) o en el bin 1.
- **Rango de frecuencia:**
  De 0 a Nyquist ($Fs / 2 = 2500 \text{ MHz}$).
  El control `f máx ST` **no** afecta a la FFT; la FFT siempre muestra el rango
  completo hasta Nyquist.
- **Escala y nivel de continua:**
  - `scaling="spectrum"` entrega $\text{mV}^2$ (potencia por bin de frecuencia, no
    densidad espectral $\text{mV}^2/\text{Hz}$). Eje vertical lineal.
  - Welch aplica por defecto `detrend="constant"`, eliminando la componente continua
    (media) de cada sub-segmento de 1024 muestras.
- **Resolución temporal / decimado:**
  La FFT se calcula sobre la ventana a resolución completa (las 5001 muestras sin decimar).

---

## 8. Transformada S (Stockwell)

Algoritmo rápido vía FFT (`transformada_s`, Stockwell 1996):
Para cada frecuencia (bin lineal $j$, $f_j = j / (N \cdot dt_{\text{µs}}) \text{ MHz}$),
$$S_j[n] = \text{IFFT}\left\{ X[(m+j) \bmod N] \cdot \exp\left(-\frac{2\pi^2 m^2}{j^2}\right) \right\}[n]$$
donde $X = \text{FFT}(x)$, $m$ es el índice de frecuencia centrado ($-N/2 \dots N/2-1$)
y $n$ es el tiempo discreto.

Dos escalas, compartiendo la misma función:
- **Ventana de 1 µs** (`figura_st_ventana`): la **misma ventana que la FFT**
  (`cap["W"]`, R-C1). Con varias señales seleccionadas se **promedia $|S|$** (magnitud).
  Vive en la tarjeta de la FFT, alternando por pestañas "FFT" | "Transformada S"
  (`tabs_espectro`).
- **Segmento completo** (`figura_st_segmento` / `st_segmento`, `_ST_SEG_CACHE`):
  una fila por canal presente (`ch1..ch4`), con la **señal cruda del segmento**
  (`cargar_segmento`) — también para CH1 (señal cruda, no el impulso promedio filtrado).
  Vive en la tarjeta del gráfico principal, alternando por pestañas "Señales" | "Transformada S"
  (`tabs_principal`).

### Límites de cálculo de la Transformada S

- **Resolución en frecuencia mostrada (fijada por `f máx` y `ST_NFREQ`):**
  - La cantidad de filas en el mapa de calor no depende de $N$, sino de `ST_NFREQ = 250`
    y de `f máx` (control `st_fmax`, por defecto `ST_FMAX_MHZ = 2500` MHz).
  - Se definen $j_{\text{max}} = \min(N // 2, \text{round}(f_{\text{máx}} \cdot N \cdot dt))$
    y $js = \text{unique}(\text{round}(\text{linspace}(1, j_{\text{max}}, \min(250, j_{\text{max}}))))$.
  - Con 250 bins lineales entre 0 y $f_{\text{máx}}$, la separación entre filas es
    $$\Delta f_{\text{mapa}} \approx \frac{f_{\text{máx}}}{250}$$
    - Con $f_{\text{máx}} = 2500 \text{ MHz}$ (defecto): $\Delta f \approx 10 \text{ MHz}$ por fila.
    - Con $f_{\text{máx}} = 500 \text{ MHz}$: $\Delta f \approx 2 \text{ MHz}$ por fila.
  - **Resolución natural de la FFT de fondo vs. grilla visual:**
    La resolución física elemental de la FFT de fondo es $\Delta f_{\text{FFT}} = 1 / (N \cdot dt)$:
    $\sim 1 \text{ MHz}$ en la ventana de $1 \text{ µs}$ ($N = 5001$) y
    $\sim 0.0286 \text{ MHz} \approx 29 \text{ kHz}$ en el segmento de $35 \text{ µs}$ ($N = 175\,001$).
    Esta resolución fina **no se mapea por completo** en el gráfico: solo se evalúan
    hasta 250 frecuencias seleccionadas, de modo que con $f_{\text{máx}}$ alto el
    mapa visual es más grueso que el espectro físico disponible. Si $j_{\text{max}} < 250$,
    se evalúan todos los bins enteros disponibles (y tras `unique` puede haber menos de 250 filas).
  - **Resolución intrínseca de la Transformada S:**
    El ancho de la gaussiana en frecuencia es proporcional a la frecuencia ($\sigma_f \propto f$),
    lo que equivale en tiempo a una ventana de ancho $\propto 1/f$. A frecuencias bajas se
    obtiene alta resolución en frecuencia y baja resolución temporal; a frecuencias altas,
    alta resolución temporal y baja resolución en frecuencia.
- **Límite inferior de frecuencia:**
  La primera fila distinta de continua corresponde a $j = 1$, es decir
  $f_1 = 1 / (N \cdot dt)$: $\approx 1 \text{ MHz}$ en la ventana de $1 \text{ µs}$ y
  $\approx 0.029 \text{ MHz}$ en el segmento completo. Una ventana de $1 \text{ µs}$ no
  puede representar fenómenos de frecuencia inferior a $1 \text{ MHz}$ (su duración
  no cubre un ciclo completo). La fila $f = 0$ almacena el valor constante
  $|\text{media}(x)|$ repetido en todas las columnas de tiempo; no representa resolución temporal.
- **Límite superior y recorte a Nyquist:**
  `f máx` se recorta estrictamente a Nyquist ($N // 2$ bins = $2500 \text{ MHz}$ a $5 \text{ GSa/s}$),
  cualquiera sea el valor que el usuario introduzca en `st_fmax`. Si el campo queda
  vacío, se toma `ST_FMAX_MHZ = 2500`.
- **Resolución temporal y factor de decimado:**
  Las operaciones FFT e IFFT se ejecutan siempre a resolución completa sobre las $N$
  muestras. El resultado se decima exclusivamente al construir la matriz final mediante
  `paso = max(1, N // n_t)`:
  - **Ventana de 1 µs:** $N = 5001$, `ST_NT_VENTANA = 500` $\implies \text{paso} = 5001 // 500 = 10$.
    Cada columna dista $10 \times 2 \times 10^{-4} \text{ µs} = 2 \text{ ns}$ ($\sim 501$ columnas de tiempo).
  - **Segmento completo (-5..30 µs = 35 µs):** $N \approx 175\,001$, `ST_NT_SEGMENTO = 1000` $\implies \text{paso} = 175001 // 1000 = 175$.
    Cada columna dista $175 \times 0.2 \text{ ns} = 35 \text{ ns}$ ($\sim 1001$ columnas de tiempo).
  - **Consecuencia del decimado:** Se realiza por submuestreo directo (`[::paso]`),
    no por promedio ni por envolvente de máximos. Por tanto, eventos transitorios
    con duración inferior a $\sim 35 \text{ ns}$ en el segmento completo pueden
    caer entre columnas y atenuarse visualmente. El mapa del segmento sirve para
    ubicar intervalos temporales con actividad; para el análisis morfológico fino
    se utiliza la Transformada S de la ventana de $1 \text{ µs}$.
- **Efectos de borde (periodicidad circular):**
  La formulación discreta vía FFT asume periodicidad de la señal. En las proximidades
  de los bordes ($-0.2$ y $+0.8 \text{ µs}$ en la ventana; $-5$ y $+30 \text{ µs}$
  en el segmento) pueden aparecer artefactos de energía espuria. Este efecto es más
  notorio a bajas frecuencias, donde la campana temporal de la ventana gaussiana es
  más extendida.
- **Truncamiento de la gaussiana y subnormales:**
  La gaussiana solo se evalúa en su soporte $|m| \le 1.2 j$; fuera de ese intervalo
  se fuerza a 0.0. En el corte, la función decae a:
  $$\exp(-2\pi^2 \cdot 1.2^2) = \exp(-2\pi^2 \cdot 1.44) \approx 4.5 \times 10^{-13}$$
  lo que garantiza una pérdida de precisión analítica despreciable ($< 10^{-12}$).
  Su objetivo es evitar la aritmética de números de punto flotante subnormales, que
  degrada drásticamente la velocidad de CPU al operar con valores de `f máx` reducidos.
- **Rendimiento, caché y promediado:**
  - El cálculo se vectoriza en bloques de 16 frecuencias (`bloque = 16`) y utiliza
    `scipy.fft` con soporte multihilo (`workers = -1`).
  - La ST del segmento completo se cachea en `_ST_SEG_CACHE` con clave
    `(carpeta, seg, canal, fmax_mhz)`.
  - La ST de la ventana **no tiene caché** y se evalúa bajo demanda para cada
    señal presente en `seleccion`, de modo que su costo computacional crece linealmente
    con el número de señales seleccionadas.
  - En multi-selección se promedia la **magnitud $|S|$** (matriz de reales positivos),
    evitando la cancelación de fase que ocurriría si se promediara el espectro complejo.
  - Calibración de escala verificada: una sinusoide pura de amplitud $A$ produce
    un valor pico $|S| \approx A/2$ en su frecuencia.

---

## 9. Reglas de rendimiento

- **R-PF1.** Trazas grandes en **WebGL** (`go.Scattergl`).
- **R-PF2.** No mezclar capas SVG con WebGL en gráficos pesados. Excepción única:
  la traza de **cruces** del trigger (`go.Scatter`, pocos puntos) por fiabilidad
  de `customdata`.
- **R-PF3.** Decimar curvas suaves para dibujar (impulso a `IMP_PUNTOS_PLOT = 6000`,
  ventanas a ~300 puntos); los cálculos van a resolución completa.
- **R-PF4.** `uirevision` para conservar estado de UI y evitar re-render completo.
- **R-PF5.** Caches de sesión: `_META_CACHE`, `_IMPULSO_CACHE`,
  `_IMPULSO_FILT_CACHE`, `_CAPTURA_CACHE` (claves con `umbral` redondeado),
  `_ST_SEG_CACHE` (clave con `carpeta, segmento, canal, f máx`).
- **R-PF6.** Las Transformadas S solo se calculan si su pestaña está visible
  (`tabs_principal`/`tabs_espectro` como `Input`; `no_update` si no coincide):
  cambiar de segmento/medición mientras se ve "Señales" no dispara el cálculo
  del segmento completo. El panel "Señales" **no se desmonta** al cambiar de
  pestaña (se oculta con `hidden`), así se conserva la línea de umbral
  arrastrada, el zoom y el estado de clic de `grafico`.

---

## 10. Mapa de callbacks

| Callback | Entrada(s) | Salida(s) |
|---|---|---|
| `actualizar_segmentos` | `carpeta` | opciones y valor de `segmento` |
| `actualizar` | `carpeta, segmento, canal, captura_params` (+State dist, tmin, umbral) | `grafico.figure` |
| `set_umbral` | `grafico.relayoutData, canal, carpeta` | `umbral.data` |
| `mostrar_umbral` | `umbral.data` | `umbral_txt.children` |
| `fijar_captura` | `btn.n_clicks` (+State carpeta, canal, dist, tmin, umbral) | `captura_params.data` |
| `calcular_peaks` | `captura_params.data` | `grafico_peaks.figure, tabla_densidad.data` |
| `set_seleccion` | `captura_params.data, grafico_scatter.selectedData, grafico_scatter.clickData, grafico_vpp_energia.selectedData, grafico_vpp_energia.clickData, grafico.clickData` (+State captura_params) | `seleccion.data` |
| `actualizar_scatter` | `captura_params.data, seleccion.data` | `grafico_scatter.figure, grafico_vpp_energia.figure` |
| `actualizar_temporal` | `seleccion.data` (+State `captura_params`) | `grafico_ventanas.figure, grafico_fft.figure` |
| `alternar_panel_principal` | `tabs_principal.value` | `panel_senales.hidden, panel_st_segmento.hidden` |
| `actualizar_st_segmento` | `tabs_principal.value, carpeta, segmento, st_fmax` | `grafico_st_segmento.figure` |
| `actualizar_st_ventana` | `seleccion.data, tabs_espectro.value, st_fmax` (+State `captura_params`) | `grafico_st_ventana.figure` |
| `seleccionar_segmento` | `grafico_peaks.clickData` | `segmento.value` |

---

## 11. Layout

- **Fila de controles:** medición (`carpeta`), segmento (`segmento`), trigger (`canal`),
  distancia (`dist`), t mín (`tmin`), botón "Calcular peaks" (`btn`), texto de umbral
  (`umbral_txt`), f máx ST (`st_fmax`).
- **Fila central (2 columnas):**
  - Columna izquierda: Gráfico principal con pestañas **Señales** (4 filas ch1..ch4) /
    **Transformada S** (4 mapas de calor, mismo eje de tiempo) — `tabs_principal`.
  - Columna derecha:
    - Tarjeta superior: Pestañas **Peaks por segmento** (`grafico_peaks`) /
      **Densidad de eventos** (`tabla_densidad`, `dash_table.DataTable` con distribución
      0..6 y fila `>6`) — `tabs_peaks`.
    - Tarjeta inferior: Pestañas **Peaks** (`grafico_scatter`) /
      **Vpp vs Energía** (`grafico_vpp_energia`) — `tabs_scatter`.
- **Última fila (2 columnas):**
  - Columna izquierda: **Ventanas** (`grafico_ventanas`), señales superpuestas alineadas en $t = 0$.
  - Columna derecha: Pestañas **FFT** (`grafico_fft`) / **Transformada S**
    (`grafico_st_ventana`), ambas aplicadas sobre las señales seleccionadas de la ventana de 1 µs — `tabs_espectro`.

---

## 12. Casos borde conocidos

- **Medición sin canal CH1:** La fila de CH1 muestra "no disponible".
- **`t50` inexistente:** Impulso con cola larga que no llega a descender al 50 % de su valor máximo dentro de la ventana de recorte.
- **Impulso con baseline alto:** Si no hay cruces de subida claros, `t0_lin` y `tmax_lin` quedan en `None`.
- **Detección previa al botón "Calcular peaks":** Las cruces visibles en el gráfico principal corresponden a la detección reactiva local con los controles de la UI; no poseen `customdata` y no son clicables hasta pulsar el botón.
- **Peaks pegados al borde del segmento o de $t_{\text{mín}}$:** Si un peak detectado dista menos de $0.2 \text{ µs}$ de $t_{\text{mín}}$ o menos de $0.8 \text{ µs}$ de $T_{\text{MAX}}$, su ventana de $1 \text{ µs}$ queda incompleta. Se dibuja como una cruz naranja en el gráfico principal ("peak sin ventana", no clicable), se incluye en el conteo total por segmento y en la tabla de densidad, pero queda excluido de los scatters, ventanas superpuestas, FFT y Transformada S.

---

## 13. Scripts auxiliares (fuera de la app)

- **`preprocesar.py`.** Filtro paso-alto Butterworth de fase cero (`sosfiltfilt`,
  **5 MHz**, orden 4) aplicado a cada segmento de `ch2.h5` (señal completa, no
  ventaneada). Genera un archivo extra `ch2_hp5MHz.h5` con la **misma
  estructura** de grupos/datasets que el original (mismos nombres), pero con
  los datos ya en **voltios** (`YInc=1`, `YOrg=0`) para que `app.py` lo cargue
  sin cambios. Se ejecuta manualmente y una sola vez por medición
  (`python3 preprocesar.py`); **no** se invoca desde la app.

- **`generate_metadata.py`.** Genera una **plantilla YAML** de metadatos enriquecida
  por medición: `Mediciones/<experimento>/metadata.yaml` (usa `PyYAML` y `h5py`, ver
  `requirements.txt`). No sobrescribe un `metadata.yaml` existente salvo que se pase `--forzar`.
  Ejecutar: `python generate_metadata.py <experimento> [--forzar]`.
  
  **Características principales:**
  1. **Extracción automática desde los archivos `.h5`:** Lee directamente los encabezados del osciloscopio (Keysight Infiniium DSOS804A) para autocompletar el modelo, serial, fecha de adquisición, base de tiempo (frecuencia de muestreo en GSa/s, ventana temporal total en µs, puntos y segmentos) y las **escalas verticales de cada canal** (`escala_v_div`, `rango_total_v`, `offset_v`).
  2. **Inferencia por nombre de carpeta:** Si la ruta sigue el formato estándar `3V224/20260915_30kV_rep01`, infiere automáticamente el código de probeta (`3V224`), tipo de geometría (`mixta`, `monodiametro` o `asimetrica`), número de vacuolas (`3`) y la tensión DC de carga (`30.0 kV`).
  3. **Trigger y Canales configurables:** CH1 queda preasignado al divisor capacitivo de tensión de impulso / sincronismo. Los canales CH2, CH3 y CH4 vienen preconfigurados pero permiten renombrar el sensor, función, atenuación y filtros según la instrumentación conectada en el ensayo.

  Esquema YAML generado:

  ```yaml
  experimento:
    id: 3V224/20260915_30kV_rep01
    fecha_hora: 10-Sep-2026 11:31:11     # Leído del osciloscopio (o a mano)
    temperatura_c: null                  # Temperatura ambiente [°C]
    humedad_relativa_pct: null           # Humedad relativa [%]

  circuito_impulso:
    forma_onda_nominal: 1.2/50us         # Norma IEC 60060-1
    tension_v_ac_prim: null              # Tensión Variac primario [V AC]
    tension_kv_ac_sec: null              # Secundario transformador elevador [kV AC]
    tension_dc_condensador_kv: 30.0      # Condensador de carga previo al disparo [kV DC]
    polaridad: positiva                  # positiva / negativa
    nro_disparos_programados: 50         # Nro de impulsos nominales
    intervalo_entre_disparos_s: 30.0     # Intervalo entre descargas [s]

  probeta:
    codigo: 3V224                        # Identificador de probeta
    tipo_geometria: mixta                # monodiametro / mixta / asimetrica
    descripcion: Pressboard sumergido en aceite mineral
    nro_capas_total: 4
    espesor_capa_mm: 0.48
    nro_vacuolas: 3
    vacuolas: []                         # lista de {id, diametro_mm, capa}
    distancias_entre_vacuolas_mm: []     # N-1 distancias
    fotos: []

  osciloscopio:
    modelo: DSOS804A
    serial: MY60060103
    fecha_adquisicion: 10-Sep-2026 11:31:11
    frecuencia_muestreo_gsas: 5.0        # Fs = 5 GSa/s
    tiempo_total_ventana_us: 200.0       # Ventana horizontal completa [µs]
    escala_tiempo_us_div: 20.0           # Base de tiempo [µs/div]
    num_segmentos_capturados: 50
    puntos_por_segmento: 1000003

  trigger:
    canal_origen: ch1                    # Canal de sincronismo
    tipo: flanco                         # flanco (edge)
    pendiente: positiva                  # positiva / negativa
    nivel_v: null                        # Nivel de umbral de disparo en osciloscopio [V]
    posicion_horizontal_pct: 10.0

  canales:
    ch1:
      sensor: Divisor capacitivo         # Fijo para impulso LI
      funcion: Tension LI / Sincronismo
      unidad: kV
      atenuacion_db: 0
      escala_v_div: 1.0                  # Extraído de YDispRange / 8
      offset_v: 0.0                      # Extraído de YDispOrigin
      rango_total_v: 8.0
    ch2:
      sensor: HFCT                       # Reconfigurable por el usuario
      funcion: Corriente PD
      unidad: V
      atenuacion_db: 30
      escala_v_div: 0.5
      offset_v: 0.0
      rango_total_v: 4.0
    ch3:
      sensor: Antena Vivaldi             # Reconfigurable por el usuario
      funcion: UHF Banda ancha
      unidad: V
      filtro: ninguno
      escala_v_div: 0.5
      offset_v: 0.0
      rango_total_v: 4.0
    ch4:
      sensor: Antena Bioinspirada        # Reconfigurable por el usuario
      funcion: UHF / Resolucion picos frente
      unidad: V
      filtro: HP_200MHz
      escala_v_div: 0.5
      offset_v: 0.0
      rango_total_v: 4.0
  ```

- **`cadencia.py`.** Diagnostica y clasifica la cadencia de adquisición de cada
  medición a partir del atributo `SegmentedTimeTag` [s] de cada segmento
  (`Waveforms/Channel N/Channel N SegKData`, relativo al segmento 1; idéntico
  en los 4 canales). Calcula Δt entre descargas consecutivas y clasifica por
  la **mediana**: a ±2 s de 60 s → `cada_1min`; a ±2 s de 30 s → `cada_30s`;
  si no → `otros`. Un Δt que se aparta más de 2 s del nominal de su clase se
  marca como **anómalo** en el reporte (no cambia la clasificación).
  - `python3 cadencia.py` → simulacro: genera `archivos_md/reporte_cadencia.md`
    (tabla resumen, conteo por clase, anomalías, Δt por medición) y
    `cadencia_segmentos.csv` (`medicion, segmento, time_tag_s, dt_s, anomalo,
    clase`), e imprime qué movería sin mover nada.
  - `python3 cadencia.py --mover` → además mueve cada medición a
    `Mediciones/<clase>/<medición>/`. Es idempotente: si ya está en su
    carpeta no la toca, y si el destino ya existe no sobrescribe.
