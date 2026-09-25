"""
Reporte por lotes de la cadencia de adquisición (1 min vs 30 s) y reorganización
opcional de carpetas.

La lógica de cadencia (SegmentedTimeTag, clasificación, anomalías) vive en
generate_metadata.py, que además la escribe en la sección 'cadencia' de cada
metadata.yaml. Este script solo la reutiliza para:
  - generar `archivos_md/reporte_cadencia.md` y `cadencia_segmentos.csv`;
  - mover cada medición a <raiz>/<clase>/<medición>/ (con --mover).

Ejecutar (<raiz>: carpeta que contiene las mediciones, se recorre recursivamente):
  python3 cadencia.py <raiz>           # simulacro: reporte + qué se movería
  python3 cadencia.py <raiz> --mover   # además mueve a <raiz>/<clase>/<medición>/
"""
import csv
import os
import shutil
import sys
from datetime import datetime

import numpy as np

import generate_metadata as gm
import rutas

AQUI = os.path.dirname(os.path.abspath(__file__))

CLASES = gm.CLASES_CADENCIA
OTROS = gm.CADENCIA_OTROS
TOL_S = gm.TOL_CADENCIA_S

REPORTE_MD = os.path.join(AQUI, "archivos_md", "reporte_cadencia.md")
REPORTE_CSV = os.path.join(AQUI, "cadencia_segmentos.csv")

_orden_natural = rutas.orden_natural
_ruta = rutas.ruta_canal


def listar_mediciones(raiz):
    """Rutas absolutas de las mediciones encontradas bajo `raiz` (recursivo)."""
    if not os.path.isdir(raiz):
        return []
    mediciones = []
    for root, dirs, files in os.walk(raiz):
        mediciones.extend(rutas.mediciones_en(root))
    return sorted(mediciones, key=_orden_natural)


def diagnosticar(carpeta, raiz):
    marcas = gm.extraer_info_h5(carpeta)["marcas"]
    cad = gm.analizar_cadencia(marcas) or {}
    canales = [c for c in rutas.CANALES if marcas.get(c)]
    ref = np.asarray(marcas[canales[0]], dtype=float) if canales else np.array([])
    return {
        "medicion": os.path.basename(carpeta),
        "ubicacion": os.path.relpath(carpeta, raiz).replace("\\", "/"),
        "ruta": carpeta,
        "canales": canales,
        "marcas": ref,
        "dt": np.diff(ref),
        "mediana": cad.get("dt_mediana_s", float("nan")),
        "clase": cad.get("clase") or OTROS,
        # índices i de dt: salto Seg(i+1) -> Seg(i+2)
        "anomalos": [a["desde_seg"] - 1 for a in cad.get("anomalias", [])],
        "coinciden": cad.get("marcas_coinciden_entre_canales", True),
    }


def mover(d, ejecutar, raiz):
    """Mueve la medición a <raiz>/<clase>/<medición>/. Devuelve un mensaje."""
    destino_rel = f"{d['clase']}/{d['medicion']}"
    if d["ubicacion"] == destino_rel:
        return f"  {d['ubicacion']}: ya esta en su carpeta"
    destino = os.path.join(raiz, d["clase"], d["medicion"])
    if os.path.exists(destino):
        return f"  {d['ubicacion']}: el destino {destino_rel} ya existe, NO se mueve"
    if not ejecutar:
        return f"  {d['ubicacion']} -> {destino_rel} (simulacro)"
    os.makedirs(destino, exist_ok=True)
    origen_dir = d["ruta"]
    if os.path.isdir(origen_dir):
        shutil.move(origen_dir, destino)
    else:
        for c in d["canales"]:
            src = _ruta(d["ruta"], c)
            if src and os.path.isfile(src):
                shutil.move(src, os.path.join(destino, f"{c}.h5"))
    origen = d["ubicacion"]
    d["ubicacion"] = destino_rel
    d["ruta"] = destino
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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Uso: python cadencia.py <carpeta_raiz_mediciones> [--mover]")
        sys.exit(1)
    raiz = os.path.abspath(args[0])
    ejecutar = "--mover" in sys.argv[1:]
    diags = [diagnosticar(c, raiz) for c in listar_mediciones(raiz)]
    diags.sort(key=lambda d: _orden_natural(d["medicion"]))

    print(f"{'medicion':<10}{'segs':>5}{'dt mediana':>12}  clase")
    for d in diags:
        print(f"{d['medicion']:<10}{d['marcas'].size:>5}{_f(d['mediana']):>12}  {d['clase']}")

    print("\nMover:" if ejecutar else "\nSimulacro (usa --mover para mover):")
    for d in diags:
        print(mover(d, ejecutar, raiz))

    escribir_csv(diags)
    escribir_md(diags)
    print("\nReporte:", REPORTE_MD)
    print("CSV:    ", REPORTE_CSV)


if __name__ == "__main__":
    main()
