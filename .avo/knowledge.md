# Base de Conocimiento del Dominio

Hechos y restricciones estables de este proyecto: arquitectura, APIs
congeladas, supuestos ya validados, decisiones que no se deben
re-litigar sin evidencia nueva. El agente consulta este archivo antes de
proponer un cambio para no violar (ni re-descubrir) invariantes ya
conocidas.

## Invariantes conocidas

1. **Ancla t10 vs O1 = ~260 ns de error sistemático**, ~20× el retardo que se mide (~10 ns). `referencia_impulso` + `ancla.t10_menos_O1_ns` son obligatorios en YAML; el lector normaliza o rehúsa explícitamente.
2. **La ventana `(-5, 30) µs` no alcanza para el Anexo B** (la cola no baja del 40 % de la cresta hasta ~88 µs en registros reales como `cada_30s/7`): O1 sobre registro completo, t10 sobre `(-5, 30)`.
3. **`front_crossing` de referencia devuelve el PRIMER cruce** donde P9 pide el ÚLTIMO cruce del 30 % antes del pico; con el vector ideal analítico coinciden, pero en señales reales con oscilación previa divergen.
4. **Split de unidades**: tiempo `t` en µs pero `dt` en segundos dentro del filtro k(f). Sufijos obligatorios en variables (`t_us`, `dt_s`) y `assert dt_s < 1e-6`.
5. **`exp` desborda en `Um`** si `td` queda muy adelante: evaluar con máscara `t >= td` y `np.clip(arg, -700, 700)` antes de `exp` (no usar `np.where`, que evalúa ambas ramas).
6. **`np.empty_like` trunca entradas enteras** en el filtro: `np.asarray(x, dtype=np.float64)` al entrar.
7. **Bucle O(N) en Python** en `k_filter`: sustituir por `lfilter` adelante+atrás (fase cero) vectorizado y demostrar equivalencia numérica exacta (< 1e-12).
8. **Arrays cacheados con `writeable=False`**: toda operación fuera de sitio (`u0 = v - base`, nunca `v -= base` in place).
9. **`lru_cache` de registros completos**: 16 MB/entrada ⇒ `maxsize=6`, no 48 (evita agotar RAM).
10. **CH1 lleva dos suavizados distintos**: Butterworth 20 MHz para t10, k(f) a 0.674 MHz para O1. Cada ancla se usa de extremo a extremo, jamás mezclar t10 de un filtro con O1 del otro. Mantener `sosfiltfilt` (fase cero).
11. **El índice `e` del Anexo B es frágil con cola ruidosa**: contrastar el último índice con `u0 > 0.4·Ue` contra el primer cruce descendente tras el pico y alertar si difieren > 1 µs.
12. **`β'` no es robusto frente a ruido**: `Ue` es un máximo puntual y el ruido lo infla (0.5 % ruido → β' = 1.5 % falso).
13. **`least_squares(method="lm")` no admite cotas** y sin la normalización del Anexo C.1 no converge.
14. **`calibracion_store` es memoria de sesión del navegador**: de ahí el botón de recarga desde disco en `app.py`.
15. **La curva 0 del scatter TRPD es la de peaks**: `_idx_scatter` filtra por `curveNumber == 0`; cualquier traza nueva (como la referencia de CH1) va después.
16. **Convenciones de unidades y direcciones**: µs y mV en memoria, ns en disco (YAML) y en la GUI; segmentos 1-based; `carpeta` siempre relativa a `MEDICIONES` con `/`; los datos `.h5` viven fuera del repositorio en `../mediciones/Mediciones`.
17. **Entorno Windows**: no hay `jq` ni `python3` en el PATH, y el `pytest` del PATH no es el del `.venv`. Todo comando de verificación usa `.venv/Scripts/python.exe` explícitamente.

## Decisiones de arquitectura congeladas

- `calibrar_app` es una aplicación autónoma modular con puerto 8051 (copia propia de lógica de datos e impulso, nunca `import app`).
- `app.py` es consumidor puro de calibración: lee `metadata.yaml`, no calcula ni guarda calibraciones.
- La referencia por defecto en `calibrar_app` es `t10`.
- En modo Vpp, la referencia de CH1 se grafica normalizada a la cresta y escalada al percentil 95 de Vpp.
