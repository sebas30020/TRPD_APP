"""Módulo de detección de tiempos de arribo y cálculo de retardo instrumental t_lag.

Conserva literalmente la semántica de detección e interpolación sub-muestra de app.py
y la filtra mediante el estimador robusto MAD (k=5.0).
"""

from __future__ import annotations
import numpy as np
from scipy.signal import find_peaks
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


def t_arribo(t: np.ndarray, v: np.ndarray, umbral: float, distancia: int | None, tmin: float | None) -> float | None:
    """Instante t_ant (µs) por primer cruce del umbral en el frente de subida de |v|.

    Aplica máscara t >= tmin. Busca peaks en |v| con distancia mínima para que
    pequeños precursores EMI queden absorbidos en el peak mayor. Luego retrocede
    desde el primer peak hasta la última muestra por debajo del umbral e interpola
    linealmente el cruce sub-muestra. Devuelve None si no hay cruce observable.
    """
    if tmin is not None:
        mask = t >= tmin
        t, v = t[mask], v[mask]
    if v.size < 2:
        return None
    a = np.abs(v)
    idx, _ = find_peaks(a, height=umbral, distance=distancia)
    if idx.size == 0:
        return None
    i_p = int(idx[0])
    # Retroceder desde i_p hasta la última muestra j < i_p con a[j] < umbral
    j_candidates = np.nonzero(a[:i_p] < umbral)[0]
    if j_candidates.size == 0:
        return None  # Señal ya superaba el umbral desde el inicio
    j = int(j_candidates[-1])
    da = a[j + 1] - a[j]
    if da <= 0:
        return float(t[j])
    return float(t[j] + (umbral - a[j]) * (t[j + 1] - t[j]) / da)


def t_arribo_por_segmento(carpeta: str, canal: str, umbral: float, dist_us: float, tmin: float) -> list[float | None]:
    """Calcula t_ant para cada segmento de un canal en la medición dada."""
    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    distancia = _muestras(carpeta, canal, dist_us)
    t_ant_list = []
    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, canal, s, ventana=VENTANA_T10)
        ta = t_arribo(t, v, umbral, distancia, tmin)
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


def calibrar_retardo(carpeta: str, canal: str, umbral: float, dist_us: float, tmin: float,
                     referencia: str = "t10") -> dict:
    """Calcula el retardo instrumental t_lag = t_ant - ancla para cada segmento.

    Filtra atípicos por MAD y promedia los válidos. Cacheado por sesión.
    """
    key = (carpeta, canal, round(float(umbral), 6) if umbral is not None else None,
           dist_us, tmin, referencia)
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
            "criterio": "primer_cruce_umbral",
            "referencia": referencia,
            "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin},
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
        ta = t_arribo(t, v, umbral, distancia, tmin)
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
        "criterio": "primer_cruce_umbral",
        "referencia": referencia,
        "ancla_us": ancla.tolist() if hasattr(ancla, "tolist") else list(ancla),
        "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin},
    }
    _ARRIBO_CACHE[key] = res
    return res
