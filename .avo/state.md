# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-20 | Intento activo: calibrar-multicanal-ui*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Implementar vista multicanal sincronizada (CH1..CH4 con eje temporal compartido) en `calibrar_app` (puerto 8051), hacer las líneas de umbral interactivamente arrastrables con el ratón sin reiniciar el zoom, resolver el error 500 en `calcular_retardo_canal` y eliminar el solapamiento visual en el gráfico de evaluación normativa IEC 60060-1.
- **Métrica objetivo:** `tests_fallidos = 0`, 0 errores 500 en Dash, 100% de tests GUI aprobados.
- **Línea base actual:** 33 tests pasando en la suite automatizada `pytest` (11 tests específicos de GUI en `test_calibrar_gui.py`).

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `calibrar-multicanal-ui`
- **ID Padre:** `dbbc52f1`
- **Hipótesis activa:** Proporcionar una vista multicanal de 4 subplots apilados con eje X compartido (`[-5, 30] µs`) análoga a la de `app.py` permite al usuario correlacionar de inmediato el frente del impulso de referencia CH1 con los frentes de subida de los sensores CH2, CH3 y CH4. Hacer el umbral arrastrable mediante `edits: {shapePosition: True}` y filtrar `relayoutData` para ignorar eventos de zoom/pan garantiza una experiencia fluida sin saltos ni reinicios de escala. La corrección de firma en `calibrar_retardo` y el rediseño tipográfico de `figura_impulso_iec` restauran la estabilidad y legibilidad completa.

## 3. Estado de la Arquitectura / Hallazgos
- **Corrección de Error 500 en `calibrar_app`:**
  - `calibrar_app/arribo.py:calibrar_retardo`: Ahora acepta indistintamente `dist_us` o `distancia_us` (alias).
  - `calibrar_app/main.py:calcular_retardo_canal`: Invocación corregida a `dist_us=dt_us`. Admite la opción `"todos"` para calcular simultáneamente CH2, CH3 y CH4.
- **Inspección Multicanal Sincronizada:**
  - `calibrar_app/figuras.py:figura_canal`: Rediseñada con subplots apilados (CH1..CH4) y eje X compartido.
  - Fila 1 (CH1): Muestra la señal del impulso con la línea vertical de ancla ($t_{10}$ u $O_1$) en verde esmeralda.
  - Filas 2..4 (CH2, CH3, CH4): Señal del sensor, ancla vertical para comparación temporal directa, línea horizontal de trigger (roja arrastrable en el canal activo, punteada en los demás), y marcador "X" de arribo ($t_{\text{ant}}$).
  - Ancho completo en `calibrar_app/interfaz.py` para máxima resolución temporal.
- **Trigger Draggable e Inmunidad de Zoom:**
  - `interfaz.py`: Configurado `config={"displayModeBar": True, "edits": {"shapePosition": True}}`.
  - `main.py:sincronizar_umbral`: Filtra estrictamente eventos que contengan `shapes[...]`. Si el usuario hace zoom o paneo, retorna `no_update`, impidiendo que Dash resetee la vista.
  - `figura_canal` y `figura_impulso_iec`: Incluyen `uirevision=f"{carpeta}|{seg}"`.
- **Eliminación de Solapamiento IEC (`image.png`):**
  - Reubicada la leyenda horizontal al margen inferior (`y=-0.22`).
  - Alternadas las posiciones de anotación vertical ($O_1$, $t_{10}$, $t_{30}$, $t_{90}$, $t_{50}$) y agrupados los valores normativos exactos en una tarjeta informativa superior derecha sobre la cola decaída de la señal.
- **Suite de Pruebas:** 33 tests pasando en verde (11 en `tests/test_calibrar_gui.py`).

## 4. Próxima Acción Inmediata
- [x] Corregir error 500 en `calibrar_app/main.py` y `calibrar_app/arribo.py`.
- [x] Implementar figura multicanal con subplots apilados y eje compartido en `figuras.py`.
- [x] Configurar trigger interactivo draggable y filtrar zoom en `main.py` e `interfaz.py`.
- [x] Rediseñar gráfico de impulso IEC 60060-1 sin solapamiento de textos.
- [x] Añadir 4 nuevos tests de integración en `tests/test_calibrar_gui.py`.
- [x] Validar contrato con `.avo/verify.sh` (33/33 tests aprobados).
- [x] Registrar intento `#9c93bde6` en `.avo/ledger.jsonl`.
- [x] Versionar cambios en Git.
