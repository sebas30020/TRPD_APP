"""Módulo de detección de tiempos de arribo y cálculo de retardo instrumental t_lag.

Conserva literalmente la semántica de detección e interpolación sub-muestra de app.py
y la filtra mediante el estimador robusto MAD (k=5.0).
"""

from __future__ import annotations
import numpy as np
from datos import (
    canales_presentes,
    n_segmentos,
    cargar_segmento,
    _muestras,
    VENTANA_T10,
)
from referencia import ancla_por_segmento

MAD_K = 5.0  # Atípico si |t_lag - mediana| > MAD_K * 1.4826 * MAD

_ARRIBO_CACHE: dict[tuple, dict] = {}


# Método de arribo (bloque calibracion_retardo.criterio). Franjas [tmin, tmax] en µs
# RELATIVAS al t10 de CH1 de cada disparo (el transitorio se corre en el tiempo del
# osciloscopio con la tensión, porque el trigger está a nivel fijo sobre CH1):
#   - HFCT (CH2, respuesta lenta): máximo global de |v| en la franja, sin umbral;
#   - antenas: máximo de la primera oscilación que supera el umbral (t_arribo), con el
#     umbral de «Ajustar umbrales» (30 % de la mediana de la ráfaga).
CRITERIO_ARRIBO = "franja_t10"
CANALES_MAXIMO = ("ch2",)
ARRIBO_CANAL = {"ch2": "maximo_franja", "ch3": "pico_primer_lobulo", "ch4": "pico_primer_lobulo"}
FRANJA_DEFECTO_US = (-0.16, -0.04)


def t_arribo(t: np.ndarray, v: np.ndarray, umbral: float, distancia: int | None, tmin: float | None,
             tmax: float | None = None) -> float | None:
    """Instante t_ant (µs) del máximo de |v| en la primera oscilación que cruza el umbral.

    Busca, dentro de tmin <= t <= tmax (tmax None: sin límite; acota la franja donde
    puede llegar el estallido del spark gap), la primera muestra con |v| >= umbral
    precedida de una con |v| < umbral (lóbulo positivo o negativo, lo que llegue
    antes). El lóbulo es el tramo de mismo signo que contiene ese cruce (entre dos
    pasos por cero; puede terminar después de tmax) y el arribo es su máximo de |v|,
    refinado con una parábola por las tres muestras del máximo. Devuelve None si no
    hay cruce observable.

    `distancia` se conserva por compatibilidad de firma y no se usa.
    """
    if t.size < 2:
        return None
    ini = 0 if tmin is None else int(np.searchsorted(t, tmin, side="left"))
    fin = t.size if tmax is None else int(np.searchsorted(t, tmax, side="right"))
    if fin - ini < 2:
        return None
    a = np.abs(v)
    seg = a[ini:fin]
    cruces = np.nonzero((seg[1:] >= umbral) & (seg[:-1] < umbral))[0]
    if cruces.size == 0:
        return None
    return _pico_lobulo(t, v, ini + int(cruces[0]) + 1)   # primera muestra sobre el umbral


def _pico_lobulo(t: np.ndarray, v: np.ndarray, k: int) -> float:
    """Instante del máximo de |v| del lóbulo (tramo de mismo signo entre dos pasos
    por cero) que contiene la muestra k, refinado con una parábola por las tres
    muestras del máximo."""
    a = np.abs(v)
    signo = np.sign(v[k])
    i0 = k
    while i0 > 0 and np.sign(v[i0 - 1]) == signo:
        i0 -= 1
    i1 = k
    while i1 + 1 < v.size and np.sign(v[i1 + 1]) == signo:
        i1 += 1
    i = i0 + int(np.argmax(a[i0:i1 + 1]))
    if i0 < i < i1:
        y0, y1, y2 = a[i - 1], a[i], a[i + 1]
        den = y0 - 2.0 * y1 + y2
        if den < 0:
            delta = 0.5 * (y0 - y2) / den     # en muestras, |delta| <= 0.5
            return float(t[i] + delta * (t[i + 1] - t[i - 1]) / 2.0)
    return float(t[i])


def pico_lobulo(t: np.ndarray, v: np.ndarray, t_us: float) -> float | None:
    """Arribo manual con el mismo criterio que t_arribo: máximo de |v| de la
    oscilación sobre la que cae la marca t_us (la muestra más cercana)."""
    if t.size == 0:
        return None
    return _pico_lobulo(t, v, int(np.argmin(np.abs(t - t_us))))


def t_arribo_por_segmento(carpeta: str, canal: str, umbral: float, dist_us: float, tmin: float,
                          tmax: float | None = None) -> list[float | None]:
    """t_ant de cada segmento del canal (franja relativa al t10 de cada disparo)."""
    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    t10 = t10_por_disparo(carpeta) if nsegs else []
    t_ant_list = []
    for s in range(1, nsegs + 1):
        a0, a1 = franja_disparo(t10, s, tmin, tmax)
        if a0 is None:
            t_ant_list.append(None)
            continue
        t, v = cargar_segmento(carpeta, canal, s, ventana=VENTANA_T10)
        t_ant_list.append(arribo_canal(t, v, canal, umbral, a0, a1))
    return t_ant_list


def filtrar_mad(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, float | None, float | None]:
    """Filtra atípicos con el criterio MAD (k=5.0) y calcula media y desviación estándar."""
    valido = ~np.isnan(arr)
    atipico = np.zeros(arr.size, dtype=bool)
    n_val = int(np.sum(valido))

    if n_val >= 3:
        med = float(np.median(arr[valido]))
        mad = float(np.median(np.abs(arr[valido] - med)))
        if mad > 0:
            umbral_mad = MAD_K * 1.4826 * mad
            atipico = valido & (np.abs(arr - med) > umbral_mad)
            valido = valido & ~atipico

    n_valid = int(np.sum(valido))
    if n_valid > 0:
        media = float(np.mean(arr[valido]))
        sigma = float(np.std(arr[valido], ddof=1)) if n_valid >= 2 else None
    else:
        media = None
        sigma = None
    return valido, atipico, media, sigma


# ---------------- Ruido de fondo y umbral relativo ----------------
# Validez de un disparo: su ráfaga (máximo de |v| en la franja [tmin, tmax]) debe superar
# SNR_MIN veces el ruido de fondo, medido al inicio del registro (antes del impulso y de
# cualquier descarga). «Ajustar umbrales» fija el umbral de cada canal en FRACCION_UMBRAL
# de la mediana de esas ráfagas sobre los disparos válidos de la medición.
SNR_MIN = 8.0
FRACCION_UMBRAL = 0.3
RUIDO_DESDE_US = 0.2      # tras el inicio del registro (se salta el transitorio del filtro)
RUIDO_DURACION_US = 2.0


def ruido_fondo(t: np.ndarray, v: np.ndarray) -> float | None:
    """Desviación estándar de v en los primeros microsegundos del registro."""
    if t.size == 0:
        return None
    m = (t >= t[0] + RUIDO_DESDE_US) & (t < t[0] + RUIDO_DESDE_US + RUIDO_DURACION_US)
    return float(np.std(v[m])) if np.count_nonzero(m) > 1 else None


def t10_por_disparo(carpeta: str) -> list[float]:
    """t10 de CH1 de cada disparo (µs, tiempo del osciloscopio): origen de las franjas."""
    return [float(x) for x in ancla_por_segmento(carpeta, referencia="t10")["ancla_us"]]


def franja_disparo(t10: list[float], seg: int, tmin: float | None,
                   tmax: float | None) -> tuple[float | None, float | None]:
    """Franja absoluta (tiempo del osciloscopio) del disparo: t10 + [tmin, tmax].
    (None, None) si el disparo no tiene t10."""
    if seg - 1 >= len(t10) or not np.isfinite(t10[seg - 1]):
        return None, None
    t0 = t10[seg - 1]
    return (t0 + tmin if tmin is not None else -np.inf), (t0 + tmax if tmax is not None else np.inf)


def maximo_franja(t: np.ndarray, v: np.ndarray, tmin: float | None, tmax: float | None) -> float | None:
    """Instante del máximo global de |v| en [tmin, tmax], refinado con la parábola de
    _pico_lobulo (criterio del HFCT)."""
    ini = 0 if tmin is None or not np.isfinite(tmin) else int(np.searchsorted(t, tmin, side="left"))
    fin = t.size if tmax is None or not np.isfinite(tmax) else int(np.searchsorted(t, tmax, side="right"))
    if fin <= ini:
        return None
    return _pico_lobulo(t, v, ini + int(np.argmax(np.abs(v[ini:fin]))))


def arribo_canal(t: np.ndarray, v: np.ndarray, canal: str, umbral: float | None,
                 tmin: float | None, tmax: float | None) -> float | None:
    """Arribo del canal en la franja absoluta [tmin, tmax] según ARRIBO_CANAL."""
    if canal in CANALES_MAXIMO:
        return maximo_franja(t, v, tmin, tmax)
    if umbral is None:
        return None
    return t_arribo(t, v, umbral, None, tmin, tmax)


def max_franja(t: np.ndarray, v: np.ndarray, tmin: float | None, tmax: float | None) -> float | None:
    """Máximo de |v| en [tmin, tmax] (la ráfaga del spark gap)."""
    ini = 0 if tmin is None or not np.isfinite(tmin) else int(np.searchsorted(t, tmin, side="left"))
    fin = t.size if tmax is None or not np.isfinite(tmax) else int(np.searchsorted(t, tmax, side="right"))
    return float(np.max(np.abs(v[ini:fin]))) if fin > ini else None


def snr_disparo(carpeta: str, canal: str, seg: int, tmin: float | None, tmax: float | None,
                t10: list[float] | None = None) -> tuple[float | None, float | None, float | None]:
    """(SNR, ráfaga en mV, ruido en mV) del disparo, con el registro completo.
    [tmin, tmax] relativos al t10 del disparo."""
    t10 = t10_por_disparo(carpeta) if t10 is None else t10
    a0, a1 = franja_disparo(t10, int(seg), tmin, tmax)
    if a0 is None:
        return None, None, None
    t, v = cargar_segmento(carpeta, canal, int(seg), ventana=None)
    ruido, rafaga = ruido_fondo(t, v), max_franja(t, v, a0, a1)
    if not ruido or rafaga is None:
        return None, rafaga, ruido
    return rafaga / ruido, rafaga, ruido


def ajustar_umbral(carpeta: str, canal: str, tmin: float | None, tmax: float | None,
                   fraccion: float = FRACCION_UMBRAL, snr_min: float = SNR_MIN) -> dict:
    """Umbral del canal con todos los disparos de la medición: fraccion × mediana de la
    ráfaga (franja relativa al t10) de los disparos con SNR >= snr_min. umbral_mv None
    si ninguno es válido."""
    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    t10 = t10_por_disparo(carpeta) if nsegs else []
    snr, rafaga, ruido = [], [], []
    for s in range(1, nsegs + 1):
        x = snr_disparo(carpeta, canal, s, tmin, tmax, t10=t10)
        snr.append(x[0]); rafaga.append(x[1]); ruido.append(x[2])
    validas = [r for q, r in zip(snr, rafaga) if q is not None and q >= snr_min]
    return {
        "canal": canal,
        "umbral_mv": float(fraccion * np.median(validas)) if validas else None,
        "n_validos": len(validas),
        "n_total": nsegs,
        "snr": snr,
        "rafaga_mv": rafaga,
        "ruido_mv": ruido,
        "fraccion": fraccion,
        "snr_min": snr_min,
    }


def calibrar_retardo(carpeta: str, canal: str, umbral: float, dist_us: float = 0.05, tmin: float = 0.15,
                     referencia: str = "t10", distancia_us: float | None = None,
                     tmax: float | None = None, snr_min: float | None = SNR_MIN) -> dict:
    """Calcula el retardo instrumental t_lag = t_ant - ancla para cada segmento.

    El arribo se busca en la franja [tmin, tmax] µs relativa al t10 de CH1 de cada
    disparo, con el criterio del canal (ARRIBO_CANAL; el HFCT no usa umbral). Un disparo
    sin arribo en esa franja o cuya ráfaga no supera snr_min veces el ruido de fondo
    (None: sin esta condición) no entra al promedio. Filtra atípicos por MAD y promedia
    los válidos. Cacheado por sesión.
    Acepta tanto dist_us como distancia_us para compatibilidad total de llamadas.
    """
    if distancia_us is not None:
        dist_us = distancia_us
    if canal in CANALES_MAXIMO:
        umbral = None   # el HFCT toma el máximo de la franja
    key = (carpeta, canal, round(float(umbral), 6) if umbral is not None else None,
           dist_us, tmin, tmax, referencia, snr_min)
    if key in _ARRIBO_CACHE:
        return _ARRIBO_CACHE[key]

    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    if nsegs == 0 or canal not in canales_presentes(carpeta):
        res = {
            "canal": canal,
            "segs": [],
            "t_ant": [],
            "t_lag": [],
            "valido": [],
            "atipico": [],
            "t_lag_us": None,
            "sigma_us": None,
            "n_valid": 0,
            "n_total": 0,
            "criterio": CRITERIO_ARRIBO,
            "arribo": ARRIBO_CANAL.get(canal),
            "referencia": referencia,
            "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin, "tmax_us": tmax,
                       "snr_min": snr_min},
        }
        _ARRIBO_CACHE[key] = res
        return res

    ancla_info = ancla_por_segmento(carpeta, referencia=referencia)
    ancla = ancla_info["ancla_us"]
    t10 = t10_por_disparo(carpeta)

    t_ant_list, snr_list, bajo_ruido = [], [], []
    t_lag_arr = np.full(nsegs, np.nan, dtype=np.float64)

    for s in range(1, nsegs + 1):
        a0, a1 = franja_disparo(t10, s, tmin, tmax)
        q = snr_disparo(carpeta, canal, s, tmin, tmax, t10=t10)[0] if snr_min is not None else None
        debil = snr_min is not None and (q is None or q < snr_min)
        snr_list.append(q)
        bajo_ruido.append(bool(debil))
        if debil or a0 is None:
            ta = None   # sin t10 o sin ráfaga clara sobre el ruido de fondo
        else:
            t, v = cargar_segmento(carpeta, canal, s, ventana=VENTANA_T10)
            ta = arribo_canal(t, v, canal, umbral, a0, a1)
        t_ant_list.append(ta)
        if ta is not None and s <= len(ancla):
            t_lag_arr[s - 1] = ta - ancla[s - 1]

    valido, atipico, t_lag_us, sigma_us = filtrar_mad(t_lag_arr)
    n_valid = int(np.sum(valido))

    res = {
        "canal": canal,
        "segs": list(range(1, nsegs + 1)),
        "t_ant": [float(x) if x is not None else None for x in t_ant_list],
        "t_lag": [float(x) if not np.isnan(x) else None for x in t_lag_arr],
        "valido": [bool(x) for x in valido],
        "atipico": [bool(x) for x in atipico],
        "t_lag_us": t_lag_us,
        "sigma_us": sigma_us,
        "n_valid": n_valid,
        "n_total": nsegs,
        "criterio": CRITERIO_ARRIBO,
        "arribo": ARRIBO_CANAL.get(canal),
        "referencia": referencia,
        "ancla_us": ancla.tolist() if hasattr(ancla, "tolist") else list(ancla),
        "snr": [float(x) if x is not None else None for x in snr_list],
        "bajo_ruido": bajo_ruido,
        "n_bajo_ruido": int(sum(bajo_ruido)),
        "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin, "tmax_us": tmax,
                   "snr_min": snr_min},
    }
    _ARRIBO_CACHE[key] = res
    return res
