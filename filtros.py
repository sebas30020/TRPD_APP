"""Filtros digitales por canal, equivalentes a los del paper (all_exps_main.py).

Butterworth de orden 4 y fase cero (sosfiltfilt). La configuración de cada canal
se lee de metadata.yaml (canales.chX.filtro, p. ej. 'HP_5MHz', 'HP_200MHz',
'ninguno'); si el campo no existe se usan los valores por defecto. CH1 (impulso)
nunca se filtra aquí: su pasa-bajos lo gestiona el código del impulso.
"""

import re

import numpy as np
from scipy.signal import butter, sosfiltfilt

FILTROS_DEFECTO = {"ch2": "HP_5MHz", "ch3": "HP_200MHz", "ch4": "HP_200MHz"}
ORDEN = 4
MARGEN_US = 1.0   # µs leídos a cada lado de la ventana para evitar transitorios de borde

_TIPOS = {"hp": "highpass", "lp": "lowpass"}
_UNIDADES = {"hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}
_RE_FILTRO = re.compile(r"^(hp|lp)[\s_-]*(\d+(?:[.,]\d+)?)\s*(hz|khz|mhz|ghz)$", re.IGNORECASE)
_SIN_FILTRO = {"", "ninguno", "none", "no", "sin filtro", "sin_filtro"}


def parsear_filtro(texto):
    """'HP_5MHz' -> ('highpass', 5e6); 'ninguno'/None/'' -> None.
    Un texto no reconocido devuelve None con una advertencia."""
    if texto is None:
        return None
    s = str(texto).strip()
    if s.lower() in _SIN_FILTRO:
        return None
    m = _RE_FILTRO.match(s)
    if not m:
        print(f"Advertencia: filtro no reconocido '{texto}' (se usa la señal sin filtrar)")
        return None
    f = float(m.group(2).replace(",", ".")) * _UNIDADES[m.group(3).lower()]
    return (_TIPOS[m.group(1).lower()], f)


def filtro_canal(meta, canal):
    """Filtro del canal: canales.<canal>.filtro de la metadata si la clave existe
    (aunque sea 'ninguno'); si no, el de FILTROS_DEFECTO. CH1 -> None."""
    canal = str(canal).lower()
    if canal == "ch1":
        return None
    cfg = ((meta or {}).get("canales") or {}).get(canal)
    if isinstance(cfg, dict) and "filtro" in cfg:
        return parsear_filtro(cfg.get("filtro"))
    return parsear_filtro(FILTROS_DEFECTO.get(canal))


def aplicar(v, fs_hz, spec):
    """Aplica el filtro `spec` a `v` (fase cero). Si la frecuencia de corte no cabe
    bajo Nyquist o la señal es demasiado corta, devuelve `v` sin cambios."""
    if spec is None or v is None or v.size == 0:
        return v
    tipo, fc = spec
    if not fs_hz or fc >= fs_hz / 2:
        print(f"Advertencia: {etiqueta(spec)} no aplicable a fs = {fs_hz:.3g} Sa/s (señal sin filtrar)")
        return v
    sos = butter(ORDEN, fc, btype=tipo, fs=fs_hz, output="sos")
    if v.size <= 3 * (2 * len(sos) + 1):   # padlen por defecto de sosfiltfilt
        return v
    return sosfiltfilt(sos, np.asarray(v, dtype=np.float64))


def _fmt_freq(f):
    for u, k in (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3)):
        if f >= k:
            return f"{f / k:g}", u
    return f"{f:g}", "Hz"


def etiqueta(spec):
    """Texto legible: ('highpass', 5e6) -> 'HP 5 MHz'; None -> 'sin filtro'."""
    if spec is None:
        return "sin filtro"
    num, u = _fmt_freq(spec[1])
    return f"{'HP' if spec[0] == 'highpass' else 'LP'} {num} {u}"


def texto(spec):
    """Inverso de parsear_filtro: ('highpass', 5e6) -> 'HP_5MHz'; None -> 'ninguno'."""
    if spec is None:
        return "ninguno"
    num, u = _fmt_freq(spec[1])
    return f"{'HP' if spec[0] == 'highpass' else 'LP'}_{num}{u}"
