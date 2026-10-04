"""Módulo de acceso a datos HDF5 y metadata para calibrar_app.

Autónomo respecto a app.py. Mantiene bit-compatibilidad con app.py en ventana (-5, 30)
y permite leer registros completos (ventana=None) para IEC 60060-1.
"""

from __future__ import annotations
import copy
import functools
import os
import re
import sys
import h5py
import numpy as np
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ_REPO = os.path.abspath(os.path.join(AQUI, os.pardir))
if RAIZ_REPO not in sys.path:
    sys.path.insert(0, RAIZ_REPO)

import datos_h5  # noqa: E402  (lectura de .h5 y cachés, compartida con app.py)
import filtros  # noqa: E402  (filtros digitales por canal, compartidos con app.py)
import rutas  # noqa: E402  (resolución de rutas compartida con app.py)

# No hay carpeta de datos fija: las mediciones se eligen con el explorador de
# carpetas y se identifican por su ruta absoluta (ver rutas.py).

CANALES = ["ch1", "ch2", "ch3", "ch4"]
TRIGGERS = ["ch2", "ch3", "ch4"]

VENTANA_T10 = (-5.0, 30.0)  # idéntica a app.T_MIN / T_MAX
VENTANA_IEC = None          # registro completo para ajuste de cola IEC

_CHAN_RE = rutas.CHAN_RE
_orden_natural = rutas.orden_natural


def _ruta(carpeta: str, canal: str) -> str | None:
    """Resuelve la ruta absoluta al archivo .h5 del canal (cacheado)."""
    return datos_h5.ruta_canal(carpeta, canal)


def canales_presentes(carpeta: str) -> list[str]:
    """Canales (ch1..ch4) cuyo archivo existe para la medición dada, en orden (cacheado)."""
    return datos_h5.canales_presentes(carpeta)


def listar_subcarpetas(ruta: str) -> list[tuple[str, str, bool]]:
    """(nombre, ruta_absoluta, tiene_h5) de las subcarpetas directas de `ruta`."""
    return rutas.listar_subcarpetas(ruta)


def meta_medicion(carpeta: str) -> dict[str, dict]:
    """Devuelve {canal: meta} cacheado (datos_h5)."""
    return datos_h5.meta_medicion(carpeta)


def n_segmentos(carpeta: str) -> int:
    return datos_h5.n_segmentos(carpeta)


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


def _cargar_segmento_leer(carpeta: str, canal: str, seg: int, ventana: tuple[float, float] | None = VENTANA_T10,
                          spec: tuple | None = None):
    """Igual que app._cargar_segmento_leer (lectura sin caché, datos_h5.leer_crudo)."""
    return datos_h5.leer_crudo(carpeta, canal, seg, ventana, spec)


def spec_filtro(carpeta: str, canal: str) -> tuple | None:
    """Filtro digital del canal según metadata.yaml (o el de defecto). CH1 -> None.
    Usa la metadata cacheada (se relee si el YAML cambia; stat como mucho cada 2 s)."""
    return filtros.filtro_canal(_metadata_compartida(carpeta), canal)


def cargar_segmento(carpeta: str, canal: str, seg: int, ventana: tuple[float, float] | None = VENTANA_T10,
                    filtrado: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (t_us, v_mv) para un canal y segmento recortado a la ventana dada.
    CH2..CH4 se filtran según metadata (filtros.py); CH1 nunca. Cacheado en datos_h5,
    compartido con todos los bucles por segmento (antes una LRU de 6 entradas)."""
    spec = spec_filtro(carpeta, canal) if filtrado and canal != "ch1" else None
    return datos_h5.cargar(carpeta, canal, seg, tuple(ventana) if ventana is not None else None, spec)


def _dir_medicion(carpeta: str) -> str | None:
    return datos_h5.dir_medicion(carpeta)


def _metadata_compartida(carpeta: str) -> dict:
    """metadata.yaml cacheado mientras no cambie (objeto compartido: no mutar)."""
    d = _dir_medicion(carpeta)
    if not d:
        return {}
    meta_path = os.path.join(d, "metadata.yaml")
    return datos_h5.cacheado_por_archivo(meta_path, ("calibrar", carpeta),
                                         lambda: _leer_metadata(meta_path))


def obtener_metadata(carpeta: str) -> dict:
    """Copia modificable de metadata.yaml ({} si no existe)."""
    return copy.deepcopy(_metadata_compartida(carpeta))


def _leer_metadata(meta_path: str) -> dict:
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
        datos_h5.invalidar_archivo(meta_path)
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
