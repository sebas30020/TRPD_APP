# Transformada S (Stockwell) en la app

## Context
El usuario quiere ver la transformada S de las señales en dos escalas:
1. **Ventana de 1 µs** alrededor de la descarga detectada (la misma ventana que
   usa la FFT: `capturar`, 20 % antes / 80 % después del peak). Debe compartir la
   tarjeta de la FFT con pestañas "FFT" | "Transformada S", igual que
   "Peaks" | "Vpp vs Energía".
2. **Segmento completo** (-5..30 µs), una por canal (ch1..ch4).

Antes hay que agrupar la documentación en `archivos_md/` (incluido este plan),
dejar `main` commiteado y sincronizado con `origin`, y trabajar en una rama
nueva `Transformada-S`.

## Estado de git (verificado)
- `main` y `origin/main` en el mismo commit `4dd1814` (0 adelante / 0 atrás).
- Sin commitear: `app.py`, `DOCUMENTACION.md`, `generate_metadata.py`
  (modificados); `cadencia.py`, `requirements.txt`, `reporte_cadencia.md`,
  `cadencia_segmentos.csv` (nuevos).

## Decisiones del usuario
- Carpeta **`archivos_md/`** con los `.md` del proyecto y este plan.
- Commitear **todo** lo pendiente (incluidos los reportes de cadencia).
- ST del segmento: **pestaña en la tarjeta del gráfico principal**
  ("Señales" | "Transformada S"), 4 filas de mapas de calor con el mismo eje t.
- Varias descargas seleccionadas: **promedio de |S|** (como la FFT).
- CH1 en el segmento: **señal cruda del segmento** (no el impulso promedio).
- Control **"f máx ST (MHz)"** en la barra, por defecto 2500 MHz (Nyquist).

## Paso 0 — Carpeta `archivos_md/`
- Crear `TRPD_APP/archivos_md/`.
- `git mv DOCUMENTACION.md archivos_md/` (trackeado, conserva historial);
  `mv reporte_cadencia.md archivos_md/` (sin trackear). Son los únicos `.md`
  del proyecto (los demás están en `.venv/`).
- Guardar este plan como `archivos_md/PLAN_Transformada-S.md`.
- Actualizar referencias:
  - `cadencia.py:35` → `REPORTE_MD = os.path.join(AQUI, "archivos_md", "reporte_cadencia.md")`.
  - `cadencia.py:11` (docstring) → `archivos_md/reporte_cadencia.md`.
  - `generate_metadata.py:5` → `archivos_md/DOCUMENTACION.md`.
  - `archivos_md/DOCUMENTACION.md:253` → ruta `archivos_md/reporte_cadencia.md`.
- `cadencia_segmentos.csv` se queda en la raíz (no es `.md`).
- Comprobar: `python cadencia.py` (simulacro, no mueve nada) escribe el reporte
  en `archivos_md/` y no deja `reporte_cadencia.md` en la raíz.

## Paso 1 — Git
1. `git add app.py generate_metadata.py cadencia.py cadencia_segmentos.csv requirements.txt archivos_md/`
   (explícitos; `.venv/` y `__pycache__/` ya están ignorados) → revisar
   `git status` (debe verse el rename de `DOCUMENTACION.md`) → commit en `main`
   → `git push origin main`.
2. Verificar: `git status` limpio y `git rev-list --left-right --count origin/main...HEAD` = `0 0`.
3. `git checkout -b Transformada-S` → `git push -u origin Transformada-S`.

## Paso 2 — Cálculo (`app.py`, junto a `figura_fft`)
- Import: `import scipy.fft as sfft`.
- Constantes: `ST_NFREQ = 250` (bins lineales 0..f máx), `ST_NT_VENTANA = 500`,
  `ST_NT_SEGMENTO = 1000` (columnas de tiempo a dibujar), `ST_FMAX_MHZ = 2500`.
- `transformada_s(x, dt_us, fmax_mhz, nfreq, n_t)` → `(t_us, f_mhz, A)`, `A = |S|` [mV]:
  - `X = sfft.fft(x, workers=-1)`; bins `j = linspace(1, jmax)`, con
    `jmax = min(N//2, round(fmax·N·dt))` (f máx recortada a Nyquist); fila f=0 = `|mean(x)|`.
  - Para cada `j`: `S_j = ifft(X[(m + j) mod N] · exp(-2π² m²/j²))`, `m` = offsets
    de bin centrados. Se procesan **en bloques** de ~16 frecuencias con
    `sfft.ifft(..., axis=1, workers=-1)` y se guarda `|S|[:, ::paso]`.
  - La gaussiana se evalúa **solo en su soporte** (`|m| ≤ 1.2·j`, fuera < 1e-12)
    para evitar subnormales (con f máx baja el cálculo se volvía 2× más lento).
  - Escala verificada en benchmark: tono de amplitud A → |S| ≈ A/2.
- `figura_st_ventana(cap, sel, canal, fmax)`: sin selección → `_fig_sin_seleccion`;
  si no, promedio de `transformada_s(W[i], ...)` sobre `sel`; `go.Heatmap`
  (x = `t_rel` decimado [µs], y = MHz), `add_vline(x=0)` "peak" como en
  `figura_ventanas`; título "Transformada S CHx — n señales (promedio |S|)"; height=430.
- `st_segmento(carpeta, seg, canal, fmax)` cacheado en `_ST_SEG_CACHE`
  (clave con fmax); usa `cargar_segmento(carpeta, canal, seg)` (CH1 crudo incluido).
- `figura_st_segmento(carpeta, seg, fmax)`: `make_subplots(rows=len(canales), shared_xaxes=True)`
  como `figura`, un `go.Heatmap` por canal con su propia colorbar alineada a la
  fila (cada canal tiene amplitudes distintas), `xaxis range = [T_MIN, T_MAX]`, height=850.

## Paso 3 — Layout
- Controles: `html.Label("f máx ST (MHz):")` + `dcc.Input(id="st_fmax", type="number",
  value=ST_FMAX_MHZ, min=1, debounce=True)` (recalcula al pulsar Enter/salir).
- Tarjeta principal: `dcc.Tabs(id="tabs_principal")` "Señales" | "Transformada S"
  **sin children**; debajo dos `html.Div` (`panel_senales` con `grafico`,
  `panel_st_segmento` con `dcc.Loading(grafico_st_segmento)`) que se alternan
  con `style.display`. Así `grafico` **no se desmonta** y la línea de umbral
  arrastrada, el zoom y los clics en cruces siguen funcionando al volver.
- Tarjeta FFT: `dcc.Tabs(id="tabs_espectro")` "FFT" | "Transformada S" con
  children, mismo patrón que `tabs_scatter`; la ST dentro de `dcc.Loading`.

## Paso 4 — Callbacks
| Callback | Entradas | Salida |
|---|---|---|
| `alternar_panel_principal` | `tabs_principal.value` | `panel_senales.style`, `panel_st_segmento.style` |
| `actualizar_st_segmento` | `tabs_principal.value, carpeta, segmento, st_fmax` | `grafico_st_segmento.figure` |
| `actualizar_st_ventana` | `seleccion, tabs_espectro.value, st_fmax` (+State `captura_params`) | `grafico_st_ventana.figure` |

- Ambas ST devuelven `no_update` si su pestaña no está activa: solo se calcula
  lo que se ve; al cambiar a la pestaña se calcula con el estado vigente.
- `actualizar_temporal` (ventanas + FFT) no cambia.

## Paso 5 — `archivos_md/DOCUMENTACION.md`
- Nueva sección **Transformada S** con reglas: definición y normalización
  (|S| en mV, tono A → A/2), ventana = la de `capturar` (R-C1), promedio de |S|
  en multi-selección, segmento completo por canal con CH1 crudo, f máx
  recortada a Nyquist.
- Actualizar: R-S4 (la ST de ventana también queda vacía con aviso), sección 7
  (gráficos), 8 (R-PF: cálculo solo con pestaña visible, bloques multihilo,
  soporte gaussiano, `_ST_SEG_CACHE`), 9 (3 callbacks nuevos), 10 (layout y control),
  y sección 12 (nueva ubicación de `reporte_cadencia.md`).

## Paso 6 — Cierre
- Commit en `Transformada-S`; push solo tras confirmación del usuario.

## Verificación
- **Reorganización**: `ls archivos_md` → `DOCUMENTACION.md`, `reporte_cadencia.md`,
  `PLAN_Transformada-S.md`; ningún `.md` en la raíz; `cadencia.py` escribe ahí.
- **Git**: tras el Paso 1, `main` limpio y `0 0` con `origin/main`; rama
  `Transformada-S` con upstream `origin/Transformada-S`.
- **Numérica** (venv): tono de 100 MHz y A=2 → máximo de |S| en ~100 MHz con valor ≈ 1;
  pulso corto en t0 → energía concentrada alrededor de t0 en todas las frecuencias.
- **Tiempos**: ST de segmento (4 canales, 2500 MHz y 500 MHz) < ~8 s;
  ST de ventana con 10 señales < 1 s.
- **App** (lanzar `app.py` y abrir http://127.0.0.1:8050):
  - `cada_30s/7` → pestaña "Transformada S" principal: 4 mapas de calor, eje -5..30 µs.
  - Volver a "Señales": la línea de umbral conserva la posición arrastrada.
  - "Calcular peaks" → seleccionar puntos → pestaña "Transformada S" de la
    tarjeta FFT: mapa con línea en t=0; "FFT" sigue igual.
  - Cambiar f máx a 500 → ambas ST se recalculan con eje hasta 500 MHz.
  - `otros/4` (sin CH1) → 3 filas.
