# Estado del Proyecto TRPD_APP (Harness AVO)
*Última actualización: 2026-09-20 | Intento activo: fix-marker-curve-alignment*

## 1. Objetivo Inmediato y Criterio de Éxito
- **Meta:** Resolver la desalineación visual donde la marca "X" de tiempo de arribo no coincidía con la traza de la señal en `figura_canal`.
- **Métrica objetivo:** `tests_fallidos = 0`, concordancia visual y física exacta entre la traza y el marcador de cruce.
- **Línea base actual:** 33 tests pasando en la suite automatizada `pytest`.

## 2. Enfoque Actual y Linaje
- **Tag de enfoque:** `fix-marker-curve-alignment`
- **ID Padre:** `9c93bde6`
- **Hipótesis activa:** La desalineación entre la marca "X" y la curva observada en `image copy.png` se debía a un doble factor: (1) `figura_canal` aplicaba un submuestreo ingenuo `x=t[::paso], y=v[::paso]` con `paso = 35` (~7 ns por muestra a 5 GHz), el cual saltaba los pulsos transitorios ultrarrápidos de descarga parcial (~2-4 ns de duración) trazando una cuerda recta por el valle de la señal que omitía la cresta donde realmente se producía el cruce de umbral; y (2) la coordenada $y$ de la marca se extraía con `v[idx_cercano]` mediante redondeo entero en vez de interpolación lineal continua a la sub-muestra $t_{\text{ant}}$. Al trazar la señal en resolución completa nativa (`np.float32` vía WebGL `Scattergl`, idéntico a `app.py`) e interpolar $v(t_{\text{ant}})$ con `np.interp`, la marca queda con precisión matemática y visual exacta sobre la curva.

## 3. Estado de la Arquitectura / Hallazgos
- **Resolución nativa en `calibrar_app/figuras.py`:**
  - Removido el diezmado `[::paso]` en `figura_canal`. La traza pasa directamente `x=t.astype(np.float32), y=v.astype(np.float32)` a `go.Scattergl`.
  - WebGL renderiza las 175.000 muestras en milisegundos sin sobrecarga y garantiza que al hacer zoom se preserven todos los puntos a 0.2 ns.
- **Interpolación exacta de la marca:**
  - Sustituido `idx_cercano = int(round(...))` y `v_arr = float(v[idx_cercano])` por `v_arr = float(np.interp(ta, t, v))`.
  - La marca $(t_{\text{ant}}, v_{\text{arr}})$ se sitúa exactamente sobre el segmento de recta interpolado que traza Plotly.
- **Suite de Pruebas y Verificador:** 33/33 tests aprobados con éxito (`.avo/verify.sh` retorna `pass: true`).

## 4. Próxima Acción Inmediata
- [x] Diagnosticar causa raíz de la desalineación en `image copy.png`.
- [x] Reemplazar submuestreo por traza nativa `np.float32` e interpolar $v_{\text{arr}}$ con `np.interp`.
- [x] Correr y aprobar suite de pruebas completa (33 tests).
- [x] Ejecutar `.avo/verify.sh` (pass: true).
- [x] Registrar intento `#6d51315e` en `.avo/ledger.jsonl`.

