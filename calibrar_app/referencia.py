"""Módulo selector de referencia temporal de impulso (t10 vs origen virtual O1).

Unifica el cálculo de las dos alternativas y proporciona la conversión delta_t10_menos_O1.
"""

from __future__ import annotations
import numpy as np
from datos import (
    canales_presentes,
    n_segmentos,
    cargar_segmento,
    dt_segundos,
    n_pre_muestras,
    VENTANA_IEC,
)
from impulso import t10_por_segmento, n_fallback_t10
from iec60060 import evaluar_impulso

REFERENCIAS = ("t10", "origen_virtual_IEC60060")

_ANCLA_CACHE: dict[tuple[str, str], dict] = {}
_IEC_SEG_CACHE: dict[tuple[str, int], dict] = {}


def evaluar_segmento_iec(carpeta: str, seg: int, con_curva: bool = True, diezmado_ajuste: int = 10) -> dict:
    """Evalúa el pipeline normativo IEC 60060-1 sobre el registro completo de CH1."""
    key = (carpeta, seg)
    if key in _IEC_SEG_CACHE and not con_curva:
        return _IEC_SEG_CACHE[key]

    if "ch1" not in canales_presentes(carpeta):
        return {"exito": False, "mensaje": "CH1 no está presente"}

    dt_s = dt_segundos(carpeta, "ch1")
    n_pre = n_pre_muestras(carpeta, "ch1")
    t, v = cargar_segmento(carpeta, "ch1", seg, ventana=VENTANA_IEC)
    if v.size == 0:
        return {"exito": False, "mensaje": "Segmento vacío"}

    res = evaluar_impulso(
        t, v, dt_s, n_pre, pol=1, diezmado_ajuste=diezmado_ajuste, con_curva=con_curva
    )
    if not con_curva:
        _IEC_SEG_CACHE[key] = res
    return res


def ancla_por_segmento(carpeta: str, referencia: str = "t10") -> dict:
    """Calcula el vector de marcas temporales de referencia (µs) por segmento.

    Retorna:
      {
        "ancla_us": np.ndarray(nsegs),
        "referencia": str,
        "n_fallback": int,
        "detalle": list[dict] | None
      }
    """
    key = (carpeta, referencia)
    if key in _ANCLA_CACHE:
        return _ANCLA_CACHE[key]

    nsegs = n_segmentos(carpeta) if ("ch1" in canales_presentes(carpeta)) else 0
    if nsegs == 0:
        res = {
            "ancla_us": np.zeros(0, dtype=np.float64),
            "referencia": referencia,
            "n_fallback": 0,
            "detalle": None,
        }
        _ANCLA_CACHE[key] = res
        return res

    if referencia == "t10":
        arr = t10_por_segmento(carpeta)
        res = {
            "ancla_us": arr,
            "referencia": "t10",
            "n_fallback": n_fallback_t10(carpeta),
            "detalle": None,
        }
        _ANCLA_CACHE[key] = res
        return res

    # Modo origen_virtual_IEC60060
    t10_arr = t10_por_segmento(carpeta)
    o1_arr = np.empty(nsegs, dtype=np.float64)
    detalles = []
    n_fb = 0

    for s in range(1, nsegs + 1):
        info = evaluar_segmento_iec(carpeta, s, con_curva=False, diezmado_ajuste=10)
        detalles.append(info)
        if info.get("exito") and info.get("O1") is not None:
            o1_arr[s - 1] = float(info["O1"])
        else:
            # Fallback operacional: usar t10 desplazado por el delta aproximado (~0.26 µs)
            o1_arr[s - 1] = float(t10_arr[s - 1] - 0.258)
            n_fb += 1

    o1_arr.flags.writeable = False
    res = {
        "ancla_us": o1_arr,
        "referencia": "origen_virtual_IEC60060",
        "n_fallback": n_fb,
        "detalle": detalles,
    }
    _ANCLA_CACHE[key] = res
    return res


def resumen_iec(carpeta: str) -> dict:
    """Calcula estadísticas y conformidad IEC del lote de impulsos en la medición."""
    ancla_info = ancla_por_segmento(carpeta, referencia="origen_virtual_IEC60060")
    detalles = ancla_info.get("detalle") or []
    validos = [d for d in detalles if d.get("exito") and d.get("T1") is not None]
    if not validos:
        return {
            "n_total": len(detalles), "n_validos": 0, "conforme": False,
            "T1_medio_us": None, "T2_medio_us": None, "Ut_medio": None,
            "beta_medio_pct": None, "beta_max_pct": None, "fuera_tolerancia": len(detalles)
        }

    t1_list = [d["T1"] for d in validos]
    t2_list = [d["T2"] for d in validos if d.get("T2") is not None]
    ut_list = [d["Ut"] for d in validos]
    beta_list = [d["beta_pct"] for d in validos]
    fuera_tol = sum(1 for d in validos if not d.get("veredicto", {}).get("conforme", False))

    return {
        "n_total": len(detalles),
        "n_validos": len(validos),
        "conforme": fuera_tol == 0,
        "T1_medio_us": float(np.mean(t1_list)),
        "T2_medio_us": float(np.mean(t2_list)) if t2_list else None,
        "Ut_medio": float(np.mean(ut_list)),
        "beta_medio_pct": float(np.mean(beta_list)),
        "beta_max_pct": float(np.max(beta_list)),
        "fuera_tolerancia": fuera_tol,
    }


def delta_t10_menos_O1(carpeta: str) -> dict:
    """Calcula la diferencia estadística t10 - O1 (en µs) por segmento.

    Permite normalizar retardos calibrados contra O1 hacia t10.
    """
    t10 = t10_por_segmento(carpeta)
    ancla_o1 = ancla_por_segmento(carpeta, referencia="origen_virtual_IEC60060")
    o1 = ancla_o1["ancla_us"]
    if t10.size == 0 or o1.size == 0 or t10.size != o1.size:
        return {"media_us": 0.258, "sigma_us": 0.0, "n": 0, "por_segmento": []}

    delta = t10 - o1
    n = len(delta)
    media = float(np.mean(delta))
    sigma = float(np.std(delta, ddof=1)) if n >= 2 else 0.0
    return {
        "media_us": media,
        "sigma_us": sigma,
        "n": n,
        "por_segmento": delta.tolist(),
    }
