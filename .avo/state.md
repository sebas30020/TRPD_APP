# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-21 | Intento completado: explorador-archivos-gui (e0ba7bea)*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Implementar un explorador interactivo de archivos/carpetas en servidor dentro de `app.py` y `calibrar_app` para permitir la selección de directorios arbitrarios de medición en disco.
- **Métrica objetivo:** `tests_fallidos = 0`, navegación fluida en frontend Dash y preservación completa de la compatibilidad hacia atrás.
- **Línea base actual:** 45 tests pasando en la suite automatizada `pytest` (0 fallos).

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `explorador-archivos-gui`
- **ID Padre:** `7b82e14a` -> **ID Actual:** `e0ba7bea`
- **Hipótesis verificada:** Un panel colapsable interactivo en Dash que liste subcarpetas del servidor mediante `os.listdir` permite seleccionar directorios de medición tanto relativos a `MEDICIONES/` como externos/absolutos, sin requerir diálogos nativos del SO ni alterar las funciones de lectura de señales.

## 3. Estado de la Arquitectura / Hallazgos
- **`app.py` (Puerto 8050):**
  1. `listar_subcarpetas(ruta)`: función con ordenamiento natural que detecta si un directorio contiene mediciones (`.mat`/`_CHAN_RE`).
  2. Componentes UI: `dcc.Store(id="explorador_ruta_actual")`, botón `📂 Examinar…` (`btn_examinar`) y panel colapsable `explorador_panel` con botones de navegación, listado de subcarpetas y botones de confirmar/cancelar.
  3. Callbacks: `toggle_explorador`, `navegar_explorador` y `renderizar_explorador`.
- **`calibrar_app` (Puerto 8051):**
  1. `calibrar_app/datos.py`: `listar_subcarpetas` exportada y compartida.
  2. `calibrar_app/interfaz.py`: Integración de `btn_examinar`, `explorador_ruta_actual` y `explorador_panel`.
  3. `calibrar_app/main.py`: Callbacks equivalentes con soporte multi-carpeta.
- **Suite de Pruebas:**
  - `tests/test_explorador_archivos.py` (4 tests cubriendo listado, navegación y callbacks de ambas aplicaciones).
  - Suite completa: 45 tests aprobados al 100%. Verificador `.avo/verify.sh` retornando `pass: true`.

## 4. Próxima Acción Inmediata
- [x] Ejecutar e implementar plan `archivos_md/plan_explorador_archivos.md`.
- [x] Crear suite de pruebas de regresión `tests/test_explorador_archivos.py`.
- [x] Ejecutar `.avo/verify.sh` con salida exitosa (`pass: true`).
- [x] Registrar entrada en `.avo/ledger.jsonl`.
