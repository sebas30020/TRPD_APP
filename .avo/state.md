# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-20 | Intento activo: ninguno*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Instaurar el ciclo AVO, implementar correcciones en `app.py`, construir la aplicación autónoma `calibrar_app` (puerto 8051) con diagnóstico IEC 60060-1 y convertir `app.py` en consumidor puro de retardos.
- **Métrica objetivo:** `tests_fallidos = 0`, `ids_colgantes = 0`, 100% de paridad con el oráculo metrológico.
- **Línea base actual:** 29 tests pasando exitosamente en la suite automatizada `pytest`.

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `plan-completado`
- **ID Padre:** `b63a9f41`
- **Hipótesis activa:** Todas las fases del plan ejecutadas y verificadas con éxito. Arquitectura desacoplada en producción operativa.

## 3. Estado de la Arquitectura / Hallazgos
- **Parte 0 (Harness AVO):** Inicializado en Windows, hooks configurados, contrato de verificación `.avo/verify.sh` determinista.
- **Paso P0 (Oráculo):** Generado oráculo metrológico (`scratch/oraculo_calibracion.json`) para `mediciones_filtros/cada_30s/7`.
- **Parte 1 (UI `app.py`):**
  - Solapamiento título/leyenda corregido con márgenes y anclaje superior.
  - Pestaña "Vpp vs Energía" y funciones asociadas eliminadas.
  - Curva CH1 normalizada añadida en modo Vpp (curva 0 sigue siendo peaks para no romper selección).
  - Valores por defecto multi-trigger actualizados: $\Delta t = 0.035\text{ µs}$, $t_{\min} = 0.15\text{ µs}$, pasos finos 0.1 y 0.005.
- **Núcleo y Calibrador `calibrar_app` (Puerto 8051):**
  - `iec60060.py`: Filtro pasa-bajos vectorizado $k(f)$ de fase cero y regla de último cruce del frente (Anexos B y C de IEC 60060-1).
  - `datos.py`: Acceso a HDF5 independiente con soporte de ventana completa (`ventana=None`) para IEC y recortada (`[-5, 30] µs`) para $t_{10}$.
  - `impulso.py` y `referencia.py`: Selector dual $t_{10}$ vs $O_1$, cálculo de $t_{10} - O_1 \approx 258\text{ ns}$ y diagnóstico de conformidad de lote.
  - `arribo.py`: Interpolación lineal sub-muestra y filtrado MAD ($k=5.0$) de atípicos.
  - `figuras.py`: 4 gráficos interactivos con soporte de arrastre de umbral por `relayoutData`.
  - `persistencia.py`: Serialización aditiva en `metadata.yaml` con clave `referencia_impulso` y sub-bloque `ancla`.
  - `interfaz.py` y `main.py`: Servidor Dash en puerto 8051.
- **Cirugía en `app.py` (Puerto 8050):**
  - `app.py` transformado en consumidor puro de solo lectura.
  - Eliminados callbacks de cálculo, sliders manuales, e IDs obsoletos (0 IDs colgantes).
  - Callback `cargar_calibracion_store` recarga desde disco; normaliza automáticamente retardos $O_1$ al ancla $t_{10}$ usando `t10_menos_O1_ns`.
- **Suite de Pruebas Automatizadas:** 29 tests en `tests/` cubriendo vectores analíticos normativos (V1-V3), equivalencia metrológica contra el oráculo (V4), consistencia de ancla (V5), round-trip de persistencia (V6), regresión TRPD (V7) y GUI (V8/V9).

## 4. Próxima Acción Inmediata
- [x] Ejecutar suite de pruebas completa y verificar contrato `.avo/verify.sh` (100% aprobado).
- [x] Versionar cambios en Git.
