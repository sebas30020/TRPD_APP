"""Edición manual de arribos (t_ant) en calibrar_app.

Equivalente a la edición de peaks de app.py, pero con un solo arribo por
(canal, disparo): se puede FIJAR el t_ant a mano o QUITAR el disparo del promedio.
Cada acción es un paso del historial del canal, guardado en metadata.yaml
(ediciones_arribo.<canal>.historial), así sobrevive a cambios de umbral y t_mín
y se puede deshacer paso a paso.
"""

from __future__ import annotations
import numpy as np
import yaml

from datos import obtener_metadata, guardar_metadata_archivo, asegurar_metadata_medicion
from arribo import filtrar_mad

SECCION = "ediciones_arribo"
CANALES = ("ch2", "ch3", "ch4")


def ediciones_canal(carpeta: str, canal: str) -> dict:
    """{'historial': [...]} del canal (vacío si no hay ediciones)."""
    sec = (obtener_metadata(carpeta) or {}).get(SECCION) if carpeta else None
    ed = sec.get(canal) if isinstance(sec, dict) else None
    hist = ed.get("historial") if isinstance(ed, dict) else None
    return {"historial": list(hist) if isinstance(hist, list) else []}


def ediciones_medicion(carpeta: str) -> dict:
    """{canal: ediciones} de los canales sensores de la medición."""
    return {ch: ediciones_canal(carpeta, ch) for ch in CANALES} if carpeta else {}


def guardar_ediciones_canal(carpeta: str, canal: str, ed: dict | None) -> tuple[bool, str]:
    """Guarda las ediciones de un canal sin tocar el resto de metadata.yaml.
    Un historial vacío borra la clave del canal (y la sección si queda vacía)."""
    asegurar_metadata_medicion(carpeta)  # sin YAML previo se guarda sobre la plantilla completa
    meta = {k: v for k, v in (obtener_metadata(carpeta) or {}).items() if not str(k).startswith("_")}
    sec = dict(meta.get(SECCION) or {})
    if ed and ed.get("historial"):
        sec[canal] = {"historial": ed["historial"]}
    else:
        sec.pop(canal, None)
    if sec:
        meta[SECCION] = sec
    else:
        meta.pop(SECCION, None)
    return guardar_metadata_archivo(carpeta, yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))


def estado_ediciones(ed: dict | None) -> dict:
    """Reproduce el historial: {'manuales': {seg: t_us}, 'quitados': set(seg)}.
    Fijar un disparo lo saca de los quitados; quitarlo descarta su arribo manual."""
    manuales: dict[int, float] = {}
    quitados: set[int] = set()
    for paso in (ed or {}).get("historial") or []:
        try:
            seg = int(paso["seg"])
        except (KeyError, TypeError, ValueError):
            continue
        if paso.get("accion") == "fijar" and paso.get("t_us") is not None:
            manuales[seg] = float(paso["t_us"])
            quitados.discard(seg)
        elif paso.get("accion") == "quitar":
            manuales.pop(seg, None)
            quitados.add(seg)
    return {"manuales": manuales, "quitados": quitados}


def aplicar_ediciones(res: dict | None, ed: dict | None) -> dict | None:
    """Resultado de calibrar_retardo con las ediciones aplicadas: t_ant manuales en
    lugar de los detectados, disparos quitados fuera del promedio, y t_lag / MAD /
    media / σ recalculados. Añade 'origen' por disparo ('auto' | 'manual' | 'quitado')
    y los conteos 'n_manual' y 'n_quitados'."""
    if not isinstance(res, dict) or not res.get("segs"):
        return res
    est = estado_ediciones(ed)
    segs = [int(s) for s in res["segs"]]
    ancla = list(res.get("ancla_us") or [])
    t_ant = list(res.get("t_ant") or [None] * len(segs))
    origen = ["auto"] * len(segs)
    t_lag = np.full(len(segs), np.nan, dtype=np.float64)

    for i, s in enumerate(segs):
        if s in est["quitados"]:
            origen[i] = "quitado"
        elif s in est["manuales"]:
            t_ant[i] = est["manuales"][s]
            origen[i] = "manual"
        ta = t_ant[i]
        if origen[i] != "quitado" and ta is not None and i < len(ancla):
            t_lag[i] = float(ta) - float(ancla[i])

    valido, atipico, media, sigma = filtrar_mad(t_lag)
    out = dict(res)
    out.update({
        "t_ant": [float(x) if x is not None else None for x in t_ant],
        "t_lag": [float(x) if not np.isnan(x) else None for x in t_lag],
        "valido": [bool(x) for x in valido],
        "atipico": [bool(x) for x in atipico],
        "t_lag_us": media,
        "sigma_us": sigma,
        "n_valid": int(np.sum(valido)),
        "origen": origen,
        "n_manual": origen.count("manual"),
        "n_quitados": origen.count("quitado"),
    })
    return out


def resultados_editados(store: dict | None, ediciones: dict | None) -> dict:
    """Copia de resultado_store con las ediciones de cada canal aplicadas."""
    store = dict(store or {})
    canales = (ediciones or {}).get("canales") or {}
    if (ediciones or {}).get("carpeta") != store.get("_carpeta"):
        canales = {}
    for ch in CANALES:
        if isinstance(store.get(ch), dict):
            store[ch] = aplicar_ediciones(store[ch], canales.get(ch))
    return store
