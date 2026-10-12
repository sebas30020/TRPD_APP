"""Informe TRPD básico (reporte 4): por cada nivel de tensión, el mapa TRPD conjunto (todos
los sensores en un solo mapa) y su tabla de densidad de eventos, precedidos de una tabla
resumen de todas las mediciones. Cada descarga es la pareja (V_p, t_abs): V_p es el máximo
de la señal en el peak marcado (v_peak); no se usa Vpp ni su ventana de 70 ns.

Se generan dos versiones del informe con los mismos mapas:
  informe_trpd_ncav.pdf       tabla sin las medias «todas» (que mezclan disparos con
                              N_PD ≠ N_cav): distribución, N_PD = N_cav, N̄_PD y sus medias
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
  densidad_vs_tension.png/.csv  densidad de eventos (N_PD por disparo) por sensor vs tensión (fuera del informe)
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
    "npd_media": ("N̄_PD\n(por disparo)", 0.08),
    "vp_media":("V̄_p (V)\ntodas", 0.11),
    "tabs_media": ("t̄_abs (µs)\ntodas", 0.11),
    "vp_media_cav": ("V̄_p (V)\nN_PD = N_cav", 0.12),
    "tabs_media_cav": ("t̄_abs (µs)\nN_PD = N_cav", 0.12),
}
VERSIONES = {
    "ncav": ["distribucion", "n_coinc", "npd_media", "vp_media_cav", "tabs_media_cav"],
    "completo": ["distribucion", "n_coinc", "npd_media", "vp_media", "tabs_media", "vp_media_cav", "tabs_media_cav"],
}
# CSV: (clave, cabecera)
COLS_CSV = [("voltage", "Voltage (kV)"), ("sensor", "Sensor"), ("distribucion", "N_PD distribution [0, 1, 2, 3, 4, > 4]"),
            ("n_coinc", "N_PD = N_cav"), ("npd_media", "N̄_PD"), ("vp_media", "V̄_p (V)"), ("tabs_media", "t̄_abs (µs)"),
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
    try:
        n = (app.obtener_metadata(carpeta).get("probeta") or {}).get("nro_vacuolas") \
            or app.inferir_parametros(carpeta).get("nro_vacuolas")
        return int(n) if n is not None else None
    except Exception:
        return None


def medias_vp(carpeta, res):
    """Añade a la fila de cada sensor las medias de la pareja (V_p, t_abs): V_p es el
    máximo de la señal en la marca del peak (v_peak), sin ventana de Vpp.
    vp_media / tabs_media: todas las descargas; *_cav: solo disparos con N_PD = N_cav.
    npd_media: N_PD medio por disparo válido (para comparar con N_cav)."""
    n_cav = n_cavidades(carpeta)
    for r in res.values():
        cuentas = np.asarray(r["cuentas"], dtype=float)
        r["fila"]["npd_media"] = f"{float(np.mean(cuentas)):.2f}" if cuentas.size else "-"
        cap, t_abs = r["cap"], np.asarray(r["t_abs"], dtype=float)
        vp = np.asarray(cap["v_peak"], dtype=float) / 1000.0
        seg = np.asarray(cap["seg"], dtype=int)
        r["vp"] = vp
        ok = {int(s) for s, k in zip(r["segs"], r["cuentas"]) if n_cav and k == n_cav}
        cav = np.array([s in ok for s in seg], dtype=bool)
        r["cav"] = cav
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


# ---------------- Gráficas vs tensión ----------------
 
CLASES_NPD = ["0", "1", "2", "3", "4", "> 4"]


def distribucion_npd(cuentas):
    """Nº de disparos con N_PD = 0, 1, 2, 3, 4 y > 4 (misma regla que app.calcular_fila_densidad)."""
    c = np.asarray(cuentas, dtype=int)
    return [int(np.sum(c == k)) for k in range(5)] + [int(np.sum(c > 4))]


def graficas_tension(salida, descs, todos):
    """vp_vs_tension.png y tabs_vs_tension.png: media ± σ de V_p y t_abs de cada sensor
    por nivel de tensión; izquierda todas las descargas, derecha solo disparos con
    N_PD = N_cav. Una figura por probeta (sufijo _<probeta> si hay más de una)."""
    probetas = sorted({d["probeta"] for d in descs})
    for prob in probetas:
        pares = [(d, res) for d, res in zip(descs, todos) if d["probeta"] == prob and d["kv"] is not None]
        canales = [c for c in app.TRIGGERS if any(c in res for _, res in pares)]
        suf = f"_{prob}" if len(probetas) > 1 else ""
        for clave, eti, nombre in (("vp", "V̄_p [V]", "vp"), ("t_abs", "t̄_abs [µs]", "tabs")):
            fig, ejes = plt.subplots(1, 2, figsize=(11.69, 4.6), sharey=True)
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
                    if not kv:
                        continue
                    sensor = next(res[c]["fila"]["sensor"] for _, res in pares if c in res)
                    dx = (k - (len(canales) - 1) / 2) * 0.08   # separa las barras de error
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
            fig.suptitle(f"{prob} · {'V_p' if clave == 'vp' else 't_abs'} medio por sensor vs tensión "
                         "(barras: ± 1 σ)", fontsize=12, fontweight="bold", x=0.02, ha="left")
            fig.tight_layout()
            ruta = os.path.join(salida, f"{nombre}_vs_tension{suf}.png")
            fig.savefig(ruta, dpi=160)
            plt.close(fig)
            print(f"Gráfica: {ruta}")


def grafica_cociente_vp(salida, descs, todos):
    """vp_cociente_tension.png (+ .csv con los valores): cociente de V̄_p de cada sensor entre niveles de tensión
    consecutivos (12/11, 13/12, ...); izquierda todas las descargas, derecha solo disparos
    con N_PD = N_cav. Referencia gris: cociente de las tensiones aplicadas."""
    probetas = sorted({d["probeta"] for d in descs})
    for prob in probetas:
        pares = sorted([(d, res) for d, res in zip(descs, todos) if d["probeta"] == prob and d["kv"] is not None],
                       key=lambda p: p[0]["kv"])
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
            for k, c in enumerate(canales):
                medias = []
                for _, res in pares:
                    r = res.get(c)
                    x = np.asarray(r["vp"], dtype=float)[r["cav"]] if (r is not None and cav) else \
                        (np.asarray(r["vp"], dtype=float) if r is not None else np.array([]))
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
        ejes[0].set_ylabel("V̄_p(n+1) / V̄_p(n)", fontsize=9)
        ejes[0].legend(fontsize=8, frameon=False)
        fig.suptitle(f"{prob} · cociente de V_p medio entre niveles de tensión consecutivos",
                     fontsize=12, fontweight="bold", x=0.02, ha="left")
        fig.tight_layout()
        ruta = os.path.join(salida, f"vp_cociente_tension{'_' + prob if len(probetas) > 1 else ''}.png")
        fig.savefig(ruta, dpi=160)
        with open(ruta[:-4] + ".csv", "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(filas_csv)
        plt.close(fig)
        print(f"Gráfica: {ruta}")


def grafica_densidad_tension(salida, descs, todos):
    """densidad_vs_tension.png (+ .csv con los valores): mapa de calor de la densidad de eventos
    (N_PD por disparo en clases 0, 1, 2, 3, 4, > 4) por nivel de tensión para cada sensor.
    Una figura por probeta (sufijo _<probeta> si hay más de una)."""
    probetas = sorted({d["probeta"] for d in descs})
    for prob in probetas:
        pares = sorted([(d, res) for d, res in zip(descs, todos) if d["probeta"] == prob and d["kv"] is not None],
                       key=lambda p: p[0]["kv"])
        if not pares:
            continue
        canales = [c for c in app.TRIGGERS if any(c in res for _, res in pares)]
        if not canales:
            continue

        try:
            n_cav = n_cavidades(pares[0][0].get("carpeta", ""))
        except Exception:
            n_cav = None

        suf = f"_{prob}" if len(probetas) > 1 else ""
        n_niveles = len(pares)
        etiquetas_x = []
        for d, _ in pares:
            kv_val = d["kv"]
            ndisp = (d["nsegs"] - len(d["excluidos"])) if ("nsegs" in d and "excluidos" in d) else None
            etiquetas_x.append(f"{kv_val:g}\n({ndisp})" if ndisp is not None else f"{kv_val:g}")

        fig, ejes = plt.subplots(1, len(canales), figsize=(11.69, 4.6), sharey=True,
                                 squeeze=False, layout="constrained")
        im = None
        for ax, c in zip(ejes[0], canales):
            N = np.full((len(CLASES_NPD), n_niveles), np.nan)
            for j, (d, res) in enumerate(pares):
                r = res.get(c)
                if r is not None and "cuentas" in r:
                    N[:, j] = distribucion_npd(r["cuentas"])

            with np.errstate(divide="ignore", invalid="ignore"):
                tot_col = np.nansum(N, axis=0, keepdims=True)
                F = np.where(tot_col > 0, N / tot_col, np.nan)

            im = ax.imshow(F, origin="lower", aspect="auto", cmap="Blues",
                           vmin=0, vmax=1, interpolation="nearest")

            for i in range(len(CLASES_NPD)):
                for j in range(n_niveles):
                    val = N[i, j]
                    if not np.isnan(val) and val > 0:
                        frac = F[i, j]
                        col = "white" if (not np.isnan(frac) and frac > 0.55) else "#1f2937"
                        ax.text(j, i, str(int(val)), ha="center", va="center",
                                fontsize=7, color=col)

            ax.set_xticks(range(n_niveles))
            ax.set_xticklabels(etiquetas_x)
            ax.set_yticks(range(len(CLASES_NPD)))
            ax.set_yticklabels(CLASES_NPD)

            if n_cav is not None and 0 <= n_cav <= 4:
                ax.axhline(n_cav, color="#4b5563", ls="--", lw=1.0, alpha=0.75,
                           label=f"$N_{{cav}} = {n_cav}$")

            sensor = next((res[c]["fila"]["sensor"] for _, res in pares if c in res and "fila" in res[c]), c.upper())
            ax.set_title(f"{sensor} ({c.upper()})", fontsize=10, loc="left",
                         color=tema.COLORES_CANALES.get(c, "#1f2937"))
            ax.set_xlabel("Tensión [kV]", fontsize=9)
            ax.tick_params(labelsize=8)

        ejes[0][0].set_ylabel("N_PD (descargas por disparo)", fontsize=9)
        if n_cav is not None and 0 <= n_cav <= 4:
            ejes[0][0].legend(loc="upper left", fontsize=8, framealpha=0.85)

        if im is not None:
            cbar = fig.colorbar(im, ax=ejes[0].tolist(), label="Fracción de disparos", shrink=0.85)
            cbar.ax.tick_params(labelsize=8)
            cbar.set_label("Fracción de disparos", fontsize=9)

        fig.suptitle(f"{prob} · densidad de eventos: N_PD por disparo vs tensión (celdas: nº de disparos)",
                     fontsize=12, fontweight="bold", x=0.02, ha="left")

        ruta = os.path.join(salida, f"densidad_vs_tension{suf}.png")
        fig.savefig(ruta, dpi=160)
        plt.close(fig)

        filas_csv = [["Probeta", "Voltage (kV)", "Sensor", "Disparos",
                      "N_PD=0", "N_PD=1", "N_PD=2", "N_PD=3", "N_PD=4", "N_PD>4",
                      "f_0", "f_1", "f_2", "f_3", "f_4", "f_>4"]]
        for d, res in pares:
            kv_str = d.get("kv_txt") or (f"{d['kv']:g}" if d.get("kv") is not None else "")
            for c in canales:
                r = res.get(c)
                if r is None or "cuentas" not in r:
                    continue
                sensor = r.get("fila", {}).get("sensor", c.upper())
                counts = distribucion_npd(r["cuentas"])
                tot = sum(counts)
                fracs = [f"{k / tot:.3f}" if tot > 0 else "0.000" for k in counts]
                filas_csv.append([prob, kv_str, sensor, tot] + counts + fracs)

        with open(ruta[:-4] + ".csv", "w", encoding="utf-8", newline="") as f:
            csv.writer(f).writerows(filas_csv)

        print(f"Gráfica: {ruta}")


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
    graficas_tension(salida, descs, todos)
    grafica_cociente_vp(salida, descs, todos)
    grafica_densidad_tension(salida, descs, todos)


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
