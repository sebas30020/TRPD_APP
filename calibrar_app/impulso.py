"""Módulo de marcas y tiempos característicos de impulso (ancla t10).

Port fiel de la lógica de app.py para cálculo de t10_por_segmento sobre VENTANA_T10.
"""

from __future__ import annotations
import numpy as np
from scipy.signal import butter, sosfiltfilt
from datos import (
    canales_presentes,
    n_segmentos,
    cargar_segmento,
    meta_medicion,
    VENTANA_T10,
)

IMP_ORDEN = 4
IMP_FCORTE = 20e6  # 20 MHz

_IMPULSO_CACHE: dict[str, tuple[np.ndarray | None, np.ndarray | None]] = {}
_IMPULSO_FILT_CACHE: dict[str, tuple[np.ndarray | None, np.ndarray | None]] = {}
_T10_SEG_CACHE: dict[str, np.ndarray] = {}
_T10_FALLBACK_COUNT: dict[str, int] = {}


def promedio_impulso(carpeta: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Señal promedio de CH1 sobre todos los segmentos disponibles."""
    if not carpeta or "ch1" not in canales_presentes(carpeta):
        return None, None
    if carpeta not in _IMPULSO_CACHE:
        acc, t0, cnt = None, None, 0
        for s in range(1, n_segmentos(carpeta) + 1):
            t, v = cargar_segmento(carpeta, "ch1", s, ventana=VENTANA_T10)
            if acc is None:
                acc, t0 = np.zeros_like(v), t
            if v.shape == acc.shape:
                acc += v
                cnt += 1
        _IMPULSO_CACHE[carpeta] = (t0, acc / cnt if cnt else acc)
    return _IMPULSO_CACHE[carpeta]


def _filtrar_impulso(carpeta: str, v: np.ndarray) -> np.ndarray:
    """Pasa-bajos Butterworth orden 4 a 20 MHz de fase cero."""
    fs = 1.0 / meta_medicion(carpeta)["ch1"]["xinc"]
    sos = butter(IMP_ORDEN, IMP_FCORTE, btype="lowpass", fs=fs, output="sos")
    return sosfiltfilt(sos, v)


def impulso_filtrado(carpeta: str) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Impulso CH1 promedio con filtro pasa-bajos de 20 MHz."""
    if carpeta not in _IMPULSO_FILT_CACHE:
        t, v = promedio_impulso(carpeta)
        if t is None:
            _IMPULSO_FILT_CACHE[carpeta] = (None, None)
        else:
            _IMPULSO_FILT_CACHE[carpeta] = (t, _filtrar_impulso(carpeta, v))
    return _IMPULSO_FILT_CACHE[carpeta]


def _cruce_subida(t: np.ndarray, s: np.ndarray, thr: float, i_pico: int) -> float | None:
    """Primer tiempo (interpolado) en que s alcanza thr en el flanco de subida."""
    ss = s[:i_pico + 1]
    idx = np.nonzero((ss[:-1] < thr) & (ss[1:] >= thr))[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    du = s[i + 1] - s[i]
    if du <= 0:
        return float(t[i])
    return float(t[i] + (thr - s[i]) * (t[i + 1] - t[i]) / du)


def _cruce_bajada(t: np.ndarray, s: np.ndarray, thr: float, i_pico: int) -> float | None:
    """Primer tiempo (interpolado) tras el pico en que s cae por debajo de thr."""
    ss = s[i_pico:]
    idx = np.nonzero((ss[:-1] >= thr) & (ss[1:] < thr))[0]
    if idx.size == 0:
        return None
    i = int(i_pico + idx[0])
    du = s[i + 1] - s[i]
    if du == 0:
        return float(t[i])
    return float(t[i] + (thr - s[i]) * (t[i + 1] - t[i]) / du)


def tiempos_impulso(carpeta: str) -> dict | None:
    """Tiempos característicos del impulso promedio filtrado (µs)."""
    t, s = impulso_filtrado(carpeta)
    if t is None or s is None:
        return None
    i_pico = int(np.argmax(s))
    vmax = float(s[i_pico])
    T = {
        "vmax": vmax,
        "t_pico": float(t[i_pico]),
        "t10": _cruce_subida(t, s, 0.10 * vmax, i_pico),
        "t30": _cruce_subida(t, s, 0.30 * vmax, i_pico),
        "t90": _cruce_subida(t, s, 0.90 * vmax, i_pico),
        "t50": _cruce_bajada(t, s, 0.50 * vmax, i_pico),
        "t0_lin": None,
        "tmax_lin": None,
    }
    t30, t90 = T["t30"], T["t90"]
    if t30 is not None and t90 is not None and t90 != t30:
        m = (0.9 * vmax - 0.3 * vmax) / (t90 - t30)
        T["t0_lin"] = t30 - (0.3 * vmax) / m
        T["tmax_lin"] = t30 + (vmax - 0.3 * vmax) / m
    return T


def t10_por_segmento(carpeta: str) -> np.ndarray:
    """t10 (µs) del impulso CH1 filtrado en cada segmento (1..nsegs).

    Usa obligatoriamente VENTANA_T10 = (-5.0, 30.0) para bit-compatibilidad con app.py.
    """
    if carpeta in _T10_SEG_CACHE:
        return _T10_SEG_CACHE[carpeta]

    nsegs = n_segmentos(carpeta) if ("ch1" in canales_presentes(carpeta)) else 0
    if nsegs == 0 or ("ch1" not in canales_presentes(carpeta)):
        arr = np.zeros(nsegs, dtype=np.float64)
        arr.flags.writeable = False
        _T10_SEG_CACHE[carpeta] = arr
        _T10_FALLBACK_COUNT[carpeta] = 0
        return arr

    T_prom = tiempos_impulso(carpeta)
    t10_fallback = T_prom["t10"] if (T_prom and T_prom.get("t10") is not None) else 0.0

    t10_arr = np.empty(nsegs, dtype=np.float64)
    n_fb = 0
    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, "ch1", s, ventana=VENTANA_T10)
        if v.size == 0:
            t10_arr[s - 1] = t10_fallback
            n_fb += 1
            continue
        sf = _filtrar_impulso(carpeta, v)
        i_pico = int(np.argmax(sf))
        vmax = float(sf[i_pico])
        if vmax <= 0:
            t10_val = None
        else:
            t10_val = _cruce_subida(t, sf, 0.10 * vmax, i_pico)

        if t10_val is None:
            t10_arr[s - 1] = t10_fallback
            n_fb += 1
        else:
            t10_arr[s - 1] = t10_val

    t10_arr.flags.writeable = False
    _T10_SEG_CACHE[carpeta] = t10_arr
    _T10_FALLBACK_COUNT[carpeta] = n_fb
    return t10_arr


def n_fallback_t10(carpeta: str) -> int:
    if carpeta not in _T10_FALLBACK_COUNT:
        t10_por_segmento(carpeta)
    return _T10_FALLBACK_COUNT.get(carpeta, 0)
