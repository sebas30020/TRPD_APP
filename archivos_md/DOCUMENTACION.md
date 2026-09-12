# Visor de Vacuolas — Documentación y reglas internas

Aplicación Dash (`app.py`) para explorar mediciones de osciloscopio Keysight y
analizar los impulsos y los peaks del canal trigger. Este documento recoge las
**reglas internas** que el programa debe respetar; actualízalo cada vez que se
añada o cambie una funcionalidad.

---

## 1. Datos

- Carpeta de datos: `../mediciones/Mediciones/` (hermana del repo, fuera de
  `TRPD_APP`). Las mediciones están clasificadas por cadencia de adquisición
  (ver `cadencia.py`, sección 13) en `Mediciones/<clase>/<experimento>/`, con
  `<clase>` ∈ `cada_1min`, `cada_30s`, `otros`, y archivos `ch1.h5 … ch4.h5`.
  `listar_mediciones` busca carpetas con `ch*.h5` directamente en
  `Mediciones/` o un nivel más abajo; el identificador de medición es la ruta
  relativa (p. ej. `cada_30s/7`).
- Cadencia: cada segmento tiene el atributo `SegmentedTimeTag` [s], instante
  de la descarga relativo al segmento 1 (idéntico en los 4 canales).
  `MEDICIONES` (en `app.py` y `generate_metadata.py`) se calcula por **ruta
  directa** desde `AQUI` (`os.path.join(AQUI, os.pardir, "mediciones",
  "Mediciones")`). Antes se accedía vía un symlink `Mediciones` dentro del
  repo; se retiró porque git en Windows no lo versiona correctamente
  (`core.symlinks=false`).
  Cada archivo es un canal con varios **segmentos** (~1.000.003 muestras `int16`).
- Conversión desde el HDF5: `v = raw * YInc + YOrg`, `t = XOrg + i * XInc`.
- Frecuencia de muestreo típica: **Fs = 5 GSa/s** (`XInc = 2e-10 s`).
- Roles de canal:
  - **CH1** = impulso de referencia (no es trigger).
  - **CH2 / CH3 / CH4** = canales seleccionables como **trigger** (`TRIGGERS`).

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
  cero** (`sosfiltfilt`), `IMP_FCORTE`, orden `IMP_ORDEN`. Cacheado por
  experimento en `_IMPULSO_FILT_CACHE` (el filtro se aplica una sola vez por
  experimento; no se recalcula en cada render).
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

---

## 3. Peaks del canal trigger

- **R-P1 · Detección.** `scipy.signal.find_peaks` con:
  - `height = umbral` (mV),
  - `distance` = "distancia entre peaks" (µs → muestras, `_muestras`),
  - solo `t ≥ tmin`.
- **R-P2 · Umbral (línea roja móvil).** El umbral es la posición de la línea
  arrastrable. Fuente de verdad: store `umbral`. Se reinicia al valor por
  defecto (50 % del `|pico|`) al cambiar de canal o de medición.

---

## 4. Captura (fuente única de análisis)

Al pulsar **"Calcular peaks"** se fija un *snapshot* de parámetros en el store
`captura_params` = `{carpeta, canal, umbral, dist, tmin}`. **Todos** los análisis
(barras, densidad, scatter Peaks, Vpp/Energía, ventanas, FFT y las cruces del
gráfico principal) derivan de ese snapshot vía `capturar`.

- **R-C1 · `capturar`** (cacheado en `_CAPTURA_CACHE`) detecta los peaks de
  todos los segmentos y extrae una **ventana de 1 µs por peak**: **20 % antes /
  80 % después** del peak, alineada al peak en `t=0`. Devuelve:
  `t_rel`, `W` (matriz nº_ventanas × muestras), `t_peak`, `v_peak`, `seg`, `dt_us`.
- **R-C2 · Conjunto único y ordenado.** Peaks y ventanas comparten **exactamente
  el mismo conjunto y orden**, de modo que el índice de un punto en cualquier
  gráfico mapea 1:1 a la misma ventana. Solo se conservan ventanas **completas**
  (se descartan peaks pegados al borde de la ventana temporal).
- **R-C3 · Coherencia.** Mientras no se pulse el botón, los análisis mantienen el
  snapshot anterior aunque se muevan parámetros en la interfaz.

---

## 5. Política de recálculo

- **R-R1.** Cambios que **NO** recalculan (son `State`, no `Input`):
  - mover la línea de **umbral**,
  - cambiar **"distancia entre peaks"**,
  - cambiar **"t mín"**.
- **R-R2.** El recálculo de peaks/ventanas ocurre **solo** al pulsar
  **"Calcular peaks"** (cambia `captura_params`).
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
- **Densidad** (`figura_densidad`): nº de segmentos que tienen cada nº de peaks.
- **Scatter Peaks** (`figura_scatter`): `t_peak` vs `v_peak` (+ CH1 promedio ref).
- **Vpp vs Energía** (`figura_vpp_energia`): por señal capturada,
  `Vpp = ptp(ventana)` [mV], `Energía = Σ v² · dt_us` [mV²·µs].
- **Ventanas** (`figura_ventanas`): señales seleccionadas superpuestas, alineadas
  al peak (`t=0`).
- **FFT** (`figura_fft`): `scipy.signal.welch(scaling="spectrum")`, **escala
  lineal** (mV²), promediando el espectro de las ventanas seleccionadas.
  `nperseg = min(len, 1024)`, eje en MHz (hasta Fs/2).

---

## 8. Transformada S (Stockwell)

Algoritmo rápido vía FFT (`transformada_s`): para cada frecuencia (bin lineal
`j`, `f_j = j/(N·dt_us)` MHz), `S_j = IFFT{ X[(m+j) mod N] · exp(-2π²m²/j²) }`,
con `X = FFT(x)` y `m` el índice de frecuencia centrado. La fila `f=0` es
`|media(x)|`. La magnitud `|S|` queda en las mismas unidades que la señal
(mV); un tono de amplitud `A` da `|S| ≈ A/2` en su frecuencia (verificado).
`f máx` (control `st_fmax`, por defecto `ST_FMAX_MHZ = 2500` MHz = Nyquist a
Fs = 5 GSa/s) se recorta siempre a Nyquist (`N//2`). Por rendimiento, las
frecuencias se procesan en bloques con `scipy.fft` multihilo
(`workers=-1`) y la gaussiana solo se evalúa en su soporte (`|m| ≤ 1.2·j`)
para evitar aritmética de subnormales, que ralentiza el cálculo con `f máx`
bajo.

Dos escalas, compartiendo la implementación:
- **Ventana de 1 µs** (`figura_st_ventana`): la **misma ventana que la FFT**
  (`cap["W"]`, la captura de `capturar`, R-C1). Con varias señales
  seleccionadas se **promedia `|S|`** (igual que la FFT). Vive en la tarjeta
  de la FFT, alternando por pestañas "FFT" | "Transformada S"
  (`tabs_espectro`), igual que "Peaks" | "Vpp vs Energía".
- **Segmento completo** (`figura_st_segmento`/`st_segmento`, `_ST_SEG_CACHE`):
  una fila por canal presente (ch1..ch4), con la **señal cruda del segmento**
  (`cargar_segmento`) — también para CH1 (no el impulso promedio filtrado de
  la fila de CH1 en `figura`). Vive en la tarjeta del gráfico principal,
  alternando por pestañas "Señales" | "Transformada S" (`tabs_principal`).

---

## 9. Reglas de rendimiento

- **R-PF1.** Trazas grandes en **WebGL** (`go.Scattergl`).
- **R-PF2.** No mezclar capas SVG con WebGL en gráficos pesados. Excepción única:
  la traza de **cruces** del trigger (`go.Scatter`, pocos puntos) por fiabilidad
  de `customdata`.
- **R-PF3.** Decimar curvas suaves para dibujar (impulso a `IMP_PUNTOS_PLOT`,
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
| `actualizar_segmentos` | `carpeta` | opciones/valor de `segmento` |
| `actualizar` | `carpeta, segmento, canal, captura_params` (+State dist/tmin/umbral) | `grafico.figure` |
| `set_umbral` | `grafico.relayoutData, canal, carpeta` | `umbral.data` |
| `mostrar_umbral` | `umbral.data` | `umbral_txt` |
| `fijar_captura` | `btn` (+State params) | `captura_params.data` |
| `calcular_peaks` | `captura_params` | barras + densidad |
| `set_seleccion` | click/box de 2 scatters + `grafico.clickData` + `captura_params` | `seleccion.data` |
| `actualizar_scatter` | `captura_params, seleccion` | scatter Peaks + Vpp/Energía |
| `actualizar_temporal` | `seleccion` (+State `captura_params`) | ventanas + FFT |
| `alternar_panel_principal` | `tabs_principal` | `hidden` de los paneles Señales/Transformada S |
| `actualizar_st_segmento` | `tabs_principal, carpeta, segmento, st_fmax` | `grafico_st_segmento.figure` |
| `actualizar_st_ventana` | `seleccion, tabs_espectro, st_fmax` (+State `captura_params`) | `grafico_st_ventana.figure` |
| `seleccionar_segmento` | `grafico_peaks.clickData` | `segmento.value` |

---

## 11. Layout

- Fila de controles: medición, segmento, trigger, distancia, t mín, botón,
  umbral, **f máx ST (MHz)**.
- Fila central (2 columnas):
  - Gráfico principal con pestañas **Señales** (4 filas ch1..ch4) /
    **Transformada S** (4 mapas de calor, mismo eje de tiempo) — `tabs_principal`.
  - Pestañas *Peaks por segmento / Densidad* y pestañas *Peaks / Vpp vs Energía*.
- Última fila (2 columnas): **Ventanas** | pestañas **FFT** / **Transformada S**
  (`tabs_espectro`), esta última de la ventana de 1 µs.

---

## 12. Casos borde conocidos

- Experimento sin CH1 → fila de CH1 muestra "no disponible".
- `t50` inexistente (impulso de cola larga que no baja al 50 % en la ventana).
- Peaks sin cruces de subida (baseline alto) → sin `t0_lin`/`tmax_lin`.
- Antes de pulsar el botón, las cruces son de detección en vivo (no clicables).

---

## 13. Scripts auxiliares (fuera de la app)

- **`preprocesar.py`.** Filtro paso-alto Butterworth de fase cero (`sosfiltfilt`,
  **5 MHz**, orden 4) aplicado a cada segmento de `ch2.h5` (señal completa, no
  ventaneada). Genera un archivo extra `ch2_hp5MHz.h5` con la **misma
  estructura** de grupos/datasets que el original (mismos nombres), pero con
  los datos ya en **voltios** (`YInc=1`, `YOrg=0`) para que `app.py` lo cargue
  sin cambios. Se ejecuta manualmente y una sola vez por medición
  (`python3 preprocesar.py`); **no** se invoca desde la app.

- **`generate_metadata.py`.** Genera una **plantilla YAML** de metadatos por
  medición: `Mediciones/<experimento>/metadata.yaml` (usa `PyYAML`, ver
  `requirements.txt`). No sobrescribe un `metadata.yaml` existente salvo que
  se pase `--forzar`. Ejecutar: `python3 generate_metadata.py <experimento>
  [--forzar]`. Esquema generado (valores en blanco/`null`, a completar a mano
  con los datos del experimento — condiciones ambientales, tensiones
  aplicadas y descripción de la probeta):

  ```yaml
  medicion:
    fecha_hora: null                     # fecha y hora del experimento
    humedad_relativa_pct: null
    temperatura_c: null
    tension_kv_ac_sec: null              # tensión kV AC secundario
    tension_v_ac_prim: null              # tensión V AC primario
    voltaje_dc_kv: null
    probeta:
      descripcion: ''
      nro_vacuolas: null
      nro_capas_total: null
      vacuolas: []                       # lista de {diametro_mm, altura_mm, posicion}
      distancias_entre_vacuolas_mm: []   # N-1 distancias
      fotos: []                          # rutas/nombres de archivo
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
