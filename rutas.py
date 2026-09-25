"""Resolución de rutas de mediciones y navegación del explorador de carpetas.

No existe una carpeta de datos fija: cada medición se identifica por su ruta
ABSOLUTA en disco, elegida con el explorador de la GUI (o pasada por línea de
comandos a los scripts). Compartido por app.py, calibrar_app, cadencia.py y
generate_metadata.py.

Valores válidos de `carpeta` (medición):
  - Directorio con ch1..ch4.h5 (o con archivos '<pref>chN<suf>.h5').
  - '<directorio>/<stem>' cuando un directorio agrupa varias mediciones con
    archivos '<pref>chN<suf>.h5' (stem = pref + suf).
  - Ruta a uno de los archivos '*chN*.h5' de la medición.
"""
import os
import re
import string

# Pseudo-ruta del explorador que lista las unidades del equipo (C:\, G:\, ...).
EQUIPO = "::equipo::"
CANALES = ["ch1", "ch2", "ch3", "ch4"]
CHAN_RE = re.compile(r"^(.*?)(ch[1-4])(.*?)\.h5$", re.IGNORECASE)


def orden_natural(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", str(s))]


def ruta_inicial():
    """Carpeta donde abre el explorador: la que contiene el repositorio."""
    repo = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.dirname(repo)
    return cand if os.path.isdir(cand) else os.path.expanduser("~")


def unidades():
    """Raíces navegables del equipo."""
    if os.name == "nt":
        return [f"{l}:\\" for l in string.ascii_uppercase if os.path.isdir(f"{l}:\\")]
    return ["/"]


def padre(ruta):
    """Carpeta superior; desde la raíz de una unidad sube al listado de unidades."""
    if not ruta or ruta == EQUIPO:
        return EQUIPO
    r = os.path.normpath(ruta)
    p = os.path.dirname(r)
    if p == r:
        return EQUIPO if os.name == "nt" else r
    return p


def tiene_h5(ruta):
    """True si `ruta` contiene directamente algún archivo '*chN*.h5'."""
    try:
        return any(CHAN_RE.match(f) and os.path.isfile(os.path.join(ruta, f))
                   for f in os.listdir(ruta))
    except Exception:
        return False


def listar_subcarpetas(ruta):
    """(nombre, ruta_absoluta, tiene_h5) de las subcarpetas directas de `ruta`.
    Con ruta == EQUIPO devuelve las unidades del equipo."""
    if ruta == EQUIPO:
        return [(u, u, False) for u in unidades()]
    if not ruta or not os.path.isdir(ruta):
        return []
    try:
        nombres = sorted(os.listdir(ruta), key=orden_natural)
    except Exception:
        return []
    items = []
    for nombre in nombres:
        if nombre.startswith((".", "$")) or nombre == "System Volume Information":
            continue
        p = os.path.join(ruta, nombre)
        if os.path.isdir(p):
            items.append((nombre, p, tiene_h5(p)))
    return items


def mediciones_en(ruta):
    """Valores de `carpeta` para las mediciones contenidas directamente en `ruta`:
    la propia carpeta si sus archivos son chN.h5 (o un único grupo), o
    '<ruta>/<stem>' por cada grupo '<pref>chN<suf>.h5' si hay varios."""
    if not ruta or not os.path.isdir(ruta):
        return []
    grupos = set()
    try:
        for f in os.listdir(ruta):
            m = CHAN_RE.match(f)
            if m and os.path.isfile(os.path.join(ruta, f)):
                grupos.add((m.group(1), m.group(3)))
    except Exception:
        return []
    if not grupos:
        return []
    if len(grupos) == 1 or ("", "") in grupos:
        return [ruta]
    return sorted((os.path.join(ruta, f"{p}{s}") for p, s in grupos), key=orden_natural)


def ruta_canal(carpeta, canal):
    """Ruta absoluta al .h5 del canal de la medición `carpeta`, o None."""
    if not carpeta or carpeta == EQUIPO:
        return None
    canal = canal.lower()
    carpeta = os.path.abspath(carpeta)

    # Ruta a uno de los archivos de la medición
    if os.path.isfile(carpeta):
        d, fname = os.path.split(carpeta)
        m = CHAN_RE.match(fname)
        if m:
            p = os.path.join(d, f"{m.group(1)}{canal}{m.group(3)}.h5")
            if os.path.isfile(p):
                return p
        return carpeta if canal in fname.lower() else None

    # Directorio de la medición
    if os.path.isdir(carpeta):
        p = os.path.join(carpeta, f"{canal}.h5")
        if os.path.isfile(p):
            return p
        try:
            nombres = sorted(os.listdir(carpeta), key=orden_natural)
        except Exception:
            return None
        for f in nombres:
            m = CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                return os.path.join(carpeta, f)
        return None

    # '<directorio>/<stem>': archivos '<pref>chN<suf>.h5' agrupados en el directorio
    parent, stem = os.path.split(carpeta)
    if os.path.isdir(parent):
        stem_clean = re.sub(r"\.h5$", "", stem, flags=re.IGNORECASE)
        stem_clean = re.sub(r"ch[1-4]", "", stem_clean, flags=re.IGNORECASE)
        for f in sorted(os.listdir(parent), key=orden_natural):
            m = CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                if f"{m.group(1)}{m.group(3)}" == stem_clean or stem_clean in f:
                    return os.path.join(parent, f)
    return None


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe para la medición, en orden."""
    return [c for c in CANALES if ruta_canal(carpeta, c)]


def dir_medicion(carpeta):
    """Directorio físico que contiene los archivos de la medición, o None."""
    if not carpeta or carpeta == EQUIPO:
        return None
    for c in CANALES:
        p = ruta_canal(carpeta, c)
        if p:
            return os.path.dirname(p)
    carpeta = os.path.abspath(carpeta)
    if os.path.isdir(carpeta):
        return carpeta
    parent = os.path.dirname(carpeta)
    return parent if os.path.isdir(parent) else None


def etiqueta(carpeta):
    """Texto corto para el selector: las dos últimas componentes de la ruta."""
    partes = os.path.normpath(carpeta).replace("\\", "/").rstrip("/").split("/")
    return "/".join(partes[-2:]) if len(partes) >= 2 else carpeta
