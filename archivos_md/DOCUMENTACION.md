# Visor de Vacuolas — Documentación y reglas internas

Aplicación Dash (`app.py`) para explorar mediciones de osciloscopio Keysight y
analizar los impulsos y los peaks del canal trigger. Este documento recoge las
**reglas internas** que el programa debe respetar; actualízalo cada vez que se
añada o cambie una funcionalidad.

---

## Puesta en marcha y ejecución de las aplicaciones

El proyecto cuenta con dos aplicaciones Dash independientes que operan en puertos diferentes:

1. **Visor TRPD Principal (`app.py`):**
   - **URL:** `http://127.0.0.1:8051` (antes 8050; se movió porque un proceso huérfano de `app.py` quedó reteniendo el 8050 de forma irrecuperable)
   - **Propósito:** Exploración de mediciones HDF5, detección de descargas parciales, visualización TRPD y cálculo de métricas. Es consumidor de calibraciones (`metadata.yaml`).
   - **Arranque recomendado:** Ejecutar el script versionado `run_app.cmd` (doble clic o desde consola) en la raíz del proyecto.
   - **Arranque manual por terminal:**
     ```cmd
     "%LOCALAPPDATA%\venvs\trpd_app\Scripts\python.exe" -u app.py
     ```

2. **Calibrador Instrumental (`calibrar_app/main.py`):**
   - **URL:** `http://127.0.0.1:8052`
   - **Propósito:** Detección de retardo instrumental ($t_{\text{lag}}$) sobre señales de calibración, ajuste de impulso IEC 60060-1 / Anexo B y guardado de resultados en `metadata.yaml`.
   - **Arranque recomendado:** Ejecutar el script versionado `run_calibrar.cmd` (doble clic o desde consola) en la raíz del proyecto.
   - **Arranque manual por terminal:**
     ```cmd
     "%LOCALAPPDATA%\venvs\trpd_app\Scripts\python.exe" -u calibrar_app\main.py
     ```

### Scripts de arranque (`run_app.cmd` y `run_calibrar.cmd`)
Ambos scripts garantizan una inicialización robusta:
- **Ruta relativa autocontenida:** Resuelven el directorio base mediante `%~dp0`, funcionando desde cualquier ubicación.
- **Aislamiento del intérprete:** Resuelven el intérprete en este orden: (1) la variable de entorno `TRPD_PYTHON`, si está definida; (2) el entorno local `%LOCALAPPDATA%\venvs\trpd_app\Scripts\python.exe`, si existe; (3) el `.venv` legado dentro de Google Drive (`%~dp0.venv\Scripts\python.exe`), con un aviso de que el arranque puede tardar minutos. Además fijan `PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\venvs\trpd_app\pycache` para que los `.pyc` del proyecto no se escriban en Drive.
- **Protección contra fallos silenciosos:** Si el entorno virtual no está presente en la ruta esperada, muestran un mensaje de diagnóstico claro en español explicando el problema y abortan con código de error, evitando degradar al Python del sistema (el cual carece de dependencias y generaría falsos errores de importación).
- **Inspección de errores:** Terminan con `pause` en caso de terminación anormal o fallo del intérprete para que las trazas sean legibles tras un doble clic.

### Consideraciones de rendimiento y entorno (Google Drive)
- **Entorno virtual fuera de Google Drive:** Con el `.venv` dentro de Drive (`G:\Mi unidad\...`, ~11.600 archivos) la importación de `scipy`, `dash` y `h5py` tarda ~3 minutos, incluso con la carpeta marcada como *Disponible sin conexión*. El entorno de trabajo vive por eso en disco local, en `%LOCALAPPDATA%\venvs\trpd_app`. El `.venv` de Drive se conserva solo como respaldo. Para recrear el entorno local:
  ```cmd
  "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" -m venv "%LOCALAPPDATA%\venvs\trpd_app"
  "%LOCALAPPDATA%\venvs\trpd_app\Scripts\python.exe" -m pip install -r requirements.txt
  ```
- **Desactivación del recargador en desarrollo:** `app.py` ejecuta con `use_reloader=False`. Esto previene que Werkzeug importe dos veces todo el árbol de dependencias, reduciendo el tiempo de inicialización a la mitad.

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
   suficiente para extraer una ventana de $70 \text{ ns}$ ($7 \text{ ns}$ / $10\%$ antes y
   $63 \text{ ns}$ / $90\%$ después del peak).
   Si la ventana se sale del segmento recortado ($i - n_{\text{antes}} < 0$ o
   $i + n_{\text{desp}} + 1 > v.\text{size}$), el evento no cumple la ventana completa y se descarta (regla **R-C2**).
5. **Captura de ventanas de 70 ns (`capturar`):**
   Para los peaks completos se extrae el recorte temporal $[-7, +63] \text{ ns}$ ($-0.007$ a $+0.063\text{ µs}$)
   alineado al peak en $t = 0$. Esta matriz $W$ y sus vectores asociados
   (`t_peak`, `v_peak`, `seg`) conforman el **conjunto único y ordenado** que
   comparten de forma 1:1 el scatter de Peaks, las
   ventanas temporales superpuestas, la FFT y la Transformada S de la ventana (regla **R-C3**).
6. **Selección de eventos por el usuario (store `seleccion`):**
   El usuario selecciona eventos individuales o grupos mediante clics o cajas de
   selección en el scatter de Peaks o haciendo
   clic directo sobre las cruces negras del canal trigger en el gráfico principal.
   El store central `seleccion` almacena la lista de índices de ventana elegidos.
7. **Análisis derivados de la selección:**
   - **Ventanas temporales (`figura_ventanas`):** superpone en pantalla únicamente
     las formas de onda seleccionadas, alineadas en su peak ($t = 0$).
   - **FFT Welch (`figura_fft`):** calcula el espectro de potencia de cada ventana
     seleccionada y grafica el promedio entre ellas.
   - **Transformada S de la ventana (`figura_st_ventana`):** calcula la distribución
     tiempo-frecuencia de cada ventana de $70 \text{ ns}$ y promedia su magnitud $|S|$.
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
    figura_scatter() (Patrón TRPD) / tabla_densidad()               |
    (cruces negras en figura(); Scattergl)                          |
                    |                                               |
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
  - **Jerarquía estándar única (v2):** Se organizan en 2 niveles:
    `<mediciones>/{N}v[H]_{d1}mm{d2}mm..._{set}/{X}kV/`
    - Carpeta principal `{N}v[H]_{d1}mm{d2}mm..._{set}`: `{N}v` número de vacuolas, sufijo `H` opcional para asimetría, diámetros concatenados en mm (`2mm3mm3.5mm`), y `_{set}` entero de repetición/set.
    - Subcarpeta `{X}kV`: nivel de tensión en el secundario del transformador de impulso (ej. `10kV`, `17.5kV`).
    - Ejemplo: `Mediciones/3v_2mm3mm3.5mm_0/10kV/`.
  - No hay carpeta de datos fija: en `app.py` y `calibrar_app` la medición se elige
    con el explorador de carpetas (📂 Examinar…), que navega todo el equipo (unidades
    `C:\`, `G:\`, …). La medición queda identificada por su **ruta absoluta**
    (ver `rutas.py`). Una carpeta es seleccionable si contiene algún `*chN*.h5`.
- Archivos por carpeta de medición:
  - `ch1.h5`: Tensión de impulso LI (divisor capacitivo / sincronismo).
  - `ch2.h5`: Corriente de descarga (HFCT, atenuador 30 dB) o sensor reconfigurable.
  - `ch3.h5`: Radiación electromagnética (Antena 1 / UHF) o sensor reconfigurable.
  - `ch4.h5`: Monopolo plano bioinspirado (filtro pasa-altos 200 MHz) o sensor reconfigurable.
  - `metadata.yaml`: Metadatos del ensayo generados por `generate_metadata.py`.
  - `registro_disparos.csv`: Registro de los 50 disparos (Npd, detecciones por canal, observaciones).
- Cadencia: cada segmento tiene el atributo `SegmentedTimeTag` [s], instante
  de la descarga relativo al segmento 1 (idéntico en los 4 canales).
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

### 1b. Filtros digitales por canal (`filtros.py`)

Para hablar el mismo idioma que el manuscrito (scripts `old_paper/posiblemente_util/scripts/all_exps_main.py`),
CH2..CH4 se filtran **en memoria** al cargar cada segmento (`cargar_segmento(..., filtrado=True)`),
con Butterworth de orden 4 y fase cero (`sosfiltfilt`):

| Canal | Sensor | Filtro por defecto | Paper |
|---|---|---|---|
| CH1 | Divisor (impulso) | ninguno aquí (LP 20 MHz propio del impulso, §2) | LP 10 MHz |
| CH2 | HFCT | HP 5 MHz | HP 5 MHz |
| CH3 | Antena 1 | HP 200 MHz | sin filtro (Vivaldi) — se filtra por decisión del grupo |
| CH4 | Antena 2 | HP 200 MHz | HP 200 MHz |

- **Configuración:** `metadata.yaml` → `canales.chX.filtro` (`HP_5MHz`, `HP_200MHz`, `LP_10MHz`, `ninguno`).
  Si la clave no existe se usan los valores por defecto (`filtros.FILTROS_DEFECTO`); `generate_metadata.py`
  ya los escribe en la plantilla. Un valor `ninguno` explícito desactiva el filtro de ese canal.
- **Bordes:** se lee la ventana pedida ampliada `MARGEN_US = 1 µs` a cada lado, se filtra y se recorta, de modo
  que el resultado no depende de la ventana. `fs = 1/XInc` de cada `.h5`; si el corte no cabe bajo Nyquist, el
  canal queda sin filtrar (aviso por consola).
- **Interruptor "Filtros del paper"** (`switch_filtros`, barra de controles, activo por defecto): alterna toda la
  app (gráfico de señales, umbrales por defecto, captura/peaks, ventanas 70 ns, FFT, Transformada S, TRPD y tabla de
  Estadística) entre señal filtrada y cruda. El snapshot `captura_params` guarda `filtrado`; al cambiar el interruptor
  con una captura hecha, se rehace con los parámetros por defecto de la nueva señal. Las cachés (`_cargar_segmento_cache`,
  `_CAPTURA_CACHE`, `_ST_SEG_CACHE`) incluyen el filtro en su clave.
- **Tabla de Estadística:** cada fila guarda `_filtrado`/`_filtro` y bajo la tabla se indica qué filtro tiene cada
  sensor (y si se mezclan filas filtradas y crudas).
- **calibrar_app** filtra siempre según la metadata (sin interruptor): el `t_lag` se mide sobre la misma señal que se
  analiza. Al guardar, `calibracion_retardo.chX.filtro` registra el filtro usado; si una calibración guardada no tiene
  ese campo, la tabla resumen avisa de que se hizo sobre señal cruda y conviene recalibrar.

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
El sistema de adquisición captura simultáneamente la tensión de impulso LI (CH1, mediante divisor capacitivo) y las señales de descarga parcial emitidas hacia los sensores (CH2: HFCT, CH3: Antena 1, CH4: Antena 2).
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
      sensor: "Antena 1"
      t_lag_ns: -5.67
      std_ns: 0.32
      n_puntos: 50
      n_outliers: 0
      umbral_mv: 15.0
      dist_us: 0.2
      tmin_us: -1.0
    ch4:
      sensor: "Antena 2"
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
  `ch3`: Antena 1, `ch4`: Antena 2) cuenta con su propia configuración
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

### 4b. Edición manual de peaks (marca temporal)

Cuando un ajuste del trigger arregla un peak pero estropea otro, los peaks se pueden
**añadir** o **quitar a mano**. Las ediciones se guardan como **(disparo, t)** en tiempo
del osciloscopio, **no como índices**, así que se reaplican igual al cambiar umbral, Δt,
t_mín o el interruptor de filtros (plan: `archivos_md/plan_peaks_manuales.md`).

- **Persistencia** en `metadata.yaml`, sección `ediciones_peaks`, un historial por canal
  (`ediciones_canal`, `ediciones_medicion`, `guardar_ediciones_canal`; reescribe el YAML con
  `safe_dump` como al guardar diámetros, por lo que se pierden los comentarios):
  ```yaml
  ediciones_peaks:
    ch4:
      historial:
      - {accion: anadir, puntos: [{seg: 18, t_us: -0.361867}], desc: Peak manual seg 18}
      - {accion: quitar, puntos: [{seg: 18, t_us: 13.770533}], desc: 1 descarga}
      - {accion: quitar_disparo, segs: [5], desc: 'Disparo(s) [5]'}
  ```
  `estado_ediciones` reproduce el historial: quitar un añadido lo saca de añadidos; añadir
  sobre un quitado lo recupera. "Deshacer" quita el último paso; "Restaurar todo" vacía el
  historial (y borra la clave del canal).
- **Aplicación** (`aplicar_ediciones`, `captura_editada`; caché `_CAPTURA_EDITADA_CACHE`):
  sobre la captura de `capturar` se quitan los peaks detectados a ≤ `TOL_PEAK_US` (5 ns) de un
  quitado del mismo disparo y todos los de un disparo excluido; cada añadido se reajusta al
  máximo de la señal en ±`RESNAP_US` (1 ns) y se le extrae su ventana de 70 ns (`vpp`, `W`,
  `t10_seg`). Si ya hay un detectado a ≤ 5 ns no se duplica: queda **forzado** (sigue aunque un
  trigger posterior no lo detecte). Un añadido cuya ventana no cabe se omite (`omitidos`).
  La captura editada lleva además `origen` (0 detectado, 1 manual) y `quitados_vis`, y está
  ordenada por (disparo, t). **Todos** los análisis la usan (`_cap_p`): barras, Estadística
  (distribución N_PD, N_PD = N_cav, V̄_pp, t̄_abs), Patrón TRPD, ventanas, FFT y ST.
- **Interfaz.** Barra encima del gráfico de señales:
  - **Marca t [µs]** (`input_marca_t`): un clic sobre la señal del **canal activo** pone la marca
    (línea discontinua), ajustada al máximo en ±`SNAP_MARCA_US` (10 ns); también se puede escribir.
  - **Añadir peak en la marca** (`btn_anadir_peak`), **Quitar peak** (`btn_quitar_peak`: la
    selección —clic en una cruz o en el TRPD— o, sin selección, el peak bajo la marca),
    **Deshacer** y **Restaurar todo**; `badge_ediciones` resume añadidos/quitados/disparos y
    `aviso_ediciones` muestra los errores (sin captura, sin marca, ventana que no cabe…).
  - Los botones del Patrón TRPD ("Quitar selección", "Excluir" disparo, "Deshacer",
    "Restaurar todo") escriben en el mismo historial.
  - Dibujo: añadidos = **rombos**; quitados = cruces grises (no seleccionables); en el TRPD los
    manuales son rombos en la curva 0 (el índice sigue en `customdata[5]`).
- Las ediciones solo se ven con una captura vigente ("Calcular peaks"); en vista previa
  (campos de trigger editados sin recalcular) las cruces son la detección automática.


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
- **Estadística / Tabla 1** (`tabla_densidad`, tabla HTML generada por `construir_tabla_paper`):
  Reproduce el formato de la Tabla 1 del manuscrito (cabecera en negrita con subíndices,
  Specimen / d / Voltage combinados por medición con `rowSpan`, una fila por sensor y
  líneas horizontales entre mediciones). **8 columnas** (`COLUMNAS_DENSIDAD`):
  - `Specimen`: solo el nº de vacuolas (`1v`, `3v`, …), de `probeta.nro_vacuolas` o del código de la carpeta.
  - `d (mm)`: diámetros de las vacuolas (ej. `2, 3, 4`).
  - `Voltage (kV)`: tensión del secundario leída de la carpeta `<probeta>/<X>kV/` (ej. `17.5`); si la ruta no tiene carpeta kV, `circuito_impulso.tension_kv_ac_sec`.
  - `Sensor`: nombre corto (`HFCT`, `Antena 1`, `Antena 2`); los nombres antiguos de metadata (Vivaldi / Bioinspirada) se traducen con `nombre_corto_sensor`.
  - `N_PD distribution [0, 1, 2, 3, 4, > 4]`: disparos con exactamente 0, 1, 2, 3, 4 y más de 4 descargas.
  - `N_PD = N_cav`: nº de disparos cuyo nº de descargas es igual al nº de cavidades.
  - `V̄_pp (V)`: media del pico-a-pico (ventana de 70 ns), 3 decimales.
  - `t̄_abs (µs)`: media de $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$, 3 decimales.

  **Promedio condicionado:** `V̄_pp` y `t̄_abs` se promedian solo sobre las descargas de los
  disparos con $N_{PD} = N_{cav}$ (criterio del paper); si no hay ninguno se muestra `-`. Si no
  se conoce $N_{cav}$ se promedian todas las descargas activas. Se calcula sobre la captura
  editada: los peaks quitados no participan y los añadidos a mano sí (§4b). Filas ordenadas por nº de cavidades, tensión y canal.
  Botones **"Calcular todos los sensores (CH2..CH4)"**, **"Limpiar tabla"** y **"Exportar CSV"**
  (`btn_exportar_densidad` → `dcc.Download` `descarga_densidad`). Historial en `densidad_store`.
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
  `nperseg = min(len, 256)`, eje en MHz **recortado a 0–3000 MHz** (`FFT_FMAX_MHZ = 3000`).

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
  De 0 a **3 GHz** (`FFT_FMAX_MHZ = 3000`): los bins por encima se descartan aunque
  Nyquist sea mayor (5 GHz a 10 GSa/s). El control `f máx ST` **no** afecta a la FFT.
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
  - La cantidad de filas en el mapa de calor no depende de $N$, sino de `ST_NFREQ = 500`
    y de `f máx` (control `st_fmax`, por defecto y como tope `ST_FMAX_MHZ = 3000` MHz).
  - **Parámetros de resolución de la imagen** (constantes al inicio de `app.py`):
    `ST_NFREQ` = filas de frecuencia (vertical); `ST_NT_SEGMENTO` / `ST_NT_VENTANA` =
    columnas de tiempo (horizontal). Además los mapas usan `zsmooth="best"` (interpolación
    entre celdas) para no verse pixelados. Coste medido a 10 GSa/s en el segmento
    ($N = 350\,000$): ~4.6 s/canal con 250×1000 y ~7.7 s/canal con 500×2000.
  - Se definen $j_{\text{max}} = \min(N // 2, \text{round}(f_{\text{máx}} \cdot N \cdot dt))$
    y $js = \text{unique}(\text{round}(\text{linspace}(1, j_{\text{max}}, \min(250, j_{\text{max}}))))$.
  - Con 500 bins lineales entre 0 y $f_{\text{máx}}$, la separación entre filas es
    $$\Delta f_{\text{mapa}} \approx \frac{f_{\text{máx}}}{500}$$
    - Con $f_{\text{máx}} = 3000 \text{ MHz}$ (defecto): $\Delta f \approx 6 \text{ MHz}$ por fila (segmento).
    - En la ventana de 70 ns la grilla no puede ser más fina que $\Delta f_{\text{FFT}} \approx 14.3$ MHz:
      hasta 3 GHz hay solo ~210 filas, por lo que ahí la suavidad la aporta `zsmooth`.
  - **Resolución natural de la FFT de fondo vs. grilla visual:**
    La resolución física elemental de la FFT de fondo es $\Delta f_{\text{FFT}} = 1 / (N \cdot dt)$:
    $\sim 14.3 \text{ MHz}$ en la ventana de $70 \text{ ns}$ ($N = 351$) y
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
  $f_1 = 1 / (N \cdot dt)$: $\approx 14.3 \text{ MHz}$ en la ventana de $70 \text{ ns}$ y
  $\approx 0.029 \text{ MHz}$ en el segmento completo. La fila $f = 0$ almacena el valor constante
  $|\text{media}(x)|$ repetido en todas las columnas de tiempo; no representa resolución temporal.
- **Límite superior y recorte a Nyquist:**
  `f máx` se limita a **3000 MHz** (`ST_FMAX_MHZ`; el campo `st_fmax` tiene `max=3000` y
  `transformada_s` aplica además el tope) y, si fuese menor, a Nyquist ($N // 2$ bins).
  Si el campo queda vacío, se toma `ST_FMAX_MHZ = 3000`.
- **Resolución temporal y factor de decimado:**
  Las operaciones FFT e IFFT se ejecutan siempre a resolución completa sobre las $N$
  muestras. El resultado se decima exclusivamente al construir la matriz final mediante
  `paso = max(1, N // n_t)`:
  - **Ventana de 70 ns** (10 GSa/s): $N = 701$, `ST_NT_VENTANA = 700` $\implies \text{paso} = 1$.
    Cada columna dista $0.1 \text{ ns}$ (resolución nativa, sin decimado).
  - **Segmento completo (-5..30 µs = 35 µs):** $N = 350\,000$, `ST_NT_SEGMENTO = 2000` $\implies \text{paso} = 175$.
    Cada columna dista $175 \times 0.1 \text{ ns} = 17.5 \text{ ns}$ ($2000$ columnas de tiempo).
  - **Consecuencia del decimado:** Se realiza por submuestreo directo (`[::paso]`),
    no por promedio ni por envolvente de máximos. Por tanto, eventos transitorios
    con duración inferior a $\sim 17.5 \text{ ns}$ en el segmento completo pueden
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

Ver el análisis completo y las mediciones antes/después en `archivos_md/plan_rendimiento_ux.md`
(`archivos_md/bench_antes.txt`, `archivos_md/bench_despues.txt`; script `scripts_tmp/bench_rendimiento.py`).

- **R-PF1 · Diezmado del gráfico de señales.** `figura()` no envía las 350 001 muestras por canal:
  `tramo_visible` → `decimar_minmax` (`DEC_BUCKETS = 2000` tramos, se conserva el mínimo y el máximo
  de cada uno, así ningún pico desaparece) ≈ 4 000 puntos por traza (12.8 MB → 0.28 MB por figura).
  **Si el tramo visible dura ≤ `SIN_DIEZMADO_US = 1 µs` se envían todas las muestras.**
- **R-PF2 · Re-diezmado por zoom.** `redecimar_zoom` (Input `grafico.relayoutData`) responde a cada
  zoom/pan con un `dash.Patch` que solo reemplaza `x/y` de las trazas de señal con el tramo visible
  (arreglos tipados float32 base64, 130–260 KB); no reconstruye la figura, no pierde zoom ni umbrales.
  El zoom vigente se guarda en `dcc.Store("rango_x")` (con carpeta y canal) para que un redibujado
  completo (umbral, segmento, filtro) respete el tramo visible.
- **R-PF3 · Interacción.** `dcc.Graph("grafico")`: rueda = zoom (`scrollZoom`), doble clic = volver a
  -5..30 µs, `edits.shapePosition=False` y solo las líneas de umbral (`editable=True`) se arrastran.
  Cruces de peaks en `Scattergl` (todo WebGL). `sincronizar_parametros_sensores` sale sin tocar el
  disco si el relayout no trae `shapes[...]`.
- **R-PF4 · Capa de lectura `datos_h5.py`** (común a `app.py` y `calibrar_app/datos.py`): rutas y
  canales cacheados, **un `h5py.File` abierto por archivo** (antes uno por segmento leído, ~200 ms en
  Drive), eje temporal compartido (`eje_t`), LRU de 128 segmentos con solo la tensión,
  `calcular_una_vez` (varios callbacks simultáneos → un único cálculo) y `cacheado_por_archivo`
  (metadata.yaml se relee solo si cambia su fecha; stat como mucho cada 2 s). El explorador llama a
  `datos_h5.limpiar_caches()` al confirmar una carpeta.
- **R-PF5 · Cachés.** `obtener_metadata` cacheada (devuelve copia); `_CAPTURA_CACHE` LRU de 64 con
  cálculo único; `_ST_SEG_CACHE` LRU acotada; CH1 se recorre **una sola vez** (`_pasada_ch1`) para
  `promedio_impulso` y `t10_por_segmento`; `generate_metadata.extraer_info_h5` cacheado por mtime.
- **R-PF6 · Transformada S por plegado espectral.** Como solo se dibuja una columna cada `paso`
  muestras, cada fila se calcula con una suma sobre el soporte de la gaussiana y una IFFT de longitud
  N/paso (antes una IFFT de longitud N); resultado idéntico (error ~1e-8), salida float32 y los 4
  canales en hilos: segmento completo 34 s / 54 MB → ~4 s / 25 MB. Solo se calcula con su pestaña visible.
- **R-PF7 · Trabajo justo.** Estadística y panel Metadata solo se calculan con su pestaña visible;
  al cambiar de medición o canal `captura_params` se limpia y los paneles derivados muestran
  "Pulse «Calcular peaks»" en lugar de resultados de otra medición.
- **R-PF8 · Servidor sin dev tools** por defecto (JS minificado, sin sondeo de hot-reload). Para
  depurar: `set TRPD_DEBUG=1` antes de `run_app.cmd`.

### 9b. Experiencia de uso
- Spinners (`dcc.Loading`, aparecen tras 300 ms) en todos los gráficos, la tabla de Estadística y
  el panel Metadata; los botones "Calcular peaks", "Calcular todos los sensores", guardar
  metadata/diámetros y, en calibrar_app, "Calcular Retardo", "Evaluar IEC" y "Guardar" se
  deshabilitan mientras calculan (`running=`).
- Persistencia en el navegador (localStorage): última medición (se restaura al abrir la app si sigue
  en disco), canal, interruptor de filtros, f máx ST, pestañas, exclusiones de descargas y tabla de
  Estadística.
- Atajos (`assets/teclado.js`): ← / → segmento anterior/siguiente; Esc cierra el explorador.
- La pestaña Calibración abre calibrar_app ya con la medición actual (`?embebido=1&carpeta=...`) y
  al volver a Análisis se releen los retardos guardados.
- Errores visibles: si una figura falla se muestra el mensaje en lugar de dejar la anterior.
- Campos vacíos de Δt/t_mín usan siempre `DIST_DEFECTO_US = 0.05` (50 ns) y `TMIN_DEFECTO_US = 0.15`.
  Δt = 50 ns y no los 36 ns del paper (180 muestras a 5 GSa/s): las antenas registran un eco de cada
  descarga 37–43 ns después del pico (~17 % de su amplitud, presente también sin filtro) que con 35 ns
  se contaba como una segunda descarga.

---

## 10. Mapa de callbacks

| Callback | Entrada(s) | Salida(s) |
|---|---|---|
| `actualizar_segmentos` | `carpeta` | opciones y valor de `segmento` |
| `sincronizar_parametros_sensores` | `carpeta, grafico.relayoutData` | `umbral_ch{2,3,4}, dist_ch{2,3,4}, tmin_ch{2,3,4}` |
| `redecimar_zoom` | `grafico.relayoutData` (+State carpeta, segmento, canal, switch_filtros) | `grafico.figure` (Patch), `rango_x.data` |
| `recordar_carpeta` / `restaurar_carpeta` | `carpeta` / `ultima_carpeta.modified_timestamp` | `ultima_carpeta.data` / `carpeta.value/options`, `explorador_panel.hidden` |
| `actualizar` | `carpeta, segmento, canal, captura_params, ediciones_peaks, marca_peak` (+9 inputs sensores) | `grafico.figure` |
| `cargar_ediciones` | `carpeta` | `ediciones_peaks.data` (desde metadata.yaml) |
| `fijar_marca` | `grafico.clickData, input_marca_t.value, carpeta, canal, segmento` | `marca_peak.data, input_marca_t.value` |
| `gestionar_ediciones_peaks` | botones de edición (barra de señales y Patrón TRPD) (+State seleccion, captura_params, marca_peak, ediciones_peaks) | `ediciones_peaks.data, input_excluir_disparo.value, aviso_ediciones.children` (y guarda metadata.yaml) |
| `actualizar_badge_filtro` | `seleccion, ediciones_peaks, captura_params, marca_peak` | estado de los botones de edición, `badge_filtro_descargas`, `badge_ediciones` |
| `fijar_captura` | `btn.n_clicks` (+State carpeta, canal, 9 inputs sensores) | `captura_params.data` |
| `calcular_peaks` | `captura_params.data, ediciones_peaks.data` | `grafico_peaks.figure` |
| `actualizar_densidad_store` | `captura_params.data, btn_calc_todos_sensores.n_clicks, btn_limpiar_densidad.n_clicks, calibracion_store.data` (+State densidad_store, 9 inputs sensores) | `densidad_store.data` |
| `sincronizar_tabla_densidad` | `densidad_store.data` | `tabla_densidad.children` |
| `exportar_densidad` | `btn_exportar_densidad.n_clicks` (+State densidad_store) | `descarga_densidad.data` |
| `actualizar_panel_metadata` | `carpeta, btn_guardar_metadata.n_clicks, btn_guardar_yaml_texto.n_clicks, calibracion_store.data` (+State meta_yaml_text) | Tarjetas, tabla canales y YAML de `panel_metadata` |
| `set_seleccion` | `captura_params.data, grafico_scatter.selectedData, grafico_scatter.clickData, grafico.clickData, ediciones_peaks.data` (+State captura_params) | `seleccion.data` |
| `actualizar_scatter` | `captura_params.data, seleccion.data, modo_magnitud_trpd.value, calibracion_store.data, ediciones_peaks.data` | `grafico_scatter.figure` |
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

## 11. Layout y Sistema de Diseño

### 11.1 Sistema de Diseño Unificado (`tema.py` y `assets/styles.css`)

Tanto `app.py` como `calibrar_app` utilizan un sistema de diseño centralizado definido en `tema.py` y respaldado por variables `:root` en `assets/styles.css`:
- **Paleta Neutra y Sobria:** Fondos claros (`BG: #f3f4f6`, `CARD: #ffffff`), bordes sutiles (`BORDER: #d9dee5`, `BORDER_SUBTLE: #eef1f5`), tipografía de alta legibilidad (`INK: #1f2933`, `MUTED: #5f6b7a`, `MUTED_LIGHT: #9aa5b1`) y un único acento primario (`ACCENT: #2f5d8a`).
- **Estados Semánticos Desaturados:** Conforme (`OK: #3f7d5c`), Advertencia (`WARN: #a8741a`), Error / Exclusión (`ERROR: #a63d3d`).
- **Paleta de Canales Formal:** `CH1` azul acero (`#4c78a8`), `CH2` ocre apagado (`#d08a2e`), `CH3` verde salvia (`#4f8f6f`), `CH4` púrpura apagado (`#8a5fa0`).
- **Plantilla Plotly `"trpd"`:** Registrada en `pio.templates["trpd"]`, con fondo blanco, cuadrícula `#e5e7eb`, ejes `#9aa5b1`, tipografía uniforme a 12 px y `colorway` coherente con la paleta de canales.
- **Tipografía y Controles:** Interfaz plana sin emojis decorativos (⚡ 🗑 💾 🔗), con botones sobrios (`.btn-primary`, `.btn-secondary`, `.btn-danger`, `.btn-warn`), pestañas con borde inferior acentuado (`.tab`, `.tab--selected`) y tarjetas de baja elevación (`.card`).

### 11.2 Estructura de la Interfaz

- **Barra de controles principales:** Medición (`carpeta`), explorador de directorios (`btn_examinar`), segmento (`segmento`), trigger activo (`canal`), botón "Calcular peaks" (`btn`), f máx ST (`st_fmax`).
- **Barra sub-panel multi-trigger:** Contenedor con 3 bloques por canal sensor:
  - `CH2 (HFCT)`: `umbral_ch2`, `dist_ch2`, `tmin_ch2`.
  - `CH3 (Antena 1)`: `umbral_ch3`, `dist_ch3`, `tmin_ch3`.
  - `CH4 (Antena 2)`: `umbral_ch4`, `dist_ch4`, `tmin_ch4`.
- **Barra de estado de calibración instrumental:** Píldora de estado global (`cal_badge_estado`), badges por canal (`cal_badge_ch2`, `cal_badge_ch3`, `cal_badge_ch4`), botón "Detalle del retardo" (despliega resumen de sólo lectura de `metadata.yaml`) y botón "Calibración instrumental" (navega directamente a la pestaña de Calibración).
- **Pestañas Principales (`tabs_principal`):**
  1. **Análisis (`value="senales"`):**
     - **Fila superior (2 columnas):**
       - Columna izquierda: Pestañas de dominio (`tabs_dominio`) con sub-pestaña **Señales** (`panel_senales`: barra de edición manual de peaks (§4b) y 4 filas ch1..ch4 con líneas de umbral interactivas) y **Transformada S** (`panel_st_segmento`, 4 mapas de calor de segmento completo).
       - Columna derecha: Tarjeta superior con **Peaks por segmento** (`tabs_peaks`, `grafico_peaks`). Tarjeta inferior con **Patrón TRPD** (`tabs_scatter`, `grafico_scatter` en tiempo absoluto $t_{\text{abs}}$, selector de magnitud $V_{\max}$ / $V_{\text{pp}}$, controles de exclusión de descargas por lazo o disparo y badge de estado del filtro).
     - **Fila inferior (2 columnas):**
       - Columna izquierda: **Ventanas** (`figura_ventanas`), formas de onda ventaneadas (70 ns) superpuestas y alineadas en $t = 0$.
       - Columna derecha: Pestañas **FFT** (`grafico_fft`) y **Transformada S** (`grafico_st_ventana`) de las ventanas seleccionadas (`tabs_espectro`).
  2. **Estadística (`value="estadistica"`):**
     - Panel a ancho completo con `tabla_densidad` (tabla HTML con el formato de la Tabla 1 del paper; estilos `.tabla-paper` en `assets/styles.css`).
     - Columnas: Specimen, d (mm), Voltage (kV), Sensor, $N_{PD}$ distribution, $N_{PD} = N_{cav}$, $\bar{V}_{\text{pp}}$, $\bar{t}_{\text{abs}}$.
     - Botones: "Calcular todos los sensores (CH2..CH4)" (`btn_calc_todos_sensores`), "Limpiar tabla" (`btn_limpiar_densidad`) y "Exportar CSV" (`btn_exportar_densidad`).
  3. **Metadata (`value="metadata"`):**
     - Panel técnico con tarjetas estructuradas: Experimento, Circuito de impulso LI, Probeta (geometría, capas, e inferencia y edición interactiva de diámetros de vacuolas con persistencia), Osciloscopio, Tabla de sensores/canales con retardo instrumental $t_{\text{lag}}$, y editor/visor del archivo `metadata.yaml` crudo.
  4. **Calibración (`value="calibracion"`):**
     - Integración diferida de la aplicación de calibración (`calibrar_app`, puerto 8052) mediante `html.Iframe` (`iframe_calibracion`), que sólo carga su contenido al ingresar a la pestaña para no penalizar el tiempo de inicio.
     - Enlace/botón "Abrir en ventana aparte" con destino `http://127.0.0.1:8052` como alternativa de visualización desacoplada.

- **Stores de sesión en `app.py`:**
  - `captura_params`: snapshot de parámetros numéricos fijados al pulsar "Calcular peaks".
  - `seleccion`: índices globales de descargas activas seleccionadas interactivamente.
  - `ediciones_peaks`: ediciones manuales de peaks de la medición (`{carpeta, canales: {ch: {historial}}}`), reflejo de `metadata.yaml` (§4b).
  - `marca_peak`: marca temporal para añadir un peak (`{carpeta, canal, seg, t_us}`).
  - `calibracion_store`: diccionario de retardo instrumental derivado de `metadata.yaml`.
  - `densidad_store`: conjunto acumulado de filas estadísticas para la tabla de densidad.
  - `explorador_ruta_actual`: ruta activa en el modal de exploración de carpetas de medición.

---

## 12. Casos borde conocidos

- **Medición sin canal CH1:** La fila de CH1 muestra "no disponible".
- **`t50` inexistente:** Impulso con cola larga que no llega a descender al 50 % de su valor máximo dentro de la ventana de recorte.
- **Impulso con baseline alto:** Si no hay cruces de subida claros, `t0_lin` y `tmax_lin` quedan en `None`.
- **Medición sin calibración previa:** Si `metadata.yaml` no contiene el bloque `calibracion_retardo`, el sistema asigna por defecto $t_{\text{lag}} = 0.0\text{ ns}$ para todos los canales y muestra la etiqueta "Sin calibrar". El patrón TRPD representa $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)}$ y $ar{t}_{	ext{abs}}$ de la tabla de estadística no lleva corrección de retardo.
- **Segmentos sin ruptura en calibración:** Si en una descarga el explosor no cebó o la señal de la antena no superó el umbral, la función `_t_arribo` retorna `None`. Ese segmento se excluye automáticamente del cómputo sin generar excepciones ni contaminar la mediana de los demás segmentos.
- **Impulsos de CH1 ruidosos o anómalos:** Si un segmento de CH1 presenta perturbaciones que impidan detectar el cruce del 10 %, `t10_por_segmento` utiliza de forma segura el $t_{10}$ del impulso promedio de la medición como *fallback*, garantizando sincronización continua y trazabilidad (`n_fallback_t10`).
- **Rendimiento desacoplado O(N):** La calibración y ajuste de $t_{\text{lag}}$ operan sobre los vectores numéricos `t_peak` y `t10_seg` en tiempo constante $O(N)$ ($\sim 1\text{ ms}$). Modificar el retardo no re-escanea los archivos HDF5, no invalida la caché de formas de onda $W$ en `_CAPTURA_CACHE`, no altera la selección activa en `seleccion` y conserva la perspectiva de zoom mediante `uirevision`.
- **Peaks pegados al borde del segmento o de $t_{\text{mín}}$:** Si un peak detectado dista menos de $7\text{ ns}$ ($0.007\text{ µs}$) de $t_{\text{mín}}$ o menos de $63\text{ ns}$ ($0.063\text{ µs}$) del final del segmento ($T_{\text{MAX}} = 30 \text{ µs}$), su ventana de $70\text{ ns}$ queda incompleta. La aplicación **descarta completamente** estas descargas: no se dibujan en el osciloscopio, no se computan en las barras de peaks ni en la tabla de densidad de eventos, y quedan excluidas de los patrones TRPD, ventanas superpuestas, FFT y Transformada S. Todo evento visualizado o computado en la aplicación posee garantizada su ventana íntegra de $70\text{ ns}$.

---

## 13. Scripts auxiliares (fuera de la app)

### `generar_presentacion.py` — presentación de señales (PowerPoint)

`python generar_presentacion.py [<raiz> ...] [--salida <ruta.pptx>] [--dpi 150] [--solo <texto>] [--crudo]`
(dependencias aparte: `pip install -r requirements_reportes.txt`, python-pptx y matplotlib).

- Por defecto lee `mediciones/med_proced_confuse` y `mediciones/med_proced/1v_2mm_01` y escribe
  `reportes/senales_med_proced_confuse.pptx`. Cada raíz puede ser una carpeta de probetas o una probeta.
- Orden: nº de vacuolas y diámetros, luego tensión creciente (p. ej. `1v_2mm_01`, 11–16 kV, va antes que
  `1v_2mm_0`, 17.5–20 kV). El set se muestra tal como está escrito en la carpeta (`01`).
- Una diapositiva por disparo con 4 gráficos apilados: Impulso (CH1, V), HFCT (CH2), Antena 1 – cercana
  (CH3) y Antena 2 – lejana (CH4), en mV. Ventana -5…30 µs; CH2..CH4 con los mismos filtros que la app
  (`cargar_segmento(..., filtrado=True)`), CH1 sin filtrar. Escala vertical común a los disparos de cada medición.
- Título: nº de vacuolas · diámetros · tensión — Disparo k / N, tomados de la jerarquía
  `<probeta>/<X>kV` (`inferir_parametros`); subtítulo con probeta, set y ruta. Incluye portada, índice
  y un separador por medición.
- `--solo "3v_2mm3mm4mm_1	kV"` genera solo las mediciones cuya ruta contiene ese texto (prueba rápida).
- Con las 18 mediciones (314 disparos): 334 diapositivas, ~28 MB, ~5–6 min.
- `--crudo`: misma presentación con las señales tal como las registró el osciloscopio (solo conversión
  a tensión, ningún filtro en ningún canal; escalas verticales recalculadas sobre la señal cruda).
  Salida por defecto `reportes/senales_med_proced_confuse_crudo.pptx`.

- **`preprocesar.py`.** Filtro paso-alto Butterworth de fase cero (`sosfiltfilt`,
  **5 MHz**, orden 4) aplicado a cada segmento de `ch2.h5` (señal completa, no
  ventaneada). Genera un archivo extra `ch2_hp5MHz.h5` con la **misma
  estructura** de grupos/datasets que el original (mismos nombres), pero con
  los datos ya en **voltios** (`YInc=1`, `YOrg=0`) para que `app.py` lo cargue
  sin cambios. Se ejecuta manualmente y una sola vez por medición
  (`python3 preprocesar.py`); **no** se invoca desde la app.

- **`generate_metadata.py`.** Punto único para **rellenar automáticamente** el
  `metadata.yaml` de cada medición (`<carpeta_medicion>/metadata.yaml`; usa `PyYAML`,
  `h5py` y `numpy`). Incluye la lógica de cadencia (sección `cadencia` del YAML),
  amplitudes por canal, saturación (segmentos fuera de pantalla) y
  canal/pendiente/nivel del trigger estimados desde CH1 en t = 0. Lo que no se
  puede deducir queda listado en `generado_automaticamente.campos_pendientes`.
  Ejecutar: `python generate_metadata.py <carpeta_medicion | carpeta_raiz> [--completar | --forzar] [--sin-senales]`
  (con una carpeta raíz procesa recursivamente todas las mediciones; `--completar`
  rellena solo campos ausentes o vacíos sin tocar lo escrito a mano ni `calibracion_retardo`).
  
  **Características principales:**
  1. **Extracción automática desde los archivos `.h5`:** Lee directamente los encabezados del osciloscopio (Keysight Infiniium DSOS804A) para autocompletar el modelo, serial, fecha del experimento (guardado del .h5 de CH1), base de tiempo (frecuencia de muestreo en GSa/s, ventana temporal total en µs, puntos y segmentos) y las **escalas verticales de cada canal** (`escala_v_div`, `rango_total_v`, `offset_v`).
  2. **Inferencia por nombre de carpeta:** Si la ruta sigue el formato estándar `{N}v[H]_{diams}_{set}/{X}kV`, infiere automáticamente el código de probeta, tipo de geometría (`mixta`, `monodiametro` o `asimetrica`), número de vacuolas (`nro_vacuolas`), lista de diámetros (`diametros`), set de impulsos (`set_impulsos`) y la tensión del secundario (`tension_kv_ac_sec`).
  3. **Trigger y Canales configurables:** CH1 queda preasignado al divisor capacitivo de tensión de impulso / sincronismo. Los canales CH2, CH3 y CH4 vienen preconfigurados pero permiten renombrar el sensor, función, atenuación y filtros según la instrumentación conectada en el ensayo.

  Esquema YAML generado:

  ```yaml
  experimento:
    id: 3v_2mm3mm3.5mm_0/10kV
    fecha_hora: '2026-09-10 11:31:11'    # Única fecha: .h5 de CH1 (≈ fin de adquisición)
    temperatura_c: null                  # Temperatura ambiente [°C]
    humedad_relativa_pct: null           # Humedad relativa [%]

  circuito_impulso:
    forma_onda_nominal: 1.2/50us         # Norma IEC 60060-1
    tension_kv_ac_sec: 10.0              # Secundario transformador elevador [kV AC]
    nro_disparos_programados: 50         # Nro de impulsos nominales
    intervalo_entre_disparos_s: 30.0     # Intervalo entre descargas [s]

  probeta:
    codigo: 3v_2mm3mm3.5mm_0             # Identificador de probeta
    tipo_geometria: mixta                # monodiametro / mixta / asimetrica
    descripcion: Pressboard sumergido en aceite mineral
    nro_capas_total: 4
    espesor_capa_mm: 0.48
    nro_vacuolas: 3
    diametros: [2, 3, 3.5]               # Diámetros de cavidades [mm]
    set_impulsos: 0                      # Set de impulsos ensayados
    vacuolas: []                         # lista de {id, diametro_mm, capa}
    distancias_entre_vacuolas_mm: []     # N-1 distancias
    fotos: []

  osciloscopio:
    modelo: DSOS804A
    serial: MY60060103
    frecuencia_muestreo_gsas: 5.0        # Fs = 5 GSa/s
    tiempo_total_ventana_us: 200.0       # Ventana horizontal completa [µs]
    escala_tiempo_us_div: 20.0           # Base de tiempo [µs/div]
    num_segmentos_capturados: 50
    puntos_por_segmento: 1000003

  trigger:
    canal_origen: ch1                    # Siempre CH1 (montaje fijo)
    tipo: flanco                         # flanco (edge)
    pendiente: positiva                  # Pendiente del trigger
    nivel_v: 0.9914                      # Medido: mediana de CH1 en t = 0 (.h5) [V]
    posicion_horizontal_pct: 10.0        # XDispOrigin / XDispRange del .h5
    nivel_v_fuente: 'medido: mediana de CH1 en t = 0 (.h5)'
    pretrigger_us: 20.0
    jitter_trigger_ns: 0.1983
    flanco_ch1_en_t0: true               # Verificación: CH1 está en su flanco en t = 0
    # El .h5 no guarda la configuración del trigger; con --completar estos campos
    # se reescriben siempre desde el .h5.

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
      sensor: Antena 1                   # Reconfigurable por el usuario
      funcion: UHF Banda ancha
      unidad: V
      filtro: ninguno
      escala_v_div: 0.5
      offset_v: 0.0
      rango_total_v: 4.0
    ch4:
      sensor: Antena 2                   # Reconfigurable por el usuario
      funcion: UHF / Resolucion picos frente
      unidad: V
      filtro: HP_200MHz
      escala_v_div: 0.5
      offset_v: 0.0
      rango_total_v: 4.0
  ```

- **`cadencia.py`.** Reporte por lotes y reorganización de carpetas; reutiliza la
  lógica de cadencia de `generate_metadata.py` (`analizar_cadencia`). Diagnostica y
  clasifica la cadencia de adquisición de cada medición a partir del atributo `SegmentedTimeTag` [s] de cada segmento
  (`Waveforms/Channel N/Channel N SegKData`, relativo al segmento 1; idéntico
  en los 4 canales). Calcula Δt entre descargas consecutivas y clasifica por
  la **mediana**: a ±2 s de 60 s → `cada_1min`; a ±2 s de 30 s → `cada_30s`;
  si no → `otros`. Un Δt que se aparta más de 2 s del nominal de su clase se
  marca como **anómalo** en el reporte (no cambia la clasificación).
  - `python3 cadencia.py <raiz>` → simulacro: genera `archivos_md/reporte_cadencia.md`
    (tabla resumen, conteo por clase, anomalías, Δt por medición) y
    `cadencia_segmentos.csv` (`medicion, segmento, time_tag_s, dt_s, anomalo,
    clase`), e imprime qué movería sin mover nada.
  - `python3 cadencia.py <raiz> --mover` → además mueve cada medición a
    `<raiz>/<clase>/<medición>/`. Es idempotente: si ya está en su
    carpeta no la toca, y si el destino ya existe no sobrescribe.

---

## 14. Calibración Instrumental y Aplicación `calibrar_app` (Puerto 8052)

Para garantizar la precisión metrológica del tiempo absoluto de las descargas parciales sin sobrecargar la aplicación principal ni introducir riesgos de desincronización, el sistema desacopla el cálculo y el consumo en dos aplicaciones independientes:

1. **`app.py` (Puerto 8051 — Consumidor TRPD):**
   - Consume exclusivamente los retardos calibrados almacenados en `metadata.yaml` bajo el bloque `calibracion_retardo`.
   - El panel desplegable de calibración es de **solo lectura**, mostrando la trazabilidad metrológica (fuente, fecha, criterio, referencia de impulso, umbrales y estadísticas $\bar{t}_{\text{lag}} \pm \sigma$, válidos / total).
   - Incluye botón `"🔄 Recargar desde disco"` para actualizar el store de sesión inmediatamente tras guardar cambios en `calibrar_app`.
   - Realiza la traslación exacta de las nubes TRPD: $t_{\text{abs}} = t_{\text{pd}} - t_{10}^{(k)} - \bar{t}_{\text{lag}, c}$.
   - Si la medición fue calibrada contra el origen virtual $O_1$ de la norma IEC 60060-1, `app.py` normaliza automáticamente restando el ancla $\Delta = t_{10} - O_1 \approx 258\text{ ns}$ almacenada en el bloque `ancla`. De esta forma, el patrón TRPD es **invariante a la referencia elegida**.

2. **`calibrar_app` (Puerto 8052 — Calibrador y Diagnóstico IEC):**
   - Aplicación Dash autónoma ejecutada desde el subdirectorio `calibrar_app/` (`python calibrar_app/main.py`).
   - Permite seleccionar interactivamente la medición, el canal sensor (`ch2`, `ch3`, `ch4`) y el segmento de prueba.
   - Sincronización bidireccional entre la caja de texto del umbral $u_{\text{cal}}$ y una línea horizontal roja editable en el gráfico de señal, permitiendo ajustar umbrales visualmente arrastrando con el cursor.
   - Detección precisa de arribo $t_{\text{ant}}$ mediante cruce de umbral por interpolación lineal sub-muestra con filtrado robusto de atípicos por desviación absoluta mediana (MAD, $k=5.0$).
   - Soporta referencia dual de tiempo de impulso en CH1:
     - **Referencia $t_{10}$:** Cruce del 10% del frente de onda en la ventana de observación $[-5, 30]\text{ µs}$.
     - **Referencia $O_1$ (IEC 60060-1):** Ajuste de curva base biexponencial $U_m(t)$ y filtro pasa-bajos de fase cero $k(f)$ sobre el registro completo (Anexos B y C), deduciendo el origen virtual $O_1$ y evaluando parámetros normativos ($T_1$, $T_2$, $\beta'$, $U_t$).
   - Visualización diagnóstica en 4 cuadrantes: señal con línea móvil, impulso CH1 con curvas y líneas normativas, dispersión de $t_{\text{lag}}$ con histograma, y evolución de marcas de ancla por disparo.
   - Botón `"💾 Guardar YAML"` que actualiza atómicamente el bloque `calibracion_retardo` en `metadata.yaml`, preservando todas las secciones preexistentes (`experimento`, `circuito_impulso`, `probeta`, `osciloscopio`, `canales`).

