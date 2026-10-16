"""Informe TRPD básico (reporte 5) para la probeta 1v_4mm_1: por cada nivel de tensión,
el mapa TRPD conjunto (todos los sensores en un solo mapa) y su tabla de densidad de
eventos, precedidos de una tabla resumen de todas las mediciones. Cada descarga es la
pareja (V_pp, t_abs): V_pp es la tensión pico a pico en la ventana de 70 ns alrededor
del peak marcado (cap["vpp"] / 1000.0, en V).

Verifica además que los triggers guardados en metadata.yaml de cada nivel coincidan con
los definidos en mediciones/med_proced/1v_4mm_1/Libro1.xlsx (sin requerir openpyxl).

Se generan dos versiones del informe con los mismos mapas:
  informe_trpd_ncav.pdf       tabla sin las medias «todas» (distribución, N_PD = N_cav,
                              N̄_PD y medias sobre N_PD = N_cav)
  informe_trpd_completo.pdf   tabla con todas las columnas

Salidas en <salida> (por defecto reportes/reporte5):
  informe_trpd_ncav.pdf, informe_trpd_completo.pdf
  tabla_trpd.csv                 tabla de todas las mediciones (todas las columnas + trigger)
  vpp_vs_tension.png/.csv        V̄_pp ± σ por sensor vs tensión (fuera del informe)
  tabs_vs_tension.png/.csv       t̄_abs ± σ por sensor vs tensión (fuera del informe)
  vpp_cociente_tension.png/.csv  cociente de V̄_pp entre niveles consecutivos (fuera del informe)
  densidad_vs_tension.png/.csv   densidad de eventos (N_PD por disparo) por sensor vs tensión
  npd_media_vs_tension.png/.csv  N̄_PD ± σ por sensor vs tensión
  <probeta>/<X>kV/pagina_ncav.png, pagina_completo.png, tabla.csv

Uso:
    python generar_reporte5.py [--agregar <medición> ...] [--salida <dir>] [--xlsx <ruta>] [--sincronizar-xlsx]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
import numpy as np  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import app  # noqa: E402
import generar_reporte4 as g4  # noqa: E402
import reproducir_trpd  # noqa: E402
import rutas  # noqa: E402
import tema  # noqa: E402

PROYECTO = os.path.dirname(AQUI)
MED = os.path.join(PROYECTO, "mediciones", "med_proced")
PROBETA_DEFECTO = os.path.join(MED, "1v_4mm_1")
RUTA_XLSX_DEFECTO = os.path.join(PROBETA_DEFECTO, "Libro1.xlsx")
SALIDA_DEFECTO = os.path.join(PROYECTO, "reportes", "reporte5")
A4 = g4.A4

COLS_BASE = g4.COLS_BASE
COLS_DATOS = {
    "distribucion": ("N_PD distribution\n[0, 1, 2, 3, 4, > 4]", 0.18),
    "n_coinc": ("N_PD =\nN_cav", 0.08),
    "npd_media": ("N̄_PD\n(por disparo)", 0.08),
    "vpp_media": ("V̄_pp (V)\ntodas", 0.11),
    "tabs_media": ("t̄_abs (µs)\ntodas", 0.11),
    "vpp_media_cav": ("V̄_pp (V)\nN_PD = N_cav", 0.12),
    "tabs_media_cav": ("t̄_abs (µs)\nN_PD = N_cav", 0.12),
}
VERSIONES = {
    "ncav": ["distribucion", "n_coinc", "npd_media", "vpp_media_cav", "tabs_media_cav"],
    "completo": ["distribucion", "n_coinc", "npd_media", "vpp_media", "tabs_media",
                 "vpp_media_cav", "tabs_media_cav"],
}
COLS_CSV = [
    ("voltage", "Voltage (kV)"),
    ("sensor", "Sensor"),
    ("distribucion", "N_PD distribution [0, 1, 2, 3, 4, > 4]"),
    ("n_coinc", "N_PD = N_cav"),
    ("npd_media", "N̄_PD"),
    ("vpp_media", "V̄_pp (V)"),
    ("tabs_media", "t̄_abs (µs)"),
    ("vpp_media_cav", "V̄_pp | N_PD = N_cav (V)"),
    ("tabs_media_cav", "t̄_abs | N_PD = N_cav (µs)"),
]

NS_XLSX = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ---------------- Lectura y verificación de Libro1.xlsx ----------------

def leer_triggers_xlsx(ruta_xlsx: str = RUTA_XLSX_DEFECTO) -> dict[int, dict[str, dict[str, float]]]:
    """Lee la tabla de triggers por nivel (kV) y canal (ch2, ch3, ch4) desde Libro1.xlsx
    empleando únicamente la biblioteca estándar (zipfile + ElementTree)."""
    if not os.path.isfile(ruta_xlsx):
        raise FileNotFoundError(f"No existe el archivo Excel: {ruta_xlsx}")

    with zipfile.ZipFile(ruta_xlsx, "r") as z:
        strings: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root_ss = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root_ss.findall(f"{NS_XLSX}si"):
                partes = [t.text or "" for t in si.iter(f"{NS_XLSX}t")]
                strings.append("".join(partes))

        root = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        celdas_por_fila: dict[int, dict[str, str]] = {}
        for row in root.iter(f"{NS_XLSX}row"):
            r_idx = int(row.attrib.get("r", "0"))
            fila_dict: dict[str, str] = {}
            for c in row:
                ref = c.attrib.get("r", "")
                m = re.match(r"^([A-Z]+)\d+$", ref)
                if not m:
                    continue
                col = m.group(1)
                t_attr = c.attrib.get("t")
                v_el = c.find(f"{NS_XLSX}v")
                if v_el is None or v_el.text is None:
                    continue
                val = strings[int(v_el.text)] if t_attr == "s" else v_el.text
                fila_dict[col] = val.strip()
            if fila_dict:
                celdas_por_fila[r_idx] = fila_dict

    mapa_canales = {
        "ch2": ("D", "E", "F"),
        "ch3": ("G", "H", "I"),
        "ch4": ("J", "K", "L"),
    }
    triggers: dict[int, dict[str, dict[str, float]]] = {}
    for _, fila in sorted(celdas_por_fila.items()):
        c_val = fila.get("C", "")
        try:
            kv = int(float(c_val))
        except ValueError:
            continue
        cfgs_kv: dict[str, dict[str, float]] = {}
        for ch, (col_mv, col_dt, col_tm) in mapa_canales.items():
            if col_mv in fila and col_dt in fila and col_tm in fila:
                cfgs_kv[ch] = {
                    "umbral": float(fila[col_mv]),
                    "dist": float(fila[col_dt]),
                    "tmin": float(fila[col_tm]),
                }
        if cfgs_kv:
            triggers[kv] = cfgs_kv
    return triggers


def verificar_triggers_xlsx(carpeta_probeta: str = PROBETA_DEFECTO,
                            ruta_xlsx: str = RUTA_XLSX_DEFECTO,
                            actualizar: bool = False) -> list[str]:
    """Comprueba que cada nivel presente en Libro1.xlsx tenga el mismo trigger en su
    metadata.yaml. Si actualizar=True, sincroniza metadata.yaml preservando ediciones_peaks.
    Devuelve la lista de rutas relativas '<probeta>/<kv>kV'."""
    triggers = leer_triggers_xlsx(ruta_xlsx)
    probeta = os.path.basename(os.path.normpath(carpeta_probeta))
    relativas: list[str] = []
    for kv, cfgs_xlsx in sorted(triggers.items()):
        carpeta_kv = os.path.join(carpeta_probeta, f"{kv}kV")
        relativas.append(f"{probeta}/{kv}kV")
        if not os.path.isdir(carpeta_kv):
            print(f"Aviso: carpeta {carpeta_kv} no existe.")
            continue
        difiere = False
        for ch, esp in cfgs_xlsx.items():
            guard = reproducir_trpd.trigger_guardado(carpeta_kv, ch)
            if guard is None:
                difiere = True
                print(f"Aviso: {probeta}/{kv}kV {ch.upper()} sin trigger en metadata.yaml.")
                continue
            for k in ("umbral", "dist", "tmin"):
                if abs(float(guard[k]) - float(esp[k])) > 1e-6:
                    difiere = True
                    print(f"Discrepancia en {probeta}/{kv}kV {ch.upper()} {k}: "
                          f"metadata={guard[k]} vs xlsx={esp[k]}")
        if difiere and actualizar:
            ok, msg = app.guardar_trigger_canales(carpeta_kv, cfgs_xlsx, filtrado=True)
            print(f"Sincronizado {probeta}/{kv}kV desde Libro1.xlsx: {msg} (ok={ok})")
    return relativas


# ---------------- Estadística V_pp ----------------

def medias_vpp(carpeta: str, res: dict) -> None:
    """Añade a la fila de cada sensor las medias de la pareja (V_pp, t_abs): V_pp es la
    amplitud pico a pico en ventana de 70 ns (cap["vpp"] / 1000.0, en V).
    vpp_media / tabs_media: todas las descargas; *_cav: solo disparos con N_PD = N_cav.
    npd_media: N_PD medio por disparo válido."""
    n_cav = g4.n_cavidades(carpeta)
    for r in res.values():
        cuentas = np.asarray(r["cuentas"], dtype=float)
        r["fila"]["npd_media"] = f"{float(np.mean(cuentas)):.2f}" if cuentas.size else "-"
        cap, t_abs = r["cap"], np.asarray(r["t_abs"], dtype=float)
        vpp = np.asarray(cap["vpp"], dtype=float) / 1000.0
        seg = np.asarray(cap["seg"], dtype=int)
        r["vpp"] = vpp
        r["vp"] = vpp  # compatibilidad con helpers de reporte4 si se consultan
        ok = {int(s) for s, k in zip(r["segs"], r["cuentas"]) if n_cav and k == n_cav}
        cav = np.array([s in ok for s in seg], dtype=bool)
        r["cav"] = cav
        for suf, m in (("", np.ones(vpp.size, dtype=bool)), ("_cav", cav)):
            hay = bool(np.any(m))
            r["fila"][f"vpp_media{suf}"] = f"{float(np.mean(vpp[m])):.3f}" if hay else "-"
            r["fila"][f"tabs_media{suf}"] = f"{float(np.mean(t_abs[m])):.3f}" if hay else "-"


# ---------------- Mapa, Tabla y Páginas PDF ----------------

def dibujar_mapa(ax, d: dict, res: dict, x_lim: tuple[float, float]) -> None:
    """Mapa TRPD conjunto: las descargas (t_abs, V_pp) de todos los sensores sobre la
    forma de referencia del impulso 1.2/50 µs."""
    t_imp, f_imp = g4._impulso(x_lim)
    vmax = [float(np.max(r["vpp"])) for r in res.values() if r["vpp"].size]
    y_max = max(vmax) if vmax else 1.0
    ax.plot(t_imp, f_imp * y_max, color="#c4cbd3", lw=1.0, zorder=1, label="Impulso 1.2/50 µs (forma)")
    for c, r in res.items():
        ax.scatter(r["t_abs"], r["vpp"], s=26, color=tema.COLORES_CANALES[c], edgecolor="white",
                   linewidth=0.4, zorder=4, label=f"{r['fila']['sensor']} · {c.upper()} ({r['vpp'].size})")
    ax.set_xlim(*x_lim)
    ax.set_ylim(-0.05 * y_max, 1.08 * y_max)
    ax.axvline(0.0, color=tema.LINEA_T10, lw=0.8, ls=":", zorder=1)
    ax.set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=9)
    ax.set_ylabel("V_pp [V]", fontsize=9)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=8)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.legend(fontsize=8, loc="upper right", frameon=False, ncol=4)


def dibujar_tabla(ax, d: dict, res: dict, claves: list[str]) -> None:
    cols = COLS_BASE + [COLS_DATOS[k] for k in claves]
    filas = [[d["probeta"], d["kv_txt"], f"{r['fila']['sensor']} ({c.upper()})"]
             + [str(r["fila"].get(k, "-")) for k in claves] for c, r in res.items()]
    ax.axis("off")
    if not filas:
        return
    anchos = np.array([w for _, w in cols])
    t = ax.table(cellText=filas, colLabels=[n for n, _ in cols], loc="upper center", cellLoc="center",
                 colWidths=list(anchos / anchos.sum()))
    t.auto_set_font_size(False)
    t.set_fontsize(8)
    t.scale(1, 1.5)
    for (i, _), celda in t.get_celld().items():
        celda.set_edgecolor("#d9dee5")
        if i == 0:
            celda.set_facecolor("#eef1f5")
            celda.set_text_props(fontweight="bold")
            celda.set_height(celda.get_height() * 1.7)


def paginas_resumen(pdf, descs: list[dict], todos: list[dict], claves: list[str]) -> None:
    """Tabla resumen de todas las mediciones al inicio del informe."""
    cols = [("Probeta", 0.10), ("Voltage\n(kV)", 0.07), ("Disparos", 0.07), ("Sensor", 0.12)] \
        + [COLS_DATOS[k] for k in claves]
    filas, nivel = [], []
    for i, (d, res) in enumerate(zip(descs, todos)):
        for c, r in res.items():
            filas.append([d["probeta"], d["kv_txt"], str(d["nsegs"] - len(d["excluidos"])),
                          f"{r['fila']['sensor']} ({c.upper()})"] + [str(r["fila"].get(k, "-")) for k in claves])
            nivel.append(i)
    anchos = np.array([w for _, w in cols])
    trozos = [range(a, min(a + g4.FILAS_RESUMEN, len(filas))) for a in range(0, len(filas), g4.FILAS_RESUMEN)]
    for n, tr in enumerate(trozos, 1):
        fig = plt.figure(figsize=A4)
        tit = "Resumen de todas las mediciones" + (f" ({n}/{len(trozos)})" if len(trozos) > 1 else "")
        fig.text(0.04, 0.95, tit, fontsize=13, fontweight="bold")
        fig.text(0.04, 0.92, "V_pp: amplitud pico a pico (ventana 70 ns) · t_abs = t_peak − t10 del disparo "
                 "· N_cav = nº de cavidades de la probeta", fontsize=8, color="#555")
        ax = fig.add_axes((0.04, 0.03, 0.92, 0.86))
        ax.axis("off")
        t = ax.table(cellText=[filas[i] for i in tr], colLabels=[c for c, _ in cols], loc="upper center",
                     cellLoc="center", colWidths=list(anchos / anchos.sum()))
        t.auto_set_font_size(False)
        t.set_fontsize(8)
        t.scale(1, 1.25)
        for (i, _), celda in t.get_celld().items():
            celda.set_edgecolor("#d9dee5")
            if i == 0:
                celda.set_facecolor("#eef1f5")
                celda.set_text_props(fontweight="bold")
                celda.set_height(celda.get_height() * 1.8)
            elif nivel[tr[i - 1]] % 2:
                celda.set_facecolor("#f7f8fa")
        pdf.savefig(fig)
        plt.close(fig)


def pagina(pdf, d: dict, res: dict, x_lim: tuple[float, float], claves: list[str], png: str | None = None) -> None:
    fig = plt.figure(figsize=A4)
    disp = f"{d['nsegs']} disparos"
    if d["excluidos"]:
        disp = (f"{d['nsegs'] - len(d['excluidos'])} de {d['nsegs']} disparos (excluido"
                f"{'s' if len(d['excluidos']) != 1 else ''}: {', '.join(str(s) for s in d['excluidos'])})")
    fig.text(0.04, 0.95, f"{d['probeta']} · {d['kv_txt']} kV · {disp}", fontsize=13, fontweight="bold")
    dibujar_mapa(fig.add_axes((0.07, 0.36, 0.89, 0.55)), d, res, x_lim)
    dibujar_tabla(fig.add_axes((0.04, 0.03, 0.92, 0.22)), d, res, claves)
    if png:
        fig.savefig(png, dpi=150)
    pdf.savefig(fig)
    plt.close(fig)


def escribir_csv(ruta: str, descs: list[dict], todos: list[dict]) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Medición", "Disparos"] + [n for _, n in COLS_CSV]
                   + ["umbral (mV)", "Δt (µs)", "t_mín (µs)", "filtro"])
        for d, res in zip(descs, todos):
            for c, r in res.items():
                f_ = r["fila"]
                w.writerow([d["probeta"], d["nsegs"] - len(d["excluidos"])] + [f_.get(k, "") for k, _ in COLS_CSV]
                           + [r["cfg"]["umbral"], r["cfg"]["dist"], r["cfg"]["tmin"], f_.get("_filtro", "")])


# ---------------- Gráficas vs tensión ----------------

def graficas_tension(salida: str, descs: list[dict], todos: list[dict]) -> None:
    """vpp_vs_tension.png (+ .csv) y tabs_vs_tension.png (+ .csv): media ± σ de V_pp y t_abs
    de cada sensor por nivel de tensión; izquierda todas las descargas, derecha solo disparos
    con N_PD = N_cav."""
    probetas = sorted({d["probeta"] for d in descs})
    for prob in probetas:
        pares = sorted([(d, res) for d, res in zip(descs, todos) if d["probeta"] == prob and d["kv"] is not None],
                       key=lambda p: p[0]["kv"])
        if not pares:
            continue
        canales = [c for c in app.TRIGGERS if any(c in res for _, res in pares)]
        suf = f"_{prob}" if len(probetas) > 1 else ""
        for clave, eti, nombre, col_m, col_s in (
            ("vpp", "V̄_pp [V]", "vpp", "V̄_pp (V)", "σ V_pp (V)"),
            ("t_abs", "t̄_abs [µs]", "tabs", "t̄_abs (µs)", "σ t_abs (µs)"),
        ):
            fig, ejes = plt.subplots(1, 2, figsize=(11.69, 4.6), sharey=True)
            filas_csv = [["Probeta", "Conjunto", "Voltage (kV)", "Sensor", "Descargas", col_m, col_s]]
            for ax, (sub, cav) in zip(ejes, (("Todas las descargas", False), ("Disparos con N_PD = N_cav", True))):
                for k, c in enumerate(canales):
                    kv, m, sd = [], [], []
                    for d, res in pares:
                        r = res.get(c)
                        if r is None:
                            continue
                        x = np.asarray(r[clave], dtype=float)
                        if cav:
                            x = x[r["cav"]]
                        if x.size:
                            kv.append(d["kv"])
                            m.append(float(np.mean(x)))
                            sd.append(float(np.std(x)))
                            filas_csv.append([
                                prob, sub, f"{d['kv']:g}", r["fila"]["sensor"],
                                str(x.size), f"{m[-1]:.3f}", f"{sd[-1]:.3f}"
                            ])
                    if not kv:
                        continue
                    sensor = next(res[c]["fila"]["sensor"] for _, res in pares if c in res)
                    dx = (k - (len(canales) - 1) / 2) * 0.08
                    ax.errorbar(np.array(kv) + dx, m, yerr=sd, color=tema.COLORES_CANALES[c], marker="o",
                                ms=5, lw=1.4, capsize=3, elinewidth=0.8, label=f"{sensor} ({c.upper()})")
                ax.set_title(sub, fontsize=10, loc="left")
                ax.set_xlabel("Tensión [kV]", fontsize=9)
                ax.grid(True, color="#e5e7eb", lw=0.6)
                ax.tick_params(labelsize=8)
                for lado in ("top", "right"):
                    ax.spines[lado].set_visible(False)
                kvs = sorted({d["kv"] for d, _ in pares})
                ax.set_xticks(kvs)
            ejes[0].set_ylabel(eti, fontsize=9)
            ejes[0].legend(fontsize=8, frameon=False)
            fig.suptitle(f"{prob} · {'V_pp' if clave == 'vpp' else 't_abs'} medio por sensor vs tensión "
                         "(barras: ± 1 σ)", fontsize=12, fontweight="bold", x=0.02, ha="left")
            fig.tight_layout()
            ruta = os.path.join(salida, f"{nombre}_vs_tension{suf}.png")
            fig.savefig(ruta, dpi=160)
            with open(ruta[:-4] + ".csv", "w", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(filas_csv)
            plt.close(fig)
            print(f"Gráfica: {ruta}")


def grafica_cociente_vpp(salida: str, descs: list[dict], todos: list[dict]) -> None:
    """vpp_cociente_tension.png (+ .csv): cociente de V̄_pp de cada sensor entre niveles
    de tensión consecutivos; izquierda todas las descargas, derecha solo disparos con
    N_PD = N_cav."""
    probetas = sorted({d["probeta"] for d in descs})
    for prob in probetas:
        pares = sorted([(d, res) for d, res in zip(descs, todos) if d["probeta"] == prob and d["kv"] is not None],
                       key=lambda p: p[0]["kv"])
        if len(pares) < 2:
            continue
        canales = [c for c in app.TRIGGERS if any(c in res for _, res in pares)]
        kvs = [d["kv"] for d, _ in pares]
        etiq = [f"{b:g}/{a:g}" for a, b in zip(kvs, kvs[1:])]
        xs = np.arange(len(etiq))
        filas_csv = [["Conjunto", "Sensor"] + etiq,
                     ["", "Tensión aplicada"] + [f"{b / a:.3f}" for a, b in zip(kvs, kvs[1:])]]
        fig, ejes = plt.subplots(1, 2, figsize=(11.69, 4.6), sharey=True)
        for ax, (sub, cav) in zip(ejes, (("Todas las descargas", False), ("Disparos con N_PD = N_cav", True))):
            ax.plot(xs, [b / a for a, b in zip(kvs, kvs[1:])], color="#9aa3ad", ls="--", lw=1.0,
                    marker="s", ms=3, label="Tensión aplicada (kV/kV)")
            for c in canales:
                medias = []
                for _, res in pares:
                    r = res.get(c)
                    x = np.asarray(r["vpp"], dtype=float)[r["cav"]] if (r is not None and cav) else \
                        (np.asarray(r["vpp"], dtype=float) if r is not None else np.array([]))
                    medias.append(float(np.mean(x)) if x.size else np.nan)
                q = [b / a for a, b in zip(medias, medias[1:])]
                sensor = next(res[c]["fila"]["sensor"] for _, res in pares if c in res)
                ax.plot(xs, q, color=tema.COLORES_CANALES[c], marker="o", ms=5, lw=1.4,
                        label=f"{sensor} ({c.upper()})")
                filas_csv.append([sub, f"{sensor} ({c.upper()})"]
                                 + ["" if not np.isfinite(qi) else f"{qi:.3f}" for qi in q])
            ax.axhline(1.0, color="#555", lw=0.7)
            ax.set_xticks(xs)
            ax.set_xticklabels(etiq, fontsize=8)
            ax.set_title(sub, fontsize=10, loc="left")
            ax.set_xlabel("Niveles de tensión [kV/kV]", fontsize=9)
            ax.grid(True, color="#e5e7eb", lw=0.6)
            ax.tick_params(labelsize=8)
            for lado in ("top", "right"):
                ax.spines[lado].set_visible(False)
        ejes[0].set_ylabel("V̄_pp(n+1) / V̄_pp(n)", fontsize=9)
        ejes[0].legend(fontsize=8, frameon=False)
        fig.suptitle(f"{prob} · cociente de V_pp medio entre niveles de tensión consecutivos",
                     fontsize=12, fontweight="bold", x=0.02, ha="left")
        fig.tight_layout()
        ruta = os.path.join(salida, f"vpp_cociente_tension{'_' + prob if len(probetas) > 1 else ''}.png")
        fig.savefig(ruta, dpi=160)
        with open(ruta[:-4] + ".csv", "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(filas_csv)
        plt.close(fig)
        print(f"Gráfica: {ruta}")


# ---------------- Principal ----------------

def generar(salida: str = SALIDA_DEFECTO,
            ruta_xlsx: str = RUTA_XLSX_DEFECTO,
            sincronizar_xlsx: bool = False) -> None:
    os.makedirs(salida, exist_ok=True)
    ruta_lista = os.path.join(salida, "mediciones_listas.txt")

    if os.path.isfile(ruta_xlsx):
        carpeta_prob = os.path.dirname(os.path.abspath(ruta_xlsx))
        meds_xlsx = verificar_triggers_xlsx(carpeta_prob, ruta_xlsx, actualizar=sincronizar_xlsx)
        if not os.path.exists(ruta_lista) and meds_xlsx:
            g4.agregar(ruta_lista, meds_xlsx)

    lista = g4.leer_lista(ruta_lista)
    if not lista:
        print("No hay mediciones en mediciones_listas.txt (use --agregar o verifique Libro1.xlsx).")
        return

    descs, todos = [], []
    for m in lista:
        carpeta = g4.absoluta(m)
        if not rutas.canales_presentes(carpeta):
            print(f"Aviso: {m} no es una medición; se omite.")
            continue
        res = reproducir_trpd.resultado_medicion(carpeta, calibrado=False)
        if not res:
            continue
        medias_vpp(carpeta, res)
        descs.append(g4.describir(carpeta))
        todos.append(res)

    pares = sorted(zip(descs, todos), key=lambda p: g4.orden(p[0]))
    descs, todos = [p[0] for p in pares], [p[1] for p in pares]

    t_max = max([float(np.max(r["t_abs"])) for res in todos for r in res.values() if r["t_abs"].size]
                or [5.0])
    x_lim = (-1.0, max(5.0, float(np.ceil(t_max + 1.0))))

    for version, claves in VERSIONES.items():
        tmp = os.path.join(salida, f"informe_trpd_{version}.tmp.pdf")
        with PdfPages(tmp) as pdf:
            paginas_resumen(pdf, descs, todos, claves)
            for d, res in zip(descs, todos):
                sub = os.path.join(salida, d["probeta"], f"{d['kv_txt']}kV")
                os.makedirs(sub, exist_ok=True)
                pagina(pdf, d, res, x_lim, claves, png=os.path.join(sub, f"pagina_{version}.png"))
        os.replace(tmp, os.path.join(salida, f"informe_trpd_{version}.pdf"))
        print(f"Informe: {os.path.join(salida, f'informe_trpd_{version}.pdf')}")

    for d, res in zip(descs, todos):
        escribir_csv(os.path.join(salida, d["probeta"], f"{d['kv_txt']}kV", "tabla.csv"), [d], [res])
        print(f"{d['probeta']} {d['kv_txt']} kV: {', '.join(c.upper() for c in res)}")

    escribir_csv(os.path.join(salida, "tabla_trpd.csv"), descs, todos)
    graficas_tension(salida, descs, todos)
    grafica_cociente_vpp(salida, descs, todos)
    g4.grafica_densidad_tension(salida, descs, todos)
    g4.grafica_npd_media(salida, descs, todos)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agregar", nargs="+", default=[], help="mediciones revisadas a añadir a la lista")
    ap.add_argument("--salida", default=SALIDA_DEFECTO)
    ap.add_argument("--xlsx", default=RUTA_XLSX_DEFECTO, help="ruta al archivo Libro1.xlsx con los triggers")
    ap.add_argument("--sincronizar-xlsx", action="store_true",
                    help="actualiza canales.<ch>.trigger en metadata.yaml si difiere de Libro1.xlsx")
    a = ap.parse_args()
    if a.agregar:
        g4.agregar(os.path.join(a.salida, "mediciones_listas.txt"), a.agregar)
    generar(a.salida, ruta_xlsx=a.xlsx, sincronizar_xlsx=a.sincronizar_xlsx)


if __name__ == "__main__":
    main()
