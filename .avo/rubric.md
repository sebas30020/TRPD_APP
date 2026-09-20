# Rúbrica de Verificación — Pipeline IEC 60060-1 y Calibración

Criterios para la auditoría de contexto fresco del pipeline IEC y la calibración temporal:

## 1. Fidelidad normativa a IEC 60060-1:2010 (Anexos B y C)
- [ ] Compensación de línea base previa sobre muestras puras de pre-disparo.
- [ ] Ventana de ajuste [d+1, e] según pasos d–f del Anexo B (excluye pie < 20% y cola < 40%).
- [ ] Ajuste Levenberg-Marquardt de la doble exponencial con la normalización recomendada en C.1.
- [ ] Curva residual `R(t) = u0(t) - Um(t)` filtrada con la función de tensión de ensayo `k(f) = 1/(1 + 2.2 f²)`.
- [ ] Filtro IIR de un polo de doble pasada (adelante y atrás, fase cero) con coeficientes calculados a >= 6 cifras significativas.
- [ ] Determinación de instantes sobre la curva de ensayo `Ut(t)`: `t30` (último cruce ascendente), `t90` (primer cruce ascendente) y `t50` (primer cruce descendente tras el pico).
- [ ] Parámetros extrapolados exactos: `T = t90 - t30`, `T1 = T / 0.6`, `O1 = t30 - 0.3 * T1`, `T2 = t50 - O1`.

## 2. Corrección de unidades y estabilidad numérica
- [ ] Separación estricta de base temporal: `t` en µs en señales y gráficas; `dt` / `Ts` en segundos dentro del filtro `k(f)`.
- [ ] Prevención de desbordamiento de `exp` en la evaluación de la doble exponencial `Um(t)` (`clip` del argumento).
- [ ] Coerción de tipos segura a `float64` antes del filtrado digital.

## 3. Trazabilidad metrológica e integridad de datos
- [ ] Todo retardo `t_lag` registrado en `metadata.yaml` documenta explícitamente su referencia (`referencia_impulso`: `t10` u `origen_virtual_IEC60060`).
- [ ] Cuando la referencia es `O1`, se almacena el bloque `ancla` con `t10_menos_O1_ns` y sus estadísticas para permitir compatibilidad estricta con consumidores que anclan en `t10`.
- [ ] Ausencia de auto-validación circular: los tests deben verificar contra vectores analíticos ideales normativos (§8.1 y §8.2 de la metodología).
