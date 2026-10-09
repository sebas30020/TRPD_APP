"""Módulo de persistencia y serialización YAML para calibrar_app.

Gestiona la lectura, construcción y escritura del bloque 'calibracion_retardo'
en metadata.yaml, preservando las secciones existentes.
"""

from __future__ import annotations
import os
import sys
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, os.pardir))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import generate_metadata
from datos import (
    obtener_metadata,
    guardar_metadata_archivo,
    _dir_medicion,
)
import referencia


def bloque_calibracion_retardo(
    resultados: dict,
    fuente: str,
    sensores: dict | None = None,
    fecha: str | None = None,
    referencia_impulso: str = "t10",
    info_ancla: dict | None = None,
    filtros: dict | None = None,
) -> dict:
    """Construye el bloque 'calibracion_retardo' para metadata.yaml.
    `filtros` ({canal: 'HP_5MHz', ...}) registra el filtro digital usado por canal."""
    return generate_metadata.bloque_calibracion_retardo(
        resultados=resultados,
        fuente=fuente,
        sensores=sensores,
        fecha=fecha,
        referencia_impulso=referencia_impulso,
        info_ancla=info_ancla,
        filtros=filtros,
    )


def construir_info_ancla(carpeta: str) -> dict:
    """Construye el diccionario canónico de ancla evaluando delta_t10_menos_O1 y resumen_iec."""
    delta = referencia.delta_t10_menos_O1(carpeta)
    res = referencia.resumen_iec(carpeta)

    return {
        "metodo": "IEC60060-1_AnexoB",
        "t10_menos_O1_ns": round(float(delta["media_us"]) * 1e3, 2),
        "sigma_t10_menos_O1_ns": round(float(delta["sigma_us"]) * 1e3, 2),
        "n_segmentos": delta["n"],
        "T1_medio_us": round(float(res["T1_medio_us"]), 3) if res.get("T1_medio_us") is not None else None,
        "T2_medio_us": round(float(res["T2_medio_us"]), 3) if res.get("T2_medio_us") is not None else None,
        "beta_medio_pct": round(float(res["beta_medio_pct"]), 3) if res.get("beta_medio_pct") is not None else None,
        "beta_max_pct": round(float(res["beta_max_pct"]), 3) if res.get("beta_max_pct") is not None else None,
        "segmentos_fuera_tolerancia": res.get("fuera_tolerancia", 0),
    }


CANALES_SENSOR = ("ch2", "ch3", "ch4")


def fusionar_con_bloque_previo(bloque: dict, previo: dict | None) -> tuple[dict, list[str], list[str]]:
    """Conserva en `bloque` los canales de `previo` que no se recalcularon.

    Guardar solo los canales calculados en la sesión borraba la calibración de los
    demás (TRPD los leía con t_lag = 0). Un canal previo se conserva solo si su bloque
    usa la misma referencia de impulso (t10 u O1): con otra referencia su t_lag no es
    comparable y se descarta. Cada canal conservado lleva la fecha de su calibración.
    Devuelve (bloque, conservados, descartados)."""
    conservados, descartados = [], []
    if not isinstance(previo, dict):
        return bloque, conservados, descartados
    ref_prev = previo.get("referencia_impulso")
    if ref_prev is None:  # bloques legados sin referencia_impulso
        ref_prev = "origen_virtual_IEC60060" if "origen_virtual" in str(previo.get("referencia") or "") else "t10"
    misma_ref = ref_prev == bloque.get("referencia_impulso", "t10")
    for ch in CANALES_SENSOR:
        b_ch = previo.get(ch)
        if ch in bloque or not isinstance(b_ch, dict) or b_ch.get("t_lag_ns") is None:
            continue
        if misma_ref:
            b_ch = dict(b_ch)
            b_ch.setdefault("fecha", previo.get("fecha"))
            bloque[ch] = b_ch
            conservados.append(ch)
        else:
            descartados.append(ch)
    return bloque, conservados, descartados


def guardar_calibracion_metadata(carpeta: str, bloque: dict) -> tuple[bool, str]:
    """Inserta/reemplaza 'calibracion_retardo' preservando el resto de metadata.yaml."""
    meta = obtener_metadata(carpeta)
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    meta["calibracion_retardo"] = bloque
    return guardar_metadata_archivo(
        carpeta,
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
    )


def mediciones_con_calibracion(mediciones: list[str]) -> list[str]:
    """De `mediciones` (rutas), las que tienen 'calibracion_retardo' en su metadata.yaml."""
    res = []
    for m in mediciones:
        d = _dir_medicion(m)
        if not d:
            continue
        meta_path = os.path.join(d, "metadata.yaml")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "calibracion_retardo" in data:
                        res.append(m)
            except Exception:
                pass
    return res
