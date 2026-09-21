# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-21 | Intento activo: fix-missing-horizontal-trigger-lines*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Restaurar la visibilidad y capacidad interactiva de arrastre de las líneas horizontales de umbral de trigger en los subplots de los canales sensores (CH2, CH3, CH4) en `calibrar_app`.
- **Métrica objetivo:** `tests_fallidos = 0`, líneas de umbral horizontales renderizadas (`shapes[0..2]`) con `editable=True`.
- **Línea base actual:** 38 tests pasando en la suite automatizada `pytest`.

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `fix-missing-horizontal-trigger-lines`
- **ID Padre:** `e319b48c`
- **Hipótesis activa:** Al construir una figura con `make_subplots` en Plotly, llamar a `fig.add_hline(..., row=i, col=1)` antes de que dicho subplot contenga al menos una traza provoca que Plotly descarte silenciosamente la figura al no poder resolver el sistema de coordenadas de los ejes. Al cargar y trazar primero las señales de los canales y随后 agregar `fig.add_hline` con `editable=True`, las líneas horizontales se dibujan fielmente en la posición exacta y vuelven a ser arrastrables por el usuario.

## 3. Estado de la Arquitectura / Hallazgos
- **Reordenamiento de Renderizado en `calibrar_app/figuras.py`:**
  1. **Trazas de señal primero:** Cada canal agrega su `Scattergl(x=t, y=v)`.
  2. **Líneas de umbral horizontales:** `fig.add_hline` para cada sensor de `trigs_presentes` (CH2, CH3, CH4) con `editable=True`, `dash="dash"`, ancho 1.8 px y etiqueta `u_{ch} = ... mV`.
  3. **Líneas verticales y marcas:** Se agregan `ancla_us` y `tmin` vlines, así como la marca de arribo interpolada `X` y las anotaciones tipo badge.
- **Tip interactivo actualizado:** En `interfaz.py` ahora se indica formalmente que cualquier línea de umbral puede ser arrastrada para calibrar su trigger.
- **Suite de Pruebas:** Agregado `test_multicanal_figura_canal_lineas_umbral_editables` en `tests/test_calibrar_gui.py`. 38 tests aprobados al 100%.
- **Servidor Activo:** Proceso en puerto 8051 (PID en ejecución) respondiendo `HTTP 200 OK`.

## 4. Próxima Acción Inmediata
- [x] Corregir orden de construcción en `figura_canal` (`figuras.py`).
- [x] Asegurar `editable=True` en `add_hline`.
- [x] Actualizar tip en `interfaz.py`.
- [x] Añadir prueba de regresión unitaria en `test_calibrar_gui.py` (38 tests).
- [x] Ejecutar `.avo/verify.sh` y registrar commit `#7b82e14a` en `.avo/ledger.jsonl`.
- [x] Reiniciar servidor en puerto 8051 y verificar respuesta HTTP 200.
