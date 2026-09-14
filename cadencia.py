"""
Cadencia de adquisición de las mediciones (1 min vs 30 s).

Lee el atributo `SegmentedTimeTag` [s] de cada segmento (relativo al segmento 1)
en los ch*.h5 de cada medición, calcula los intervalos entre descargas (dt) y
clasifica la medición por la mediana de dt:
  cada_1min -> mediana a ±TOL_S de 60 s
  cada_30s  -> mediana a ±TOL_S de 30 s
  otros     -> cualquier otra cadencia
Un dt que se aparta más de TOL_S del nominal de su clase se marca como anómalo.
Genera `archivos_md/reporte_cadencia.md` y `cadencia_segmentos.csv` junto a
este script.

Ejecutar:
  python3 cadencia.py           # simulacro: reporte + qué se movería
  python3 cadencia.py --mover   # además mueve a Mediciones/<clase>/<medición>/
"""
import csv
import os
import re
import shutil
import sys
from datetime import datetime

import h5py
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
MEDICIONES = os.path.abspath(os.path.join(AQUI, os.pardir, "mediciones", "Mediciones"))
CANALES = ["ch1", "ch2", "ch3", "ch4"]

CLASES = {"cada_1min": 60.0, "cada_30s": 30.0}  # clase -> dt nominal [s]
OTROS = "otros"
TOL_S = 2.0

REPORTE_MD = os.path.join(AQUI, "archivos_md", "reporte_cadencia.md")
REPORTE_CSV = os.path.join(AQUI, "cadencia_segmentos.csv")


_CHAN_RE = re.compile(r"^(.*?)(ch[1-4])(.*?)\.h5$", re.IGNORECASE)


def _orden_natural(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def _ruta(carpeta, canal):
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

    # 2. Si carpeta es un directorio existente (ej. Mediciones/otros/4)
    dir_directo = os.path.join(MEDICIONES, carpeta)
    if os.path.isdir(dir_directo):
        for f in os.listdir(dir_directo):
            m = _CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                return os.path.join(dir_directo, f)
        return None

    # 3. Si carpeta es de la forma 'categoria/stem' (ej. 'otros/1v2-30s')
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


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe para la medición dada, en orden."""
    return [c for c in CANALES if _ruta(carpeta, c) is not None and os.path.isfile(_ruta(carpeta, c))]


def listar_mediciones():
    """Rutas relativas a MEDICIONES de las mediciones encontradas."""
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


def marcas_temporales(ruta_h5):
    """SegmentedTimeTag [s] de cada segmento, ordenado por nº de segmento.
    Solo lee atributos (no carga las señales)."""
    with h5py.File(ruta_h5, "r") as f:
        g = f["Waveforms/" + list(f["Waveforms"].keys())[0]]
        marcas = {}
        for k in g.keys():
            m = re.search(r"Seg(\d+)Data$", k)
            if m:
                marcas[int(m.group(1))] = float(g[k].attrs["SegmentedTimeTag"])
    return np.array([marcas[k] for k in sorted(marcas)])


def clasificar(mediana):
    for clase, nominal in CLASES.items():
        if abs(mediana - nominal) <= TOL_S:
            return clase, nominal
    return OTROS, None


def diagnosticar(carpeta):
    canales = canales_presentes(carpeta)
    marcas = {c: marcas_temporales(_ruta(carpeta, c)) for c in canales}
    ref = marcas[canales[0]]
    coinciden = all(m.shape == ref.shape and np.allclose(m, ref) for m in marcas.values())
    dt = np.diff(ref)
    mediana = float(np.median(dt)) if dt.size else float("nan")
    clase, nominal = clasificar(mediana)
    anomalos = [] if nominal is None else [i for i, d in enumerate(dt) if abs(d - nominal) > TOL_S]
    return {
        "medicion": os.path.basename(carpeta),
        "ubicacion": carpeta,
        "canales": canales,
        "marcas": ref,
        "dt": dt,
        "mediana": mediana,
        "clase": clase,
        "anomalos": anomalos,  # índices i de dt: salto Seg(i+1) -> Seg(i+2)
        "coinciden": coinciden,
    }


def mover(d, ejecutar):
    """Mueve la medición a MEDICIONES/<clase>/<medición>/. Devuelve un mensaje."""
    destino_rel = f"{d['clase']}/{d['medicion']}"
    if d["ubicacion"] == destino_rel:
        return f"  {d['ubicacion']}: ya esta en su carpeta"
    destino = os.path.join(MEDICIONES, d["clase"], d["medicion"])
    if os.path.exists(destino):
        return f"  {d['ubicacion']}: el destino {destino_rel} ya existe, NO se mueve"
    if not ejecutar:
        return f"  {d['ubicacion']} -> {destino_rel} (simulacro)"
    os.makedirs(destino, exist_ok=True)
    origen_dir = os.path.join(MEDICIONES, d["ubicacion"])
    if os.path.isdir(origen_dir):
        shutil.move(origen_dir, destino)
    else:
        for c in d["canales"]:
            src = _ruta(d["ubicacion"], c)
            if src and os.path.isfile(src):
                shutil.move(src, os.path.join(destino, f"{c}.h5"))
    origen = d["ubicacion"]
    d["ubicacion"] = destino_rel
    return f"  {origen} -> {destino_rel} (movido)"


def _f(x):
    return "" if x is None or np.isnan(x) else f"{x:.2f}"


def escribir_csv(diags):
    with open(REPORTE_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["medicion", "segmento", "time_tag_s", "dt_s", "anomalo", "clase"])
        for d in diags:
            for k, tag in enumerate(d["marcas"]):
                dt = d["dt"][k - 1] if k else None
                anomalo = k and (k - 1) in d["anomalos"]
                w.writerow([d["medicion"], k + 1, f"{tag:.4f}",
                            "" if dt is None else f"{dt:.4f}", int(bool(anomalo)), d["clase"]])


def escribir_md(diags):
    L = [
        "# Reporte de cadencia de adquisición",
        "",
        f"Generado por `cadencia.py` el {datetime.now():%Y-%m-%d %H:%M}.",
        "",
        "- **Fuente:** atributo `SegmentedTimeTag` [s] de cada segmento "
        "(`Waveforms/Channel N/Channel N SegKData`), relativo al segmento 1. "
        "`Frame/TheFrame.Date` es la hora de guardado del archivo, no de adquisición.",
        f"- **Criterio:** mediana de Δt a ±{TOL_S:g} s de 60 s → `cada_1min`; "
        f"de 30 s → `cada_30s`; si no → `otros`.",
        f"- **Anómalo:** Δt que se aparta más de {TOL_S:g} s del nominal de su clase.",
        "",
        "## Resumen",
        "",
        "| Medición | Ubicación | Canales | Segmentos | Duración [s] | Δt mediana [s] "
        "| Δt mín [s] | Δt máx [s] | Clase |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for d in diags:
        dt = d["dt"]
        L.append(
            f"| {d['medicion']} | `{d['ubicacion']}` | {', '.join(d['canales'])} "
            f"| {d['marcas'].size} | {_f(d['marcas'][-1])} | {_f(d['mediana'])} "
            f"| {_f(dt.min()) if dt.size else ''} | {_f(dt.max()) if dt.size else ''} "
            f"| **{d['clase']}** |"
        )
    L += ["", "## Conteo por clase", ""]
    for clase in [*CLASES, OTROS]:
        meds = [d["medicion"] for d in diags if d["clase"] == clase]
        L.append(f"- `{clase}`: {len(meds)}" + (f" ({', '.join(meds)})" if meds else ""))

    L += ["", "## Anomalías", ""]
    hay = False
    for d in diags:
        for i in d["anomalos"]:
            hay = True
            L.append(f"- Medición {d['medicion']} (`{d['clase']}`): "
                     f"Seg{i + 1} → Seg{i + 2}, Δt = {d['dt'][i]:.2f} s")
        if d["clase"] == OTROS:
            hay = True
            L.append(f"- Medición {d['medicion']}: cadencia no reconocida "
                     f"(mediana {_f(d['mediana'])} s).")
        if not d["coinciden"]:
            hay = True
            L.append(f"- Medición {d['medicion']}: las marcas temporales NO coinciden entre canales.")
    if not hay:
        L.append("Ninguna.")

    L += ["", "## Δt por medición [s]", ""]
    for d in diags:
        L.append(f"- **{d['medicion']}:** " + ", ".join(f"{x:.2f}" for x in d["dt"]))
    L.append("")
    with open(REPORTE_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def main():
    ejecutar = "--mover" in sys.argv[1:]
    diags = [diagnosticar(c) for c in listar_mediciones()]
    diags.sort(key=lambda d: _orden_natural(d["medicion"]))

    print(f"{'medicion':<10}{'segs':>5}{'dt mediana':>12}  clase")
    for d in diags:
        print(f"{d['medicion']:<10}{d['marcas'].size:>5}{_f(d['mediana']):>12}  {d['clase']}")

    print("\nMover:" if ejecutar else "\nSimulacro (usa --mover para mover):")
    for d in diags:
        print(mover(d, ejecutar))

    escribir_csv(diags)
    escribir_md(diags)
    print("\nReporte:", REPORTE_MD)
    print("CSV:    ", REPORTE_CSV)


if __name__ == "__main__":
    main()
