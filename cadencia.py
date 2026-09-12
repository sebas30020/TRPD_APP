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


def _orden_natural(s):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", s)]


def canales_presentes(ruta):
    return [c for c in CANALES if os.path.exists(os.path.join(ruta, f"{c}.h5"))]


def listar_mediciones():
    """Rutas relativas a MEDICIONES ("7" o "cada_30s/7") de las carpetas con
    algún ch*.h5, directas o un nivel más abajo."""
    encontradas = []
    for nombre in sorted(os.listdir(MEDICIONES), key=_orden_natural):
        ruta = os.path.join(MEDICIONES, nombre)
        if not os.path.isdir(ruta):
            continue
        if canales_presentes(ruta):
            encontradas.append(nombre)
            continue
        for sub in sorted(os.listdir(ruta), key=_orden_natural):
            if os.path.isdir(os.path.join(ruta, sub)) and canales_presentes(os.path.join(ruta, sub)):
                encontradas.append(f"{nombre}/{sub}")
    return encontradas


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
    ruta = os.path.join(MEDICIONES, carpeta)
    canales = canales_presentes(ruta)
    marcas = {c: marcas_temporales(os.path.join(ruta, f"{c}.h5")) for c in canales}
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
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(os.path.join(MEDICIONES, d["ubicacion"]), destino)
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
