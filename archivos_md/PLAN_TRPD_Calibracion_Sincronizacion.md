# PLAN — Calibración de retardo instrumental, sincronización multicanal y patrón TRPD

> **Destino de este documento:** `archivos_md/PLAN_TRPD_Calibracion_Sincronizacion.md`
> **Agente ejecutor:** Antigravity (o cualquier agente de código). El documento se sostiene solo: no supone contexto previo.
> **Especificación de origen:** `archivos_md/PROMPT_TRPD_Calibracion_Sincronizacion.md`. Léela antes de empezar, sobre todo las §2 y §3 (fórmulas).
> **Repositorio:** `C:\0_matrix\doctorado\proyectos\inv_pd_vac\TRPD_APP` (Windows, Python, Dash + Plotly, rama base `main`).
> **Datos:** fuera del repo, en `..\mediciones\Mediciones\` (constante `MEDICIONES` en `app.py:33`). Por ejemplo `mediciones_filtros/cada_30s/7/ch1..ch4.h5` + `metadata.yaml`. **No hay todavía un set de calibración de explosor.**

---

## 0. Contexto y objetivo

Hoy el patrón TRPD (`figura_scatter`, `app.py:1074`) grafica `x = cap["t_peak"]`, el tiempo **crudo** del osciloscopio. Ese eje arrastra dos errores:
- el retardo instrumental de cada sensor ($t_{lag}$: cables, atenuadores, vuelo EM), distinto por canal y por campaña;
- el jitter del disparo de CH1 entre segmentos.

Hay dos problemas más:
- la traza de referencia de CH1 del TRPD no está anclada a $t_{10}$;
- la columna `t̄_abs (µs)` de la tabla de densidad (`app.py:890`) es en realidad `mean(t_peak)` crudo.

**Objetivo:**
1. calibrar $\bar t_{lag,c}$ por canal (ch2, ch3, ch4) con disparos de explosor;
2. guardarlo en `metadata.yaml` y en un `dcc.Store`;
3. graficar el TRPD y calcular la tabla de densidad con

$$t_{abs} = t_{pd} - t_{10}^{(k)} - \bar t_{lag,c}$$

donde $k$ es el segmento del peak.

### 0.1 Decisiones de diseño (cerradas, no reabrir)
| Tema | Decisión |
|---|---|
| Criterio de $t_{ant}$ | **Primer cruce del umbral** $\lvert v\rvert \ge u_{cal}$ con $t \ge t_{min,cal}$, interpolado linealmente sub-muestra (detalle en §2.3). |
| $t_{10}$ usado en $t_{abs}$ | **El del propio segmento** $t_{10}^{(k)}$. Si falla, se usa el $t_{10}$ del impulso promedio filtrado. |
| $t_{10}$ usado en la calibración | También $t_{10}^{(k)}$ del segmento: $t_{lag}^{(k)} = t_{ant}^{(k)} - t_{10}^{(k)}$. |
| Unidades | Internas en **µs**, como toda la app. En YAML y badges, en **ns**. |
| Cache de captura | $t_{abs}$ **no** entra en la clave de `_CAPTURA_CACHE`: recalibrar no vuelve a capturar. |
| `uirevision` | La calibración **no** entra en `uirevision`: se conserva el zoom al recalibrar. |
| Semántica física | $t_{lag}$ es **relativo a CH1**, así que ya absorbe el retardo del divisor y su cable. CH1 no se corrige aparte. |

### 0.2 Convenciones del repo (respetar)
- Todo el código vive en `app.py`: funciones puras arriba, `app.layout` y callbacks abajo. `generate_metadata.py` define el esquema YAML.
- Nombres, comentarios y docstrings **en español**, sin tildes en identificadores. Estilos Dash **inline** (dicts), igual que las barras existentes.
- Caches de sesión como dicts globales `_ALGO_CACHE = {}` con clave tupla (ver `_CAPTURA_CACHE`, `_IMPULSO_CACHE`).
- Callbacks con varios disparadores: se despacha con `ctx.triggered_id` (ver `actualizar_densidad_store`, `app.py:1606`). **Un Output lo escribe un solo callback**; si hace falta otro escritor, se usa `allow_duplicate=True` + `prevent_initial_call=True`.
- Gráficos grandes con `go.Scattergl`. **La curva 0 del scatter TRPD debe seguir 1:1 con las ventanas capturadas** (la selección mapea por `pointNumber`; ver `_idx_scatter`, `app.py:507`).
- Commits: mensajes en español, estilo `feat: ...` / `perf: ...` / `docs: ...`.

### 0.3 Mapa del código relevante (`app.py`)
| Símbolo | Línea aprox. | Uso en este plan |
|---|---|---|
| `TRIGGERS = ["ch2","ch3","ch4"]` | 35 | canales calibrables |
| `IMP_FCORTE`, `IMP_ORDEN` | 46-47 | filtro de CH1 |
| `cargar_segmento(carpeta, canal, seg)` | 214 | lectura cacheada −5..30 µs |
| `meta_medicion`, `n_segmentos`, `canales_presentes` | 110-178 | metadatos HDF5 |
| `umbral_defecto(carpeta, canal, seg)` | 345 | umbral inicial |
| `_muestras(carpeta, canal, dist_us)` | 381 | µs → muestras para `find_peaks` |
| `capturar(...)` | 445 | captura; devuelve dict con `t_peak, v_peak, vpp, seg, W, t_rel, dt_us` |
| `obtener_metadata(carpeta)` | 766 | lee YAML o genera plantilla; agrega claves `_ruta_yaml`, `_existe_en_disco` |
| `guardar_metadata_archivo(carpeta, yaml_str)` | 797 | escribe `metadata.yaml` |
| `COLUMNAS_DENSIDAD`, `calcular_fila_densidad` | 812, 825 | tabla de densidad |
| `promedio_impulso`, `impulso_filtrado` | 916, 936 | CH1 promedio y filtrado |
| `_cruce_subida(t, s, thr, i_pico)` | 953 | cruce interpolado |
| `tiempos_impulso(carpeta)` | 973 | `t10`, `t_pico`, `vmax`… del promedio filtrado |
| `figura_scatter(...)` | 1074 | gráfico TRPD |
| `app.layout`, stores | 1125-1131 | layout |
| barra "Configuración Multi-Trigger" | 1167-1232 | los nuevos controles van debajo |
| `actualizar_densidad_store` | 1606 | tabla de densidad |
| `actualizar_panel_metadata` | 1676 | pestaña Metadata |
| `actualizar_scatter` | 1835 | callback del TRPD |

---

## Fase 0 — Preparación y Git

1. `git status`. Si `app.py` tiene cambios de rendimiento sin commitear (lectura HDF5 por ventana, `functools.lru_cache` en `_cargar_segmento_cache`, `welch` vectorizado, decimado de la referencia CH1, `dev_tools_props_check=False`), commitearlos **en `main`** antes de seguir:
   `git add app.py && git commit -m "perf: lectura HDF5 por ventana, cache de segmentos y FFT vectorizada"`
2. `git checkout -b feature/trpd-calibracion-sincronizacion`
3. Primer commit de la rama: `archivos_md/PROMPT_TRPD_Calibracion_Sincronizacion.md` + este plan (`docs: prompt y plan de calibración TRPD`).
4. Comprobación previa: `python -c "import app"` debe importar sin errores. Verifica también que exista `..\mediciones\Mediciones`.

**Criterio de salida:** árbol limpio, en la rama nueva.

---

## Fase 1 — Backend matemático (`app.py`)

Crear un bloque `# ---------------- Calibración de retardo / TRPD ----------------` **justo después de `tiempos_impulso`** (antes de `_IMP_LINEAS`).

### 1.1 `_filtrar_impulso(carpeta, v)` (refactor sin cambio de comportamiento)
Extraer de `impulso_filtrado` (`app.py:936`) el filtrado:
```python
def _filtrar_impulso(carpeta, v):
    """Pasa-bajos Butterworth (IMP_ORDEN, IMP_FCORTE) de fase cero sobre una señal de CH1."""
    fs = 1.0 / meta_medicion(carpeta)["ch1"]["xinc"]
    sos = butter(IMP_ORDEN, IMP_FCORTE, btype="lowpass", fs=fs, output="sos")
    return sosfiltfilt(sos, v)
```
`impulso_filtrado` pasa a usar `_filtrar_impulso(carpeta, v)`.

### 1.2 `t10_por_segmento(carpeta)`: $t_{10}^{(k)}$ con fallback
```python
_T10_SEG_CACHE = {}

def t10_por_segmento(carpeta):
    """t10 (µs) del impulso CH1 filtrado en cada segmento (índice k-1 = segmento k).
    Si falla en un segmento, usa el t10 del impulso promedio. Sin CH1: ceros."""
```
Para cada `s in 1..n_segmentos`:
- `t, v = cargar_segmento(carpeta, "ch1", s)` y `sf = _filtrar_impulso(carpeta, v)`;
- `i_pico = int(np.argmax(sf))`, `vmax = float(sf[i_pico])`;
- si `vmax <= 0`, NaN; si no, `_cruce_subida(t, sf, 0.10*vmax, i_pico)`, con NaN si da `None`.

Los NaN se rellenan con `tiempos_impulso(carpeta)["t10"]`. Si ese valor también es `None`, se usa 0.0. Si no hay `"ch1"` en `canales_presentes`, devuelve `np.zeros(n_segmentos)`. Se guarda en cache un `np.ndarray` float con `writeable=False`. Además, `n_fallback_t10(carpeta)` (o una tupla `(arr, n_fallback)`) informa en la GUI cuántos segmentos usaron fallback.

### 1.3 `_t_arribo(t, v, umbral, distancia, tmin)`: $t_{ant}$ por primer cruce
Algoritmo:
1. Máscara `t >= tmin` (si `tmin` no es None). Tomar `a = np.abs(v)`.
2. `idx, _ = find_peaks(a, height=umbral, distance=distancia)`. Si `idx.size == 0`, devolver `None` (disparo sin chispa).
3. `i_p = idx[0]`. Retroceder desde `i_p` hasta la última muestra `j < i_p` con `a[j] < umbral`. Si no existe (la señal ya supera el umbral desde el primer punto de la ventana), devolver `None`, porque el frente no es observable.
4. Interpolar entre `j` y `j+1`: `t[j] + (umbral - a[j]) * (t[j+1]-t[j]) / (a[j+1]-a[j])`.

Justificación, para el docstring: `distance` hace que un precursor EMI pequeño, a menos de $\Delta t_{cal}$ de la chispa, quede absorbido por el peak mayor.

### 1.4 `calibrar_retardo(carpeta, canal, umbral, dist_us, tmin)`
```python
_CALIB_CACHE = {}
MAD_K = 5.0   # atípico si |t_lag - mediana| > MAD_K · 1.4826 · MAD
```
- Clave de cache: `(carpeta, canal, round(umbral, 6), dist_us, tmin)`.
- `distancia = _muestras(carpeta, canal, dist_us)` y `t10 = t10_por_segmento(carpeta)`.
- Por segmento k: `t, v = cargar_segmento(carpeta, canal, k)`, `ta = _t_arribo(...)`, `t_lag[k-1] = ta - t10[k-1]` o NaN.
- Validez: `valido = ~isnan(t_lag)`. Si hay al menos 3 válidos, calcular mediana y MAD, y marcar `atipico` a los que excedan el criterio (`valido &= ~atipico`). Si MAD == 0, no se marca ninguno.
- Estadísticos sobre `valido`: `t_lag_us = mean`, `sigma_us = std(ddof=1)` (NaN si n<2), `n_valid`, `n_total = n_segmentos`.
- Si `canal` no está presente o `n_valid == 0`: `t_lag_us = None` y se devuelve igual, sin excepción.

Retorna:
```python
{"canal", "segs": list, "t_ant": list, "t_lag": list (None = inválido), "valido": list[bool],
 "atipico": list[bool], "t_lag_us", "sigma_us", "n_valid", "n_total",
 "criterio": "primer_cruce_umbral",
 "params": {"umbral_mv", "distancia_us", "tmin_us"}}
```
Todas las listas deben ser JSON-serializables, porque van a un `dcc.Store`.

### 1.5 Propagación a la captura
- En `capturar` (`app.py:445`), después de armar `segs`: agregar `"t10_seg": t10_por_segmento(carpeta)[seg_arr - 1]` si hay peaks (si no, `np.array([])`). Hacerlo también en el dict vacío del caso "canal no presente". La clave de cache **no cambia**.
- Nueva función:
```python
def t_abs_captura(cap, t_lag_us=0.0):
    """t_abs (µs) = t_peak − t10 del segmento − t_lag del canal. Traslación O(N)."""
    if not cap["t_peak"].size:
        return np.array([])
    return cap["t_peak"] - cap["t10_seg"] - (t_lag_us or 0.0)
```

### 1.6 Estado de calibración (lectura)
```python
def calibracion_desde_metadata(carpeta):
    """Dict para calibracion_store a partir de metadata.yaml (ns -> µs).
    Sin bloque 'calibracion_retardo': calibrado=False y t_lag_us=0.0 por canal."""
```
Formato del store, que es **el contrato** para todos los callbacks:
```python
{"carpeta": str, "calibrado": bool, "fuente": str|None, "fecha": str|None,
 "canales": {"ch2": {"t_lag_us": float, "sigma_us": float|None, "n_valid": int|None, "n_total": int|None},
             "ch3": {...}, "ch4": {...}}}
```
- Por canal, se considera calibrado si existe `t_lag_ns` numérico. `calibrado` global = al menos un canal calibrado. Se agrega `"calibrado"` también por canal.
```python
def lag_canal(cal, carpeta, canal):
    """t_lag (µs) del canal si el store corresponde a la carpeta; 0.0 en otro caso."""
```

**Criterio de salida:** `python -c "import app"` importa bien, y `app.t10_por_segmento("mediciones_filtros/cada_30s/7")` devuelve 50 valores finitos.

---

## Fase 2 — Metadatos y persistencia

### 2.1 `generate_metadata.py`
Agregar:
```python
def bloque_calibracion_retardo(resultados, fuente, sensores=None, fecha=None):
    """Bloque 'calibracion_retardo' para metadata.yaml. resultados: {ch: dict de
    calibrar_retardo o {'t_lag_us','sigma_us','n_valid','n_total','params'}}.
    Unidades de tiempo en ns (3 decimales). fecha por defecto: hoy ISO."""
```
Esquema resultante (claves en este orden):
```yaml
calibracion_retardo:
  fecha: "2026-09-16"
  fuente_calibracion: "calibracion_esferas_30kV"   # id de la carpeta de calibración o "manual"
  criterio: primer_cruce_umbral
  referencia: t10_CH1_por_segmento
  ch2:
    sensor: HFCT
    t_lag_ns: 12.4
    sigma_ns: 0.8
    n_valid: 50
    n_total: 50
    umbral_mv: 35.0
    distancia_us: 0.5
    tmin_us: 0.0
  ch3: {...}
  ch4: {...}
```
- Si `sensores` es None, se usan los nombres por defecto de `plantilla_metadata` (HFCT, Antena Vivaldi, Antena Bioinspirada).
- Valores None → `null`. Solo se incluyen los canales que traen `t_lag_us` no None.
- `plantilla_metadata` **no** agrega este bloque: su ausencia significa "sin calibrar". Documentarlo en el docstring del módulo.

### 2.2 `app.py`: escritura
```python
def guardar_calibracion_metadata(carpeta, bloque):
    """Inserta/reemplaza 'calibracion_retardo' preservando el resto de metadata.yaml."""
    meta = obtener_metadata(carpeta)
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    meta["calibracion_retardo"] = bloque
    return guardar_metadata_archivo(carpeta, yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))
```
Importar `bloque_calibracion_retardo` en la línea de import desde `generate_metadata` (`app.py:26`). Los nombres de sensor salen de `meta["canales"][ch]["sensor"]` cuando existan.

### 2.3 Importar calibración previa
`calibracion_desde_metadata(otra_carpeta)` devuelve el store; luego se reescribe `carpeta` = carpeta actual y `fuente` = `otra_carpeta` (o la `fuente_calibracion` original si existe).

Función auxiliar para el dropdown:
```python
def mediciones_con_calibracion():
    """Mediciones cuyo metadata.yaml en disco contiene 'calibracion_retardo'."""
```
Solo debe leer YAML existentes, **nunca** generar plantillas desde HDF5: es lento. Usar `_dir_medicion` + `os.path.isfile` + `yaml.safe_load`.

**Criterio de salida:** hacer un round-trip `guardar_calibracion_metadata` → `calibracion_desde_metadata` sobre una **copia temporal** de una medición (ver Fase 5.5) y recuperar los µs.

---

## Fase 3 — Frontend Dash (layout + callbacks)

### 3.1 Stores (junto a los existentes, `app.py:1128`)
```python
dcc.Store(id="calibracion_store"),      # contrato §1.6
dcc.Store(id="calibracion_resultado"),  # {ch: dict de calibrar_retardo} de la última corrida (sin aplicar)
```

### 3.2 Barra de calibración (nuevo `html.Div` inmediatamente **debajo** de la barra Multi-Trigger)
Mismo estilo contenedor que la barra Multi-Trigger (`#f8fafc`, borde `#e2e8f0`, `flexWrap`). Contenido:
- `html.Span("⏱ Retardo instrumental:")` en negrita.
- `html.Span(id="cal_badge_estado")`: la píldora (`borderRadius 10px`, `fontSize 11px`) va verde `#d1fae5/#065f46` con "Calibrado · {fuente} · {fecha}", o ámbar `#fef3c7/#92400e` con "Sin calibrar — retardo 0 ns". Mismo estilo que `meta_badge_estado`.
- `html.Span(id="cal_badge_ch2")`, `cal_badge_ch3` y `cal_badge_ch4`: texto `CH2: 12.4 ns` (o `CH2: 0 ns (sin cal.)`), con borde izquierdo del color de `_COLORES_CANALES[ch]`.
- `html.Button("⚙️ Calibrar Retardos", id="btn_toggle_calibracion", n_clicks=0)`.

### 3.3 Panel de calibración `html.Div(id="panel_calibracion", hidden=True, ...)` (debajo de la barra)
1. **Parámetros por canal:** una tarjeta por canal, igual que las del Multi-Trigger, con los inputs `ucal_ch2`, `dtcal_ch2`, `tmincal_ch2` (y sus equivalentes ch3/ch4), `type="number"`, `step="any"`.
2. Botones `btn_calcular_calibracion` ("▶ Calcular desde set actual"), `btn_aplicar_calibracion` ("✔ Aplicar (sesión)") y `btn_guardar_calibracion` ("💾 Guardar en metadata.yaml").
3. `dcc.Loading(dcc.Graph(id="grafico_calibracion"))` y `html.Div(id="cal_tabla_resumen")`.
4. **Retardo manual (ns):** `tlag_manual_ch2`, `tlag_manual_ch3` y `tlag_manual_ch4`, editables.
5. **Importar:** `dcc.Dropdown(id="cal_import_carpeta", options=[...mediciones_con_calibracion()])` + `html.Button("📥 Importar", id="btn_importar_calibracion")`.
6. `html.Div(id="cal_msg_feedback")`.

### 3.4 Función de figura
```python
def figura_calibracion(resultado):
    """make_subplots(1, 2): izq. t_lag^(k) [ns] vs segmento por canal (válidos: marcador
    del color del canal; inválidos/atípicos: 'x' gris); líneas horizontales de media ±σ;
    der. histograma de t_lag válidos [ns] por canal (barmode='overlay', opacity 0.6)."""
```
Se usa `go.Scatter` (pocos puntos). Si `resultado` está vacío, se devuelve una figura con un aviso centrado, igual que `_fig_sin_seleccion`.

### 3.5 Callbacks
| # | Nombre | Inputs → Outputs | Lógica |
|---|---|---|---|
| C1 | `toggle_panel_calibracion` | `btn_toggle_calibracion.n_clicks` → `panel_calibracion.hidden` | `hidden = (n % 2 == 0)` |
| C2 | `init_params_calibracion` | `carpeta.value` → `ucal/dtcal/tmincal_chN.value` (9) | Toma de `config_sensores_defecto(carpeta)` y usa `dist=0.5`, `tmin=0.0` si faltan |
| C3 | `ejecutar_calibracion` | `btn_calcular_calibracion` + States (`carpeta`, 9 params) → `calibracion_resultado.data`, `tlag_manual_chN.value` (3), `cal_msg_feedback.children` | `calibrar_retardo` por canal presente, en `try/except` por canal. Carga manual en ns (`round(t_lag_us*1e3, 3)`), o `no_update` si es None. El mensaje resume `n_valid/n_total` y los canales fallidos |
| C4 | `mostrar_calibracion` | `calibracion_resultado.data` → `grafico_calibracion.figure`, `cal_tabla_resumen.children` | Tabla: Canal, t̄_lag (ns), σ (ns), válidos, % |
| C5 | `gestionar_calibracion_store` | Inputs: `carpeta`, `btn_aplicar_calibracion`, `btn_guardar_calibracion`, `btn_importar_calibracion`; States: `tlag_manual_chN`, `calibracion_resultado`, `cal_import_carpeta` → `calibracion_store.data`, `cal_msg_feedback.children` (allow_duplicate) | **Único escritor del store**, despachado por `ctx.triggered_id`. `carpeta` → `calibracion_desde_metadata`. `aplicar` → valores manuales ns→µs; σ, n y params se toman de `calibracion_resultado` si `abs(manual − calculado) < 1e-6 ns`, y si no son None con `fuente="manual"`; `fuente` = carpeta actual si viene del cálculo. `guardar` → como aplicar + `bloque_calibracion_retardo` + `guardar_calibracion_metadata`, con feedback verde/rojo. `importar` → store de la otra carpeta |
| C6 | `rellenar_manual_desde_store` | `calibracion_store.data` → `tlag_manual_chN.value` (3, `allow_duplicate=True`, `prevent_initial_call=True`) | Muestra en ns los valores activos (cubre carga e importación) |
| C7 | `badges_calibracion` | `calibracion_store.data` → `cal_badge_estado.children/style`, `cal_badge_chN.children` | Textos §3.2 |
| C8 | **modificar** `actualizar_scatter` | + `Input("calibracion_store","data")` | Ver Fase 4. `rev` sin cambios |
| C9 | **modificar** `actualizar_densidad_store` | + `State("calibracion_store","data")` | Pasa `lag_canal(...)` a cada `calcular_fila_densidad` |
| C10 | **modificar** `actualizar_panel_metadata` | + `Input("calibracion_store","data")` | Refresca el YAML crudo tras guardar. Agrega la columna "t_lag (ns)" a `meta_tabla_canales`, leída de `meta.get("calibracion_retardo", {})` |

Ojo con los ciclos: C6 escribe inputs que C5 solo lee como **State**, así que no hay ciclo. `cal_msg_feedback` tiene dos escritores (C3 y C5), así que uno debe llevar `allow_duplicate=True`.

**Criterio de salida:** la app arranca (`python app.py`) sin errores de callbacks en la consola del navegador ni en la de Dash.

---

## Fase 4 — Gráfico TRPD y tabla de densidad

### 4.1 `figura_scatter` (`app.py:1074`)
Nueva firma, compatible hacia atrás:
```python
def figura_scatter(cap, t_ref, v_ref, canal, highlight=None, uirev=None, modo="vmax",
                   t_abs=None, t10_ref=None, t_lag_us=0.0, calibrado=False):
```
- `x = t_abs if t_abs is not None else cap["t_peak"]`.
- **Curva 0** (sin cambiar orden ni cantidad de puntos):
  - `customdata = np.stack([v_peak, vpp, t_peak, seg, x*1e3], axis=1)`;
  - `hovertemplate`: `"t_abs=%{x:.4f} µs (%{customdata[4]:.2f} ns)<br>t_osc=%{customdata[2]:.4f} µs<br>Vmax=%{customdata[0]:.2f} mV<br>Vpp=%{customdata[1]:.2f} mV<br>Seg %{customdata[3]:.0f}<extra>CH?</extra>"`.
- Referencia CH1 (solo en modo vmax, como hoy): `x_ref = t_ref[::paso] - (t10_ref or 0.0)`. Agregar `fig.add_vline(x=0, line=dict(color="#2ca02c", width=1, dash="dot"))` con la anotación "t10".
- Resaltado amarillo: `x[h]`.
- `xaxis_title="Tiempo relativo al impulso t_abs [µs] (t10 = 0)"`.
- Título: `f"Patrón TRPD ({Vpp|Vmax}) — {CANAL} · t_lag = {t_lag_us*1e3:.2f} ns"`, con el sufijo `" (sin calibrar)"` si `not calibrado`.

### 4.2 `actualizar_scatter` (`app.py:1835`)
```python
t_lag = lag_canal(cal, p["carpeta"], p["canal"])
t_abs = t_abs_captura(cap, t_lag)
T = tiempos_impulso(p["carpeta"]); t10_ref = T["t10"] if T else None
calibrado = bool(cal and cal.get("carpeta") == p["carpeta"] and cal["canales"].get(p["canal"], {}).get("calibrado"))
```
`figura_vpp_energia` no cambia.

### 4.3 Tabla de densidad
- `COLUMNAS_DENSIDAD`: agregar `{"name": "t_lag (ns)", "id": "tlag"}` justo antes de `t̄_abs (µs)`.
- `calcular_fila_densidad(carpeta, canal, umbral, dist_us, tmin, t_lag_us=0.0)`: `tabs_mean = mean(t_abs_captura(cap, t_lag_us))`. La fila agrega `"tlag": f"{t_lag_us*1e3:.2f}"`.

### 4.4 No cambian
`figura` (señales crudas, tiempo de osciloscopio), `figura_ventanas`, `figura_fft`, `figura_st_*` (relativas al peak), `_idx_scatter`, `_idx_cruces` y `set_seleccion`.

**Criterio de salida:** la selección por caja o clic en el TRPD sigue resaltando y actualizando ventanas, FFT y ST, igual que antes.

---

## Fase 5 — Verificación

Crear `scripts_tmp/verificar_trpd_cal.py` (**no** commitear; o en una carpeta temporal fuera del repo). Debe correr con `python` desde la raíz del repo e `import app`.

1. **Interpolación sintética de `_t_arribo`:** `t = np.arange(0, 1, 2e-4)` y `v` = rampa lineal que cruza `umbral=1` en `t*=0.30013`, seguida de un pulso. Afirmar `abs(t_ant - t*) < 1e-7`.
   - Sin cruce → `None`.
   - Precursor de 1.05·u a 0.1·Δt antes de un pico de 5·u, con `distance` que cubra ambos: el t_ant sale del flanco del pico **mayor**. Documentar el resultado observado.
   - Señal negativa (−v) → mismo t_ant (usa |v|).
2. **t10 por segmento** en `mediciones_filtros/cada_30s/7`: 50 valores finitos. Imprimir `mean`, `std`, `min` y `max` en ns. Afirmar `abs(mean - tiempos_impulso()["t10"]) < 3·std + 1e-4`. Reportar cuántos usaron fallback.
3. **Humo de calibración** (no hay set de explosor): `calibrar_retardo(carpeta, "ch4", u, 0.5, 0.0)`, con `u` = 60 % del máximo |v| de CH4 en el segmento 1. Imprimir `n_valid/n_total`, `t_lag_us*1e3` y `sigma_us*1e3`. Afirmar que no hay excepción, que `len(t_lag) == n_total` y que los atípicos quedan marcados. Con un umbral absurdo (1e9): `n_valid == 0`, `t_lag_us is None`, sin excepción.
4. **TRPD antes/después:** para cada canal presente, capturar con los parámetros por defecto (`config_sensores_defecto`) e imprimir una tabla con `mean(t_peak)`, `mean(t_abs lag=0)` y `mean(t_abs lag=0.0124 µs)`. Afirmar:
   - `np.allclose(t_abs(0), t_peak - t10_seg)`;
   - `np.allclose(t_abs(0) - t_abs(X), X)`;
   - tamaño de `t_abs` == tamaño de `t_peak`.
5. **Persistencia:** copiar `..\mediciones\Mediciones\mediciones_filtros\cada_30s\7\metadata.yaml` a un respaldo antes de tocarlo. Luego:
   - llamar `guardar_calibracion_metadata` con un bloque de prueba;
   - leer con `calibracion_desde_metadata` y afirmar `t_lag_us == t_lag_ns/1000` y que las secciones `experimento`, `osciloscopio` y `canales` sigan intactas;
   - **restaurar el respaldo** al terminar (en `finally`).
6. **App real:** `python app.py` → `http://127.0.0.1:8050`. Checklist manual o con navegador:
   - [ ] Al cargar una medición sin calibración: badge ámbar, badges en 0 ns.
   - [ ] "⚡ Calcular peaks" → el TRPD muestra el eje "t_abs … (t10 = 0)" y la traza CH1 cruza el 10 % de su cresta en x = 0.
   - [ ] "⚙️ Calibrar Retardos" → "Calcular desde set actual" → dispersión + histograma + tabla, con retardos manuales precargados.
   - [ ] "Aplicar" → badges verdes con ns, y el TRPD se desplaza en X **sin perder el zoom**.
   - [ ] Selección en el TRPD → ventanas, FFT y ST se actualizan (1:1).
   - [ ] Tabla de densidad → columnas `t_lag (ns)` y `t̄_abs` coherentes con la calibración.
   - [ ] Editar un retardo manual → Aplicar → fuente "manual".
   - [ ] "Guardar" (**solo sobre una medición de prueba o con respaldo**) → la pestaña Metadata muestra `calibracion_retardo`. Al recargar la carpeta, el badge sigue verde.
   - [ ] Importar desde otra medición calibrada → los valores cambian.
   - [ ] Consola del navegador sin errores de callbacks.

**Entregable de verificación:** pegar la salida del script (tablas de 2-4) en la descripción del commit final o en la sección "Resultados de verificación" al final de este documento.

---

## Fase 6 — Documentación (`archivos_md/DOCUMENTACION.md`)

Actualizar sin reescribir secciones ajenas:
- **§0 Ruta de los datos + diagrama de flujo:** `metadata.yaml[calibracion_retardo] → calibracion_store → actualizar_scatter / actualizar_densidad_store`.
- **§2 Impulso CH1:** $t_{10}^{(k)}$ por segmento (`t10_por_segmento`), fallback al $t_{10}$ promedio y `_filtrar_impulso`.
- **Nueva sección "Calibración de retardo instrumental"** (después de §2): definiciones de $t_{imp}$, $t_{ant}$ (primer cruce + rol de `distance`/`tmin`), $t_{lag}^{(k)}$, $\bar t_{lag}$, σ (ddof=1), atípicos MAD (k = 5), esquema YAML en ns, $t_{lag}$ relativo a CH1 y los tres orígenes (set actual / importar / manual).
- **§4 Captura:** nueva clave `t10_seg`; `t_abs` calculado fuera de la cache.
- **§7 Gráficos derivados:** eje X, hover, referencia CH1 desplazada y título del TRPD. Nueva columna `t_lag (ns)` en densidad.
- **§10 Mapa de callbacks:** C1-C7 nuevos y cambios en C8-C10.
- **§11 Layout:** barra y panel de calibración, stores nuevos.
- **§12 Casos borde:** disparo sin chispa, t10 fallido, sin calibración (0 ns + badge ámbar), rendimiento O(N), `uirevision`.

---

## Fase 7 — Commits y cierre

Commits sugeridos en la rama:
1. `feat: t10 por segmento y motor de calibración de retardo (t_ant, t_lag)`: Fase 1.
2. `feat: persistencia de calibracion_retardo en metadata.yaml`: Fase 2.
3. `feat: barra y panel de calibración de retardos en la GUI`: Fase 3.
4. `feat: TRPD en tiempo absoluto t_abs y t̄_abs sincronizado en densidad`: Fase 4.
5. `docs: calibración de retardo y TRPD sincronizado en DOCUMENTACION.md`: Fase 6.

No hacer merge a `main` ni push sin confirmación del usuario.

## Archivos a modificar
- `app.py`: bloque de calibración, `impulso_filtrado`, `capturar`, `figura_scatter`, `COLUMNAS_DENSIDAD`, `calcular_fila_densidad`, layout y callbacks.
- `generate_metadata.py`: `bloque_calibracion_retardo` y docstring.
- `archivos_md/DOCUMENTACION.md`.
- `archivos_md/PLAN_TRPD_Calibracion_Sincronizacion.md` (este documento).

---

## Resultados de verificación (Fase 5)

Ejecución de `scripts_tmp/verificar_trpd_cal.py` sobre el entorno virtual (`.venv\Scripts\python.exe`):

```text
=== TEST 1: Verificación sintética de _t_arribo ===
1.1 Cruce exacto esperado: 0.300130, obtenido: 0.300130
1.2 Sin cruce: None [OK]
1.3 Precursor EMI absorbido por pico mayor, ta observado: 0.301000 s [OK]
1.4 Señal negativa: ta=0.300130 igual a positivo [OK]
Test 1 completado exitosamente.

=== TEST 2: t10 por segmento en mediciones_filtros/cada_30s/7 ===
Segmentos: 50, Fallbacks: 0/50
t10 media: -149.188 ns, std: 9.983 ns
t10 min:   -170.407 ns, max: -137.886 ns
t10 promedio global CH1: -151.870 ns
|mean - t10_prom| = 2.6824 ns (< 3*std = 29.9496 ns)
Test 2 completado exitosamente.

=== TEST 3: Humo de calibración en mediciones_filtros/cada_30s/7 ===
Umbral de prueba para CH4: 329.99 mV
CH4: Válidos: 39/50
t_lag_mean: 2425.11 ns, sigma: 1497.00 ns
Atípicos detectados por MAD: 2
Umbral absurdo (1e9 mV) manejado limpiamente: n_valid = 0, t_lag_us = None [OK]
Test 3 completado exitosamente.

=== TEST 4: TRPD antes vs después de calibración en mediciones_filtros/cada_30s/7 ===
Canal  N_peaks  mean(t_peak) [µs]  mean(t_abs 0 ns) [µs]  mean(t_abs 12.4ns) [µs] 
--------------------------------------------------------------------------------
CH2    39       2.2383             2.3884                 2.3760                  
CH3    72       2.6107             2.7604                 2.7480                  
CH4    42       2.6046             2.7554                 2.7430                  
--------------------------------------------------------------------------------
Propiedades matemáticas de t_abs verificadas: O(N), traslación exacta [OK]
Test 4 completado exitosamente.

=== TEST 5: Persistencia y round-trip en metadata.yaml de mediciones_filtros/cada_30s/7 ===
Copia de seguridad creada en C:\0_matrix\doctorado\proyectos\inv_pd_vac\mediciones\Mediciones\mediciones_filtros/cada_30s/7\metadata.yaml.bak_test
Guardado exitoso: Guardado exitoso en metadata.yaml
mediciones_con_calibracion() encontró: 1 carpetas (incluye mediciones_filtros/cada_30s/7)
Secciones originales de metadata.yaml preservadas intactas.
Round-trip de persistencia verificado [OK]
Respaldo restaurado limpiamente en C:\0_matrix\doctorado\proyectos\inv_pd_vac\mediciones\Mediciones\mediciones_filtros/cada_30s/7\metadata.yaml
Test 5 completado exitosamente.

=====================================================
✅ TODAS LAS FASES DE VERIFICACIÓN PASARON CON ÉXITO!
=====================================================
```

