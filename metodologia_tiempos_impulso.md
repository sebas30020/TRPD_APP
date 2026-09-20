# Cálculo de los parámetros temporales del impulso tipo rayo a partir de registros digitales

**Base normativa:** IEC 60060-1:2010, cláusula 7.1 (definiciones), Anexo B (procedimiento normativo de evaluación) y Anexo C (guía informativa de implementación de software). Validación del software: IEC 61083-2.

**Objetivo:** obtener, desde el registro digital del canal de tensión, el valor de la tensión de ensayo `Ut`, el origen virtual `O1`, el tiempo de frente `T1`, el tiempo al valor mitad `T2` y la sobreoscilación relativa `β'`, de forma reproducible y trazable, para luego referir a `O1` los eventos de DP detectados en los canales de sensores.

---

## 1. Entradas requeridas

| Entrada | Símbolo | Notas |
|---|---|---|
| Muestras de tensión del divisor | `u_raw[i]` | en voltios de osciloscopio o en kV si ya está escalado |
| Base de tiempo | `t[i]` | uniforme; `Ts = t[i] - t[i-1]` |
| Intervalo de muestreo | `Ts` | en **segundos** para el filtro; en µs para los tiempos |
| Ventana pre-disparo | `n_pre` | número de muestras usadas para el nivel base |
| Polaridad | `pol` | +1 o −1 |
| Factor de escala del divisor | `k_div` | para expresar `Ut` en kV |

**Requisitos de la señal:**

- La ventana pre-disparo debe contener **solo línea base**, sin el transitorio del explosor. Si el explosor acopla al canal del divisor, hay que empezar la ventana antes del disparo del gap.
- El registro debe llegar al menos hasta que la cola baje del 40 % de la cresta, porque el ajuste del Anexo B lo exige. Para un 1,2/50 eso significa ≳ 70 µs. Para cerrar `T2` con margen, ≳ 100 µs.
- La resolución vertical debe evitar la saturación: el Anexo B usa el máximo real `Ue`, y si el pico está recortado todo el cálculo se invalida.

**Sobre el filtrado analógico previo.** Un pasa-bajos en el canal de tensión es admisible y reduce el jitter, pero:

- su frecuencia de corte debe estar muy por encima del contenido del frente (≳ 5 MHz para un 1,2/50, cuyo contenido útil está por debajo de ~1 MHz);
- si es causal, introduce un retardo de grupo (≈ `1/(2π·fc)`, es decir ~32 ns a 5 MHz) que **debe** calibrarse y restarse antes de comparar con los canales de DP;
- nunca un pasa-altos ni un pasabanda en este canal.

---

## 2. Nomenclatura (IEC 60060-1, 7.1)

| Símbolo | Definición |
|---|---|
| `U(t)` | curva registrada |
| `U0(t)` | curva registrada compensada de offset |
| `Ue` | **valor extremo**: máximo de `U0(t)` |
| `Um(t)` | **curva base**: doble exponencial ajustada |
| `Ub` | máximo de la curva base |
| `R(t)` | **curva residual**: `U0(t) − Um(t)` |
| `Rf(t)` | residual filtrada con `k(f)` |
| `Ut(t)` | **curva de tensión de ensayo**: `Um(t) + Rf(t)` |
| `Ut` | **valor de la tensión de ensayo**: máximo de `Ut(t)` |
| `β'` | sobreoscilación relativa: `100·(Ue − Ub)/Ue` [%] |
| `t30`, `t90` | instantes del 30 % y 90 % de `Ut` en el frente (puntos A y B) |
| `T` | `t90 − t30` |
| `T1` | tiempo de frente: `T/0,6` |
| `O1` | origen virtual: `t30 − 0,3·T1` |
| `t50` | instante en que `Ut(t)` cae por primera vez a `0,5·Ut` |
| `T2` | tiempo al valor mitad: `t50 − O1` |

> **Todos los niveles porcentuales del frente y de la cola se refieren a `Ut` y se buscan sobre `Ut(t)`, no sobre la señal cruda.** La única excepción es la tasa media de subida (7.1.20), que se define sobre la curva registrada y con niveles referidos a `Ue`.

---

## 3. Procedimiento paso a paso

### P1. Normalizar polaridad

```
u = pol * u_raw
```

Todo el resto del procedimiento asume impulso positivo.

### P2. Nivel base y compensación de offset

```
U_base = mean(u[0 : n_pre])
u0 = u - U_base
```

La ventana debe ser suficientemente larga para promediar el ruido: unas 1000 muestras o ≥ 1 µs, lo que sea mayor.

### P3. Valor extremo

```
Ue    = max(u0)
i_pk  = argmax(u0)
```

> **Cuidado con el ruido.** `Ue` es un máximo puntual, así que el ruido lo infla y produce una `β'` falsa. En una prueba con 0,5 % de ruido blanco sobre un impulso sin sobreoscilación, `β'` salió 1,5 % en lugar de 0 %. Si el SNR es bajo, conviene estimar `Ue` sobre una versión suavizada (por ejemplo, mediana móvil de unos pocos ns) y documentarlo.

### P4. Ventana de ajuste (Anexo B, pasos d–f)

```
d = último índice en el frente (i < i_pk) con u0[i] < 0,2·Ue
e = último índice en la cola (i > i_pk) con u0[i] > 0,4·Ue
ventana = índices [d+1, e]
```

El ajuste se hace **solo** con esos datos. Se excluye deliberadamente el pie del frente por debajo del 20 %.

### P5. Ajuste de la curva base (Anexo B paso g, Anexo C.1)

Modelo de cuatro parámetros libres `U`, `τ1`, `τ2`, `td`:

```
ud(t) = U · ( exp(-(t - td)/τ1) - exp(-(t - td)/τ2) )
```

**Algoritmo:** Levenberg-Marquardt (o Newton-Raphson, que da resultados equivalentes según C.1).

**Valores iniciales sugeridos por C.1:**

| Parámetro | Valor inicial |
|---|---|
| `U` | `Ue` |
| `τ1` | 70 µs |
| `τ2` | 0,4 µs |
| `td` | origen real o virtual de la curva |

**Normalización.** El Anexo C.1 advierte que conviene escalar los datos para que tensión y tiempo abarquen aproximadamente de 0 a 1, y devolver después los parámetros a las escalas originales. En la práctica esto es lo que separa un ajuste que converge de uno que no.

### P6. Curva base

```
Um(t) = 0                         para t < td
Um(t) = ud(t)                     para td ≤ t ≤ t[e]
```

### P7. Residual y filtro de la función de tensión de ensayo

```
R(t) = u0(t) - Um(t)
Rf   = k_filter(R, Ts)
```

La función de tensión de ensayo es

```
k(f) = 1 / (1 + 2,2·f²)        con f en MHz
```

Su punto de −3 dB está en `fc = 1/√2,2 = 0,6742 MHz`.

**Implementación del filtro (Anexo C.2).** IIR de un polo aplicado dos veces, hacia adelante y hacia atrás, para obtener fase cero:

```
a  = 2,2e-12                      (s², el cuadrado de la constante del filtro k)
x  = tan(π · Ts / √a)             Ts en segundos
b0 = b1 = x / (1 + x)
a1 = (1 - x) / (1 + x)

y[i] = b0·(v[i] + v[i-1]) + a1·y[i-1]
```

Se aplica la recursión al arreglo completo, se invierte el resultado, se vuelve a aplicar y se invierte de nuevo. Cada pasada aporta `1/√(1+2,2f²)`, así que las dos juntas reproducen `k(f)`.

**Coeficientes verificados:**

| `Ts` | `x` | `b0 = b1` | `a1` |
|---|---|---|---|
| 10 ns | 0,021183781 | 0,020744338 | 0,958511325 |
| 1 ns | 0,002118065 | 0,002113588 | 0,995772824 |
| 0,2 ns (5 GS/s) | 0,000423612 | 0,000423433 | 0,999153134 |

Los valores para 10 ns coinciden con el ejemplo del Anexo C.2. Usar **≥ 6 cifras significativas** en los coeficientes, como exige la norma, para evitar problemas numéricos del IIR.

Verificación del filtro implementado: la respuesta de doble pasada debe reproducir `k(f)` con error < 1e-3 en la banda de interés. En mi verificación a 10 ns el error máximo fue 2,9e-4.

### P8. Curva de tensión de ensayo

```
Ut_curve = Um + Rf
Ut       = max(Ut_curve)
i_pk_t   = argmax(Ut_curve)
Ub       = max(Um)
β'       = 100 · (Ue - Ub) / Ue          [%]
```

Si el impulso no tiene sobreoscilación apreciable, `Ut(t) ≈ u0(t)` y `β' ≈ 0`. En ese caso los pasos P5 a P8 se pueden omitir y trabajar directamente sobre `u0(t)`, pero **hay que verificar** `β'` antes de tomar ese atajo, no asumirlo.

### P9. Instantes de cruce

**Selección robusta del punto (nota de 7.1.20, extendida a los cruces):**

- `t30`: **último** cruce ascendente del nivel `0,3·Ut` antes de que la señal ya no vuelva a bajar de él.
- `t90`: **primer** cruce ascendente del nivel `0,9·Ut`.
- `t50`: **primer** cruce descendente de `0,5·Ut` después de `i_pk_t`.

**Interpolación lineal** entre las dos muestras que encierran el nivel `V_L`:

```
t_L = t[i-1] + (V_L - u[i-1]) · (t[i] - t[i-1]) / (u[i] - u[i-1])
```

La norma no prescribe el método de interpolación; delega la validación a IEC 61083-2. La lineal es la práctica habitual y su error es despreciable para muestreos finos:

| `Ts` | Error en `T1` con interpolación lineal | Error tomando la primera muestra sobre el umbral |
|---|---|---|
| 0,2 ns | despreciable | despreciable |
| 50 ns | −0,04 % | −2,8 % a +4,2 % |
| 100 ns | +0,26 % | −2,8 % |

### P10. Parámetros

```
T  = t90 - t30
T1 = T / 0,6
O1 = t30 - 0,3·T1        (equivalente: O1 = t30 - 0,5·T = 1,5·t30 - 0,5·t90)
T2 = t50 - O1
```

**Interpretación geométrica de `O1`.** Es la intersección con el eje de tiempo de la recta que pasa por A `(t30, 0,3·Ut)` y B `(t90, 0,9·Ut)`. Esa recta tiene pendiente `0,6·Ut/T` y alcanza `Ut` exactamente en `O1 + T1`.

### P11. Parámetros opcionales

**Tasa media de subida (7.1.20).** Pendiente de la recta de mínimos cuadrados sobre **todos** los puntos de la **curva registrada** entre el 30 % y el 90 % de `Ue`. Con ruido, el conjunto se acota entre el primer punto después del último cruce del 30 % y el último punto antes del primer cruce del 90 %.

**Tiempo de pico `Te` (7.1.21).** `Te = Ue / tasa media de subida`. Parámetro en consideración, no normativo para aceptación.

**`t10` (no normativo).** Si se necesita por compatibilidad con series anteriores, se calcula igual que `t30` pero con nivel `0,1·Ut`, y **debe declararse explícitamente como criterio operacional propio**, no como convención IEC. Para el 1,2/50 nominal, `t10 − O1 ≈ 0,26 µs`, pero ese valor depende del frente: 0,184 µs para `T1 = 0,84` y 0,339 µs para `T1 = 1,56`. Aproximación útil: `t10 − O1 ≈ 0,215·T1`.

---

## 4. Verificación de tolerancias (7.2.2)

El programa debe emitir un veredicto por impulso:

| Parámetro | Valor nominal | Tolerancia | Rango |
|---|---|---|---|
| `Ut` | especificado por el ensayo | ±3 % | — |
| `T1` | 1,2 µs | ±30 % | 0,84 a 1,56 µs |
| `T2` | 50 µs | ±20 % | 40 a 60 µs |
| `β'` | — | ≤ 10 % | — |

Nota: IEC 60060-3 (ensayos en sitio) admite `T1` entre 0,8 y 20 µs y `T2` entre 40 y 100 µs.

---

## 5. Aplicación a los eventos de DP

Una vez obtenido `O1` por impulso:

**Tiempo de ocurrencia**

```
t_abs = t_PD - O1 - Δτ_canal
```

donde `Δτ_canal` es la diferencia de retardos de trayecto (cables, respuesta del sensor, retardo de grupo de filtros) entre el canal de DP y el canal de tensión, determinada una sola vez por calibración.

**Normalización por forma de onda.** Para comparar probetas ensayadas con frentes distintos:

```
t_norm = (t_PD - O1) / T1
```

**Tensión instantánea en el momento de la DP.** Es la magnitud físicamente más informativa, y no depende del ancla ni de la forma del frente. Se lee directamente del registro:

```
U_a(t_PD) = Ut_curve(t_PD) · k_div
```

Aproximación lineal, válida **solo** si `t30 ≤ t_PD ≤ t90`:

```
U_a(t_PD) ≈ Ut · (t_PD - O1) / T1
```

**Conversión desde una serie referida a `t10`**

```
t_abs(O1) = t_abs(t10) + (t10 - O1)
```

---

## 6. Pseudocódigo

```
función evaluar_impulso(u_raw, t, Ts, n_pre, pol):
    u  = pol * u_raw
    u0 = u - media(u[0:n_pre])

    Ue   = max(u0);  i_pk = argmax(u0)
    d    = último i < i_pk con u0[i] < 0.2*Ue
    e    = último i > i_pk con u0[i] > 0.4*Ue

    (U, tau1, tau2, td) = ajustar_LM(t[d+1:e], u0[d+1:e],
                                     p0 = (Ue, 70us, 0.4us, origen),
                                     normalizando a [0,1])

    Um = 0 si t < td, si no U*(exp(-(t-td)/tau1) - exp(-(t-td)/tau2))
    R  = u0 - Um
    Rf = filtro_k(R, Ts)             # IIR de un polo, doble pasada
    Utc = Um + Rf

    Ut = max(Utc);  Ub = max(Um)
    beta = 100*(Ue - Ub)/Ue

    t30 = cruce_frente(t, Utc, 0.3*Ut)   # último cruce
    t90 = cruce_frente(t, Utc, 0.9*Ut)   # primer cruce
    t50 = cruce_cola (t, Utc, 0.5*Ut)    # primer cruce descendente

    T  = t90 - t30
    T1 = T / 0.6
    O1 = t30 - 0.3*T1
    T2 = t50 - O1

    verificar_tolerancias(Ut, T1, T2, beta)
    retornar (Ut, T1, T2, O1, t30, t90, t50, beta, tau1, tau2, td)
```

---

## 7. Implementación de referencia (Python)

```python
import numpy as np
from scipy.optimize import least_squares

def front_crossing(t, u, level):
    """Último cruce ascendente del nivel, con interpolación lineal."""
    i = np.nonzero(u >= level)[0][0]
    j = np.nonzero(u[:i] < level)[0][-1]
    return t[j] + (level - u[j]) * (t[j+1] - t[j]) / (u[j+1] - u[j])

def tail_crossing(t, u, level, i_pk):
    """Primer cruce descendente del nivel después del pico."""
    i = i_pk + np.nonzero(u[i_pk:] <= level)[0][0]
    return t[i-1] + (level - u[i-1]) * (t[i] - t[i-1]) / (u[i] - u[i-1])

def k_filter(x, Ts):
    """Filtro de la función de tensión de ensayo k(f)=1/(1+2.2 f^2), f en MHz.
       Ts en segundos. IIR de un polo aplicado hacia adelante y hacia atrás."""
    a = 2.2e-12
    xx = np.tan(np.pi * Ts / np.sqrt(a))
    b = xx / (1.0 + xx)
    a1 = (1.0 - xx) / (1.0 + xx)
    def fwd(v):
        y = np.empty_like(v); yp = 0.0; xp = 0.0
        for i, xi in enumerate(v):
            yp = b * (xi + xp) + a1 * yp
            xp = xi
            y[i] = yp
        return y
    return fwd(fwd(x[::-1])[::-1])

def fit_base_curve(t, u0, Ue):
    i_pk = int(np.argmax(u0))
    d = np.nonzero(u0[:i_pk] < 0.2 * Ue)[0][-1] + 1
    e = np.nonzero(u0[i_pk:] > 0.4 * Ue)[0][-1] + i_pk
    ts, us = t[d:e+1], u0[d:e+1]
    span = ts[-1] - ts[0]
    x = (ts - ts[0]) / span            # normalización recomendada por C.1
    y = us / Ue
    model = lambda p, x: p[0]*(np.exp(-(x-p[3])/p[1]) - np.exp(-(x-p[3])/p[2]))
    p0 = [1.0, 70.0/span, 0.4/span, -ts[0]/span]   # t en µs
    r = least_squares(lambda p: model(p, x) - y, p0, method='lm', max_nfev=20000)
    U, tau1, tau2, td = r.x
    return U*Ue, tau1*span, tau2*span, td*span + ts[0]

def evaluate(t, u_raw, n_pre, Ts, pol=1):
    """t en µs, Ts en segundos."""
    u0 = pol*u_raw - np.mean(pol*u_raw[:n_pre])
    Ue = float(np.max(u0))
    U, tau1, tau2, td = fit_base_curve(t, u0, Ue)
    Um = np.where(t >= td,
                  U*(np.exp(-(t-td)/tau1) - np.exp(-(t-td)/tau2)), 0.0)
    Utc = Um + k_filter(u0 - Um, Ts)
    Ut = float(np.max(Utc)); i_pk = int(np.argmax(Utc))
    t30 = front_crossing(t, Utc, 0.3*Ut)
    t90 = front_crossing(t, Utc, 0.9*Ut)
    t50 = tail_crossing(t, Utc, 0.5*Ut, i_pk)
    T = t90 - t30; T1 = T/0.6; O1 = t30 - 0.3*T1
    return dict(Ue=Ue, Ut=Ut, Ub=float(np.max(Um)),
                beta=100*(Ue-float(np.max(Um)))/Ue,
                t30=t30, t90=t90, t50=t50, T=T, T1=T1, O1=O1, T2=t50-O1,
                tau1=tau1, tau2=tau2, td=td, Ut_curve=Utc)
```

El `np.where` en `Um` puede desbordar `exp` si `td` queda muy adelante; conviene recortar el argumento o evaluar solo en `t ≥ td`.

---

## 8. Vectores de prueba

### 8.1 Impulso ideal 1,2/50 sin sobreoscilación

Doble exponencial con `td = 0`, `τ1 = 68,21697156 µs`, `τ2 = 0,40503431 µs`, cresta normalizada a 100 kV, muestreo 2 ns, ventana de −1 a 200 µs.

| Magnitud | Valor esperado |
|---|---|
| `Ut` | 100,000 kV |
| `t30` | 0,1394 µs |
| `t90` | 0,8594 µs |
| `T` | 0,7200 µs |
| `T1` | **1,2000 µs** |
| `O1` | **−0,2206 µs** |
| `t50` | 49,7794 µs |
| `T2` | **50,000 µs** |
| `β'` | 0,000 % |
| `τ1`, `τ2` recuperados | 68,217 / 0,40503 µs |
| `t10` (no normativo) | 0,0413 µs |

Si la implementación reproduce estos valores, el ajuste, el filtro y la interpolación están correctos.

### 8.2 Mismo impulso con 0,5 % de ruido blanco

| Magnitud | Resultado obtenido |
|---|---|
| `Ut` | 99,957 kV |
| `T1` | 1,2010 µs |
| `O1` | −0,2210 µs |
| `T2` | 49,950 µs |
| `β'` | **1,515 %** (artefacto del ruido) |

Muestra que los tiempos son robustos pero `β'` no lo es. Ver la advertencia del paso P3.

### 8.3 Con sobreoscilación superpuesta

Oscilación amortiguada de 10 % de amplitud sobre el mismo impulso:

| `f0` | `k(f0)` | `Ue` | `Ut` | `β'` | `T1` | `O1` |
|---|---|---|---|---|---|---|
| 0,5 MHz | 0,645 | 102,73 | 101,61 | 2,56 % | 1,174 µs | −0,240 µs |
| 1,0 MHz | 0,312 | 103,22 | 101,00 | 3,33 % | 1,411 µs | −0,325 µs |
| 2,0 MHz | 0,102 | 103,84 | 100,38 | 3,83 % | 1,315 µs | −0,278 µs |

Lo esperable: cuanto mayor la frecuencia de la oscilación, menor su contribución a `Ut`, porque `k(f)` la atenúa. Los valores exactos dependen del modelo de oscilación usado; sirven como comprobación cualitativa, no como referencia normativa.

### 8.4 Validación formal

Para certificar el software, IEC 61083-2 define formas de onda de referencia con valores esperados y límites de error. Lo anterior es autoverificación, no sustituye esa validación.

---

## 9. Casos borde a manejar en el código

| Situación | Acción sugerida |
|---|---|
| Pico recortado (saturación) | rechazar el registro |
| La cola no baja del 40 % dentro del registro | rechazar: no se puede ajustar ni calcular `T2` |
| El ajuste no converge | reintentar con otros valores iniciales; si falla, marcar el impulso y reportar los tiempos calculados directamente sobre `u0(t)`, indicando que no se aplicó el Anexo B |
| Múltiples cruces del 30 % o del 90 % por ruido | aplicar la regla último/primero del paso P9 |
| `β' > 10 %` | reportar fuera de tolerancia; el impulso no es un 1,2/50 válido |
| `td` fuera de la ventana del registro | revisar valores iniciales y normalización |
| Impulso cortado | procedimiento distinto (Anexo B.5 para corte en la cola, `Tc` para corte en el frente) |

---

## 10. Checklist de reporte por serie de impulsos

Para que los resultados sean comparables y trazables, reportar por probeta:

- [ ] `Ut` medio y dispersión
- [ ] `T1` medio y dispersión
- [ ] `T2` medio y dispersión
- [ ] `β'` medio y máximo
- [ ] Veredicto de tolerancias (cuántos impulsos dentro de 1,2/50 ±30 %/±20 %)
- [ ] Ancla usada para los tiempos de DP (`O1`), y `Δτ_canal` calibrado
- [ ] Intervalo de muestreo y filtrado analógico de cada canal
- [ ] Si se usó la ruta simplificada (sin Anexo B), justificarlo con `β'`
