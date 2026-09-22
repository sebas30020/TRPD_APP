# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-22 | Intento completado: filtrado-descargas-trpd (c4d9a128)*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Implementar filtrado interactivo de descargas en el gráfico TRPD (selección de lazo/caja y exclusión manual de disparos) con pila de deshacer paso a paso ("↩ Deshacer") y restauración completa ("🔄 Restaurar todo"), sincronizado con el conteo de peaks y la tabla de densidad de eventos.
- **Métrica objetivo:** `tests_fallidos = 0`, interfaz fluida en Dash y preservación completa de la consistencia en el cálculo de densidad de eventos.
- **Línea base actual:** 55 tests pasando en la suite automatizada `pytest` (0 fallos).

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `filtrado-descargas-trpd`
- **ID Padre:** `e0ba7bea` -> **ID Actual:** `c4d9a128`
- **Hipótesis verificada:** Mantener un historial de exclusiones en `dcc.Store(id="store_excluidos_descargas")` por cada combinación de medición y canal (`carpeta|canal`) permite aplicar exclusiones acumulativas desde la selección de lazo o manual por disparo, calcular de forma reactiva los picos efectivos en `contar_peaks`, sincronizar la tabla de densidad de eventos y revertir cambios paso a paso o en su totalidad sin recargar datos.

## 3. Estado de la Arquitectura / Hallazgos
- **`app.py` (Puerto 8050):**
  1. Funciones auxiliares: `_obtener_excluidos(store, clave)`, `_obtener_historial(store, clave)` y `parsear_lista_disparos(texto)`.
  2. Modificación de cálculo: `contar_peaks(..., excluidos=None)` y `calcular_fila_densidad(..., excluidos=None)` filtran los disparos excluidos antes del conteo y cálculo estadístico.
  3. Componentes UI en pestaña TRPD: `btn_excluir_seleccion`, `btn_deshacer_exclusion`, `btn_restaurar_descargas`, `input_excluir_disparo`, `btn_excluir_disparo` y `badge_filtro_descargas`.
  4. Callbacks conectados: `set_seleccion`, `gestionar_exclusiones_descargas`, `actualizar_badge_filtro`, `calcular_peaks`, `actualizar_densidad_store` y `actualizar_scatter`.
- **Documentación y Reporte Comparativo:**
  - `archivos_md/reporte_comparativo_tabla1_antena.md`: Análisis comparativo detallado entre la aplicación y los resultados del paper original (Tabla 1, 2 mm, 1-4 vacuolas), documentando la causa de las discrepancias en $V_p$ (filtro pasa altos de 200 MHz no mencionado en el texto del paper) y $t_{10}$ (interpolación continua IEC 60060-1 vs discretización por muestra).
- **Suite de Pruebas:**
  - `tests/test_filtrado_descargas.py`: 10 pruebas unitarias específicas verificando la interfaz, el parser, la lógica de exclusión, callbacks y cálculo de densidad.
  - Suite completa: 55 tests aprobados al 100% (0 fallos).

## 4. Próxima Acción Inmediata
- [x] Ejecutar e implementar filtrado de descargas en `app.py`.
- [x] Crear suite de pruebas de regresión `tests/test_filtrado_descargas.py`.
- [x] Elaborar reporte comparativo `archivos_md/reporte_comparativo_tabla1_antena.md`.
- [x] Ejecutar suite completa con pytest (55/55 pasados).
- [x] Registrar entrada en `.avo/ledger.jsonl`.
- [x] Realizar commit y sincronizar con el repositorio remoto de GitHub (`origin/main`).
