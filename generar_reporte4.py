"""Informe TRPD básico (reporte 4): mapas TRPD de todos los sensores y tabla por nivel de
tensión, a partir de las mediciones ya revisadas en la app.

Cada medición se reproduce SOLO desde su metadata.yaml (reproducir_trpd.py): trigger
guardado por canal (umbral, Δt, t_mín, filtro), peaks añadidos/quitados y disparos
excluidos (ediciones_peaks) y retardo de calibración (calibracion_retardo). El resultado
es el mismo que muestra la app.

Las mediciones listas se anotan en <salida>/mediciones_listas.txt (una ruta por línea,
absoluta o relativa a mediciones/med_proced). Cada ejecución regenera todo el informe.

Salidas en <salida> (por defecto reportes/reporte4):
  informe_trpd.pdf            resumen + una página por medición (mapas + tabla)
  resumen.png                 página de resumen (tabla de todas las mediciones)
  tabla_trpd.csv              tabla de todas las mediciones
  <probeta>/<X>kV/mapa_trpd.png, tabla.csv

Uso:
    python generar_reporte4.py [--agregar <medición> ...] [--salida <dir>]
"""

import argparse
import csv
import datetime
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
CANALES = ["ch2", "ch3", "ch4"]
A4 = (11.69, 8.27)   # apaisado, pulgadas
GRIS = "#5f6b7a"
COLS = ["Medición", "Voltage\n(kV)", "Sensor", "N_PD distribution\n[0, 1, 2, 3, 4, > 4]",
        "N_PD =\nN_cav", "V̄_pp (V)\ntodas", "t̄_abs (µs)\ntodas",
        "V̄_pp (V)\nN_PD = N_cav", "t̄_abs (µs)\nN_PD = N_cav"]
ANCHOS = [0.13, 0.07, 0.10, 0.17, 0.07, 0.11, 0.11, 0.12, 0.12]
CLAVES = ["distribucion", "n_coinc", "vpp_media", "tabs_media", "vpp_media_cav", "tabs_media_cav"]


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
            "nsegs": app.n_segmentos(carpeta),
            "cal": app.calibracion_desde_metadata(carpeta)}


def orden(d):
    return (d["probeta"], d["kv"] if d["kv"] is not None else 1e9)


# ---------------- Mapas ----------------

def _impulso(carpeta):
    """(t, forma normalizada -1..1) del CH1 promedio con t10 = 0, como en la app."""
    t_ref, v_ref = app.promedio_impulso(carpeta)
    if t_ref is None or v_ref is None or not v_ref.size:
        return None, None
    t10 = (app.tiempos_impulso(carpeta) or {}).get("t10") or 0.0
    paso = max(1, t_ref.size // app.IMP_PUNTOS_PLOT)
    v = v_ref[::paso]
    return t_ref[::paso] - t10, v / (float(np.max(np.abs(v))) or 1.0)


def _ejes(ax, x_lim, y_max, ylabel):
    ax.set_xlim(*x_lim)
    ax.set_ylim(-0.05 * y_max, 1.08 * y_max)
    ax.axvline(0.0, color=tema.LINEA_T10, lw=0.8, ls=":", zorder=1)
    ax.set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=8)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=7)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)


def _puntos(ax, r, etiqueta, s=26):
    cap, color = r["cap"], tema.COLORES_CANALES[r["canal"]]
    vpp = np.asarray(cap["vpp"], dtype=float) / 1000.0
    ax.scatter(r["t_abs"], vpp, s=s, color=color, edgecolor="white", linewidth=0.4,
               zorder=4, label=f"{etiqueta} ({vpp.size})")
    return vpp


def dibujar_mapas(fig, rect, d, res, x_lim):
    """Mapa conjunto (arriba) y un mapa por sensor (abajo) dentro de rect (x0, y0, w, h)."""
    x0, y0, w, h = rect
    t_imp, f_imp = _impulso(d["carpeta"])
    ax = fig.add_axes((x0, y0 + 0.52 * h, w, 0.48 * h))
    vmax = [float(np.max(np.asarray(r["cap"]["vpp"]) / 1000.0)) for r in res.values() if r["cap"]["vpp"].size]
    y_max = max(vmax) if vmax else 1.0
    if t_imp is not None:
        ax.plot(t_imp, f_imp * y_max, color="#c4cbd3", lw=1.0, zorder=1, label="CH1 impulso (forma)")
    for c, r in res.items():
        _puntos(ax, r, f"{r['fila']['sensor']} · {c.upper()}")
    _ejes(ax, x_lim, y_max, "Vpp [V]")
    ax.set_title("Mapa TRPD conjunto", fontsize=9, loc="left")
    ax.legend(fontsize=7, loc="upper right", frameon=False, ncol=4)

    n = len(CANALES)
    sep = 0.035
    wp = (w - sep * (n - 1)) / n
    for k, c in enumerate(CANALES):
        axk = fig.add_axes((x0 + k * (wp + sep), y0, wp, 0.30 * h))
        r = res.get(c)
        if r is None:
            axk.text(0.5, 0.5, f"{c.upper()}: sin trigger guardado", transform=axk.transAxes,
                     ha="center", va="center", color="#9aa5b1", fontsize=9)
            _ejes(axk, x_lim, 1.0, "Vpp [V]")
            continue
        vpp = r["cap"]["vpp"] / 1000.0
        ym = float(np.max(vpp)) if vpp.size else 1.0
        if t_imp is not None:
            axk.plot(t_imp, f_imp * ym, color="#c4cbd3", lw=0.9, zorder=1)
        _puntos(axk, r, c.upper(), s=18)
        if not vpp.size:
            axk.text(0.5, 0.5, "sin descargas", transform=axk.transAxes, ha="center", va="center",
                     color="#9aa5b1", fontsize=9)
        _ejes(axk, x_lim, ym, "Vpp [V]" if k == 0 else "")
        axk.set_title(f"{r['fila']['sensor']} ({c.upper()}) · {vpp.size} descargas", fontsize=8, loc="left")


# ---------------- Tablas ----------------

def _tabla(ax, filas, tam=7.5, cols=None, anchos=None):
    ax.axis("off")
    if not filas:
        return None
    t = ax.table(cellText=filas, colLabels=cols or COLS, loc="upper center", cellLoc="center",
                 colWidths=anchos or ANCHOS)
    t.auto_set_font_size(False)
    t.set_fontsize(tam)
    t.scale(1, 1.45)
    for (i, _), celda in t.get_celld().items():
        celda.set_edgecolor("#d9dee5")
        if i == 0:
            celda.set_facecolor("#eef1f5")
            celda.set_text_props(fontweight="bold")
            celda.set_height(celda.get_height() * 1.7)
    return t


def filas_medicion(d, res):
    return [[d["probeta"], d["kv_txt"], f"{r['fila']['sensor']} ({c.upper()})"]
            + [str(r["fila"].get(k, "-")) for k in CLAVES] for c, r in res.items()]


COLS_CAL = ["Sensor", "t_lag (ns)", "σ (ns)", "Disparos\nválidos", "Umbral\narribo (mV)",
            "Ventana\n[t_mín, t_máx] (µs)", "Filtro", "Arribos\nmanuales", "Disparos\nquitados"]
ANCHOS_CAL = [0.15, 0.10, 0.09, 0.10, 0.11, 0.14, 0.11, 0.10, 0.10]


def filas_calibracion(d, res):
    """Filas de calibracion_retardo (metadata.yaml) de los sensores del informe."""
    bloque = app.obtener_metadata(d["carpeta"]).get("calibracion_retardo") or {}
    filas = []
    for c, r in res.items():
        b = bloque.get(c) if isinstance(bloque, dict) else None
        nombre = f"{r['fila']['sensor']} ({c.upper()})"
        if not isinstance(b, dict) or b.get("t_lag_ns") is None:
            filas.append([nombre, "sin calibrar"] + ["-"] * (len(COLS_CAL) - 2))
            continue

        def num(k, fmt="{:.2f}"):
            return fmt.format(float(b[k])) if b.get(k) is not None else "-"
        tmax = num("tmax_us", "{:g}") if b.get("tmax_us") is not None else "sin límite"
        filas.append([nombre, num("t_lag_ns"), num("sigma_ns"),
                      f"{b.get('n_valid', '-')} / {b.get('n_total', '-')}", num("umbral_mv", "{:g}"),
                      f"[{num('tmin_us', '{:g}')}, {tmax}]",
                      str(b.get("filtro") or "-").replace("_", " "),
                      str(b.get("n_arribos_manuales", "-")), str(b.get("n_disparos_quitados", "-"))])
    return filas, bloque


def texto_parametros(d, res):
    """Una línea por sensor: trigger, filtro, retardo y ediciones manuales."""
    lineas = []
    for c, r in res.items():
        cfg = r["cfg"]
        est = app.estado_ediciones(app.ediciones_canal(d["carpeta"], c))
        filtro = r["fila"].get("_filtro") or ("sin filtro" if not cfg["filtrado"] else "")
        lineas.append(
            f"{r['fila']['sensor']} ({c.upper()}): umbral {cfg['umbral']:g} mV · Δt {cfg['dist'] * 1e3:g} ns · "
            f"t_mín {cfg['tmin']:g} µs · {filtro} · edición manual: "
            f"{len(est['anadidos'])} añadidos, {len(est['quitados'])} quitados, "
            f"{len(est['disparos'])} disparos excluidos")
    return "\n".join(lineas)


# ---------------- PDF ----------------

def pagina_resumen(pdf, descs, todos, png=None):
    fig = plt.figure(figsize=A4)
    fig.text(0.04, 0.94, "Informe TRPD — mapas y tabla por nivel de tensión", fontsize=15, fontweight="bold")
    probetas = sorted({d["probeta"] for d in descs})
    n_cav = {todos[i][next(iter(todos[i]))]["fila"].get("_n_cav") for i in range(len(descs)) if todos[i]}
    texto = [
        f"Mediciones: {', '.join(probetas)} · {len(descs)} nivel(es) de tensión · "
        f"N_cav = {', '.join(str(n) for n in sorted(x for x in n_cav if x))} · {datetime.date.today().isoformat()}",
        "Sensores: CH2 HFCT · CH3 Antena 1 · CH4 Antena 2. CH1 (divisor capacitivo) da el impulso de "
        "referencia; su forma se dibuja escalada al mayor Vpp del mapa.",
        "Descargas: peaks de cada sensor sobre su umbral (señal filtrada), separados al menos Δt y con t ≥ t_mín;",
        "luego revisión manual: peaks falsos quitados, peaks perdidos añadidos y disparos inválidos excluidos.",
        "t_abs = t_peak − t10 del impulso en ese disparo − t_lag del sensor. "
        "N_PD distribution: nº de disparos con 0, 1, 2, 3, 4 y > 4 descargas.",
        "Calibración (calibrar_app): t_lag = arribo del frente del impulso al sensor (máximo de |v| de la primera "
        "oscilación que cruza el umbral de arribo en [t_mín, t_máx]) − t10 de CH1,",
        "promediado sobre los disparos válidos (atípicos descartados por MAD; arribos corregidos o disparos "
        "quitados a mano en la revisión).",
        "N_PD = N_cav: disparos con tantas descargas como vacuolas. V̄_pp / t̄_abs «todas»: media sobre todas "
        "las descargas del sensor; «N_PD = N_cav»: solo las de esos disparos (\"-\" si no hay).",
        "Reproducible: trigger y ediciones guardados en el metadata.yaml de cada medición "
        "(TRPD_APP/reproducir_trpd.py).",
    ]
    fig.text(0.04, 0.905, "\n".join(texto), fontsize=8, color=GRIS, va="top", linespacing=1.6)
    filas = [f for i, d in enumerate(descs) for f in filas_medicion(d, todos[i])]
    ax = fig.add_axes((0.03, 0.03, 0.94, 0.70))
    t = _tabla(ax, filas)
    if t is not None:
        grupo, prev = -1, None
        for i in range(1, len(filas) + 1):
            clave = (filas[i - 1][0], filas[i - 1][1])
            if clave != prev:
                grupo, prev = grupo + 1, clave
            if grupo % 2 == 1:
                for j in range(len(COLS)):
                    t[i, j].set_facecolor("#f7f8fa")
    if png:
        fig.savefig(png, dpi=150)
    pdf.savefig(fig)
    plt.close(fig)


def pagina_medicion(pdf, d, res, x_lim, png=None):
    fig = plt.figure(figsize=A4)
    fig.text(0.04, 0.955, f"{d['probeta']} · {d['kv_txt']} kV · {d['nsegs']} disparos", fontsize=13,
             fontweight="bold")
    fig.text(0.04, 0.935, texto_parametros(d, res), fontsize=7, color=GRIS, va="top", linespacing=1.5)
    dibujar_mapas(fig, (0.06, 0.445, 0.91, 0.405), d, res, x_lim)
    filas_cal, bloque = filas_calibracion(d, res)
    cab = "Calibración de retardo"
    if bloque.get("fecha"):
        crit = {"pico_primer_lobulo": "máximo de la primera oscilación que cruza el umbral",
                "primer_cruce_umbral": "primer cruce del umbral (criterio anterior)"}.get(
            bloque.get("criterio") or "primer_cruce_umbral", str(bloque.get("criterio")))
        cab += f" · {bloque.get('fecha')} · referencia t10 de CH1 por disparo · arribo: {crit}"
    fig.text(0.04, 0.345, cab, fontsize=8, fontweight="bold")
    _tabla(fig.add_axes((0.04, 0.19, 0.92, 0.15)), filas_cal, tam=6.5, cols=COLS_CAL, anchos=ANCHOS_CAL)
    fig.text(0.04, 0.17, "Descargas", fontsize=8, fontweight="bold")
    _tabla(fig.add_axes((0.04, 0.005, 0.92, 0.16)), filas_medicion(d, res), tam=6.5)
    if png:
        fig.savefig(png, dpi=150)
    pdf.savefig(fig)
    plt.close(fig)


def escribir_csv(ruta, descs, todos):
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Medición"] + [c["name"] for c in app.COLUMNAS_DENSIDAD]
                   + ["umbral (mV)", "Δt (µs)", "t_mín (µs)", "filtro"])
        for d, res in zip(descs, todos):
            for c, r in res.items():
                f_ = r["fila"]
                w.writerow([d["probeta"]] + [f_.get(col["id"], "") for col in app.COLUMNAS_DENSIDAD]
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
        res = reproducir_trpd.resultado_medicion(carpeta)
        if not res:
            continue
        descs.append(describir(carpeta))
        todos.append(res)
    pares = sorted(zip(descs, todos), key=lambda p: orden(p[0]))
    descs, todos = [p[0] for p in pares], [p[1] for p in pares]

    t_max = max([float(np.max(r["t_abs"])) for res in todos for r in res.values() if r["t_abs"].size]
                or [5.0])
    x_lim = (-1.0, max(5.0, float(np.ceil(t_max + 1.0))))

    tmp = os.path.join(salida, "informe_trpd.tmp.pdf")
    with PdfPages(tmp) as pdf:
        pagina_resumen(pdf, descs, todos, png=os.path.join(salida, "resumen.png"))
        for d, res in zip(descs, todos):
            sub = os.path.join(salida, d["probeta"], f"{d['kv_txt']}kV")
            os.makedirs(sub, exist_ok=True)
            pagina_medicion(pdf, d, res, x_lim, png=os.path.join(sub, "mapa_trpd.png"))
            escribir_csv(os.path.join(sub, "tabla.csv"), [d], [res])
            print(f"{d['probeta']} {d['kv_txt']} kV: {', '.join(c.upper() for c in res)}")
    os.replace(tmp, os.path.join(salida, "informe_trpd.pdf"))
    escribir_csv(os.path.join(salida, "tabla_trpd.csv"), descs, todos)
    print(f"Informe: {os.path.join(salida, 'informe_trpd.pdf')}")


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
