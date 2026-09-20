# Plan ejecutable: arreglar el arranque del servidor (8050 / 8051)

> Documento autocontenido para un agente que ejecuta sin haber visto el diagnóstico.
> Proyecto: `G:\Mi unidad\yo\usm\investigacion\proyectos\inv_pd_vac\TRPD_APP`
> Rama: `main` · Último commit relevante: `c3f515b`
> Fecha del diagnóstico: 2026-09-20

## 1. Qué se reportó y qué está pasando en realidad

Síntoma reportado: *"no se ejecuta el servidor `http://127.0.0.1:8050`"*.

**El código no está roto.** Arrancado con el intérprete del entorno virtual, `app.py` levanta y responde correctamente. Verificado así:

```bash
cd "G:/Mi unidad/yo/usm/investigacion/proyectos/inv_pd_vac/TRPD_APP"
./.venv/Scripts/python.exe -u app.py &
curl -s -o /dev/null -w "%{http_code}\n" --retry 8 --retry-delay 2 --retry-all-errors http://127.0.0.1:8050/
# -> 200
# log: "Dash is running on http://127.0.0.1:8050/"
```

Importante para no reabrir trabajo ya hecho: **el plan anterior está íntegramente implementado** en `c3f515b`. Verificado en el código: margen `t=75` y `legend(y=1.04)` en `figura_scatter` (`app.py:1263-1264`), pestaña "Vpp vs Energía" eliminada (0 referencias a `grafico_vpp_energia`), curva CH1 normalizada en modo Vpp (`app.py:1236-1239`, con `frac` y `percentile(95)`), defectos de trigger `dist=0.035` / `tmin=0.15` (`app.py:231-233`), cirugía de `app.py` a consumidor puro (`cal_detalle` y `btn_recargar_calibracion` presentes; `btn_calcular_calibracion`, `ucal_ch2`, `grafico_calibracion` con 0 referencias), `calibrar_app/` con sus 10 módulos, `tests/` con 5 archivos, `pytest` en `requirements.txt`, y el harness AVO instalado con perfil `software`. **No reimplementar nada de eso.**

Hay tres causas del síntoma, ninguna en el código del proyecto.

### Causa 1 — el entorno virtual vive dentro de Google Drive

`sys.executable` y `site-packages` están en `G:\Mi unidad\...\TRPD_APP\.venv`: 11.632 archivos, 339 MB, sobre un sistema de archivos de streaming. Medido:

| Import | Tiempo |
|---|---|
| `scipy.signal` | 84.9 s |
| `dash` | 46.8 s |
| `h5py` | 7.7 s |
| **`import app` (total)** | **178.7 s** |
| **`import main` de calibrar_app** | **181.2 s** |

Los dos totales son casi idénticos: el coste es de la biblioteca, no del código de ninguna de las dos apps. Incluso `find .venv/Lib/site-packages -type f | wc -l` excede 120 s. El servidor no falla, tarda minutos en abrir el puerto, y en ese intervalo el navegador dice "no se puede conectar".

Procedencia: `pyvenv.cfg` registra `command = ...python.exe -m venv C:\0_matrix\doctorado\proyectos\inv_pd_vac\TRPD_APP\.venv`, o sea que el entorno se creó en disco local y luego se copió a Drive. Sigue siendo **funcional** (tiene `pip.exe`, `activate`, `pytest.exe`) porque `home` apunta al Python 3.13 global, que existe.

### Causa 2 — el recargador de Dash paga el arranque dos veces

`app.py:2714` usa `app.run(debug=True, ...)`. El recargador de Werkzeug importa el módulo en el proceso padre y lo vuelve a importar en el hijo, así que `app.py` cuesta ~2 × 178 s ≈ **6 minutos**. `calibrar_app/main.py` usa `debug=False` y paga una sola vez. Eso explica que la queja sea específicamente sobre el 8050.

### Causa 3 — el intérprete equivocado

`python` en el PATH es el Python 3.13 global (`C:\Users\runi2\AppData\Local\Programs\Python\Python313`), que **no** tiene las dependencias:

```
$ python -c "import dash"
ModuleNotFoundError: No module named 'dash'
```

`python app.py` falla al instante; `.venv/Scripts/python.exe app.py` funciona.

## 2. Decisiones ya tomadas por el usuario — no reabrir

- **El `.venv` se queda donde está.** Se cachea en local marcándolo "Disponible sin conexión" en Google Drive. **No se borra, no se mueve, no se reconstruye.**
- Se añaden **scripts de arranque** versionados para no depender de recordar la ruta del intérprete.
- Mover el entorno fuera de Drive es el **pivote previsto** (§Paso 6), solo si la métrica no baja.

## 3. Marco de ejecución: ciclo AVO

El harness AVO está instalado (`.avo/`, `.claude/hooks`, skills `avo-resume` / `avo-attempt` / `avo-record` / `avo-pivot`). Obligaciones que aplican a este trabajo:

- Empezar con `avo-resume` (leer `.avo/state.md`, ledger reciente, `.avo/deadends.md`, `.avo/knowledge.md`).
- Este trabajo es **un intento**: `approach_tag: arranque-entorno`, métrica `arranque_s`, línea base **178.7**, objetivo **< 10**.
- Cerrar con `avo-record`. El hook `Stop` bloquea el fin de sesión (`exit 2`) si el árbol de trabajo cambió y no se registró ningún intento en el ledger.
- `verify.sh` en verde es condición para el veredicto `commit`. No marcar `commit` sin esa señal.

---

## Paso 1 — Cachear el `.venv` en local (acción MANUAL del usuario)

En el Explorador de Windows: clic derecho sobre
`G:\Mi unidad\yo\usm\investigacion\proyectos\inv_pd_vac\TRPD_APP\.venv`
→ **Acceso offline** → **Disponible sin conexión**, y esperar a que Drive termine de descargar los 339 MB.

**El agente no puede hacer este paso**: el acceso offline es una propiedad del cliente de sincronización de Google Drive, no un atributo del sistema de archivos, y no hay comando fiable para activarlo. Pedirlo al usuario y esperar confirmación antes del Paso 2. No se borra ni se mueve nada; ninguna ruta del proyecto cambia.

## Paso 2 — Medir la métrica

```bash
cd "G:/Mi unidad/yo/usm/investigacion/proyectos/inv_pd_vac/TRPD_APP"
./.venv/Scripts/python.exe -u -c "import time; t=time.time(); import app; print('%.1f s' % (time.time()-t))"
```

Ese número es `arranque_s`. Criterio de `commit`: **< 10 s** (línea base 178.7). Si queda por encima, ir al Paso 6.

Aviso práctico: cualquier comando que importe estas librerías puede tardar ~3 min mientras la caché esté fría. Ejecutarlos en segundo plano y no interpretar un timeout de 120 s como un fallo.

## Paso 3 — Scripts de arranque

Crear dos archivos en la raíz del repositorio, versionados:

- **`run_app.cmd`** — visor TRPD, puerto 8050.
- **`run_calibrar.cmd`** — calibrador, puerto 8051.

Requisitos de cada script:

1. Resolver su propia ubicación con `%~dp0`, para que funcione con doble clic desde cualquier directorio.
2. Invocar `"%~dp0.venv\Scripts\python.exe"` de forma explícita — nunca `python` a secas.
3. Si ese ejecutable no existe, imprimir un mensaje claro (qué falta y cómo recrearlo) y salir con código distinto de 0. **No** degradar al Python global: produciría un `ModuleNotFoundError` que parece un bug del proyecto.
4. Dejar la ventana abierta al terminar (`pause` o equivalente) para que el error sea legible tras un doble clic.
5. `run_calibrar.cmd` lanza `calibrar_app\main.py`, que ya trae su propio `if __name__ == "__main__"` en el puerto 8051.

## Paso 4 — Eliminar el doble import del recargador

En `app.py:2714`, añadir `use_reloader=False` a la llamada `app.run(...)`, manteniendo `debug=True`:

```python
app.run(debug=True, use_reloader=False, dev_tools_props_check=False, host="127.0.0.1", port=8050)
```

Es el cambio de una línea con mayor retorno: divide por dos el tiempo de arranque, con o sin el Paso 1. Se conserva `debug=True` porque lo valioso al depurar es la traza en el navegador, no la recarga en caliente.

Contrapartida a documentar: los cambios en el código ya no se recargan solos, hay que reiniciar el proceso. Con un arranque de ~3 s es asumible.

## Paso 5 — Registrar la lección en la memoria del harness

- **`.avo/knowledge.md`** — añadir como invariantes de entorno: (a) el `.venv` está dentro de Google Drive y necesita acceso offline, o el arranque se va a minutos; (b) nunca invocar `python` a secas, siempre `.venv/Scripts/python.exe`, porque el Python del PATH no tiene las dependencias; (c) `debug=True` sin `use_reloader=False` duplica el coste de arranque; (d) cualquier comando que importe scipy/dash puede tardar ~3 min con caché fría, no es un cuelgue.
- **`archivos_md/DOCUMENTACION.md`** — sección de puesta en marcha: cómo se lanzan las dos apps (`run_app.cmd` / `run_calibrar.cmd`), puertos 8050 y 8051.
- **`.avo/state.md`** — reescribir (no acumular, máx. ~200 líneas): el plan anterior queda cerrado, el estado pasa a reflejar este intento y su métrica.
- **`.avo/ledger.jsonl`** — cerrar vía CLI, no a mano:

```bash
.avo/bin/avo record commit --tag "arranque-entorno" \
  --hypothesis "El arranque de 178.7 s se debe a que site-packages esta en Google Drive y a que el recargador de Dash importa dos veces; cachear el venv offline y desactivar el recargador debe bajarlo por debajo de 10 s" \
  --change "use_reloader=False, scripts run_app.cmd/run_calibrar.cmd, venv marcado offline" \
  --metric-name "arranque_s" --metric-value <medido> --baseline 178.7
```

**Corrección en `.avo/profiles/software.sh:13-15`**: define `PYTHON="$PROJECT_DIR/.venv/Scripts/python.exe"` con fallback a `python` si no existe. Ese fallback es una trampa silenciosa — si faltara el venv, el perfil correría con el Python global y daría un rojo por `ModuleNotFoundError` que parecería un bug del proyecto. Cambiarlo para que aborte con `error_details` explícito en vez de degradar al intérprete equivocado.

## Paso 6 — Pivote previsto (solo si `arranque_s` ≥ 10 s)

Si tras el Paso 1 el arranque sigue por encima de 10 s, el enfoque "mantener el venv en Drive" queda descartado. Entonces: usar la skill `avo-pivot`, registrar la causa raíz en `.avo/deadends.md`, y mover el entorno fuera de Drive:

```bash
C:/Users/runi2/AppData/Local/Programs/Python/Python313/python.exe -m venv C:/venvs/trpd_app
C:/venvs/trpd_app/Scripts/python.exe -m pip install -r requirements.txt
```

Eso obliga a actualizar tres referencias al intérprete: `run_app.cmd` / `run_calibrar.cmd`, `.vscode/settings.json` (`python.defaultInterpreterPath`, hoy `${workspaceFolder}/.venv/Scripts/python.exe`) y `.avo/profiles/software.sh`. Lo más limpio es que los tres lean una variable `TRPD_PYTHON` con el valor actual por defecto, para que un cambio futuro de ubicación sea de un solo sitio.

`.venv/` está en `.gitignore`, así que mover el entorno no toca el repositorio ni el historial. **El `.venv` de Drive no se borra en este plan**; su eliminación es una decisión aparte del usuario, posterior a verificar el entorno nuevo.

---

## Verificación

1. **Métrica**: el comando del Paso 2 devuelve < 10 s.
2. **El servidor responde**: ejecutar `run_app.cmd` y comprobar `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8050/` → `200`. Idem `run_calibrar.cmd` contra `http://127.0.0.1:8051/`.
3. **El intérprete equivocado falla con mensaje claro**: renombrar temporalmente `.venv` a `.venv_tmp`, ejecutar `run_app.cmd` → debe imprimir el mensaje explicativo del punto 3 del Paso 3, no un `ModuleNotFoundError`. **Restaurar el nombre inmediatamente después.**
4. **Sin regresiones**: `.avo/verify.sh` en verde. Incluye el humo de import de las dos apps y `pytest -q tests/` (29 tests según `state.md`). Es también la comprobación de que `use_reloader=False` no rompió nada.
5. **GUI viva** (lo que nunca se pudo comprobar por no arrancar el servidor): con el visor abierto, medición `mediciones_filtros/cada_30s/7`, trigger `ch4`, `⚡ Calcular peaks` → el patrón TRPD se dibuja, el título termina en `· t_lag = 0.00 ns (sin calibrar)`; cambiar "Magnitud TRPD" a **Vpp** → la curva gris de CH1 aparece normalizada, con la vline verde de t10 en x=0 y el eje Y todavía en `Vpp [mV]`; clic en un punto → la selección se resalta en amarillo (confirma que la traza de referencia añadida no rompió el invariante de `curveNumber == 0` que usa `_idx_scatter`).

## Archivos afectados

| Archivo | Cambio |
|---|---|
| `app.py:2714` | `use_reloader=False` |
| `run_app.cmd`, `run_calibrar.cmd` | nuevos, en la raíz |
| `.avo/knowledge.md` | invariantes de entorno |
| `.avo/state.md` | reescribir al estado de este intento |
| `.avo/ledger.jsonl` | entrada del intento vía `.avo/bin/avo record` |
| `.avo/profiles/software.sh:13-15` | abortar en vez de degradar al Python global |
| `archivos_md/DOCUMENTACION.md` | sección de puesta en marcha |
| `G:\...\TRPD_APP\.venv` | acceso offline de Drive (manual, fuera de git) |
