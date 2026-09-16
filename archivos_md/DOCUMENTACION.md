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
10. **Calibración de retardo instrumental y sincronización TRPD:**
    El retardo instrumental $\bar{t}_{\text{lag}, c}$ por canal (leído de `metadata.yaml` bajo `calibracion_retardo` o ingresado en sesión) se gestiona centralizadamente en `calibracion_store`. El gráfico TRPD (`figura_scatter`) y la tabla de densidad de eventos (`tabla_densidad`) calculan el tiempo absoluto sincronizado $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$, garantizando la alineación física precisa de todas las descargas respecto al origen de tensión en la probeta.

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
promedio_impulso() /                       | (pestaña "Transformada S"     | (control canal trigger,
t10_por_segmento()                         |  en tabs_principal;           |  umbral, dist_us, tmin)
(t10 individual por seg.)                  |  control st_fmax)             v
          |                                v                     _detectar() / capturar()
impulso_filtrado()                         st_segmento() /               (find_peaks en t >= tmin)
(Butterworth pasa-bajos                    figura_st_segmento()                    |
 20 MHz, orden 4)                          (ST cruda de ch1..ch4,                  v
          |                                cacheada por sesión)          Bifurcación en capturar()
tiempos_impulso()                                                         (botón "Calcular peaks")
(t10, t30, t90, t50,                                                      +--------+--------+
 t0_lin, tmax_lin)                                                        |                 |
          |                                                               v                 v
          |      [ Calibración t_lag ]                             Peaks completos    Peaks sin ventana
          |   (calibracion_store / metadata)                      (con margen 70 ns)  (muy cerca de borde/tmin)
          |                 |                                             |                 |
          v                 v                                      Ventana W (70 ns)        |
_dibujar_impulso_ch1()     |                                     [t_peak, v_peak, seg]     | [t_peak_borde, seg_borde]
(fila CH1 en figura())     |                                     [t10_seg]                 |
          |                 |                                             |                 |
          +--------+--------+                                      +------+------+          |
                   |                                               |             |          |
                   v                                               |       contar_peaks()   |
   t_abs = t_peak - t10_seg - t_lag                                |       tabla_densidad() |
                   |                                               |       (barras y tabla) <
                   v                                               |       (cruces naranjas
   figura_scatter() (Patrón TRPD) / tabla_densidad()               |        en figura())
   (cruces negras en figura(); Scattergl)                          v
                   |                                  figura_vpp_energia()
                   +-----------------------+-----------------------+
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
- **R-I6 · t10 por segmento.** La función `t10_por_segmento(carpeta)` (cacheada en
  `_T10_SEG_CACHE`) extrae el instante de inicio $t_{10}^{(k)}$ de cada segmento $k$ de
  CH1 de forma individual. Cada segmento se filtra con `_filtrar_impulso` (filtro
  Butterworth pasa-bajos $20\text{ MHz}$, orden 4) y se interpola linealmente a
  sub-muestra para encontrar el cruce al 10 % de su propio $V_{\max}^{(k)}$. Si un segmento
  anómalo no registra cruce válido, recurre como *fallback* al $t_{10}$ del impulso
  promedio (`_IMPULSO_CACHE`), garantizando robustez total y reportando el conteo en
  `n_fallback_t10`.

---

## 2b. Calibración de retardo instrumental y sincronización temporal

### Justificación física
El sistema de adquisición captura simultáneamente la tensión de impulso LI (CH1, mediante divisor capacitivo) y las señales de descarga parcial emitidas hacia los sensores (CH2: HFCT, CH3: Antena Vivaldi, CH4: Antena Bioinspirada).
Debido a que cada canal utiliza longitudes de cable coaxial distintas (p. ej. RG-58 vs. doble apantallado), atenuadores, filtros pasa-altos acoplados y antenas con diferentes características de propagación, las señales experimentan un retardo de propagación instrumental intrínseco respecto a CH1.

Para sincronizar con precisión física el patrón TRPD (Time-Resolved Partial Discharge), cada canal detector $c \in \{\text{ch2}, \text{ch3}, \text{ch4}\}$ cuenta con un retardo medio característico $\bar{t}_{\text{lag}, c}$, de modo que el tiempo absoluto de ocurrencia de cada evento de DP se define como:
$$t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$$
donde $t_{\text{pd}}$ es el instante temporal del peak en el registro del osciloscopio, $t_{10}^{(k)}$ es el tiempo de inicio al 10 % del impulso de tensión en el segmento $k$, y $\bar{t}_{\text{lag}, c}$ es el retardo instrumental calibrado.

### Principio de calibración por explosor de esferas
La calibración se efectúa típicamente sobre mediciones de referencia con explosor de esferas (breakdown dieléctrico rápido sin probeta). Durante la ruptura, se produce simultáneamente la caída de tensión en el explosor y la emisión de radiación electromagnética de frente ultra-empinado:
1. **Instante del impulso ($t_{\text{imp}}^{(k)}$):** Se toma el tiempo de inicio al 10 % de la tensión del segmento $k$ en CH1:
   $$t_{\text{imp}}^{(k)} = t_{10}^{(k)}$$
2. **Instante de arribo del sensor ($t_{\text{ant}}^{(k)}$):** Se calcula con `_t_arribo(t, v, umbral, dist_us, tmin)`. Se evalúa el primer cruce de umbral ascendente $v[i] \ge u$ para $t \ge t_{\text{mín}}$, interpolando linealmente a sub-muestra entre $(t_{i-1}, v_{i-1})$ y $(t_i, v_i)$. Para evitar disparos espurios por precursores electromagnéticos o ruido previo, la función absorbe precursores menores mediante una ventana de guarda `dist_us`.
3. **Retardo por disparo ($t_{\text{lag}}^{(k)}$):**
   $$t_{\text{lag}}^{(k)} = t_{\text{ant}}^{(k)} - t_{\text{imp}}^{(k)}$$

### Algoritmo de filtrado de outliers (MAD)
En ensayos reales, algunos disparos pueden presentar conmutaciones anómalas o pre-disparos. La función `calibrar_retardo(carpeta, canal, umbral, dist_us, tmin)` implementa un descarte robusto mediante la Desviación Absoluta respecto a la Mediana (**MAD**):
1. Se calcula la mediana: $\tilde{t} = \text{median}(t_{\text{lag}})$.
2. Se evalúa el MAD: $\text{MAD} = \text{median}\left(\left| t_{\text{lag}}^{(k)} - \tilde{t} \right|\right)$.
3. El estimador de escala consistente con una distribución normal es $\hat{\sigma} = 1.4826 \times \text{MAD}$.
4. Se marcan como válidos los disparos que cumplen:
   $$\left| t_{\text{lag}}^{(k)} - \tilde{t} \right| \le k_{\text{mad}} \times \hat{\sigma}, \quad \text{con } k_{\text{mad}} = 5.0$$
   *(Si todos los puntos son idénticos y $\text{MAD} = 0$, se emplea como fallback $3\sigma$ de la muestra).*
5. Se calcula la media y desviación estándar de los puntos válidos:
   $$\bar{t}_{\text{lag}, c} = \frac{1}{N_{\text{valid}}} \sum_{k \in \text{valid}} t_{\text{lag}}^{(k)}, \qquad \sigma_c = \sqrt{\frac{1}{N_{\text{valid}}-1} \sum_{k \in \text{valid}} \left(t_{\text{lag}}^{(k)} - \bar{t}_{\text{lag}, c}\right)^2}$$

### Fuentes de calibración y flujo de trabajo
La aplicación soporta tres modalidades para alimentar `calibracion_store`:
- **Modo 1: Calibrar desde la medición actual:** El usuario abre el panel de calibración, ajusta umbral/distancia/tmin para CH2, CH3 y CH4, y presiona *"Calcular retardo"*. El sistema ejecuta `calibrar_retardo` multicanal, presenta el gráfico diagnóstico de dispersión e histograma, y permite persistir los valores en `metadata.yaml` mediante *"Guardar en metadata.yaml"*.
- **Modo 2: Importar calibración de otra medición:** Se selecciona una medición previa del catálogo que ya posea calibración y se pulsa *"Importar"*. Los parámetros se cargan inmediatamente a la sesión activa.
- **Modo 3: Ajuste manual:** El usuario puede ingresar directamente los valores en nanosegundos en los campos de entrada manual de cada canal.

### Esquema de persistencia en `metadata.yaml`
```yaml
calibracion_retardo:
  fuente: "medicion_actual"          # "medicion_actual" | "importado" | "manual"
  fecha_calibracion: "2026-09-16 13:00:00"
  medicion_origen: "3V224/20260915_30kV_rep01"
  canales:
    ch2:
      sensor: "HFCT"
      t_lag_ns: 12.34
      std_ns: 0.45
      n_puntos: 48
      n_outliers: 2
      umbral_mv: 50.0
      dist_us: 0.5
      tmin_us: -2.0
    ch3:
      sensor: "Antena Vivaldi"
      t_lag_ns: -5.67
      std_ns: 0.32
      n_puntos: 50
      n_outliers: 0
      umbral_mv: 15.0
      dist_us: 0.2
      tmin_us: -1.0
    ch4:
      sensor: "Antena Bioinspirada"
      t_lag_ns: 8.90
      std_ns: 0.61
      n_puntos: 49
      n_outliers: 1
      umbral_mv: 20.0
      dist_us: 0.3
      tmin_us: -1.5
```

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
- **R-P5 · Multi-Trigger independiente por sensor.** Cada canal detector (`ch2`: HFCT,
  `ch3`: Antena Vivaldi, `ch4`: Antena Bioinspirada) cuenta con su propia configuración
  de trigger independiente: umbral $u$ (mV), distancia mínima $\Delta t$ (µs) y tiempo
  mínimo $t_{\text{mín}}$ (µs). Las líneas de umbral se representan en el osciloscopio
  con colores distintivos (roja para el canal activo, azul/verde/ámbar para los demás)
  y son interactivamente arrastrables.

### Resumen de participación de peaks por análisis

| Análisis / Visualización | Peaks válidos (ventana 70 ns completa) | Filtrado por selección (`seleccion`) |
|---|:---:|:---:|
| **Barras de peaks por segmento** (`figura_peaks`) | Sí | No (todos los del segmento) |
| **Tabla de densidad de eventos** (`tabla_densidad`) | Sí | No (evaluación multi-sensor independiente) |
| **Cruces negras en gráfico principal** (`figura`) | Sí | Clicables (alimentan `seleccion`) |
| **Patrón TRPD ($V_{\max}$ o $V_{\text{pp}}$)** (`figura_scatter`) | Sí | Resalta seleccionados en amarillo |
| **Scatter Vpp vs Energía** (`figura_vpp_energia`) | Sí | Resalta seleccionados en amarillo |
| **Ventanas temporales** (`figura_ventanas`) | Sí | **Solo los seleccionados** |
| **FFT Welch** (`figura_fft`) | Sí | **Solo los seleccionados** (promedio) |
| **Transformada S de la ventana** (`figura_st_ventana`) | Sí | **Solo los seleccionados** (promedio \|S\|) |

> [!NOTE]
> Cualquier descarga cuyo intervalo temporal de $70\text{ ns}$ ($-7\text{ ns}$ antes a $+63\text{ ns}$ después del peak) no quepa íntegramente dentro de los límites del segmento o de $t \ge t_{\text{mín}}$ es **descartada de forma estricta**. No se dibujan cruces, no se contabiliza en barras ni en densidad, y no participa en los scatters.

---

## 4. Captura (fuente única de análisis)

Al pulsar **"Calcular peaks"** se fija un *snapshot* de parámetros en el store
`captura_params` = `{carpeta, canal, umbral, dist, tmin, cfg_sensores}`. **Todos** los análisis
(barras, densidad, patrón TRPD, Vpp/Energía, ventanas, FFT, Transformada S y las
cruces del gráfico principal) derivan de ese snapshot vía `capturar`.

- **R-C1 · `capturar`** (cacheado en `_CAPTURA_CACHE`) detecta los peaks de
  todos los segmentos y extrae una **ventana de 70 ns por peak**: **10 % antes /
  90 % después** del peak (`antes_us = 0.007`, `desp_us = 0.063`), alineada al peak en $t = 0$. Devuelve:
  - `t_rel`: eje temporal relativo al peak (µs), común a todas las ventanas (de $-0.007$ a $+0.063\text{ µs}$, 351 muestras a $5\text{ GSa/s}$).
  - `W`: matriz ($n_{\text{ventanas}} \times 351$) con las señales capturadas (mV).
  - `t_peak`, `v_peak`: instante (µs) y amplitud máxima instantánea $V_{\max}$ (mV) de cada peak con ventana completa.
  - `vpp`: amplitud peak-to-peak $V_{\text{pp}} = \max(W_i) - \min(W_i)$ (mV) calculada estrictamente en la ventana de 70 ns.
  - `seg`: segmento de origen de cada ventana completa.
  - `dt_us`: paso de muestreo (µs).
- **R-C2 · Criterio de exclusión estricto de bordes.**
  El recorte se valida con $a = i - n_{\text{antes}} < 0$ o $b = i + n_{\text{desp}} + 1 > v.\text{size}$,
  donde $v$ es la señal **recortada a $t \ge t_{\text{mín}}$**.
  Cualquier peak que diste menos de $7\text{ ns}$ de $t_{\text{mín}}$ o menos de $63\text{ ns}$ del
  final del segmento ($T_{\text{MAX}} = 30 \text{ µs}$) se descarta de forma absoluta.
- **R-C3 · Conjunto único y ordenado.** Peaks completos y ventanas comparten
  **exactamente el mismo conjunto y orden**, de modo que el índice $i$ de una fila
  en la matriz $W$ mapea 1:1 al punto $i$ de los scatters.
- **R-C4 · Coherencia.** Mientras no se pulse el botón, los análisis mantienen el
  snapshot anterior aunque se muevan parámetros en la interfaz.
- **R-C5 · Vector t10_seg en captura y sincronización O(N).** La función `capturar`
  asocia a cada descarga capturada el tiempo de inicio de su respectivo segmento de CH1,
  incluyendo en el diccionario el array `t10_seg`. La proyección a tiempo absoluto
  sincronizado se realiza mediante `t_abs_captura(cap, t_lag_us)`:
  $$t_{\text{abs}} = t_{\text{peak}} - t_{\text{10\_seg}} - t_{\text{lag\_us}}$$
  Este cálculo se ejecuta **estrictamente fuera** de `_CAPTURA_CACHE`. De este modo,
  recalibrar o modificar los retardos $t_{\text{lag}}$ recomputa el eje temporal de forma
  instantánea en $O(N)$ ($\sim 1\text{ ms}$) sin requerir una nueva lectura de los archivos
  HDF5 ni invalidar la matriz de formas de onda $W$, la FFT, la Transformada S o la
  selección activa de eventos.


---

## 5. Política de recálculo

- **R-R1.** Cambios que **NO** recalculan automáticamente (son `State`, no `Input`):
  - mover cualquiera de las líneas de **umbral** en el osciloscopio,
  - cambiar valores en los campos de entrada de los sensores (`umbral`, `dist`, `tmin`).
- **R-R2.** El recálculo de peaks y ventanas ocurre **solo** al pulsar
  **"Calcular peaks"** (modifica el store `captura_params`).
- **R-R3.** El gráfico principal se redibuja al pulsar el botón o al cambiar de
  **segmento / canal / medición**. Al cambiar de medición se cargan los umbrales
  y parámetros calibrados en `metadata.yaml` (o inferidos por defecto).

---

## 6. Selección de señales (modelo unificado)

Store central **`seleccion`** = lista de índices globales de ventana. Es la única
fuente para el gráfico temporal, la FFT y el resaltado amarillo.

- **R-S1 · Fuentes.** Alimentan la selección (`set_seleccion`):
  1. clic o caja en el **Patrón TRPD** (ya sea en modo $V_{\max}$ o $V_{\text{pp}}$),
  2. clic o caja en el scatter **Vpp vs Energía**,
  3. **clic en las cruces negras** del canal trigger en el gráfico principal.
- **R-S2 · Mapeo por fuente** (crítico por fiabilidad de eventos WebGL):
  - Scatters (TRPD, Vpp/Energía): trazas **Scattergl**, la **curva 0** es 1:1
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
  borrar la selección. `uirevision` (estable por captura y modo) preserva zoom/caja.

---

## 7. Gráficos derivados

- **Barras** (`figura_peaks`): nº de peaks por segmento.
- **Densidad de eventos** (`tabla_densidad`, `dash_table.DataTable` id="tabla_densidad"):
  Tabla resumen de caracterización experimental multi-sensor de **10 columnas**:
  - `Specimen`: código y geometría de la probeta (ej. `2V33H (asimetrica)`).
  - `Voltage (kV)`: tensión DC previa en el condensador de carga (ej. `15.0 kV`).
  - `Sensor`: sensor y canal evaluado (ej. `HFCT (CH2)`, `Antena Vivaldi (CH3)`, `Antena Bioinspirada (CH4)`).
  - `t_lag (ns)`: retardo instrumental aplicado al canal ($\bar{t}_{\text{lag}, c}$), obtenido de la calibración activa o 0.0 ns si no está calibrado.
  - `N_PD distribution [0, 1, 2, 3, 4, > 4]`: vector con el conteo de disparos/segmentos que registraron exactamente 0, 1, 2, 3, 4 y más de 4 eventos de DP (ej. `[9, 33, 8, 0, 0, 0]`).
  - `Media de N_PD`: promedio de eventos detectados por disparo ($\bar{N}_{PD}$).
  - `d (mm)`: diámetro(s) de cavidad(es) de la probeta inferidos del código o leídos de los metadatos (ej. `D1=3 mm, D2=3 mm`).
  - `V̄_max (V)`: amplitud de pico máxima media de todas las descargas detectadas (expresada en Voltios y con valor en mV).
  - `V̄_pp (V)`: amplitud peak-to-peak media de las descargas en su ventana de 70 ns (expresada en Voltios y con valor en mV).
  - `t̄_abs (µs)`: tiempo absoluto medio sincronizado de ocurrencia de las descargas en la probeta, respecto al inicio del impulso al 10 % y corregido por retardo instrumental:
    $$t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$$
  Dispone de botón **"⚡ Calcular todos los sensores (CH2..CH4)"** (que procesa cada sensor con su propia configuración calibrada de trigger y su respectivo retardo instrumental), botón **"Limpiar tabla"** y exportación nativa a **CSV**. Almacena su historial en `densidad_store`.
- **Patrón TRPD** (`figura_scatter`): Dispone de selector de magnitud con dos modos:
  1. **Modo $V_{\max}$:** Grafica el par $(t_{\text{abs}}, V_{\max})$, representando el pico máximo instantáneo junto con la traza de referencia del impulso en CH1 alineada en $t_{\text{abs}} = 0$.
  2. **Modo $V_{\text{pp}}$:** Grafica el par $(t_{\text{abs}}, V_{\text{pp}})$, donde $V_{\text{pp}}$ es la amplitud peak-to-peak calculada en la ventana normalizada de 70 ns $[-7\text{ ns}, +63\text{ ns}]$ centrada en el peak.
  - **Alineación temporal:** El eje horizontal representa el tiempo absoluto $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$. La traza del impulso promedio de CH1 se desplaza temporalmente a $t - t_{10}^{\text{ref}}$, de modo que el 10 % del flanco de subida coincide exactamente en $t_{\text{abs}} = 0\text{ µs}$. Una línea vertical discontinua marca la referencia en $t = 0\text{ µs}$.
  - **Hover multivariable:** El `hovertemplate` despliega simultáneamente $t_{\text{abs}}$, el tiempo original sin sincronizar del osciloscopio $t_{\text{osc}}$, $V_{\max}$, $V_{\text{pp}}$, segmento y orden de la descarga.
  - **Subtítulo dinámico:** Indica explícitamente el factor de retardo instrumental aplicado (ej. `t_lag aplicado: 12.3 ns`).
- **Vpp vs Energía** (`figura_vpp_energia`): por señal capturada,
  `Vpp = ptp(ventana)` [mV], `Energía = Σ v² · dt_us` [mV²·µs].
- **Ventanas** (`figura_ventanas`): señales seleccionadas superpuestas, alineadas
  al peak ($t = 0$). Con 351 muestras en 70 ns se visualiza punto a punto sin submuestreo.
- **FFT** (`figura_fft`): `scipy.signal.welch(scaling="spectrum")`, **escala
  lineal** (mV²), promediando el espectro de las ventanas seleccionadas.
  `nperseg = min(len, 256)`, eje en MHz (hasta Nyquist = Fs/2).

### Límites de cálculo de la FFT

A partir de las constantes y configuración vigentes ($XInc = 2 \times 10^{-10} \text{ s} \implies Fs = 5 \text{ GSa/s}$,
$dt = 2 \times 10^{-4} \text{ µs}$, `antes_us = 0.007`, `desp_us = 0.063`):

- **Longitud de la señal analizada:**
  $n_{\text{antes}} = \text{round}(0.007 / 2 \times 10^{-4}) = 35$ muestras ($-7\text{ ns}$),
  $n_{\text{desp}} = \text{round}(0.063 / 2 \times 10^{-4}) = 315$ muestras ($+63\text{ ns}$).
  La ventana temporal contiene $[-35, 315]$ muestras, es decir **351 muestras** ($70\text{ ns}$).
- **Parámetros de Welch:**
  - `nperseg = min(351, 256) = 256`.
  - Welch utiliza una ventana Hann con 50 % de solapamiento (`noverlap = 128`),
    lo que da un salto de 128 muestras entre bloques.
  - Sub-segmentos por ventana:
    $$\frac{351 - 128}{128} \approx 2 \text{ sub-segmentos}$$
  - **Doble promediado:** Welch promedia los sub-segmentos dentro de cada
    señal capturada para reducir varianza. Luego, `figura_fft` promedia esos
    espectros resultantes **entre todas las señales seleccionadas** en el store `seleccion`.
- **Resolución en frecuencia:**
  $$\Delta f = \frac{Fs}{\text{nperseg}} = \frac{5 \times 10^9 \text{ Sa/s}}{256} \approx 19.5312 \text{ MHz por bin}$$
- **Rango de frecuencia:**
  De 0 a Nyquist ($Fs / 2 = 2500 \text{ MHz}$).
  El control `f máx ST` **no** afecta a la FFT; la FFT siempre muestra el rango
  completo hasta Nyquist.
- **Escala y nivel de continua:**
  - `scaling="spectrum"` entrega $\text{mV}^2$ (potencia por bin de frecuencia, no
    densidad espectral $\text{mV}^2/\text{Hz}$). Eje vertical lineal.
  - Welch aplica por defecto `detrend="constant"`, eliminando la componente continua
    (media) de cada sub-segmento.
- **Resolución temporal:**
  La FFT se calcula sobre la ventana de 70 ns a resolución completa (las 351 muestras sin decimar).

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
  - **Ventana de 70 ns:** $N = 351$, `ST_NT_VENTANA = 350` $\implies \text{paso} = \max(1, 351 // 350) = 1$.
    Cada columna dista exactamente $0.2 \text{ ns}$ (resolución nativa punto a punto sin decimado).
  - **Segmento completo (-5..30 µs = 35 µs):** $N \approx 175\,001$, `ST_NT_SEGMENTO = 1000` $\implies \text{paso} = 175001 // 1000 = 175$.
    Cada columna dista $175 \times 0.2 \text{ ns} = 35 \text{ ns}$ ($\sim 1001$ columnas de tiempo).
  - **Consecuencia del decimado:** Se realiza por submuestreo directo (`[::paso]`),
    no por promedio ni por envolvente de máximos. Por tanto, eventos transitorios
    con duración inferior a $\sim 35 \text{ ns}$ en el segmento completo pueden
    caer entre columnas y atenuarse visualmente. El mapa del segmento sirve para
    ubicar intervalos temporales con actividad; para el análisis morfológico fino
    se utiliza la Transformada S de la ventana de $70\text{ ns}$.
- **Efectos de borde (periodicidad circular):**
  La formulación discreta vía FFT asume periodicidad de la señal. En las proximidades
  de los bordes ($-7\text{ ns}$ y $+63\text{ ns}$ en la ventana; $-5$ y $+30 \text{ µs}$
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
| `sincronizar_parametros_sensores` | `carpeta, grafico.relayoutData` | `umbral_ch{2,3,4}, dist_ch{2,3,4}, tmin_ch{2,3,4}` |
| `actualizar` | `carpeta, segmento, canal, captura_params` (+State 9 inputs sensores) | `grafico.figure` |
| `fijar_captura` | `btn.n_clicks` (+State carpeta, canal, 9 inputs sensores) | `captura_params.data` |
| `calcular_peaks` | `captura_params.data` | `grafico_peaks.figure` |
| `actualizar_densidad_store` | `captura_params.data, btn_calc_todos_sensores.n_clicks, btn_limpiar_densidad.n_clicks, calibracion_store.data` (+State densidad_store, 9 inputs sensores) | `densidad_store.data` |
| `sincronizar_tabla_densidad` | `densidad_store.data` | `tabla_densidad.data` |
| `actualizar_panel_metadata` | `carpeta, btn_guardar_metadata.n_clicks, btn_guardar_yaml_texto.n_clicks, calibracion_store.data` (+State meta_yaml_text) | Tarjetas, tabla canales y YAML de `panel_metadata` |
| `set_seleccion` | `captura_params.data, grafico_scatter.selectedData, grafico_scatter.clickData, grafico_vpp_energia.selectedData, grafico_vpp_energia.clickData, grafico.clickData` (+State captura_params) | `seleccion.data` |
| `actualizar_scatter` | `captura_params.data, seleccion.data, modo_magnitud_trpd.value, calibracion_store.data` | `grafico_scatter.figure, grafico_vpp_energia.figure` |
| `actualizar_temporal` | `seleccion.data` (+State `captura_params`) | `grafico_ventanas.figure, grafico_fft.figure` |
| `alternar_panel_principal` | `tabs_principal.value` | `panel_senales.hidden, panel_st_segmento.hidden, panel_metadata.hidden` |
| `actualizar_st_segmento` | `tabs_principal.value, carpeta, segmento, st_fmax` | `grafico_st_segmento.figure` |
| `actualizar_st_ventana` | `seleccion.data, tabs_espectro.value, st_fmax` (+State `captura_params`) | `grafico_st_ventana.figure` |
| `seleccionar_segmento` | `grafico_peaks.clickData` | `segmento.value` |
| **C1** `toggle_panel_calibracion` | `btn_toggle_calibracion.n_clicks` (+State `panel_calibracion_colapsable.is_open`) | `panel_calibracion_colapsable.is_open, btn_toggle_calibracion.children` |
| **C2** `init_params_calibracion` | `carpeta, umbral_ch{2,3,4}, dist_ch{2,3,4}, tmin_ch{2,3,4}` | `cal_umbral_ch{2,3,4}, cal_dist_ch{2,3,4}, cal_tmin_ch{2,3,4}, cal_import_dropdown.options` |
| **C3** `ejecutar_calibracion` | `btn_calc_calibracion.n_clicks` (+State `carpeta, cal_check_canales.value, cal_umbral_ch{2,3,4}, cal_dist_ch{2,3,4}, cal_tmin_ch{2,3,4}`) | `calibracion_resultado.data, cal_msg_feedback.children` |
| **C4** `mostrar_calibracion` | `calibracion_resultado.data` | `grafico_calibracion.figure, cal_resumen_tabla.children` |
| **C5** `gestionar_calibracion_store` | `carpeta, btn_aplicar_sesion.n_clicks, btn_guardar_cal_yaml.n_clicks, btn_importar_cal.n_clicks` (+State `calibracion_store, calibracion_resultado, tlag_manual_ch{2,3,4}, cal_import_dropdown.value`) | `calibracion_store.data, cal_msg_feedback.children` |
| **C6** `rellenar_manual_desde_store` | `calibracion_store.data` | `tlag_manual_ch2.value, tlag_manual_ch3.value, tlag_manual_ch4.value` |
| **C7** `badges_calibracion` | `calibracion_store.data, carpeta` | `cal_status_pill.children, cal_badge_ch2.children, cal_badge_ch3.children, cal_badge_ch4.children` |


---

## 11. Layout

- **Barra de controles principales:** Medición (`carpeta`), segmento (`segmento`), trigger activo (`canal`),
  botón "⚡ Calcular peaks" (`btn`), f máx ST (`st_fmax`).
- **Barra sub-panel multi-trigger:** Contenedor estilizado con 3 tarjetas identificadas por color:
  - `CH2 (HFCT)` en azul (`#2563eb`): `umbral_ch2`, `dist_ch2`, `tmin_ch2`.
  - `CH3 (Vivaldi)` en verde (`#059669`): `umbral_ch3`, `dist_ch3`, `tmin_ch3`.
  - `CH4 (Bioinspirada)` en ámbar (`#d97706`): `umbral_ch4`, `dist_ch4`, `tmin_ch4`.
- **Barra y panel de calibración de retardo instrumental:**
  - **Barra de estado (`barra_calibracion`):** Botón colapsable para desplegar la sección de calibración, píldora de resumen de estado (`cal_status_pill`: "Calibrado (metadata)", "Calibrado (sesión)" o "Sin calibrar") y tres badges por canal (`cal_badge_ch2`, `cal_badge_ch3`, `cal_badge_ch4`) que indican el retardo vigente en nanosegundos (ej. `CH2: 12.3 ns`).
  - **Panel colapsable (`panel_calibracion_colapsable`):**
    - Tarjetas de configuración de arribo por sensor: umbral (mV), distancia de guarda para absorción de precursores EMI (µs) y tiempo mínimo (µs).
    - Selector de canales a calibrar y botón "⚡ Calcular retardo".
    - Controles manuales (`tlag_manual_ch2`, `tlag_manual_ch3`, `tlag_manual_ch4`) y botón "Aplicar a sesión".
    - Importador desde catálogo: selector desplegable con mediciones que poseen calibración previa y botón "Importar".
    - Gráfico diagnóstico interactivo (`grafico_calibracion`): 2 subplots con la dispersión de $t_{\text{lag}}$ por segmento (puntos válidos en verde, descartados por MAD en rojo con cruz) y el histograma con curva gaussiana teórica.
    - Tabla resumen estadística y botón "💾 Guardar en metadata.yaml".
- **Stores de sesión:**
  - `calibracion_store`: diccionario con los retardos aplicados a la sesión `{fuente, canales: {ch: {t_lag_ns, ...}}}`.
  - `calibracion_resultado`: almacena los datos numéricos brutos del último cálculo de calibración para visualización diagnóstica.
- **Fila central (2 columnas):**
  - Columna izquierda: Panel principal con pestañas **Señales** (4 filas ch1..ch4 con líneas de umbral interactivas para ch2, ch3, ch4) /
    **Transformada S** (4 mapas de calor de segmento completo) / **Metadata**
    (panel técnico con tarjetas de experimento, circuito LI, probeta, osciloscopio,
    asignación de sensores por canal, editor/visor YAML y bloque de calibración) — `tabs_principal`.
  - Columna derecha:
    - Tarjeta superior: Pestañas **Peaks por segmento** (`grafico_peaks`) /
      **Densidad de eventos** (`tabla_densidad`, `dash_table.DataTable` resumen de
      10 columnas: Specimen, Voltage, Sensor, $t_{\text{lag}}$ (ns), $N_{PD}$ dist., Media $N_{PD}$, $d$, $\bar{V}_{\max}$, $\bar{V}_{\text{pp}}$, $\bar{t}_{\text{abs}}$,
      con botones para calcular todos los sensores con sus respectivos triggers y retardos, limpiar y exportar a CSV) — `tabs_peaks`.
    - Tarjeta inferior: Pestañas **Patrón TRPD** (`grafico_scatter` en tiempo absoluto $t_{\text{abs}}$ sincronizado con selector radio para alternar entre $V_{\max}$ y $V_{\text{pp}}$, traza de CH1 alineada en $t=0$ y línea vertical de referencia) /
      **Vpp vs Energía** (`grafico_vpp_energia`) — `tabs_scatter`.
- **Última fila (2 columnas):**
  - Columna izquierda: **Ventanas** (`figura_ventanas`), señales superpuestas alineadas en $t = 0$.
  - Columna derecha: Pestañas **FFT** (`grafico_fft`) / **Transformada S**
    (`grafico_st_ventana`), ambas aplicadas sobre las señales seleccionadas de la ventana de 1 µs — `tabs_espectro`.

---

## 12. Casos borde conocidos

- **Medición sin canal CH1:** La fila de CH1 muestra "no disponible".
- **`t50` inexistente:** Impulso con cola larga que no llega a descender al 50 % de su valor máximo dentro de la ventana de recorte.
- **Impulso con baseline alto:** Si no hay cruces de subida claros, `t0_lin` y `tmax_lin` quedan en `None`.
- **Medición sin calibración previa:** Si `metadata.yaml` no contiene el bloque `calibracion_retardo`, el sistema asigna por defecto $t_{\text{lag}} = 0.0\text{ ns}$ para todos los canales y muestra la etiqueta "Sin calibrar". El patrón TRPD representa $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)}$ y la tabla de densidad refleja `0.0` en `t_lag (ns)`.
- **Segmentos sin ruptura en calibración:** Si en una descarga el explosor no cebó o la señal de la antena no superó el umbral, la función `_t_arribo` retorna `None`. Ese segmento se excluye automáticamente del cómputo sin generar excepciones ni contaminar la mediana de los demás segmentos.
- **Impulsos de CH1 ruidosos o anómalos:** Si un segmento de CH1 presenta perturbaciones que impidan detectar el cruce del 10 %, `t10_por_segmento` utiliza de forma segura el $t_{10}$ del impulso promedio de la medición como *fallback*, garantizando sincronización continua y trazabilidad (`n_fallback_t10`).
- **Rendimiento desacoplado O(N):** La calibración y ajuste de $t_{\text{lag}}$ operan sobre los vectores numéricos `t_peak` y `t10_seg` en tiempo constante $O(N)$ ($\sim 1\text{ ms}$). Modificar el retardo no re-escanea los archivos HDF5, no invalida la caché de formas de onda $W$ en `_CAPTURA_CACHE`, no altera la selección activa en `seleccion` y conserva la perspectiva de zoom mediante `uirevision`.
- **Peaks pegados al borde del segmento o de $t_{\text{mín}}$:** Si un peak detectado dista menos de $7\text{ ns}$ ($0.007\text{ µs}$) de $t_{\text{mín}}$ o menos de $63\text{ ns}$ ($0.063\text{ µs}$) del final del segmento ($T_{\text{MAX}} = 30 \text{ µs}$), su ventana de $70\text{ ns}$ queda incompleta. La aplicación **descarta completamente** estas descargas: no se dibujan en el osciloscopio, no se computan en las barras de peaks ni en la tabla de densidad de eventos, y quedan excluidas de los patrones TRPD, ventanas superpuestas, FFT y Transformada S. Todo evento visualizado o computado en la aplicación posee garantizada su ventana íntegra de $70\text{ ns}$.

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
