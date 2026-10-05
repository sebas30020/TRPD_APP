# Plan: reporte2 — página HTML interactiva para validar el mapa TRPD (CH3 + CH2, filtrado y crudo)

> Copia de este plan en `TRPD_APP/archivos_md/plan_reporte2_html_trpd.md` (mismo contenido).

## Contexto

Proyecto `G:\Mi unidad\yo\usm\investigacion\proyectos\inv_pd_vac` (código en `TRPD_APP/`, datos en
`mediciones/`, informes en `reportes/`). El "reporte 1" (ya movido por el usuario a
`reportes/reporte1/`) tenía dos piezas separadas:
1. **Mapas TRPD** (PDF) de Antena 1 (CH3) y HFCT (CH2), generados por `TRPD_APP/generar_informe_trpd.py`.
2. **Señales del osciloscopio** (PPTX, una diapositiva por disparo, filtradas y crudas), generadas por
   `TRPD_APP/generar_presentacion.py`.

El usuario necesita **unirlas** en `reportes/reporte2/`: ver el mapa TRPD y, para cada punto, la señal
exacta del osciloscopio que lo originó (disparo y tiempo), para poder decir "el punto X no es una
descarga parcial: quítalo" o "el pulso del disparo s en t sí es una descarga: cuéntalo". Debe poder
compararse **con filtros** (HP 200 MHz CH3/CH4, HP 5 MHz CH2) y **sin filtros**. Formato: **página
HTML local medianamente interactiva** (no PDF).

Decisiones del usuario:
- Sin filtros = **ambas cosas**: un TRPD detectado sobre la señal cruda (además del filtrado) con
  interruptor Filtrado/Crudo, y las señales también filtradas o crudas.
- Marcar **candidatos bajo el umbral** (máximos entre 0.5× y 1× el umbral) en gris, con ID propio.
- Plan guardado como `archivos_md/plan_reporte2_html_trpd.md`.

## Lo que ya existe (reutilizar, no reescribir)

`TRPD_APP/generar_informe_trpd.py` (commit 9e97a91):
- `analizar_estandar(carpeta, canal, umbral)`: detección CH3/CH4 con `app.captura_editada`
  (Δt 50 ns, desde t_abs = `T_INI_US` = 0.25 µs, ediciones manuales del metadata.yaml).
- `malla_resonancia`, `disparos_limpios`, `plantilla`, `ajustar_resonancia`, `analizar_resonancia`:
  detección CH2 restando la resonancia del HFCT (plantilla de disparos sin descargas en CH3),
  umbral `U + 0.1·envolvente`, desde t_abs 0.2 µs, Δt 0.5 µs, sin colas de oscilación.
- `coincidencias(ra, rb)`: misma descarga en dos sensores (mismo disparo, ≤ 50 ns tras restar
  `RETARDO_US`: CH2 − CH3 = 11 ns).
- `fila_tabla1`, `_contar`, `umbral_de`, `UMBRAL_DEFECTO` (CH3 250, CH2 40 mV),
  `UMBRAL_POR_MEDICION` (CH2 65 mV en `med_proced\1v_2mm_01`).
- `generar(...)` hace el cálculo **y** escribe PNG/CSV/PDF en un único bloque.

`TRPD_APP/app.py`: `cargar_segmento(carpeta, canal, seg, ventana, filtrado)`, `capturar(...,
filtrado=)`, `captura_editada(..., filtrado=, ediciones=)`, `calcular_fila_densidad(..., filtrado=)`,
`t10_por_segmento`, `t_abs_captura`, `decimar_minmax(t, v, n)`, `n_segmentos`, `canales_presentes`,
`meta_medicion` (`xinc`), `ediciones_canal` / `guardar_ediciones_canal(carpeta, canal, ed)`
(ediciones = `{"historial": [{"accion": "quitar"|"anadir", "puntos": [{"seg", "t_us"}]}]}`, t en
tiempo del osciloscopio, tolerancia `TOL_PEAK_US` = 5 ns; se reaplican igual con o sin filtro).

`TRPD_APP/generar_presentacion.py`: `descubrir(raices, solo)`, `describir(carpeta, inf, raiz)`
(claves `titulo`, `ruta`, `probeta`, `set`, `nsegs`), `CANALES` (CH1..CH4 con nombres y unidades),
`limites_y`.

Plotly offline: `%LOCALAPPDATA%\venvs\trpd_app\Lib\site-packages\plotly\package_data\plotly.min.js`.
Python del entorno: `%LOCALAPPDATA%\venvs\trpd_app\Scripts\python.exe`.

Datos: 18 mediciones (med_proced\1v_2mm_01 11-16 kV; med_proced_confuse\1v_2mm_0 17.5-20 kV,
3v_2mm3mm4mm_0 10-11 kV, 3v_2mm3mm4mm_1 11-16 kV), 4-20 disparos cada una, muestreo 0.1 ns,
ventana −5…30 µs (~350 k muestras/canal/disparo). Resultado filtrado de referencia (reporte1):
CH3 100 descargas, CH2 96, 94 coincidentes (`reportes/reporte1/resumen_trpd_ch*.csv`).

## Diseño

### 1. Refactor mínimo de `generar_informe_trpd.py`
- Añadir parámetro `filtrado=True` a `analizar_estandar`, `malla_resonancia`,
  `analizar_resonancia` (pasar a `app.cargar_segmento`, `app.captura_editada`,
  `app.calcular_fila_densidad`, `app.contar_peaks`, `app.aplicar_ediciones`) y a `fila_tabla1`.
- Extraer de `generar()` una función `calcular(raices, canales, umbrales, solo, propios, filtrado)`
  que devuelva `(descs, res)` con coincidencias ya calculadas; `generar()` la llama y conserva su
  salida exacta (los PDF/CSV de reporte1 deben salir idénticos con `filtrado=True`).
- Candidatos bajo umbral, clave nueva `r["candidatos"]` = lista de `(seg, t_osc, v)`:
  - CH3/CH4: `app.capturar(carpeta, canal, 0.5*umbral, dist, tmin, filtrado=...)` menos los peaks
    ya detectados (mismo seg y |Δt| ≤ `app.TOL_PEAK_US`).
  - CH2: en `analizar_resonancia`, `find_peaks(r, height=0.5*umb, distance=n_dist)` sobre el
    residuo, con t_abs ≥ t_ini, excluyendo los detectados.
- No cambiar umbrales, ventanas ni métodos: esta tarea es de visualización y revisión.

### 2. Script nuevo `TRPD_APP/generar_reporte_html.py`
Uso: `python generar_reporte_html.py [<raiz> ...] [--salida <dir>] [--solo <texto>]`
(salida por defecto `reportes/reporte2`). Pasos:
1. `descs, res_f = gi.calcular(..., filtrado=True)` y `res_c = gi.calcular(..., filtrado=False)`
   para canales `["ch3", "ch2"]` (CH2 crudo usa la misma resta de resonancia sobre la señal cruda).
2. Por medición escribe `data/m<NN>.js` con `window.TRPD_DATA["m<NN>"] = {...}` (JSON compacto):
   - `meta`: titulo, ruta, set, nsegs, umbrales por canal, t10 por disparo, t_ini por canal.
   - Para cada estado `F` (filtrado) y `C` (crudo) y canal ch3/ch2:
     - `det`: lista de descargas `[id, seg, t_osc, t_abs, vmax_mV, vpp_mV, en_otro(0/1), manual(0/1)]`.
     - `cand`: candidatos `[id, seg, t_osc, t_abs, v_mV]`.
     - `fila`: fila Tabla 1 (`distribucion`, `n_coinc`, `vpp_media`, `tabs_media`) y `cuentas` por disparo.
   - `senal[F|C][seg][ch1..ch4]`: traza completa diezmada con `app.decimar_minmax` (~4000 puntos,
     ventana `app.T_MIN..app.T_MAX` en tiempo del osciloscopio; CH1 nunca se filtra, en V).
   - `detalle[F|C]`: para cada descarga y candidato, ventana ±0.25 µs a resolución nativa de
     CH2, CH3 y CH4 (clave = id). Codificar como Int16 en base64 con factor de escala por traza para
     reducir tamaño; registrar el tamaño de cada `.js` en consola y avisar si alguno supera 15 MB.
   - ID estable y legible por punto: `"<NN>-<canal>-<F|C>-<k>"` (k correlativo por medición), y en el
     JSON también la clave completa (ruta, canal, seg, t_osc con 4 decimales).
3. Copia `plotly.min.js` a `assets/` y escribe `assets/visor.js`, `assets/visor.css`, `index.html`
   (los datos se cargan inyectando `<script src="data/m<NN>.js">`, que funciona con `file://`;
   **no** usar `fetch`, que Chrome bloquea en `file://`).

### 3. Página `reportes/reporte2/index.html` (vanilla JS + Plotly local)
- **Cabecera**: selector de medición (agrupado por set, con N de descargas CH3/CH2), interruptor
  **Filtrado / Crudo**, casilla "mostrar candidatos", resumen Tabla 1 de la medición (dos filas,
  CH3 y CH2, del estado activo) y una mini-tabla comparativa F vs C (descargas, coincidentes).
- **Mapas TRPD** (dos gráficos Plotly, CH3 arriba, CH2 abajo; Vpp [V] vs t_abs [µs]; zona gris
  t_abs < t_ini): relleno = también en el otro sensor, hueco = solo en ese sensor, rombo = manual,
  gris pequeño = candidato. Hover: ID, disparo, t_abs, t_osc, Vpp, coincidencia.
- **Clic en un punto** → selecciona su disparo y su tiempo:
  - Panel **Señales del disparo**: 4 trazas apiladas con eje x compartido (CH1..CH4, colores de
    `tema.COLORES_CANALES`), líneas verticales en todas las descargas del disparo (color de canal,
    discontinua si es candidato) y la seleccionada resaltada; los tiempos se dibujan en tiempo del
    osciloscopio corrigiendo el retardo (CH2 − 11 ns) para que la descarga caiga en la misma vertical.
  - Panel **Detalle** (±0.25 µs a resolución nativa) de CH2, CH3 y CH4 alrededor del punto, con
    marcador en el máximo detectado y el umbral dibujado.
  - Navegación: disparo anterior/siguiente y descarga anterior/siguiente; selector de disparo para
    revisar disparos sin descargas (solo panel de señales completas).
- **Tabla del disparo**: descargas y candidatos de ese disparo (ID, canal, t_abs, Vpp, coincidencia)
  con botones **"No es DP (quitar)"** en descargas y **"Es DP (contar)"** en candidatos; además
  "añadir en t" haciendo clic en el panel Detalle (registra el t del clic).
- **Revisión**: las marcas se guardan en `localStorage` (try/catch; la página funciona sin él), se
  listan en un panel lateral y se exportan con **"Exportar revisión"** (descarga `revision_trpd.json`
  y copia al portapapeles). Formato, una entrada por marca:
  `{"ruta": "...", "canal": "ch3", "estado": "F", "accion": "quitar"|"anadir", "seg": 4, "t_us": 1.2345, "id": "..."}`
  — directamente convertible a `ediciones_peaks.<canal>.historial` de `metadata.yaml`.

### 4. (Cierre del ciclo) `--aplicar revision_trpd.json` en `generar_reporte_html.py`
Agrupa por `(ruta, canal)` y añade un paso `{"accion", "puntos": [{"seg", "t_us"}]}` al historial
con `app.ediciones_canal` + `app.guardar_ediciones_canal` (respaldo previo de cada `metadata.yaml`
en el scratchpad). Después se regeneran reporte2 y, si se pide, reporte1. Las ediciones valen para
filtrado y crudo (se guardan en tiempo del osciloscopio).

### 5. Documentación
Añadir sección en `archivos_md/DOCUMENTACION.md` (uso, estructura de `reporte2/`, formato del JSON
de revisión) y nota en el docstring de `generar_informe_trpd.py` sobre `calcular()`.

## Restricciones (lo que NO hacer)
- No cambiar los métodos de detección, umbrales ni ventanas (solo añadir `filtrado` y candidatos).
- No modificar `metadata.yaml` salvo con `--aplicar` y a petición explícita del usuario.
- No depender de internet (Plotly local) ni de un servidor (abrir con doble clic, `file://`).
- No tocar `reportes/reporte1/`.
- No hacer commit sin que el usuario lo pida.

## Verificación
1. `python generar_informe_trpd.py --salida <scratch>` y comparar `resumen_trpd_ch3.csv` /
   `resumen_trpd_ch2.csv` con los de `reportes/reporte1/` → idénticos (refactor sin efectos).
2. `python generar_reporte_html.py` → crea `reportes/reporte2/{index.html, assets/, data/}`; ningún
   `data/*.js` > 15 MB (informar tamaño total).
3. Abrir `index.html` en Chrome (claude-in-chrome con `file://` o pedir al usuario):
   - Estado Filtrado: totales 100 (CH3) y 96 (CH2), 94 coincidentes; Tabla 1 igual a reporte1.
   - Clic en un punto de 1v_2mm_0/19kV: el panel muestra su disparo; la vertical cae en el pulso; el
     máximo del Detalle coincide con `vmax_mV` y `t_osc` de la descarga (±1 muestra).
   - Interruptor Crudo: cambian mapas, señales y conteos; anotar los totales crudos.
   - Candidatos visibles al activar la casilla.
   - Marcar 1 "quitar" y 1 "contar", recargar (persisten), exportar y comprobar el JSON.
   - Consola del navegador sin errores.
4. `pytest` de `TRPD_APP/tests` sigue pasando (no se toca `app.py`).

## Riesgos y supuestos
- Tamaño: 342 disparos × 4 canales × 2 estados de traza diezmada + ventanas de detalle; si un
  archivo excede 15 MB, reducir el diezmado a 3000 puntos o el detalle a ±0.15 µs.
- CH3 crudo con 250 mV puede detectar mucho más (acoplamiento de baja frecuencia del impulso); es
  justamente lo que se quiere comparar, no se corrige.
- CH2 crudo: la plantilla de resonancia se construye sobre señal cruda (disparos limpios según CH3
  crudo); si el ajuste se degrada, se verá en la comparación F/C, sin cambiar el método.
- Tiempo de cálculo: dos pasadas completas (~1-2 min cada una) + escritura.
- Pregunta abierta: si se quiere revisar también CH4 (Antena 2) como sensor con mapa propio; por
  ahora solo se muestra su señal.
