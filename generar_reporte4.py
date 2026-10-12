"""Informe TRPD básico (reporte 4): por cada nivel de tensión, el mapa TRPD conjunto (todos
los sensores en un solo mapa) y su tabla de densidad de eventos, precedidos de una tabla
resumen de todas las mediciones. Cada descarga es la pareja (V_p, t_abs): V_p es el máximo
de la señal en el peak marcado (v_peak); no se usa Vpp ni su ventana de 70 ns.

Se generan dos versiones del informe con los mismos mapas:
  informe_trpd_ncav.pdf       tabla sin las medias «todas» (que mezclan disparos con
                              N_PD ≠ N_cav): distribución, N_PD = N_cav y sus medias
  informe_trpd_completo.pdf   tabla con todas las columnas

Cada medición se reproduce SOLO desde su metadata.yaml (reproducir_trpd.py): trigger
guardado por canal (umbral, Δt, t_mín, filtro), peaks añadidos/quitados y disparos
excluidos (ediciones_peaks). La calibración de retardo NO se aplica: t_abs = t_peak − t10
del disparo (t_lag = 0 en todos los sensores, aunque la medición tenga calibracion_retardo).

Las mediciones listas se anotan en <salida>/mediciones_listas.txt (una ruta por línea,
absoluta o relativa a mediciones/med_proced). Cada ejecución regenera todo el informe.

Salidas en <salida> (por defecto reportes/reporte4):
  informe_trpd_ncav.pdf, informe_trpd_completo.pdf
  tabla_trpd.csv              tabla de todas las mediciones (todas las columnas + trigger)
  <probeta>/<X>kV/pagina_ncav.png, pagina_completo.png, tabla.csv

Uso:
    python generar_reporte4.py [--agregar <medición> ...] [--salida <dir>]
"""

import argparse
import csv
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
import numpy as np  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import app  # noqa: E402
import reproducir_trpd  # noqa: E402
import rutas  # noqa: E402
import tema  # noqa: E402

PROYECTO = os.path.dirname(AQUI)
MED = os.path.join(PROYECTO, "mediciones", "med_proced")
SALIDA_DEFECTO = os.path.join(PROYECTO, "reportes", "reporte4")
A4 = (11.69, 8.27)   # apaisado, pulgadas

# (clave de la fila de densidad, cabecera, ancho relativo)
COLS_BASE = [("Medición", 0.13), ("Voltage\n(kV)", 0.07), ("Sensor", 0.12)]
COLS_DATOS = {
    "distribucion": ("N_PD distribution\n[0, 1, 2, 3, 4, > 4]", 0.18),
    "n_coinc": ("N_PD =\nN_cav", 0.08),
    "vp_media": ("V̄_p (V)\ntodas", 0.11),
    "tabs_media": ("t̄_abs (µs)\ntodas", 0.11),
    "vp_media_cav": ("V̄_p (V)\nN_PD = N_cav", 0.12),
    "tabs_media_cav": ("t̄_abs (µs)\nN_PD = N_cav", 0.12),
}
VERSIONES = {
    "ncav": ["distribucion", "n_coinc", "vp_media_cav", "tabs_media_cav"],
    "completo": ["distribucion", "n_coinc", "vp_media", "tabs_media", "vp_media_cav", "tabs_media_cav"],
}
# CSV: (clave, cabecera)
COLS_CSV = [("voltage", "Voltage (kV)"), ("sensor", "Sensor"), ("distribucion", "N_PD distribution [0, 1, 2, 3, 4, > 4]"),
            ("n_coinc", "N_PD = N_cav"), ("vp_media", "V̄_p (V)"), ("tabs_media", "t̄_abs (µs)"),
            ("vp_media_cav", "V̄_p | N_PD = N_cav (V)"), ("tabs_media_cav", "t̄_abs | N_PD = N_cav (µs)")]


# ---------------- Mediciones ----------------

def leer_lista(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]


def absoluta(m):
    return os.path.normpath(m if os.path.isabs(m) else os.path.join(MED, m))


def agregar(ruta_lista, nuevas):
    lista = leer_lista(ruta_lista)
    claves = {absoluta(m) for m in lista}
    for m in nuevas:
        a = os.path.normpath(os.path.abspath(m)) if os.path.isabs(m) or os.path.exists(m) else absoluta(m)
        if a not in claves:
            rel = os.path.relpath(a, MED) if a.startswith(os.path.normpath(MED)) else a
            lista.append(rel.replace("\\", "/"))
            claves.add(a)
    os.makedirs(os.path.dirname(ruta_lista), exist_ok=True)
    with open(ruta_lista, "w", encoding="utf-8") as f:
        f.write("# Mediciones revisadas en la app y listas para el informe (relativas a "
                "mediciones/med_proced)\n" + "\n".join(lista) + "\n")
    return lista


def describir(carpeta):
    """Probeta, tensión y nº de disparos de la medición."""
    meta = app.obtener_metadata(carpeta)
    kv = app._tension_kv(carpeta, meta)
    return {"carpeta": carpeta, "probeta": os.path.basename(os.path.dirname(carpeta)),
            "kv": kv, "kv_txt": f"{kv:g}" if kv is not None else os.path.basename(carpeta),
            "nsegs": app.n_segmentos(carpeta), "excluidos": sorted(app.segmentos_excluidos(carpeta))}


def orden(d):
    return (d["probeta"], d["kv"] if d["kv"] is not None else 1e9)


def n_cavidades(carpeta):
    """N_cav de la probeta (metadata o inferido del nombre), o None."""
    n = (app.obtener_metadata(carpeta).get("probeta") or {}).get("nro_vacuolas") \
        or app.inferir_parametros(carpeta).get("nro_vacuolas")
    try:
        return int(n) if n is not None else None
    except (TypeError, ValueError):
        return None


def medias_vp(carpeta, res):
    """Añade a la fila de cada sensor las medias de la pareja (V_p, t_abs): V_p es el
    máximo de la señal en la marca del peak (v_peak), sin ventana de Vpp.
    vp_media / tabs_media: todas las descargas; *_cav: solo disparos con N_PD = N_cav."""
    n_cav = n_cavidades(carpeta)
    for r in res.values():
        cap, t_abs = r["cap"], np.asarray(r["t_abs"], dtype=float)
        vp = np.asarray(cap["v_peak"], dtype=float) / 1000.0
        seg = np.asarray(cap["seg"], dtype=int)
        r["vp"] = vp
        ok = {int(s) for s, k in zip(r["segs"], r["cuentas"]) if n_cav and k == n_cav}
        cav = np.array([s in ok for s in seg], dtype=bool)
        for suf, m in (("", np.ones(vp.size, dtype=bool)), ("_cav", cav)):
            hay = bool(np.any(m))
            r["fila"][f"vp_media{suf}"] = f"{float(np.mean(vp[m])):.3f}" if hay else "-"
            r["fila"][f"tabs_media{suf}"] = f"{float(np.mean(t_abs[m])):.3f}" if hay else "-"


# ---------------- Mapa ----------------

def _impulso(x_lim):
    """(t, forma) del impulso tipo rayo normalizado 1.2/50 µs (doble exponencial,
    IEC 60060-1), máximo = 1 y con su 10 % de subida en t = 0 como el t10 de los datos.
    Es solo la referencia de forma: no se usa el CH1 medido."""
    tau1, tau2 = 68.22, 0.4046   # µs

    def u(t):
        return np.where(t > 0, np.exp(-t / tau1) - np.exp(-t / tau2), 0.0)
    t = np.linspace(0.0, 10.0, 100001)
    ref = u(t)
    t10 = t[np.argmax(ref >= 0.1 * ref.max())]
    tt = np.linspace(x_lim[0], x_lim[1], 2000)
    return tt, u(tt + t10) / ref.max()


def dibujar_mapa(ax, d, res, x_lim):
    """Mapa TRPD conjunto: las descargas de todos los sensores sobre la forma del impulso."""
    t_imp, f_imp = _impulso(x_lim)
    vmax = [float(np.max(r["vp"])) for r in res.values() if r["vp"].size]
    y_max = max(vmax) if vmax else 1.0
    ax.plot(t_imp, f_imp * y_max, color="#c4cbd3", lw=1.0, zorder=1, label="Impulso 1.2/50 µs (forma)")
    for c, r in res.items():
        ax.scatter(r["t_abs"], r["vp"], s=26, color=tema.COLORES_CANALES[c], edgecolor="white", linewidth=0.4,
                   zorder=4, label=f"{r['fila']['sensor']} · {c.upper()} ({r['vp'].size})")
    ax.set_xlim(*x_lim)
    ax.set_ylim(-0.05 * y_max, 1.08 * y_max)
    ax.axvline(0.0, color=tema.LINEA_T10, lw=0.8, ls=":", zorder=1)
    ax.set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=9)
    ax.set_ylabel("V_p [V]", fontsize=9)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=8)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.legend(fontsize=8, loc="upper right", frameon=False, ncol=4)


# ---------------- Tabla ----------------

def dibujar_tabla(ax, d, res, claves):
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


# ---------------- Resumen ----------------

FILAS_RESUMEN = 30   # filas por página de la tabla resumen


def paginas_resumen(pdf, descs, todos, claves):
    """Tabla resumen de todas las mediciones (una fila por nivel y sensor) al inicio
    del informe; se parte en varias páginas si no cabe."""
    cols = [("Probeta", 0.10), ("Voltage\n(kV)", 0.07), ("Disparos", 0.07), ("Sensor", 0.12)] \
        + [COLS_DATOS[k] for k in claves]
    filas, nivel = [], []
    for i, (d, res) in enumerate(zip(descs, todos)):
        for c, r in res.items():
            filas.append([d["probeta"], d["kv_txt"], str(d["nsegs"] - len(d["excluidos"])),
                          f"{r['fila']['sensor']} ({c.upper()})"] + [str(r["fila"].get(k, "-")) for k in claves])
            nivel.append(i)
    anchos = np.array([w for _, w in cols])
    trozos = [range(a, min(a + FILAS_RESUMEN, len(filas))) for a in range(0, len(filas), FILAS_RESUMEN)]
    for n, tr in enumerate(trozos, 1):
        fig = plt.figure(figsize=A4)
        tit = "Resumen de todas las mediciones" + (f" ({n}/{len(trozos)})" if len(trozos) > 1 else "")
        fig.text(0.04, 0.95, tit, fontsize=13, fontweight="bold")
        fig.text(0.04, 0.92, "V_p: máximo de la señal en el peak marcado · t_abs = t_peak − t10 del disparo "
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


# ---------------- PDF / CSV ----------------

def pagina(pdf, d, res, x_lim, claves, png=None):
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


def escribir_csv(ruta, descs, todos):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Medición", "Disparos"] + [n for _, n in COLS_CSV]
                   + ["umbral (mV)", "Δt (µs)", "t_mín (µs)", "filtro"])
        for d, res in zip(descs, todos):
            for c, r in res.items():
                f_ = r["fila"]
                w.writerow([d["probeta"], d["nsegs"] - len(d["excluidos"])] + [f_.get(k, "") for k, _ in COLS_CSV]
                           + [r["cfg"]["umbral"], r["cfg"]["dist"], r["cfg"]["tmin"], f_.get("_filtro", "")])


# ---------------- Principal ----------------

def generar(salida):
    lista = leer_lista(os.path.join(salida, "mediciones_listas.txt"))
    if not lista:
        print("No hay mediciones en mediciones_listas.txt (use --agregar).")
        return
    descs, todos = [], []
    for m in lista:
        carpeta = absoluta(m)
        if not rutas.canales_presentes(carpeta):
            print(f"Aviso: {m} no es una medición; se omite.")
            continue
        res = reproducir_trpd.resultado_medicion(carpeta, calibrado=False)
        if not res:
            continue
        medias_vp(carpeta, res)
        descs.append(describir(carpeta))
        todos.append(res)
    pares = sorted(zip(descs, todos), key=lambda p: orden(p[0]))
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agregar", nargs="+", default=[], help="mediciones revisadas a añadir a la lista")
    ap.add_argument("--salida", default=SALIDA_DEFECTO)
    a = ap.parse_args()
    if a.agregar:
        agregar(os.path.join(a.salida, "mediciones_listas.txt"), a.agregar)
    generar(a.salida)


if __name__ == "__main__":
    main()
