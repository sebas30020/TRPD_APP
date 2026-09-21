"""Módulo de acceso a datos HDF5 y metadata para calibrar_app.

Autónomo respecto a app.py. Mantiene bit-compatibilidad con app.py en ventana (-5, 30)
y permite leer registros completos (ventana=None) para IEC 60060-1.
"""

from __future__ import annotations
import functools
import os
import re
import h5py
import numpy as np
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ_REPO = os.path.abspath(os.path.join(AQUI, os.pardir))
MEDICIONES = os.path.abspath(os.path.join(RAIZ_REPO, os.pardir, "mediciones", "Mediciones"))

CANALES = ["ch1", "ch2", "ch3", "ch4"]
TRIGGERS = ["ch2", "ch3", "ch4"]

VENTANA_T10 = (-5.0, 30.0)  # idéntica a app.T_MIN / T_MAX
VENTANA_IEC = None          # registro completo para ajuste de cola IEC

_CHAN_RE = re.compile(r"^(.*?)(ch[1-4])(.*)\.h5$", re.IGNORECASE)


def _orden_natural(texto: str):
    """Clave para ordenar cadenas con números de forma natural."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(texto))]


def _ruta(carpeta: str, canal: str) -> str | None:
    """Resuelve la ruta absoluta al archivo .h5 del canal."""
    if not carpeta:
        return None
    canal = canal.lower()

    if os.path.isabs(carpeta):
        if os.path.isfile(carpeta):
            d, fname = os.path.split(carpeta)
            m = _CHAN_RE.match(fname)
            if m:
                pref, suff = m.group(1), m.group(3)
                p = os.path.join(d, f"{pref}{canal}{suff}.h5")
                if os.path.isfile(p):
                    return p
            return carpeta if canal in fname.lower() else None
        elif os.path.isdir(carpeta):
            carpeta = os.path.relpath(carpeta, MEDICIONES).replace("\\", "/")

    # 1. Caso directo estándar: carpeta/canal.h5
    p = os.path.join(MEDICIONES, carpeta, f"{canal}.h5")
    if os.path.isfile(p):
        return p

    # 2. Si carpeta es un directorio existente
    dir_directo = os.path.join(MEDICIONES, carpeta)
    if os.path.isdir(dir_directo):
        for f in os.listdir(dir_directo):
            m = _CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                return os.path.join(dir_directo, f)
        return None

    # 3. Archivos agrupados en parent
    parent, stem = os.path.split(carpeta)
    parent_dir = os.path.join(MEDICIONES, parent)
    if os.path.isdir(parent_dir):
        stem_clean = re.sub(r"\.h5$", "", stem, flags=re.IGNORECASE)
        stem_clean = re.sub(r"ch[1-4]", "", stem_clean, flags=re.IGNORECASE)
        for f in os.listdir(parent_dir):
            m = _CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                pref, suff = m.group(1), m.group(3)
                if f"{pref}{suff}" == stem_clean or stem_clean in f:
                    return os.path.join(parent_dir, f)

    return None


def canales_presentes(carpeta: str) -> list[str]:
    """Canales (ch1..ch4) cuyo archivo existe para la medición dada, en orden."""
    return [c for c in CANALES if _ruta(carpeta, c) is not None and os.path.isfile(_ruta(carpeta, c))]


def listar_mediciones() -> list[str]:
    """Lista todas las mediciones disponibles."""
    if not os.path.isdir(MEDICIONES):
        return []
    mediciones = set()
    for root, dirs, files in os.walk(MEDICIONES):
        h5_files = [f for f in files if f.lower().endswith(".h5")]
        if not h5_files:
            continue
        rel_dir = os.path.relpath(root, MEDICIONES).replace("\\", "/")
        grupos = {}
        for f in h5_files:
            m = _CHAN_RE.match(f)
            if m:
                pref, ch, suff = m.group(1), m.group(2).lower(), m.group(3)
                grupos.setdefault((pref, suff), {})[ch] = f

        for (pref, suff), chans in grupos.items():
            if not chans:
                continue
            if not pref and not suff:
                if rel_dir != ".":
                    mediciones.add(rel_dir)
            else:
                stem = f"{pref}{suff}"
                if rel_dir.endswith(stem):
                    mediciones.add(rel_dir)
                elif rel_dir != ".":
                    mediciones.add(f"{rel_dir}/{stem}")
                else:
                    mediciones.add(stem)
    return sorted(mediciones, key=_orden_natural)


def listar_subcarpetas(ruta: str) -> list[tuple[str, str, bool]]:
    """(nombre, ruta_absoluta, tiene_h5) de las subcarpetas directas de `ruta`."""
    if not ruta or not os.path.isdir(ruta):
        return []
    items = []
    try:
        nombres = sorted(os.listdir(ruta), key=_orden_natural)
    except Exception:
        return []
    for nombre in nombres:
        p = os.path.join(ruta, nombre)
        if os.path.isdir(p):
            try:
                archivos = os.listdir(p)
                tiene_h5 = any(
                    _CHAN_RE.match(f) for f in archivos
                    if os.path.isfile(os.path.join(p, f))
                )
            except Exception:
                tiene_h5 = False
            items.append((nombre, p, tiene_h5))
    return items


def _meta(carpeta: str, canal: str) -> dict:
    """Lee metadatos de escala y número de segmentos del archivo HDF5."""
    with h5py.File(_ruta(carpeta, canal), "r") as f:
        chan = list(f["Waveforms"].keys())[0]
        ch = f["Waveforms/" + chan]
        return {
            "chan": chan,
            "yinc": float(ch.attrs["YInc"]),
            "yorg": float(ch.attrs["YOrg"]),
            "xinc": float(ch.attrs["XInc"]),
            "xorg": float(ch.attrs["XOrg"]),
            "nsegs": int(ch.attrs["NumSegments"]),
        }


_META_CACHE: dict[str, dict] = {}


def meta_medicion(carpeta: str) -> dict[str, dict]:
    """Devuelve {canal: meta} cacheado."""
    if carpeta not in _META_CACHE:
        _META_CACHE[carpeta] = {c: _meta(carpeta, c) for c in canales_presentes(carpeta)}
    return _META_CACHE[carpeta]


def n_segmentos(carpeta: str) -> int:
    metas = meta_medicion(carpeta)
    if not metas:
        return 0
    return min(m["nsegs"] for m in metas.values())


def dt_segundos(carpeta: str, canal: str) -> float:
    """Paso de muestreo Ts en SEGUNDOS (meta['xinc'])."""
    return meta_medicion(carpeta)[canal]["xinc"]


def n_pre_muestras(carpeta: str, canal: str, guarda_us: float = 1.0) -> int:
    """Número de muestras en el pre-disparo (línea base antes del impulso).

    Calcula cuántas muestras corresponden a t < -guarda_us respecto al inicio.
    """
    m = meta_medicion(carpeta)[canal]
    dt_us = m["xinc"] * 1e6
    t_cero_idx = int(round(-m["xorg"] / m["xinc"]))
    muestras_guarda = int(round(guarda_us / dt_us))
    n_pre = t_cero_idx - muestras_guarda
    return max(100, min(n_pre, 10000))


def _cargar_segmento_leer(carpeta: str, canal: str, seg: int, ventana: tuple[float, float] | None = VENTANA_T10):
    m = meta_medicion(carpeta)[canal]
    with h5py.File(_ruta(carpeta, canal), "r") as f:
        dset = f[f"Waveforms/{m['chan']}/{m['chan']} Seg{seg}Data"]
        n = dset.shape[0]
        if ventana is None:
            i0, i1 = 0, n
        else:
            i0 = int(np.ceil((ventana[0] * 1e-6 - m["xorg"]) / m["xinc"]))
            i1 = int(np.floor((ventana[1] * 1e-6 - m["xorg"]) / m["xinc"])) + 1
            i0, i1 = max(i0, 0), min(i1, n)
            if i1 <= i0:
                return np.array([]), np.array([])
        raw = dset[i0:i1]
    v = (raw.astype(np.float64) * m["yinc"] + m["yorg"]) * 1e3  # milivoltios
    t = (m["xorg"] + np.arange(i0, i1) * m["xinc"]) * 1e6      # microsegundos
    return t, v


@functools.lru_cache(maxsize=6)
def _cargar_segmento_cache(carpeta: str, canal: str, seg: int, ventana: tuple[float, float] | None):
    t, v = _cargar_segmento_leer(carpeta, canal, seg, ventana)
    t.flags.writeable = False
    v.flags.writeable = False
    return t, v


def cargar_segmento(carpeta: str, canal: str, seg: int, ventana: tuple[float, float] | None = VENTANA_T10) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (t_us, v_mv) para un canal y segmento recortado a la ventana dada."""
    return _cargar_segmento_cache(carpeta, canal, seg, tuple(ventana) if ventana is not None else None)


def _dir_medicion(carpeta: str) -> str | None:
    if not carpeta:
        return None
    r = _ruta(carpeta, "ch1") or _ruta(carpeta, "ch2") or _ruta(carpeta, "ch3") or _ruta(carpeta, "ch4")
    return os.path.dirname(r) if r else None


def obtener_metadata(carpeta: str) -> dict:
    d = _dir_medicion(carpeta)
    if not d:
        return {}
    meta_path = os.path.join(d, "metadata.yaml")
    if not os.path.isfile(meta_path):
        return {}
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def guardar_metadata_archivo(carpeta: str, contenido_yaml_str: str) -> tuple[bool, str]:
    d = _dir_medicion(carpeta)
    if not d:
        return False, "No se encontró el directorio de la medición"
    meta_path = os.path.join(d, "metadata.yaml")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(contenido_yaml_str)
        return True, f"Guardado exitoso en {os.path.basename(meta_path)}"
    except Exception as e:
        return False, f"Error al guardar: {e}"


def umbral_defecto(carpeta: str, canal: str = "ch4", seg: int = 1) -> float:
    if canal not in canales_presentes(carpeta):
        return 0.0
    _, v = cargar_segmento(carpeta, canal, seg, ventana=VENTANA_T10)
    return 0.5 * float(np.max(np.abs(v))) if v.size else 0.0


def _muestras(carpeta: str, canal: str, dist_us: float | None) -> int | None:
    if dist_us is None:
        return None
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
    return max(1, int(round(dist_us / dt_us)))
