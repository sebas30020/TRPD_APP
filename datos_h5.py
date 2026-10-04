"""Capa de lectura de mediciones (.h5 Keysight) común a app.py y calibrar_app.

Objetivo: que cada acción del usuario toque el disco (Google Drive) lo mínimo.
- Rutas de canal y canales presentes cacheados (rutas.py hace varios stat por llamada).
- Un handle h5py.File de solo lectura por archivo, reutilizado (abrir un .h5 en
  Drive cuesta ~200 ms; antes se abría uno por cada segmento leído).
- Eje temporal de cada ventana calculado una vez por canal; la LRU de segmentos
  guarda solo las tensiones.
- calcular_una_vez: si varios callbacks piden el mismo cálculo a la vez (servidor
  con hilos), solo el primero lo ejecuta y el resto espera su resultado.
- cacheado_por_archivo: resultados que dependen de un archivo (metadata.yaml) se
  recalculan solo si cambia su fecha de modificación, revisada como mucho cada
  INTERVALO_STAT_S segundos.

Si un .h5 se reemplaza en disco con la app abierta, llamar a limpiar_caches()
(el explorador de carpetas lo hace al confirmar una carpeta).
"""

import atexit
import functools
import os
import threading
import time
from collections import OrderedDict

import h5py
import numpy as np

import filtros
import rutas

CANALES = rutas.CANALES
SEGMENTOS_EN_CACHE = 128          # ~2.8 MB por segmento (-5..30 µs a 10 GSa/s)
INTERVALO_STAT_S = 2.0


# ---------------- Rutas ----------------

@functools.lru_cache(maxsize=1024)
def ruta_canal(carpeta, canal):
    """Ruta absoluta al .h5 del canal (cacheada), o None."""
    return rutas.ruta_canal(carpeta, canal)


@functools.lru_cache(maxsize=512)
def _canales(carpeta):
    return tuple(c for c in CANALES if ruta_canal(carpeta, c))


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe para la medición, en orden."""
    return list(_canales(carpeta))


@functools.lru_cache(maxsize=512)
def dir_medicion(carpeta):
    """Directorio físico de la medición (cacheado)."""
    for c in _canales(carpeta):
        return os.path.dirname(ruta_canal(carpeta, c))
    return rutas.dir_medicion(carpeta)


# ---------------- Archivos abiertos ----------------

_ARCHIVOS = {}
_LOCK_ARCHIVOS = threading.Lock()


def archivo(ruta):
    """h5py.File de solo lectura reutilizado para `ruta`."""
    with _LOCK_ARCHIVOS:
        f = _ARCHIVOS.get(ruta)
        if f is None or not f.id.valid:
            f = h5py.File(ruta, "r")
            _ARCHIVOS[ruta] = f
        return f


def cerrar_archivos():
    with _LOCK_ARCHIVOS:
        for f in _ARCHIVOS.values():
            try:
                f.close()
            except Exception:
                pass
        _ARCHIVOS.clear()


atexit.register(cerrar_archivos)


# ---------------- Metadatos de la adquisición ----------------

_META = {}


def _meta(carpeta, canal):
    f = archivo(ruta_canal(carpeta, canal))
    chan = list(f["Waveforms"].keys())[0]
    g = f["Waveforms/" + chan]
    npts = g.attrs.get("NumPoints")
    if npts is None:
        npts = g[f"{chan} Seg1Data"].shape[0]
    return {
        "chan": chan,
        "yinc": float(g.attrs["YInc"]),
        "yorg": float(g.attrs["YOrg"]),
        "xinc": float(g.attrs["XInc"]),
        "xorg": float(g.attrs["XOrg"]),
        "nsegs": int(g.attrs["NumSegments"]),
        "npts": int(npts),
    }


def meta_medicion(carpeta):
    """{canal: meta} para los canales presentes, cacheado."""
    if carpeta not in _META:
        _META[carpeta] = {c: _meta(carpeta, c) for c in _canales(carpeta)}
    return _META[carpeta]


def n_segmentos(carpeta):
    metas = meta_medicion(carpeta)
    return min(m["nsegs"] for m in metas.values()) if metas else 0


def _indices(m, n, ventana):
    """(i0, i1) de la ventana en µs; mismos índices que la máscara (t >= v0) & (t <= v1)."""
    if ventana is None:
        return 0, n
    i0 = int(np.ceil((ventana[0] * 1e-6 - m["xorg"]) / m["xinc"]))
    i1 = int(np.floor((ventana[1] * 1e-6 - m["xorg"]) / m["xinc"])) + 1
    return max(i0, 0), min(i1, n)


@functools.lru_cache(maxsize=64)
def eje_t(carpeta, canal, ventana):
    """Eje temporal (µs, solo lectura) de la ventana: igual para todos los segmentos."""
    m = meta_medicion(carpeta)[canal]
    i0, i1 = _indices(m, m["npts"], ventana)
    if i1 <= i0:
        t = np.array([])
    else:
        t = (m["xorg"] + np.arange(i0, i1) * m["xinc"]) * 1e6
    t.flags.writeable = False
    return t


def leer_crudo(carpeta, canal, seg, ventana, spec=None):
    """(t_us, v_mV) leídos del disco, sin caché. Con `spec` (filtros.py) se lee la
    ventana ampliada filtros.MARGEN_US a cada lado, se filtra y se recorta, de modo
    que el resultado no depende de los bordes de la ventana."""
    m = meta_medicion(carpeta)[canal]
    f = archivo(ruta_canal(carpeta, canal))
    dset = f[f"Waveforms/{m['chan']}/{m['chan']} Seg{seg}Data"]
    n = dset.shape[0]
    i0, i1 = _indices(m, n, ventana)
    if i1 <= i0:
        return np.array([]), np.array([])
    if spec is None:
        a0, a1 = i0, i1
    else:
        margen = int(round(filtros.MARGEN_US * 1e-6 / m["xinc"]))
        a0, a1 = max(i0 - margen, 0), min(i1 + margen, n)
    raw = dset[a0:a1]
    v = (raw.astype(np.float64) * m["yinc"] + m["yorg"]) * 1e3  # milivoltios
    if spec is not None:
        v = filtros.aplicar(v, 1.0 / m["xinc"], spec)[i0 - a0:i1 - a0]
    t = (m["xorg"] + np.arange(i0, i1) * m["xinc"]) * 1e6       # microsegundos
    return t, v


@functools.lru_cache(maxsize=SEGMENTOS_EN_CACHE)
def _tension(carpeta, canal, seg, ventana, spec):
    t, v = leer_crudo(carpeta, canal, seg, ventana, spec)
    v.flags.writeable = False   # evita que un consumidor mute la copia cacheada
    return v, t.size


def cargar(carpeta, canal, seg, ventana, spec=None):
    """(t_us, v_mV) del segmento recortado a `ventana` (tupla o None), cacheado."""
    ventana = tuple(ventana) if ventana is not None else None
    v, n = _tension(carpeta, canal, seg, ventana, spec)
    t = eje_t(carpeta, canal, ventana)
    if t.size != n:          # segmento con distinta longitud que NumPoints
        t, v = leer_crudo(carpeta, canal, seg, ventana, spec)
    return t, v


def limpiar_caches():
    """Olvida rutas, metadatos, ejes y segmentos cacheados y cierra los archivos."""
    ruta_canal.cache_clear()
    _canales.cache_clear()
    dir_medicion.cache_clear()
    eje_t.cache_clear()
    _tension.cache_clear()
    _META.clear()
    cerrar_archivos()


# ---------------- Cálculo único y cachés acotadas ----------------

_LOCKS = {}
_LOCK_LOCKS = threading.Lock()


def calcular_una_vez(cache, clave, fn, maxsize=None):
    """Devuelve cache[clave]; si no existe, ejecuta fn() UNA sola vez aunque
    varios hilos lo pidan a la vez (los demás esperan el resultado). Si `cache`
    es un OrderedDict y se da `maxsize`, se comporta como LRU acotada."""
    if clave in cache:
        if maxsize and isinstance(cache, OrderedDict):
            try:
                cache.move_to_end(clave)
            except KeyError:
                pass
        try:
            return cache[clave]
        except KeyError:
            pass
    k = (id(cache), clave)
    with _LOCK_LOCKS:
        lock = _LOCKS.setdefault(k, threading.Lock())
    with lock:
        if clave in cache:
            return cache[clave]
        valor = fn()
        cache[clave] = valor
        if maxsize and isinstance(cache, OrderedDict):
            while len(cache) > maxsize:
                cache.popitem(last=False)
    with _LOCK_LOCKS:
        _LOCKS.pop(k, None)
    return valor


# ---------------- Resultados que dependen de un archivo ----------------

_POR_ARCHIVO = {}
_LOCK_POR_ARCHIVO = threading.Lock()


def _mtime(ruta):
    try:
        return os.path.getmtime(ruta)
    except OSError:
        return None


def cacheado_por_archivo(ruta, clave, cargar_fn):
    """Resultado de cargar_fn() cacheado mientras no cambie la fecha de
    modificación de `ruta` (o su existencia). El stat se hace como mucho cada
    INTERVALO_STAT_S s. El resultado es compartido: no mutarlo."""
    k = (ruta, clave)
    ahora = time.monotonic()
    e = _POR_ARCHIVO.get(k)
    if e is not None and ahora - e["chk"] < INTERVALO_STAT_S:
        return e["valor"]
    mt = _mtime(ruta)
    if e is not None and e["mtime"] == mt:
        e["chk"] = ahora
        return e["valor"]
    with _LOCK_POR_ARCHIVO:
        valor = cargar_fn()
        _POR_ARCHIVO[k] = {"mtime": mt, "chk": ahora, "valor": valor}
    return valor


def invalidar_archivo(ruta):
    """Fuerza a recalcular todo lo cacheado sobre `ruta` (tras escribirla)."""
    with _LOCK_POR_ARCHIVO:
        for k in [k for k in _POR_ARCHIVO if k[0] == ruta]:
            del _POR_ARCHIVO[k]
