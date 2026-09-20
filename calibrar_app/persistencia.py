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
    listar_mediciones,
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
) -> dict:
    """Construye el bloque 'calibracion_retardo' para metadata.yaml."""
    return generate_metadata.bloque_calibracion_retardo(
        resultados=resultados,
        fuente=fuente,
        sensores=sensores,
        fecha=fecha,
        referencia_impulso=referencia_impulso,
        info_ancla=info_ancla,
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


def guardar_calibracion_metadata(carpeta: str, bloque: dict) -> tuple[bool, str]:
    """Inserta/reemplaza 'calibracion_retardo' preservando el resto de metadata.yaml."""
    meta = obtener_metadata(carpeta)
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    meta["calibracion_retardo"] = bloque
    return guardar_metadata_archivo(
        carpeta,
        yaml.safe_dump(meta, sort_keys=False, allow_unicode=True),
    )


def mediciones_con_calibracion() -> list[str]:
    """Lista las mediciones cuyo metadata.yaml contiene 'calibracion_retardo'."""
    res = []
    for m in listar_mediciones():
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
