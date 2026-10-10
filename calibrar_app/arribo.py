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


CRITERIO_ARRIBO = "pico_primer_lobulo"


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
    k = ini + int(cruces[0]) + 1          # primera muestra sobre el umbral
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


def t_arribo_por_segmento(carpeta: str, canal: str, umbral: float, dist_us: float, tmin: float,
                          tmax: float | None = None) -> list[float | None]:
    """Calcula t_ant para cada segmento de un canal en la medición dada."""
    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    distancia = _muestras(carpeta, canal, dist_us)
    t_ant_list = []
    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, canal, s, ventana=VENTANA_T10)
        ta = t_arribo(t, v, umbral, distancia, tmin, tmax)
        t_ant_list.append(ta)
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


def calibrar_retardo(carpeta: str, canal: str, umbral: float, dist_us: float = 0.05, tmin: float = 0.15,
                     referencia: str = "t10", distancia_us: float | None = None,
                     tmax: float | None = None) -> dict:
    """Calcula el retardo instrumental t_lag = t_ant - ancla para cada segmento.

    El arribo se busca en [tmin, tmax]: un disparo sin cruce en esa franja (p. ej. sin
    estallido del spark gap) no entra al promedio. Filtra atípicos por MAD y promedia
    los válidos. Cacheado por sesión.
    Acepta tanto dist_us como distancia_us para compatibilidad total de llamadas.
    """
    if distancia_us is not None:
        dist_us = distancia_us
    key = (carpeta, canal, round(float(umbral), 6) if umbral is not None else None,
           dist_us, tmin, tmax, referencia)
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
            "referencia": referencia,
            "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin, "tmax_us": tmax},
        }
        _ARRIBO_CACHE[key] = res
        return res

    distancia = _muestras(carpeta, canal, dist_us)
    ancla_info = ancla_por_segmento(carpeta, referencia=referencia)
    ancla = ancla_info["ancla_us"]

    t_ant_list = []
    t_lag_arr = np.full(nsegs, np.nan, dtype=np.float64)

    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, canal, s, ventana=VENTANA_T10)
        ta = t_arribo(t, v, umbral, distancia, tmin, tmax)
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
        "referencia": referencia,
        "ancla_us": ancla.tolist() if hasattr(ancla, "tolist") else list(ancla),
        "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin, "tmax_us": tmax},
    }
    _ARRIBO_CACHE[key] = res
    return res
