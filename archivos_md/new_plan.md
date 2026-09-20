# Plan: ciclo AVO + correcciones en TRPD_APP + nueva app `calibrar_app`

## Contexto

`TRPD_APP/app.py` (2715 líneas, módulo plano) es el visor de mediciones de descargas parciales bajo impulso tipo rayo: CH1 es el divisor capacitivo (impulso ~1.2/50 µs), CH2/CH3/CH4 son sensores de DP (HFCT, antena Vivaldi, antena bioinspirada). El patrón TRPD grafica cada descarga en el tiempo referido al impulso, lo que exige conocer el retardo instrumental `t_lag` de cada canal sensor respecto a CH1.

Hoy la calibración de `t_lag` vive dentro de `app.py`, ancla en `t10` (10 % de la cresta de CH1 — criterio operacional propio, **no** una convención IEC) y se opera desde un panel embebido en el visor. Dos problemas: el visor mezcla dos roles (analizar mediciones y producir calibraciones), y la referencia temporal no es la normativa. La IEC 60060-1:2010 (Anexos B y C) define el **origen virtual `O1`** mediante un procedimiento riguroso —compensación de línea base, ajuste de curva base doble exponencial, filtrado de la residual con `k(f)` y extrapolación desde `t30`/`t90`— que no está implementado en ninguna parte del repositorio; solo está especificado en `metodologia_tiempos_impulso.md` (raíz, aún sin versionar).

Este trabajo se ejecuta además bajo el **ciclo AVO** del repositorio `sebas30020/tool`, que queda instaurado permanentemente en TRPD_APP. AVO aporta dos mecanismos: **memoria persistente de dos velocidades** (`state.md` reescribible + `ledger.jsonl`/`deadends.md` append-only, todo versionado en git) y **feedback anclado en el entorno** (`verify.sh` emite un JSON con `pass` booleano, y la regla innegociable es que el verificador nunca le pregunta al agente autor si lo hizo bien). El ciclo por intento es: `avo-resume` → `avo-attempt` (proponer, modificar, verificar, evaluar/reparar) → `avo-record` (`commit`/`reject`/`park`), con `avo-pivot` cuando el ledger muestre estancamiento.

Resultado buscado:

1. **Ciclo AVO instaurado y operativo** en TRPD_APP, con un contrato de verificación que dé señal real (hoy daría verde vacío, ver Parte 0).
2. **`app.py` como consumidor puro de calibración**: lee `calibracion_retardo` de `metadata.yaml`, lo aplica al TRPD y a la tabla de densidad, y muestra estado. Más cuatro correcciones de interfaz.
3. **`calibrar_app/`**: app Dash autónoma para producir calibraciones de forma interactiva, capaz de anclar en `t10` o en el `O1` normativo, registrando explícitamente cuál se usó.

Decisiones que enmarcan el plan: `calibrar_app` es **autónoma** (copia propia del código, nunca `import app`); en modo Vpp la referencia de CH1 se muestra **normalizada**; `app.py` **no calcula ni guarda** calibraciones; la referencia por defecto en `calibrar_app` es **`t10`**; perfil AVO **`software`** con una crítica de contexto fresco puntual sobre el pipeline IEC; contrato anclado en **`tests/` con pytest ejecutado por el intérprete del `.venv`**; **métrica por fase**.

### Riesgo dominante: el desfase de ancla de ~260 ns

`t_lag(O1) = t_lag(t10) + (t10 − O1)`, y `t10 − O1 ≈ 0.26 µs` — unas **20 veces mayor que el propio retardo instrumental** (~10 ns). Si `app.py` resta un `t_lag` medido contra O1 mientras sigue anclando el eje en `t10_seg`, la nube TRPD se corre 260 ns sin ningún síntoma visible. De ahí que el bloque en YAML deba declarar la referencia **y** el delta, y que el lector normalice o rehúse explícitamente.

### Hallazgo que condiciona la Parte 2

Medido en `mediciones_filtros/cada_30s/7/ch1.h5`: `XInc = 2e-10 s` (5 GSa/s), `NumPoints = 1000003`, `NumSegments = 50`, `Ue = 3046.73 mV`, y **la cola no baja del 40 % de la cresta hasta t ≈ 88.25 µs**. La ventana `(-5, 30) µs` de `app.py` es por tanto insuficiente para el ajuste del Anexo B: el pipeline O1 debe leer el **registro completo**, mientras `t10` debe seguir calculándose en `(-5, 30)` para ser compatible con el `t10_seg` que consume `capturar`.

---

## PARTE 0 — Instaurar el ciclo AVO

### 0.1 Instalación

```bash
git clone https://github.com/sebas30020/tool.git "$TMPDIR/tool"     # repo privado: requiere gh auth
"$TMPDIR/tool/bin/avo-init" "G:/Mi unidad/yo/usm/investigacion/proyectos/inv_pd_vac/TRPD_APP"
```

`avo-init` es idempotente y copia `bin/avo` + `lib/*.sh` dentro de `.avo/`, así que **el proyecto queda autocontenido** y el clon temporal puede borrarse después. TRPD_APP **no tiene `.claude/` hoy**, así que la instalación es limpia: no hay `settings.json` que fusionar ni `GEMINI.md` que preservar.

Qué queda instalado: `.avo/` (memoria + `verify.sh` + perfiles + CLI), `.claude/` (hooks `SessionStart`/`Stop` y las skills `avo-resume`/`avo-attempt`/`avo-record`/`avo-pivot`), `.gemini/` + `GEMINI.md` (mismo ciclo para Gemini CLI), y `.gitattributes` con `merge=union` sobre el ledger.

**Cambio de flujo de trabajo que conviene saber de antemano:** el hook `Stop` bloquea el fin de sesión (`exit 2`) si el árbol de trabajo cambió y no se registró ningún intento en el ledger durante esa sesión. Es el mecanismo central de la disciplina, no un fallo. El bloqueo es por sesión, no por turno.

**Todo `.avo/` se versiona en git**, incluida la memoria: en este harness, memoria no commiteada es memoria perdida.

### 0.2 Arreglar el verde vacío de `verify.sh` (bloqueante)

Tal cual se instala, en este proyecto **`verify.sh` pasaría sin comprobar nada**: el perfil `software` detecta Python por `requirements.txt`, pero luego no ejecuta ningún check porque no hay `tests/` ni `test_*.py`, no hay `[tool.mypy]` en un `pyproject.toml` (que tampoco existe) y `ruff` no está instalado. Salida: `{"pass":true,"signals":[]}`, exit 0. Un harness cuya regla central es que la señal venga del entorno no puede arrancar dando luz verde sin señal.

Dos landmines más del entorno, verificados en esta máquina:

- **`jq` y `python3` no existen en el PATH** (solo `python`). `verify.sh` intenta leer `.avo/config.json` con `jq`, luego con `python3`, y al fallar ambos cae a `software` por defecto **sin avisar**. Hoy es benigno porque `software` es justo lo que queremos, pero deja de serlo en cuanto alguien cambie el perfil. Parchear el `verify.sh` local para probar también `python` a secas.
- **El `pytest` del PATH es el Python 3.13 global, no el `.venv`** del proyecto (`.venv/Scripts/` solo tiene `python.exe`/`pythonw.exe`). Ejecutar `pytest` a secas fallaría al importar `dash`/`h5py`/`scipy`, dando rojo por la razón equivocada.

Acciones:

1. Añadir `pytest` a `requirements.txt` e instalarlo en el `.venv`.
2. Crear `tests/` (§0.3).
3. Reescribir el `.avo/profiles/software.sh` **local** (el perfil se copia dentro del proyecto justamente para que el dueño lo endurezca) sustituyendo la autodetección por comandos explícitos con el intérprete del venv:
   - `.venv/Scripts/python.exe -c "import app"` — humo de importación; es lo que caza un nombre borrado que todavía se referencia tras la cirugía de §2.10.
   - `.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'calibrar_app'); import main"` — lo mismo para la app nueva.
   - `.venv/Scripts/python.exe -m pytest -q tests/`
   - Emitir `metric_name="tests_fallidos"`, `metric_value=<n>` en el JSON. Es la métrica *del contrato*; la métrica *del intento* (por fase, §0.5) se pasa aparte en `avo record`.

### 0.3 `tests/` — el contrato real

```
tests/
  conftest.py            # skip automático si MEDICIONES no está montado (los datos viven fuera del repo)
  test_iec60060.py       # V1 vectores §8.1/§8.2, V2 filtro k(f), V3 regla de cruce
  test_port_calibrar.py  # V4 equivalencia contra el oráculo, V5 consistencia de anclas
  test_metadata_yaml.py  # V6 round-trip con backup/restore
```

`test_iec60060.py` es **puro numérico y sin I/O**: corre en cualquier máquina, sin datos, y es el núcleo del contrato. `test_port_calibrar.py` y `test_metadata_yaml.py` dependen de los `.h5` reales, que viven fuera del repositorio en `../mediciones/Mediciones` (Google Drive): `conftest.py` los marca como `skip` cuando la ruta no existe, para que el contrato siga siendo verde-significativo en un contenedor sin los datos. El detalle de cada verificación está en §V1–V9.

Nota de coherencia con la filosofía del harness: `scripts_tmp/` está en `.gitignore`, así que **los verificadores no pueden vivir ahí**. Van a `tests/` (versionado). Lo mismo aplica a `metodologia_tiempos_impulso.md`, que hoy está sin versionar y es la especificación normativa de la que depende todo `iec60060.py`: debe entrar al repositorio.

### 0.4 Sembrar la memoria antes del primer intento

- **`.avo/knowledge.md`** ← las invariantes del proyecto, que son exactamente la lista de trampas del final de este plan. Es el archivo cuyo propósito es "lo que no debes violar ni re-descubrir", y esas 16 trampas costaron una investigación entera de descubrir. Sembrarlas ahí es lo que evita que el próximo ciclo (u otro agente) vuelva a tropezar con el split µs/segundos o con los arrays `writeable=False`.
- **`.avo/state.md`** ← objetivo inmediato, métrica de la fase activa y su línea base, `approach_tag` inicial, e hipótesis. Acotado a ~200 líneas; se **reescribe** cada ciclo, no se acumula.
- **`.avo/deadends.md`** ← arranca vacío. La cautela de la ventana `(-5,30)` para el Anexo B **no** va aquí (no es un enfoque que probamos y rechazamos, es un hecho medido): va a `knowledge.md`.
- **`.avo/rubric.md`** ← criterios para la crítica de contexto fresco del pipeline IEC (§0.6): fidelidad al Anexo B, corrección de unidades, trazabilidad de cada constante hasta la norma, y ausencia de auto-validación circular.
- **`.avo/config.json`** ← `profile: "software"`.

### 0.5 Mapa de intentos y métrica por fase

Cada fila es un `avo-attempt` con su `approach_tag`. La métrica va en `avo record --metric-name/--metric-value`; el criterio de `commit` es siempre "`verify.sh` en verde **y** la métrica en su objetivo".

| `approach_tag` | Fase | Métrica | Objetivo |
|---|---|---|---|
| `parte1-ui` | §1.1–1.4 | `regresiones_gui` (booleana) | 0 |
| `oraculo-port` | P0 | `entradas_oraculo` | 4 (t10 + 3 canales) |
| `iec-pipeline` | §2.4 | `err_O1_ns` vs vectores §8.1 | < 1 |
| `port-nucleo` | §2.2–2.3, 2.6 | `max_delta_t_lag_ns` vs oráculo | 0 exacto |
| `calibrar-gui` | §2.5, 2.7–2.8 | `regresiones_gui` (booleana) | 0 |
| `formato-yaml` | §2.9 | `tests_fallidos` | 0 |
| `cirugia-appy` | §2.10 | `ids_colgantes` + `tests_fallidos` | 0 |

Los valores no son comparables entre fases — por eso `state.md` declara cuál está activa. Sí son comparables **dentro** de una fase, que es lo que permite a `avo-pivot` detectar estancamiento (3+ intentos con el mismo tag sin mover la métrica).

Dos reglas del ciclo que aquí muerden de verdad:

- **Una hipótesis por intento.** La Parte 1 son cuatro correcciones independientes; si se mezclan en un solo intento y `verify.sh` da rojo, no se sabe cuál lo rompió. `parte1-ui` puede necesitar cuatro intentos, y eso está bien.
- **Un `reject` revierte el árbol de trabajo** (`git restore .`) salvo que las notas documenten por qué se conserva algo. Antes de cualquier `reject`, `git status` — es la salvaguarda contra descartar trabajo no relacionado.

### 0.6 Crítica de contexto fresco (una vez, no por ciclo)

El perfil queda en `software` (determinista, sin ceremonia por intento). Pero el pipeline IEC tiene una parte que ningún script juzga más allá de los vectores analíticos: si la implementación es *fiel a la norma* o solo *numéricamente coincidente en un caso ideal*. Antes del `commit` del intento `iec-pipeline`, invocar un **agente de contexto fresco** (sin el historial de la sesión que escribió el código) que lea `iec60060.py`, `metodologia_tiempos_impulso.md` y `.avo/rubric.md`, y escriba su veredicto en `.avo/critique.json`. No lo escribe quien programó el pipeline: ese es justamente el punto.

---

## PARTE 1 — Correcciones en `app.py`  ·  `approach_tag: parte1-ui`

### 1.1 Solapamiento leyenda/título en el TRPD

`app.py:1496-1502` (`figura_scatter`). El título es dinámico (`titulo_patron`: canal + `t_lag` + sufijo `(sin calibrar)`) y con `margin=dict(t=50, r=20)` la leyenda horizontal en `y=1.02` se le monta encima.

Subir a `margin=dict(t=75, r=20)` y anclar la leyenda bajo el título: `legend=dict(orientation="h", y=1.04, yanchor="bottom", x=0, xanchor="left")`. Probar con el título más largo posible (`CH4`, `t_lag` de 3 cifras, sufijo `(sin calibrar)`). `figura_peaks` (`app.py:432`) usa el mismo margen pero sin leyenda horizontal: no se toca.

### 1.2 Eliminar la pestaña "Vpp vs Energía"

| Ubicación | Acción |
|---|---|
| `app.py:1916-1917` | Borrar el `dcc.Tab(label="Vpp vs Energía", value="vpp", ...)`. |
| `app.py:719-752` | Borrar `_vpp_energia` y `figura_vpp_energia` (quedan sin uso). |
| `app.py:2610-2611` | Quitar los dos `Input("grafico_vpp_energia", ...)` de `set_seleccion`. |
| `app.py:2615` | Quitar los parámetros `sel_ve, click_ve` de la firma. |
| `app.py:2632-2635` | Quitar las dos ramas `elif trg == "grafico_vpp_energia..."`. |
| `app.py:2644` | Quitar `Output("grafico_vpp_energia", "figure")`. |
| `app.py:2666-2668` | El `return` deja de ser tupla: solo `figura_scatter(...)`. |

**No tocar** `modo_magnitud_trpd` (`app.py:1900-1911`): el `value="vpp"` de la pestaña y el `"value": "vpp"` del RadioItems son espacios de nombres distintos, ningún callback lee `tabs_scatter`, y el selector alimenta `modo=modo` en `figura_scatter`.

### 1.3 Referencia de CH1 también en modo Vpp (normalizada)

`app.py:1476-1485`. La condición `if t_ref is not None and not es_vpp:` oculta en Vpp tanto la curva `CH1 promedio (ref.)` como la vline de `t10`. `v_ref` son mV crudos del impulso (cientos de mV) y `cap["vpp"]` es pico-a-pico en 70 ns de un sensor (mucho menor): quitar la condición sin más estiraría el eje Y y aplastaría los puntos contra cero.

Reemplazar el bloque por una rama única que dibuje en ambos modos, normalizando solo en Vpp:

```python
if t_ref is not None and v_ref is not None and v_ref.size:
    paso = max(1, t_ref.size // IMP_PUNTOS_PLOT)
    x_ref = t_ref[::paso] - (t10_ref or 0.0)
    v_r = v_ref[::paso]
    frac = v_r / (float(np.max(np.abs(v_r))) or 1.0)      # adimensional, -1..1
    if es_vpp:
        esc = float(np.percentile(y_val, 95)) if y_val.size >= 20 else (float(np.max(y_val)) if y_val.size else 1.0)
        y_r, cd_ref = frac * esc, frac
        nombre = "CH1 promedio (forma normalizada)"
        htmpl = "t_abs=%{x:.4f} µs<br>%{customdata:.1%} de la cresta CH1<extra>CH1</extra>"
    else:
        y_r, cd_ref = v_r, None
        nombre, htmpl = "CH1 promedio (ref.)", "t_abs=%{x:.4f} µs<br>%{y:.2f} mV<extra>CH1</extra>"
    fig.add_trace(go.Scattergl(x=x_ref, y=y_r, customdata=cd_ref, mode="lines",
                               name=nombre, line=dict(color="#999", width=1),
                               opacity=0.6, hovertemplate=htmpl))
    fig.add_vline(x=0, line=dict(color="#2ca02c", width=1, dash="dot"),
                  annotation_text="t10", annotation_position="top")
```

`percentile(95)` evita que un Vpp atípico aplaste la forma. En Vpp el hover deja de anunciar mV, porque la curva pasa a ser forma adimensional para ubicar el frente. La vline de `t10` no depende del eje Y.

**Invariante que no se puede romper:** la traza de peaks debe seguir siendo la curva 0 — `_idx_scatter` (`app.py:512-521`) filtra la selección por `curveNumber == 0`. La referencia se añade después, como hasta ahora.

### 1.4 Defectos de multi-trigger y paso fino de umbral

**Defectos** — `config_sensores_defecto` (`app.py:231-235`): poner `dist=0.035` y `tmin=0.15` en `ch2`, `ch3` y `ch4` (hoy `dist` es 1.0/0.5/0.5 y `tmin` es 0.0). `umbral` sigue en `None` para caer en `umbral_defecto`. Los valores de `metadata.yaml` (`distancia_us`, `tmin_us`) mantienen prioridad, que es el comportamiento correcto. Se propagan a la barra multi-trigger vía `sincronizar_parametros_sensores` (`app.py:1985`).

**Paso fino** — los `dcc.Input` numéricos usan `step="any"`, que según HTML5 **desactiva** el incremento de las flechas. Cambiar a paso explícito:

- `umbral_ch2/3/4` (`app.py:1579, 1597, 1615`): `step=0.1` (mV).
- `dist_ch2/3/4` (`1581, 1599, 1617`) y `tmin_ch2/3/4` (`1583, 1601, 1619`): `step=0.005` (µs), coherente con los nuevos defectos.

La sincronización bidireccional no cambia de estructura: `umbrales_desde_relayout` (`app.py:388`) mapea `shapes[i].y0` al canal y `sincronizar_parametros_sensores` (`app.py:1954`) escribe con `round(..., 4)` — más fino que el `step`, así que arrastrar no produce saltos; el `step` solo gobierna flechas y validación del navegador.

---

## PARTE 2 — `calibrar_app` y la cirugía en `app.py`

### Orden de ejecución (crítico)

La equivalencia del código portado solo se puede demostrar **mientras el original exista**. Por tanto:

| Paso | `approach_tag` | Acción |
|---|---|---|
| **P0** | `oraculo-port` | Generar el **oráculo** en el scratchpad (fuera del repo): JSON con `app.t10_por_segmento(carpeta)` y `app.calibrar_retardo(carpeta, ch, u, dist, tmin)` para ch2/ch3/ch4, con `u = 0.6·max|v|` del segmento 1. Sobrevive a la cirugía y es el único testigo del comportamiento previo. |
| **P1** | `parte1-ui` | Parte 1 completa (1.1–1.4), independiente del resto. |
| **P2** | `iec-pipeline`, `port-nucleo`, `calibrar-gui` | Construir `calibrar_app/` (§2.1–2.8). |
| **P3** | `port-nucleo` | Diferenciar el port contra `app.*` y contra el oráculo (§V4). |
| **P4** | `formato-yaml` | Extensión **aditiva** de `generate_metadata.bloque_calibracion_retardo` y de `app.calibracion_desde_metadata` (§2.9). |
| **P5** | `cirugia-appy` | **Recién aquí** las eliminaciones en `app.py` (§2.10). |

### 2.1 Convenciones y arranque

Sin `__init__.py` (el repo no tiene paquetes). Se ejecuta `python calibrar_app/main.py`, lo que pone `calibrar_app/` en `sys.path[0]` y permite `import datos`, `import iec60060`… como módulos planos, igual filosofía que `app.py`. `python -m calibrar_app.main` no funciona por diseño; documentarlo.

Puerto **8051** (8050 está tomado). CSS compartido sin duplicar reglas: `Dash(__name__, assets_folder=os.path.abspath(os.path.join(AQUI, os.pardir, "assets")))` — la restricción de autonomía es de código, no de hoja de estilo. Cuidado: `assets/styles.css` tiene una regla `#btn`; no reutilizar ese id.

Única dependencia cruzada permitida: `generate_metadata` (ya es biblioteca compartida, la importa `app.py:27`). El formato del bloque `calibracion_retardo` debe tener una sola fuente o las dos apps divergirán, así que `persistencia.py` hace `sys.path.insert(0, RAIZ_REPO)` e `import generate_metadata`. **Prohibido `import app`.**

### 2.2 `calibrar_app/datos.py` — HDF5 y metadata

Port casi literal de `app.py`: `_CHAN_RE`, `_orden_natural`, `_ruta`, `canales_presentes`, `listar_mediciones`, `_meta`, `meta_medicion`, `n_segmentos`, `_cargar_segmento_leer`, `_cargar_segmento_cache`, `cargar_segmento`, `_dir_medicion`, `obtener_metadata`, `guardar_metadata_archivo`, `umbral_defecto`, `_muestras`.

```python
VENTANA_T10 = (-5.0, 30.0)   # idéntica a app.T_MIN/T_MAX: t10 debe ser bit-compatible
VENTANA_IEC = None           # registro completo: la cola no baja del 40 % hasta ~88 µs

def cargar_segmento(carpeta, canal, seg, ventana=VENTANA_T10) -> tuple[np.ndarray, np.ndarray]
@functools.lru_cache(maxsize=6)      # 16 MB/entrada con ventana=None (maxsize=48 serían 800 MB)
def _cargar_segmento_cache(carpeta, canal, seg, ventana)
def dt_segundos(carpeta, canal) -> float           # meta["xinc"], en SEGUNDOS
def n_pre_muestras(carpeta, canal, guarda_us=1.0) -> int   # línea base: muestras con t < -guarda
```

### 2.3 `calibrar_app/impulso.py` — marcas estilo `app.py` (ancla t10)

Port de `promedio_impulso`, `_filtrar_impulso` (Butterworth orden 4 / 20 MHz / `sosfiltfilt`), `impulso_filtrado`, `_cruce_subida`, `_cruce_bajada`, `tiempos_impulso`, `t10_por_segmento`, `n_fallback_t10`, con las mismas cachés de sesión. `t10_por_segmento` usa `VENTANA_T10` obligatoriamente.

### 2.4 `calibrar_app/iec60060.py` — pipeline normativo puro (sin I/O, sin Dash)

Código nuevo desde `metodologia_tiempos_impulso.md` §3/§6/§7, **con el bug de §7 corregido**.

```python
A_FILTRO_K = 2.2e-12        # s², constante de k(f) = 1/(1 + 2.2 f²), f en MHz
TOL = {"T1": (0.84, 1.56), "T2": (40.0, 60.0), "beta_max_pct": 10.0}

def compensar_base(u_raw, n_pre, pol=1) -> tuple[np.ndarray, float]
def valor_extremo(u0, suavizado_muestras=0) -> tuple[float, int]
def ventana_ajuste(u0, Ue, i_pk) -> tuple[int, int]           # (d, e), Anexo B d–f
def ajustar_curva_base(t_us, u0, d, e, Ue, diezmado=1) -> dict
def curva_base(t_us, U, tau1, tau2, td) -> np.ndarray
def coeficientes_k(dt_s) -> tuple[float, float]               # (b0, a1), >= 6 cifras
def filtro_k(x, dt_s) -> np.ndarray                           # doble pasada, vectorizada
def respuesta_k(f_mhz) -> np.ndarray                          # analítica, para verificación
def cruce_frente_ultimo(t, u, nivel, i_pk) -> float | None    # t30  (ÚLTIMO)
def cruce_frente_primero(t, u, nivel, i_pk) -> float | None   # t90  (PRIMERO)
def cruce_cola(t, u, nivel, i_pk) -> float | None             # t50
def veredicto_tolerancias(Ut, T1, T2, beta_pct) -> dict
def evaluar_impulso(t_us, u_raw, dt_s, n_pre, pol=1, diezmado_ajuste=1,
                    suavizado_ue_ns=0.0, con_curva=False) -> dict
    # Ue, Ut, Ub, beta_pct, t10, t30, t90, t50, T, T1, O1, T2,
    # tau1, tau2, td, exito_ajuste, veredicto, (Ut_curva si con_curva)
```

Decisiones de implementación:

- **`cruce_frente_ultimo` corrige el bug de §7**: el `front_crossing` de referencia toma el *primer* índice con `u >= nivel` y retrocede, devolviendo el **primer** cruce ascendente, contra lo que piden su propio docstring y la regla P9. Implementar como "último índice `< i_pk` con `u[j] < nivel`" e interpolar entre `j` y `j+1`. Con el vector ideal §8.1 ambos criterios coinciden, así que el bug es invisible ahí y necesita test propio (§V3).
- **`filtro_k` vectorizado**: `b=[b0, b0]`, `a=[1.0, -a1]`, `lfilter` adelante → invertir → `lfilter` → invertir (con `np.ascontiguousarray` en las inversiones) reproduce exactamente la recursión `y[i] = b0(x[i]+x[i-1]) + a1·y[i-1]` con estado inicial nulo. El bucle Python de §7 es inviable a 1e6 muestras × 2 pasadas × 50 segmentos. `np.asarray(x, dtype=np.float64)` al entrar, porque el `np.empty_like` de §7 truncaría una entrada entera.
- **`curva_base` sin overflow**: evaluar solo donde `t >= td` con máscara (no `np.where`, que evalúa ambas ramas) y `np.clip(arg, -700, 700)` antes de `exp`.
- **`ajustar_curva_base`**: normalización del Anexo C.1 (`x = (t−t[d])/span`, `y = u/Ue`, `p0 = [1, 70/span, 0.4/span, −t[d]/span]`), `least_squares(method="lm", max_nfev=20000)`, desescalado al final. Si no converge, reintento con `method="trf"` acotado (`tau2 > 0`, `tau1 > tau2`); si vuelve a fallar, `exito=False` y tiempos sobre `u0` marcando "sin Anexo B" (§9 de la metodología). `diezmado_ajuste` porque la ventana `d..e` son ~440 000 muestras para 4 parámetros: diezmar a ~1/50 no cambia el ajuste y lo acelera un orden de magnitud. **Los cruces siempre a resolución completa.**
- **`ventana_ajuste`**: además del `e` normativo ("último índice con `u0 > 0.4·Ue`"), calcular el primer cruce descendente de `0.4·Ue` tras el pico y avisar si difieren en más de ~1 µs; en cola ruidosa el "último índice" puede engancharse a una excursión tardía.
- **Unidades**: sufijos obligatorios en los nombres (`t_us`, `dt_s`) y `assert dt_s < 1e-6` al entrar en `filtro_k`/`coeficientes_k`. El split µs/segundos de §7 es la trampa de unidades más probable.

### 2.5 `calibrar_app/referencia.py` — selector de ancla

Único módulo que conoce a la vez `impulso.py` e `iec60060.py`.

```python
REFERENCIAS = ("t10", "origen_virtual_IEC60060")

def ancla_por_segmento(carpeta, referencia="t10") -> dict
    # {"ancla_us": ndarray(nsegs), "referencia": str, "n_fallback": int, "detalle": [...] | None}
def evaluar_segmento_iec(carpeta, seg, **kw) -> dict      # evaluar_impulso sobre ch1 completo
def resumen_iec(carpeta) -> dict                          # T1/T2/Ut/beta medios, fuera de tolerancia
def delta_t10_menos_O1(carpeta) -> dict                   # {"media_us","sigma_us","n","por_segmento"}
```

`delta_t10_menos_O1` es la pieza que permite que `app.py` siga anclando en `t10` aunque la calibración se haya hecho contra `O1`. Cachés de sesión por `(carpeta, referencia)`.

### 2.6 `calibrar_app/arribo.py` — arribo y t_lag

Port de `_t_arribo` (verbatim: ya verificado a 1e-7 por el script existente), `_muestras`, `MAD_K = 5.0`, y `calibrar_retardo` generalizada al ancla.

```python
def t_arribo(t_us, v, umbral, distancia, tmin) -> float | None        # == app._t_arribo
def t_arribo_por_segmento(carpeta, canal, umbral, dist_us, tmin) -> np.ndarray
def filtrar_mad(x) -> tuple[np.ndarray, np.ndarray, float, float]
def calibrar_retardo(carpeta, canal, umbral, dist_us, tmin, referencia="t10") -> dict
    # misma forma JSON que app.calibrar_retardo + {"referencia", "ancla_us"}
```

Conservar literalmente la semántica de `app.py` (MAD con `n >= 3`, `mean`, `std(ddof=1)` solo si `n_valid >= 2`, `criterio="primer_cruce_umbral"`, `params`), sustituyendo `t10[s-1]` por `ancla[s-1]`. Así, con `referencia="t10"`, el resultado es diferenciable bit a bit contra el original.

### 2.7 `calibrar_app/figuras.py`

```python
def figura_canal(carpeta, canal, seg, umbral, dist_us, tmin, ancla_us, t_arr_us) -> go.Figure
def figura_impulso_iec(carpeta, seg, res_iec) -> go.Figure    # u0, Um, Ut_curva, vlines t30/t90/t50/t10/O1
def figura_dispersion_lag(resultados) -> go.Figure            # port de app.figura_calibracion (1x2)
def figura_ancla_por_segmento(carpeta, referencia, info) -> go.Figure
def umbral_desde_relayout(relayout, fallback) -> float        # portada de app.py:408 (código muerto allí)
```

`figura_canal`: traza decimada (la detección corre a resolución completa), **una sola** `add_hline` editable ⇒ `shapes[0]` ⇒ la variante mono-shape `umbral_desde_relayout` es robusta (sin el mapeo por orden que necesita `umbrales_desde_relayout`); `uirevision=f"{carpeta}|{canal}"` para que arrastrar no reinicie el zoom; marcador en `t_arr`, vline en el ancla, anotación con `t_arr / ancla / t_lag` en ns.

`umbral_desde_relayout` (`app.py:408-417`) es código muerto en `app.py` hoy: portarlo aquí y borrarlo allí en la misma cirugía.

### 2.8 `calibrar_app/interfaz.py` + `calibrar_app/main.py`

`interfaz.py` expone `layout(mediciones, carpeta_inicial) -> html.Div` y los dicts de estilo, dejando el árbol fuera del módulo de callbacks sin riesgo de import circular. `main.py` instancia `Dash`, asigna el layout, define los callbacks y corre en 8051.

Controles: `carpeta`, `canal` (ch2/3/4), `segmento`, `referencia` (radio `t10` / `origen_virtual_IEC60060`), `ucal` (numérico sincronizado con el arrastre, `step=0.1`), `dtcal`, `tmincal`, `fuente_calibracion` (texto), `diezmado_ajuste`, botones `btn_calcular` / `btn_evaluar_iec` / `btn_guardar`. Stores `resultado_store`, `iec_store`. Gráficos `grafico_canal`, `grafico_impulso`, `grafico_dispersion`, `grafico_ancla`. `tabla_resumen` + `msg_feedback`.

Sincronía umbral↔arrastre, con el patrón de `sincronizar_parametros_sensores` (`app.py:1968`):

```python
@app.callback(Output("ucal", "value"),
              Input("grafico_canal", "relayoutData"),
              Input("carpeta", "value"), Input("canal", "value"),
              prevent_initial_call=False)
def sincronizar_umbral(relayout, carpeta, canal):
    # ctx.triggered_id == "grafico_canal" -> umbral_desde_relayout(...); si no, umbral_defecto(...)
```

La figura toma `ucal.value` como Input; no hay bucle porque redibujar no emite `relayoutData`.

Rendimiento: `ancla_por_segmento(..., "origen_virtual_IEC60060")` son 50 evaluaciones sobre registros de 1000003 muestras ≈ 0.3 s cada una ⇒ ~15 s. Envolver en `dcc.Loading` y ofrecer "evaluar solo el impulso promedio" como vista previa rápida.

### 2.9 Formato del bloque y lector (extensión aditiva)

`generate_metadata.bloque_calibracion_retardo` gana dos parámetros; **las claves de canal no cambian**, para que el lector actual siga funcionando:

```python
def bloque_calibracion_retardo(resultados, fuente, sensores=None, fecha=None,
                               referencia_impulso="t10", info_ancla=None):
```

```yaml
criterio: primer_cruce_umbral
referencia: origen_virtual_IEC60060_por_segmento   # clave LEGADO, se sigue escribiendo
referencia_impulso: origen_virtual_IEC60060        # clave canónica nueva
ancla:                                             # obligatoria si referencia_impulso == O1
  metodo: IEC60060-1_AnexoB
  t10_menos_O1_ns: 258.4
  sigma_t10_menos_O1_ns: 3.1
  n_segmentos: 50
  T1_medio_us: 1.21
  T2_medio_us: 49.8
  beta_medio_pct: 0.8
  beta_max_pct: 2.1
  segmentos_fuera_tolerancia: 0
ch2: {sensor: HFCT, t_lag_ns: ..., sigma_ns: ..., n_valid: ..., n_total: ..., umbral_mv: ..., distancia_us: ..., tmin_us: ...}
```

`referencia` se deriva de `referencia_impulso` con el mapa `{"t10": "t10_CH1_por_segmento", "origen_virtual_IEC60060": "origen_virtual_IEC60060_por_segmento"}`, así el YAML sigue siendo legible por lectores viejos y por humanos.

Lector `app.calibracion_desde_metadata` (`app.py:1200`), extensión aditiva:

```python
ref = bloque.get("referencia_impulso")
if ref is None:                                  # compatibilidad con bloques ya escritos
    leg = str(bloque.get("referencia") or "")
    ref = "origen_virtual_IEC60060" if "origen_virtual" in leg else "t10"
delta_ns = (bloque.get("ancla") or {}).get("t10_menos_O1_ns")
```

- `ref == "t10"` → `t_lag_us = t_lag_ns*1e-3` (**idéntico a hoy**).
- `ref == O1` con `delta` → `t_lag_us = t_lag_ns*1e-3 − delta_us`, de `t_lag_O1 = t_lag_t10 + (t10 − O1)`.
- `ref == O1` **sin** `delta` → `t_lag_us = 0.0`, `calibrado = False`, `aviso` explicando que no se puede convertir. Rehusar es muy preferible a aplicar callado un error de ~260 ns; `calibrar_app` escribe `ancla` siempre que la referencia sea O1.

El store gana `referencia_impulso`, `delta_t10_O1_us` y `aviso`.

### 2.10 Cirugía en `app.py`: "solo consumidor"

**Layout.** Conservar `dcc.Store(id="calibracion_store")` (1521) y la barra de badges (1624–1664), cambiando el texto del botón a `"⏱ Detalle del retardo"` y añadiendo un `html.Span` que apunte a `calibrar_app` (puerto 8051). Borrar `dcc.Store(id="calibracion_resultado")` (1522). Conservar el contenedor `panel_calibracion` (1666–1673) y su cabecera, reescrita como *"Retardo instrumental almacenado en metadata.yaml (solo lectura)"*; borrar `cal_msg_feedback` (1680) y **todo** el bloque 1683–1759 (tarjetas de parámetros, botonera, manuales, importar, gráfico y tabla). Como único hijo nuevo: `html.Div(id="cal_detalle")` + `html.Button("🔄 Recargar desde disco", id="btn_recargar_calibracion", n_clicks=0)`.

Ids que desaparecen (verificado que ninguno queda referenciado): `ucal_ch2/3/4`, `dtcal_ch2/3/4`, `tmincal_ch2/3/4`, `tlag_manual_ch2/3/4`, `cal_import_carpeta`, `btn_calcular/aplicar/guardar/importar_calibracion`, `grafico_calibracion`, `cal_tabla_resumen`, `cal_msg_feedback`, `calibracion_resultado`.

**El panel sobrevive como resumen de solo lectura** porque los badges solo muestran ns: la trazabilidad metrológica (fuente, fecha, criterio, σ, `n_valid/n_total`, umbral usado) y sobre todo `referencia_impulso` + `t10 − O1` no caben en un badge, y son justo lo que hay que poder auditar cuando la nube TRPD aparece desplazada. Además `toggle_panel_calibracion` queda intacto; borrarlo obligaría a reestructurar la barra de badges (más diff, no menos).

**Callbacks a borrar** (de abajo hacia arriba para no desplazar líneas): `rellenar_manual_desde_store` (2341–2357), `gestionar_calibracion_store` (2249–2338), `mostrar_calibracion` (2201–2246), `ejecutar_calibracion` (2151–2198), `init_params_calibracion` (2127–2148).

**Callbacks intactos**: `toggle_panel_calibracion` (2118–2124) y `badges_calibracion` (2360–2391) — sus Inputs/Outputs sobreviven todos.

**Dos callbacks nuevos.** El primero es el único poblador del store, sustituyendo la rama final de `gestionar_calibracion_store`:

```python
@app.callback(
    Output("calibracion_store", "data"),
    Input("carpeta", "value"),
    Input("btn_recargar_calibracion", "n_clicks"),
)
def cargar_calibracion_store(carpeta, _n):
    """Único poblador de `calibracion_store`: lee `calibracion_retardo` de
    metadata.yaml (ns -> µs, normalizado al ancla t10)."""
    if not carpeta:
        return no_update
    return calibracion_desde_metadata(carpeta)
```

Sin `allow_duplicate` ⇒ sin `prevent_initial_call`: dispara en la carga inicial porque `carpeta` arranca con `CARPETA_INICIAL`. El botón de recarga existe porque `calibracion_store` es memoria de sesión del navegador: tras guardar desde `calibrar_app`, `app.py` no lo vería hasta cambiar de medición. No hay caché de metadata que invalidar (`obtener_metadata` relee el archivo en cada llamada).

El segundo llena el panel: `mostrar_detalle_calibracion(cal)` con `Output("cal_detalle", "children")`, `Input("calibracion_store", "data")` — cabecera (`fuente_calibracion`, `fecha`, `criterio`, `referencia_impulso`, y si aplica `t10 − O1 = … ns ± …`), tabla `Canal | Sensor | t̄_lag (ns) | σ (ns) | Válidos | u_cal (mV) | Δt (µs) | t_mín (µs)`, y si no hay bloque: *"Sin bloque `calibracion_retardo` en metadata.yaml para ‹carpeta› — retardo 0 ns. Calcular en calibrar_app (puerto 8051)."*

**Funciones de módulo a borrar** (call-site único, en código que se elimina): `_t_arribo` (1075–1102), `_CALIB_CACHE` y `MAD_K` (1105–1106), `calibrar_retardo` (1109–1187), `guardar_calibracion_metadata` (1268–1273), `mediciones_con_calibracion` (1276–1290), `figura_calibracion` (1293–1381), `umbral_desde_relayout` (408–417, ya muerto), `import datetime` (13) y `bloque_calibracion_retardo` del import de la línea 27. **No** quitar `make_subplots`: lo siguen usando `figura` y `figura_st_segmento`.

**Funciones que se conservan** por tener consumidores vivos: `t10_por_segmento` (usada por `capturar`), `t_abs_captura` (densidad y scatter), `calibracion_desde_metadata` (nuevo poblador), `lag_canal`, `promedio_impulso` / `_filtrar_impulso` / `impulso_filtrado` / `_cruce_subida` / `_cruce_bajada` / `tiempos_impulso`, `guardar_metadata_archivo` (pestaña Metadata), `config_sensores_defecto`, `n_fallback_t10` (sin call-site en `app.py` pero lo usa el script de verificación).

**La pestaña Metadata no se ve afectada**: el bloque 2556–2570 itera solo sobre `CANALES`, nunca sobre claves de nivel de bloque, así que añadir `referencia_impulso` y `ancla` no rompe el renderizado. Mejora opcional de 2 líneas: mostrar `referencia_impulso` y `ancla.t10_menos_O1_ns` bajo la tabla de canales.

---

## Verificación

Lo automatizable vive en `tests/` y es lo que `verify.sh` ejecuta en cada `avo-attempt`. Lo que exige un navegador (V8, V9) es comprobación manual antes del `commit` de su fase.

**V1 — vectores analíticos §8.1** (`tests/test_iec60060.py`). Impulso ideal: `t = np.arange(-1.0, 200.0, 0.002)` µs, `τ1 = 68.21697156`, `τ2 = 0.40503431`, cresta 100 kV, `n_pre = 500`, `dt_s = 2e-9`. Asserts con tolerancia de medio dígito del último decimal publicado: `Ut = 100.000` (5e-3), `t30 = 0.1394` (5e-4), `t90 = 0.8594` (5e-4), `T1 = 1.2000` (1e-3), `O1 = −0.2206` (1e-3), `t50 = 49.7794` (2e-3), `T2 = 50.000` (5e-3), `β' < 0.01 %`, `τ1/τ2` recuperados (0.01 / 1e-4), `t10 = 0.0413` (5e-4). El error en `O1` es la métrica `err_O1_ns` de la fase `iec-pipeline`. §8.2 con 0.5 % de ruido (`default_rng(0)`): `|T1 − 1.2| < 5e-3`, `|O1 + 0.2206| < 5e-3` y `0.5 % < β' < 3 %` — rango y no valor, porque β' es el único parámetro no robusto.

**V2 — filtro k(f)**, cuatro comprobaciones independientes:
1. `coeficientes_k` para `Ts ∈ {10e-9, 1e-9, 0.2e-9}` contra la tabla verificada de la metodología, `abs < 1e-9` (la norma exige ≥6 cifras significativas).
2. Respuesta en frecuencia: `N = 65536`, impulso unitario **centrado** (la doble pasada no es circular; media ventana ≈ 27 constantes de tiempo, así que las colas decaen dentro del array), `H = |rfft(filtro_k(x, Ts))|` contra `respuesta_k` en `0..5 MHz`, assert `max|H − k| < 1e-3` (la metodología reporta 2.9e-4 a 10 ns). Repetir a `Ts = 10 ns`.
3. Fidelidad del port vectorizado: implementar en el propio test el bucle literal de §7 y comparar con `filtro_k` sobre ruido gaussiano de 5000 muestras, `max|Δ| < 1e-12`. Esto convierte el cambio de rendimiento en un refactor demostrado.
4. Guarda de dtype: `filtro_k(np.arange(100, dtype=np.int16), 1e-9)` debe dar `float64` y coincidir con la versión float.

**V3 — la regla de cruce** (el bug de §7, que §8.1 no puede detectar). Sobre el impulso ideal, añadir una espiga de 3 muestras de `0.35·Ut` en `t = −0.5 µs`: `cruce_frente_primero(0.3·Ut) ≈ −0.5` (ancla equivocada) y `cruce_frente_ultimo(0.3·Ut) ≈ 0.1394`. Assert `|ultimo − 0.1394| < 5e-4` **y** `|primero − ultimo| > 0.5`, probando que los dos criterios son distinguibles y que el pipeline usa el correcto. `evaluar_impulso` sobre esa señal debe seguir dando `O1 = −0.2206 ± 2e-3`. Caso simétrico: una espiga de `0.95·Ut` tras el pico no debe mover `t90`.

**V4 — equivalencia del port contra `app.py`** (`tests/test_port_calibrar.py`), ejecutado **antes** de la cirugía:
1. `arribo.t_arribo` vs `app._t_arribo` sobre los vectores sintéticos del script existente → diferencia exactamente 0.
2. `impulso.t10_por_segmento` vs `app.t10_por_segmento` → `allclose(rtol=0, atol=1e-12)`. Solo válido porque ambos usan `(-5, 30)`.
3. `arribo.calibrar_retardo(..., referencia="t10")` vs `app.calibrar_retardo(...)` para ch2/ch3/ch4 → `t_lag_us`, `sigma_us`, `n_valid`, `n_total`, `valido`, `atipico` idénticos, y también contra el oráculo JSON del paso P0. El máximo `|Δt_lag|` es la métrica `max_delta_t_lag_ns` de la fase `port-nucleo`, y su objetivo es **0 exacto**, no "pequeño".
4. Umbral absurdo `1e9` → `n_valid == 0`, `t_lag_us is None`, sin excepción.

**V5 — consistencia de anclas** (la salvaguarda de los 260 ns):
1. `delta_t10_menos_O1(carpeta)["media_us"]` debe caer en `[0.18, 0.34]` µs — cota física de la metodología para `T1 ∈ [0.84, 1.56]`, sin valores de referencia externos.
2. Con el mismo canal y umbral, `t_lag(O1) − t_lag(t10)` debe igualar ese delta dentro de `3·(σ/√n) + 2 ns`.
3. End-to-end: guardar con `referencia_impulso="t10"` y leer con `app.calibracion_desde_metadata` → `t_lag_A`; guardar con `O1` + `ancla` → `t_lag_B`; assert `|A − B| < 3σ`. Es la prueba de que ambas referencias producen **el mismo TRPD**.

**V6 — round-trip de `metadata.yaml`** (`tests/test_metadata_yaml.py`) sobre `mediciones_filtros/cada_30s/7` (el **único** `metadata.yaml` en disco, y sin bloque `calibracion_retardo` todavía), con `shutil.copy2` y restauración en `finally`: bloque O1 con `ancla` → la resta de delta se aplica; bloque **legado** (solo `referencia: t10_CH1_por_segmento`) → `t_lag_us == t_lag_ns*1e-3` sin modificar y `calibrado is True` (compatibilidad retroactiva demostrada); bloque O1 **sin** `ancla` → `calibrado is False`, `t_lag_us == 0.0`, `aviso` no vacío; secciones `experimento`/`probeta`/`canales`… intactas tras el merge.

**V7 — migrar el script existente.** `scripts_tmp/verificar_trpd_cal.py` está en un directorio gitignorado, así que su contenido debe migrar a `tests/`. Tras la cirugía, sus tests 1, 3 y 5 referencian `app._t_arribo`, `app.calibrar_retardo`, `app.guardar_calibracion_metadata` y `app.mediciones_con_calibracion` → `AttributeError`: reapuntarlos a `calibrar_app`. Los tests 2 y 4 siguen siendo válidos sobre `app.py` y se conservan como regresión de lo retenido.

**V8 — GUI de `app.py`.** Estático primero, dentro de `verify.sh`: `import app` sin excepción, y `rg` de cada id eliminado → 0 coincidencias (un id colgante en un `Input/Output/State` no falla en el import, sino con *"A nonexistent object was used…"* en la primera carga de página; ese conteo es la métrica `ids_colgantes`). Luego en el navegador (`python app.py`, `http://127.0.0.1:8050`), con `cada_30s/7`, cuyo camino por defecto es el **no calibrado**:

1. Consola sin errores y sin el toast rojo de Dash.
2. Badges `"Sin calibrar — retardo 0 ns"` / `CH2..CH4: 0.00 ns`. Como ese es también el estado inicial por defecto, el testigo real de que `cargar_calibracion_store` disparó es el panel: debe decir *"Sin bloque calibracion_retardo… para mediciones_filtros/cada_30s/7"*, texto que solo puede venir del store.
3. `⏱ Detalle del retardo` → el panel abre con **solo** la tabla de lectura (cero inputs, cero botones de cálculo, cero gráfico); segundo clic cierra.
4. Trigger `ch4`, `⚡ Calcular peaks` → el TRPD se dibuja, título terminando en `· t_lag = 0.00 ns (sin calibrar)`, curva gris de CH1 y vline verde de t10 en x=0.
5. Magnitud TRPD → **Vpp**: la curva gris **ahora aparece**, escalada, con la vline en 0, eje Y todavía `Vpp [mV]` y su máximo dominado por los Vpp (no por los mV de CH1); el hover de la curva gris dice `% de la cresta CH1`.
6. Pestaña Densidad → `⚡ Calcular todos los sensores` → filas CH2/CH3/CH4 con `t_lag (ns) = 0.00` y `t̄_abs (µs)` poblado (prueba `lag_canal` + `t_abs_captura`).
7. Pestaña Metadata → tarjetas pobladas y textarea con el YAML de disco. **No** pulsar guardar (reescribiría el archivo).
8. Selección: clic en una cruz del canal trigger y caja de selección en el scatter → puntos en amarillo y "Señales"/"FFT" actualizadas. Prueba que el orden de trazas no rompió el invariante de la curva 0.

Ruta calibrada: con `calibrar_app` en 8051, calcular y guardar para `cada_30s/7`; en `app.py` pulsar `🔄 Recargar desde disco` → badge verde con fuente y fecha, ns por canal distintos de 0, panel con σ / `n_valid` / referencia, y la nube TRPD desplazada exactamente `t_lag`: en el hover `t_osc` no cambia y `t_abs` baja en `t_lag`. Repetir con un bloque de referencia O1 y comprobar que el desplazamiento sigue siendo de ~10 ns y **no** de ~270 ns. Restaurar `metadata.yaml` del backup al terminar.

**V9 — GUI de `calibrar_app`** (8051): arrastrar la línea de umbral actualiza la caja sin perder el zoom; escribir en la caja mueve la línea; subir `t_mín` por encima del arribo hace desaparecer el marcador y cuenta el segmento como inválido; `▶ Calcular` da dispersión + histograma y tabla con `t̄_lag ± σ` y `n_valid/50`; cambiar la referencia de t10 a O1 sube todos los `t_lag` ~258 ns de golpe (comprobación visual instantánea del ancla); `💾 Guardar` deja en el YAML `referencia_impulso` y `ancla`.

---

## Invariantes del proyecto → semilla de `.avo/knowledge.md`

Esta lista es el contenido inicial de `.avo/knowledge.md`: lo que no se debe violar ni volver a descubrir.

1. **Ancla t10 vs O1 = ~260 ns de error sistemático**, ~20× el retardo que se mide. `referencia_impulso` + `ancla.t10_menos_O1_ns` son obligatorios; el lector normaliza o rehúsa.
2. **La ventana `(-5, 30) µs` no alcanza para el Anexo B** (la cola baja del 40 % a ~88 µs): O1 sobre registro completo, t10 sobre `(-5, 30)`.
3. **`front_crossing` de §7 devuelve el PRIMER cruce** donde P9 pide el ÚLTIMO; invisible con el vector ideal.
4. **Split de unidades**: `t` en µs pero `dt` en segundos dentro del filtro. Sufijos en los nombres y `assert`.
5. **`exp` desborda en `Um`** si `td` queda muy adelante: máscara + `clip`, no `np.where`.
6. **`np.empty_like` trunca entradas enteras** en el filtro: `asarray(..., float64)` al entrar.
7. **Bucle O(N) en Python** en `k_filter`: sustituir por `lfilter` adelante+atrás y demostrar la equivalencia.
8. **Arrays cacheados con `writeable=False`**: toda operación fuera de sitio (`u0 = v - base`, nunca `v -= base`).
9. **`lru_cache` de registros completos**: 16 MB/entrada ⇒ `maxsize=6`, no 48.
10. **CH1 lleva dos suavizados distintos** (Butterworth 20 MHz para t10, k(f) a 0.674 MHz para O1): cada ancla se usa de extremo a extremo, jamás mezclar t10 de un filtro con O1 del otro. Mantener `sosfiltfilt` (fase cero): un filtro causal añadiría ~8 ns de retardo de grupo, del mismo orden que el `t_lag` medido.
11. **El índice `e`** del Anexo B es frágil con cola ruidosa: contrastar con el primer cruce descendente de `0.4·Ue`.
12. **`β'` no es robusto**: `Ue` es un máximo puntual y el ruido lo infla (0.5 % de ruido → β' = 1.5 %).
13. **`least_squares(method="lm")` no admite cotas** y sin la normalización C.1 no converge.
14. **`calibracion_store` es memoria de sesión del navegador**: de ahí el botón de recarga.
15. **La curva 0 del scatter TRPD es la de peaks** — `_idx_scatter` filtra por `curveNumber == 0`; cualquier traza nueva va después.
16. **Convenciones de unidades y direcciones**: µs y mV en memoria, ns en disco (YAML) y en la GUI; segmentos 1-based; `carpeta` siempre relativa a `MEDICIONES` con `/`; los datos `.h5` viven **fuera** del repositorio.
17. **Entorno Windows**: no hay `jq` ni `python3` en el PATH, y el `pytest` del PATH no es el del `.venv`. Todo comando de verificación usa `.venv/Scripts/python.exe` explícitamente.

Higiene pendiente, no bloqueante: `archivos_md/PROMPT_TRPD_Calibracion_Sincronizacion.md:5` apunta a `C:\0_matrix\...` y **sí** está versionado (mientras `archivos_md/PLAN_*.md` está ignorado). Corregir esa ruta y actualizar `archivos_md/DOCUMENTACION.md` con la nueva topología: dos apps, puertos 8050/8051, dónde vive ahora el cálculo de calibración, y el ciclo AVO.

---

## Archivos críticos

- `TRPD_APP/.avo/` — memoria del harness, `verify.sh` y el perfil local endurecido. **Se versiona.**
- `TRPD_APP/.claude/` — hooks y skills del ciclo (instalados por `avo-init`).
- `TRPD_APP/tests/` — nuevo: `conftest.py`, `test_iec60060.py`, `test_port_calibrar.py`, `test_metadata_yaml.py`.
- `TRPD_APP/app.py` — Parte 1 completa y cirugía §2.10.
- `TRPD_APP/generate_metadata.py` — `bloque_calibracion_retardo` (§2.9).
- `TRPD_APP/metodologia_tiempos_impulso.md` — especificación de `iec60060.py`; **hay que versionarlo**.
- `TRPD_APP/calibrar_app/` — nuevo: `datos.py`, `impulso.py`, `iec60060.py`, `referencia.py`, `arribo.py`, `persistencia.py`, `figuras.py`, `interfaz.py`, `main.py`.
- `TRPD_APP/requirements.txt` — añadir `pytest`.
- `../mediciones/Mediciones/mediciones_filtros/cada_30s/7/metadata.yaml` — único YAML en disco; usar siempre con backup.
