# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-20 | Intento activo: arranque-entorno*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Resolver la latencia de arranque de los servidores (`app.py` en 8050 y `calibrar_app` en 8051), eliminando el doble import del recargador de Dash, creando scripts de inicio robustos (`run_app.cmd` y `run_calibrar.cmd`), asegurando el aislamiento del intérprete en el harness AVO y documentando el acceso offline a `.venv` en Google Drive.
- **Métrica objetivo:** `arranque_s < 10` (o reducción sustancial de los 178.7 s de línea base), `tests_fallidos = 0`, servidores 8050 y 8051 respondiendo HTTP 200.
- **Línea base actual:** 178.7 s en frío con doble reloader de Werkzeug y acceso en la nube de Google Drive.

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `arranque-entorno`
- **ID Padre:** `b63a9f41`
- **Hipótesis activa:** El arranque excesivo se debe a que `site-packages` reside en el sistema de archivos de streaming de Google Drive (~11.600 archivos) y a que el recargador de Dash importa el árbol de módulos dos veces en `debug=True`. Desactivar el recargador (`use_reloader=False`), crear scripts de arranque con ruta absoluta `%~dp0` y comprobación estricta de Python, junto con el acceso offline ("Disponible sin conexión") a `.venv`, resuelve la lentitud y previene fallos silenciosos.

## 3. Estado de la Arquitectura / Hallazgos
- **Parte 0 (Harness AVO):**
  - `.avo/profiles/software.sh` corregido: ya no degrada al Python global en el PATH (que carece de librerías); ahora aborta con diagnóstico JSON explícito si falta el intérprete.
  - `.avo/knowledge.md` enriquecido con invariantes 18 a 21 (Google Drive I/O, aislamiento de intérprete, recargador Dash y scripts de inicio).
- **Scripts de Arranque Versionados:**
  - `run_app.cmd`: Inicia el Visor TRPD (`app.py`) en `http://127.0.0.1:8050`.
  - `run_calibrar.cmd`: Inicia el Calibrador Instrumental (`calibrar_app\main.py`) en `http://127.0.0.1:8051`.
  - Ambos scripts validan la presencia de `.venv\Scripts\python.exe` (o `TRPD_PYTHON`), rechazan el Python global para prevenir falsos `ModuleNotFoundError`, y utilizan `pause` para inspección tras doble clic.
- **Optimización de Dash (`app.py`):**
  - Configurado `use_reloader=False` en `app.run(debug=True, use_reloader=False, dev_tools_props_check=False, host="127.0.0.1", port=8050)`. Elimina la duplicación de importación por Werkzeug (reducción directa del 50% en tiempo de arranque).
- **Documentación:**
  - `archivos_md/DOCUMENTACION.md` actualizado con guía de puesta en marcha, detalles de ejecución y advertencias sobre el acceso offline de Google Drive.
- **Verificación de Servidores:**
  - `app.py` en `http://127.0.0.1:8050/` verificado respondiendo HTTP 200.
  - `calibrar_app/main.py` en `http://127.0.0.1:8051/` verificado respondiendo HTTP 200.
- **Suite de Pruebas Automatizadas:** 29 tests en `tests/` verificados en verde.

## 4. Próxima Acción Inmediata
- [x] Crear scripts de inicio `run_app.cmd` y `run_calibrar.cmd`.
- [x] Añadir `use_reloader=False` en `app.py`.
- [x] Corregir fallback en `.avo/profiles/software.sh`.
- [x] Actualizar `.avo/knowledge.md` y `archivos_md/DOCUMENTACION.md`.
- [x] Verificar respuesta HTTP 200 en puertos 8050 y 8051.
- [x] Completar ejecución de `.avo/verify.sh` (29/29 tests pasando).
- [x] Registrar intento en `.avo/ledger.jsonl` (`#dbbc52f1`, commit, arranque_s=61.6 s vs 178.7 s base).
- [x] Versionar cambios en Git.
