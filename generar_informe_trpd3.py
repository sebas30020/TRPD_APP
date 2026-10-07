"""Informe TRPD con tres sensores (CH3 + CH4 + CH2) contando solo las descargas que ven los tres.

Pensado para las probetas 3v_4mm_0 y 3v_4mm_1 (3 vacuolas de Ø 4 mm), pero sirve para
cualquier raíz. 3v_4mm_0 se lee de mediciones/med_proced_hfct_inv (HFCT montado al revés en la
medición; copia con CH2 invertido hecha con invertir_canal.py). La detección por canal es la de generar_informe_trpd.py (CH3/CH4: HP 200 MHz,
umbral 250 mV, Δt 50 ns; CH2: resta de la resonancia, umbral dinámico U + k·envolvente).

Eventos: las detecciones de los tres canales se agrupan por disparo. Cada evento parte de una
detección ancla (CH3, si no CH4, si no CH2) y toma de cada otro canal la detección más cercana a
≤ TOL_COINC_US (tras corregir el retardo fijo del sensor). Categorías:
  triple               CH3 + CH4 + CH2. Única que cuenta (N_PD, Tabla 1).
  antenas_resonancia   CH3 + CH4 sin CH2, y la resonancia de CH2 en ese instante (envolvente
                       ajustada en el disparo) ≥ umbral de CH2: el HFCT pudo quedar tapado.
                       Se dibuja en el mapa con marcador propio, no cuenta.
  antenas_hfct_solapado CH3 + CH4 sin CH2, con otra descarga de CH2 a < Δt (0.5 µs) en el mismo
                       disparo: el HFCT no separa los dos pulsos.
  antenas_sin_hfct     CH3 + CH4 sin CH2, fuera de los dos casos anteriores.
  ch3_ch2, ch4_ch2     pares parciales; solo_ch3, solo_ch4, solo_ch2: un solo sensor.
Todo lo que no es triple es dudoso: va a descargas_a_revisar.txt con su figura temporal.

Salidas en <salida> (por defecto reportes/reporte3):
  informe_trpd_3v_4mm.pdf, resumen_trpd_3sensores.csv, descargas_a_revisar.txt,
  <probeta>/<X>kV/ trpd_<canal>.png, tabla_<canal>.csv, eventos.csv,
  dudosas/<probeta>/<X>kV/*.png (una por evento dudoso; una por disparo si tiene muchos).

Uso:
    python generar_informe_trpd3.py [<raiz> ...] [--salida <dir>] [--solo <texto>]
                                    [--umbral-medicion CANAL:RUTA=MV ...]
"""

import argparse
import csv
import datetime
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.ndimage import maximum_filter1d  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import app  # noqa: E402
import generar_informe_trpd as git3  # noqa: E402
import tema  # noqa: E402
from generate_metadata import inferir_parametros  # noqa: E402

PROYECTO = os.path.dirname(AQUI)
MED = os.path.join(PROYECTO, "mediciones", "med_proced")
# 3v_4mm_0 se midió con el HFCT al revés: se usa la copia con CH2 invertido (invertir_canal.py).
MED_HFCT_INV = os.path.join(PROYECTO, "mediciones", "med_proced_hfct_inv")
RAICES_DEFECTO = [os.path.join(MED_HFCT_INV, "3v_4mm_0"), os.path.join(MED, "3v_4mm_1")]
SALIDA_DEFECTO = os.path.join(PROYECTO, "reportes", "reporte3")
CANALES = ["ch3", "ch4", "ch2"]
NOMBRE_CANAL = {"ch2": "HFCT", "ch3": "Antena 1", "ch4": "Antena 2"}
# CH2 a 65 mV: estas mediciones se tomaron a ~0.5 V/div y el ruido del HFCT tras el HP 5 MHz
# tiene máximos de 40-53 mV (cuantización), como med_proced/1v_2mm_01.
UMBRALES = {"ch3": 250.0, "ch4": 250.0, "ch2": 65.0}
# Probetas cuyo código no describe todas las vacuolas (3v_4mm = 3 vacuolas de 4 mm): sin
# metadata.yaml, generate_metadata.inferir_parametros no las reconoce.
PROBETAS = {"3v_4mm": (3, [4, 4, 4])}
TOL_US = git3.TOL_COINC_US
RETARDO_US = git3.RETARDO_US
PRIORIDAD = ["ch3", "ch4", "ch2"]          # canal ancla de un evento
CATEGORIAS = ["triple", "antenas_resonancia", "antenas_hfct_solapado", "antenas_sin_hfct",
              "ch3_ch2", "ch4_ch2", "solo_ch3", "solo_ch4", "solo_ch2"]
ETIQUETA_CAT = {
    "triple": "CH3 + CH4 + CH2 (cuenta)",
    "antenas_resonancia": "CH3 + CH4, HFCT posiblemente oculto en la resonancia",
    "antenas_hfct_solapado": "CH3 + CH4, HFCT con otra descarga a < 0.5 µs (no separable)",
    "antenas_sin_hfct": "CH3 + CH4, sin HFCT fuera de la resonancia",
    "ch3_ch2": "CH3 + CH2, sin CH4", "ch4_ch2": "CH4 + CH2, sin CH3",
    "solo_ch3": "solo CH3", "solo_ch4": "solo CH4", "solo_ch2": "solo CH2",
}
MAX_FIG_POR_DISPARO = 8   # más dudosas en un disparo: una sola figura del disparo
VENTANA_FIG_US = 1.0      # ± alrededor del evento en las figuras de dudosas
A4 = git3.A4_APAISADO


# ---------------- Mediciones ----------------

def _probeta_conocida(probeta):
    base = probeta.rsplit("_", 1)[0]
    return PROBETAS.get(base)


def completar_desc(d):
    """Título, N_cav y diámetros de las probetas de PROBETAS (sin metadata.yaml)."""
    inf = inferir_parametros(d["carpeta"])
    d["kv"] = inf.get("tension_sec_kv")
    conocida = _probeta_conocida(d["probeta"])
    d["n_cav"], d["diam"] = conocida if conocida else (inf.get("nro_vacuolas"), inf.get("diametros") or [])
    if conocida:
        n, diam = conocida
        d["set"] = d["probeta"].rsplit("_", 1)[-1]
        d["titulo"] = f"{n} vacuolas · Ø {diam[0]:g} mm · {d['kv']:g} kV"
    return d


# ---------------- Eventos ----------------

def _t_corr(r):
    return r["cap"]["t_peak"] - RETARDO_US.get(r["canal"], 0.0)


def env_resonancia(r2, seg, ta):
    """Envolvente (mV) de la resonancia de CH2 ajustada en el disparo, en los t_abs `ta`."""
    mod = (r2.get("modelo") or {}).get(int(seg))
    if mod is None:
        return np.zeros_like(np.atleast_1d(ta), dtype=float)
    malla = r2["malla"]
    n_env = max(1, int(round(0.07 / (malla[1] - malla[0]))))
    env = maximum_filter1d(np.abs(mod.astype(float)), n_env)
    return np.interp(ta, malla, env, left=0.0, right=0.0)


def agrupar_eventos(rs, n_segs):
    """Eventos de una medición. `rs` {canal: resultado}. Devuelve lista de dicts con
    disparo, idx {canal: índice en su captura}, multiple, categoria, t_abs (del ancla)."""
    eventos = []
    tc = {c: _t_corr(rs[c]) for c in CANALES}
    sg = {c: np.asarray(rs[c]["cap"]["seg"], dtype=int) for c in CANALES}
    r2 = rs["ch2"]
    dist2 = git3.DIST_US.get("ch2", app.DIST_DEFECTO_US)
    for s in range(1, n_segs + 1):
        libres = {c: set(np.nonzero(sg[c] == s)[0].tolist()) for c in CANALES}
        while any(libres.values()):
            ancla = next(c for c in PRIORIDAD if libres[c])
            ia = min(libres[ancla], key=lambda i: tc[ancla][i])
            libres[ancla].discard(ia)
            idx, multiple = {ancla: ia}, False
            for c in CANALES:
                if c == ancla:
                    continue
                cand = [i for i in libres[c] if abs(tc[c][i] - tc[ancla][ia]) <= TOL_US]
                if cand:
                    multiple |= len(cand) > 1
                    i = min(cand, key=lambda i: abs(tc[c][i] - tc[ancla][ia]))
                    idx[c] = i
                    libres[c].discard(i)
            ev = {"disparo": s, "idx": idx, "multiple": multiple, "ancla": ancla,
                  "t_abs": float(rs[ancla]["t_abs"][ia])}
            ev["categoria"] = categoria(ev, rs, r2, dist2)
            eventos.append(ev)
    eventos.sort(key=lambda e: (e["disparo"], e["t_abs"]))
    for k, e in enumerate(eventos, start=1):
        e["id"] = k
    return eventos


def categoria(ev, rs, r2, dist2):
    canales = set(ev["idx"])
    if canales == {"ch3", "ch4", "ch2"}:
        return "triple"
    if canales == {"ch3", "ch4"}:
        t2 = ev["t_abs"] + RETARDO_US["ch2"] - RETARDO_US.get(ev["ancla"], 0.0)
        ev["env_ch2"] = float(env_resonancia(r2, ev["disparo"], t2))
        s2 = np.asarray(r2["cap"]["seg"], dtype=int) == ev["disparo"]
        t_osc = rs[ev["ancla"]]["cap"]["t_peak"][ev["idx"][ev["ancla"]]] - RETARDO_US.get(ev["ancla"], 0.0)
        ev["hfct_cerca"] = bool(np.any(np.abs(_t_corr(r2)[s2] - t_osc) < dist2))
        if ev["env_ch2"] >= r2["umbral"] or t2 < git3.T_INI_US["ch2"]:
            return "antenas_resonancia"
        if ev["hfct_cerca"]:
            return "antenas_hfct_solapado"
        return "antenas_sin_hfct"
    if canales == {"ch3", "ch2"}:
        return "ch3_ch2"
    if canales == {"ch4", "ch2"}:
        return "ch4_ch2"
    return "solo_" + next(iter(canales))


def sub_captura(cap, idx):
    """Captura con solo las descargas de índices `idx` (mismas claves)."""
    n = np.asarray(cap["t_peak"]).size
    idx = np.asarray(sorted(idx), dtype=int)
    out = {}
    for k, v in cap.items():
        if isinstance(v, np.ndarray) and v.ndim >= 1 and v.shape[0] == n and k != "t_rel":
            out[k] = v[idx]
        else:
            out[k] = v
    return out


def fila_triple(d, canal, cap_t, cuentas, t_lag):
    """Fila Tabla 1 sobre las descargas triples (V̄_pp y t̄_abs en los disparos con N_PD = N_cav)."""
    c = np.asarray(cuentas)
    n_cav = d["n_cav"]
    fila = {"specimen": f"{n_cav}v" if n_cav else d["probeta"],
            "diametro": ", ".join(f"{x:g}" for x in d["diam"]) or "-",
            "voltage": f"{d['kv']:g}" if d["kv"] else "-",
            "sensor": NOMBRE_CANAL[canal],
            "distribucion": "[" + ", ".join(str(x) for x in [int(np.sum(c == k)) for k in range(5)]
                                            + [int(np.sum(c > 4))]) + "]"}
    if n_cav:
        fila["n_coinc"] = str(int(np.sum(c == n_cav)))
        ok = {s for s, k in enumerate(cuentas, start=1) if k == n_cav}
        idx = [i for i, s in enumerate(cap_t["seg"]) if int(s) in ok]
    else:
        fila["n_coinc"] = "-"
        idx = list(range(cap_t["t_peak"].size))
    if idx:
        fila["vpp_media"] = f"{float(np.mean(cap_t['vpp'][idx])) / 1000.0:.3f}"
        fila["tabs_media"] = f"{float(np.mean(app.t_abs_captura(cap_t, t_lag)[idx])):.3f}"
    else:
        fila["vpp_media"] = fila["tabs_media"] = "-"
    return fila


def analizar_medicion(d, rs):
    """Eventos, capturas triples, N_PD y filas Tabla 1 de una medición."""
    n_segs = d["nsegs"]
    ev = agrupar_eventos(rs, n_segs)
    m = {"eventos": ev, "cat_por_det": {c: {} for c in CANALES}}
    for e in ev:
        for c, i in e["idx"].items():
            m["cat_por_det"][c][i] = e
    triples = [e for e in ev if e["categoria"] == "triple"]
    m["cap_t"], m["filas"] = {}, {}
    cuentas_ref, segs = None, []
    for c in CANALES:
        cap_t = sub_captura(rs[c]["cap"], [e["idx"][c] for e in triples])
        segs, cuentas = git3._contar(cap_t, n_segs)
        assert cuentas_ref is None or cuentas == cuentas_ref, "N_PD distinto entre canales"
        cuentas_ref = cuentas
        m["cap_t"][c] = cap_t
        m["filas"][c] = fila_triple(d, c, cap_t, cuentas, rs[c]["t_lag"])
    m["segs"], m["cuentas"] = segs, cuentas_ref
    m["res_por_disparo"] = [sum(1 for e in ev if e["disparo"] == s and e["categoria"] == "antenas_resonancia")
                            for s in segs]
    m["conteo"] = {k: sum(1 for e in ev if e["categoria"] == k) for k in CATEGORIAS}
    return m


# ---------------- Mapas TRPD ----------------

def banda_resonancia(r2):
    """t_abs final (µs) del tramo inicial donde la envolvente mediana de la resonancia de CH2
    supera el umbral (None si nunca)."""
    mods = r2.get("modelo") or {}
    if not mods:
        return None
    malla = r2["malla"]
    n_env = max(1, int(round(0.07 / (malla[1] - malla[0]))))
    env = np.median([maximum_filter1d(np.abs(x.astype(float)), n_env) for x in mods.values()], axis=0)
    sobre = np.nonzero(env >= r2["umbral"])[0]
    return float(malla[sobre[-1]]) if sobre.size else None


def dibujar_mapa(ax, d, r, m, y_max, titulo=True, leyenda=True):
    canal, cap, t_abs = r["canal"], r["cap"], r["t_abs"]
    color = tema.COLORES_CANALES.get(canal, tema.ACCENT)
    t_ref, v_ref = app.promedio_impulso(d["carpeta"])
    T = app.tiempos_impulso(d["carpeta"])
    if t_ref is not None and v_ref is not None and v_ref.size:
        paso = max(1, t_ref.size // app.IMP_PUNTOS_PLOT)
        frac = v_ref[::paso] / (float(np.max(np.abs(v_ref))) or 1.0)
        ax.plot(t_ref[::paso] - ((T or {}).get("t10") or 0.0), frac * 0.9 * y_max,
                color="#c4cbd3", lw=1.0, zorder=1, label="CH1 (forma normalizada)")
    ax.axvline(0.0, color=tema.LINEA_T10, lw=0.8, ls=":", zorder=1)
    ax.axvspan(git3.X_LIM[0], git3.T_INI_US[canal], color="#eef1f5", zorder=0)
    if canal == "ch2":
        fin = banda_resonancia(r)
        if fin is not None:
            ax.axvspan(git3.T_INI_US[canal], fin, color="#fbe3c8", alpha=0.7, zorder=0,
                       label=f"resonancia HFCT ≥ umbral (hasta {fin:.2f} µs)")
    vpp = cap["vpp"] / 1000.0
    cats = np.array([m["cat_por_det"][canal][i]["categoria"] for i in range(vpp.size)])
    tri, res = cats == "triple", cats == "antenas_resonancia"
    otras = ~tri & ~res
    if tri.any():
        ax.scatter(t_abs[tri], vpp[tri], s=24, color=color, edgecolor="white", linewidth=0.4,
                   zorder=4, label=f"triple, cuenta ({tri.sum()})")
    if res.any():
        ax.scatter(t_abs[res], vpp[res], s=30, marker="x", color="#d9822b", linewidth=1.1, zorder=3,
                   label=f"CH3+CH4, HFCT oculto en resonancia? ({res.sum()}, no cuenta)")
    if otras.any():
        ax.scatter(t_abs[otras], vpp[otras], s=22, facecolor="white", edgecolor="#8a94a3",
                   linewidth=0.8, zorder=3, label=f"dudosa ({otras.sum()}, no cuenta)")
    if not vpp.size:
        ax.text(0.5, 0.5, "sin descargas", transform=ax.transAxes, ha="center", va="center",
                color="#9aa5b1", fontsize=11)
    ax.set_xlim(*git3.X_LIM)
    ax.set_ylim(0, y_max)
    ax.set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=8)
    ax.set_ylabel(f"Vpp {canal.upper()} [V]", fontsize=8)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=7)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    sub = (f"{NOMBRE_CANAL[canal]} ({canal.upper()}) · {vpp.size} detecciones · {tri.sum()} triples · "
           f"{res.sum()} en resonancia · {otras.sum()} dudosas · umbral {r['umbral']:g} mV")
    if canal in git3.RESONANCIA:
        sub += f" + {git3.RESONANCIA[canal]['k_env']:g}·resonancia"
    if titulo:
        ax.set_title(f"{d['titulo']} · set {d['set']} · {d['nsegs']} disparos", fontsize=11,
                     fontweight="bold", loc="left", pad=14)
    ax.text(0.0, 1.01, sub, transform=ax.transAxes, ha="left", va="bottom", fontsize=7, color="#5f6b7a")
    if leyenda:
        ax.legend(fontsize=6, loc="upper right", frameon=False, ncol=2)


def png_mapa(ruta, d, r, m, y_max):
    fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=150)
    dibujar_mapa(ax, d, r, m, y_max)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


# ---------------- PDF ----------------

COL_EXTRA = "Triples / Res. / Dud.\n(medición)"


def _fila_pdf(d, r, fila, m):
    dud = len(m["eventos"]) - m["conteo"]["triple"] - m["conteo"]["antenas_resonancia"]
    return ([d["probeta"], f"{r['umbral']:g}"] + [str(fila.get(k, "")) for k in git3.CLAVES_RESUMEN]
            + [f"{m['conteo']['triple']} / {m['conteo']['antenas_resonancia']} / {dud}"])


def _cols():
    return (git3.COLS_RESUMEN + [COL_EXTRA],
            [0.11, 0.05, 0.06, 0.06, 0.07, 0.07, 0.18, 0.08, 0.07, 0.07, 0.11])


def _texto_cabecera(descs, res):
    lineas = [git3._texto_parametros(c, res[c], UMBRALES[c], all(r["t_lag"] == 0.0 for r in res[c]))
              for c in CANALES]
    lineas.append(f"Cuenta una descarga solo si aparece en CH3, CH4 y CH2 (mismo disparo, ≤ {TOL_US * 1000:g} ns "
                  f"tras corregir el retardo fijo: CH4 − CH3 = {RETARDO_US['ch4'] * 1000:g} ns, "
                  f"CH2 − CH3 = {RETARDO_US['ch2'] * 1000:g} ns). N_PD, V̄_pp y t̄_abs solo con esas descargas.")
    lineas.append("Res.: en CH3 y CH4 pero no en CH2, con la resonancia del HFCT ≥ umbral en ese instante "
                  "(se dibujan, no cuentan). Dud.: el resto de descargas que no están en los 3 sensores "
                  "(ver descargas_a_revisar.txt).")
    return "\n".join(lineas + [datetime.date.today().isoformat()])


def pagina_resumen(pdf, titulo, descs, res, ms):
    texto = _texto_cabecera(descs, res)
    cols, anchos = _cols()
    por_pagina = 6
    for p0 in range(0, len(descs), por_pagina):
        fig = plt.figure(figsize=A4)
        fig.text(0.04, 0.95, titulo + (" (cont.)" if p0 else ""), fontsize=15, fontweight="bold")
        fig.text(0.04, 0.925, texto, fontsize=7.5, color="#5f6b7a", va="top", linespacing=1.45)
        filas = [_fila_pdf(d, res[c][i], ms[i]["filas"][c], ms[i])
                 for i, d in enumerate(descs) if p0 <= i < p0 + por_pagina for c in CANALES]
        alto_texto = 0.017 * (texto.count("\n") + 1)
        ax = fig.add_axes((0.03, 0.02, 0.94, 0.88 - alto_texto))
        t = git3._tabla(ax, filas, cols, tam=7.5, anchos=anchos)
        for (i, _), celda in t.get_celld().items():
            if i > 0 and ((i - 1) // len(CANALES)) % 2 == 1:
                celda.set_facecolor("#f7f8fa")
        pdf.savefig(fig)
        plt.close(fig)


def pagina_medicion(pdf, d, rs, m, y_max):
    fig = plt.figure(figsize=A4)
    alto_mapa, sep, y_top = 0.175, 0.055, 0.915
    for k, c in enumerate(CANALES):
        y0 = y_top - (k + 1) * alto_mapa - k * sep
        ax = fig.add_axes((0.07, y0, 0.89, alto_mapa))
        dibujar_mapa(ax, d, rs[c], m, y_max[c], titulo=(k == 0))
        if k < len(CANALES) - 1:
            ax.set_xlabel("")
    cols, anchos = _cols()
    ax_t = fig.add_axes((0.04, 0.115, 0.92, 0.115))
    git3._tabla(ax_t, [_fila_pdf(d, rs[c], m["filas"][c], m) for c in CANALES], cols, tam=7, anchos=anchos)
    ax_d = fig.add_axes((0.04, 0.015, 0.92, 0.075))
    git3._tabla(ax_d, [["N_PD (triples)"] + [str(x) for x in m["cuentas"]],
                       ["en resonancia"] + [str(x) for x in m["res_por_disparo"]]],
                ["Disparo"] + [str(s) for s in m["segs"]], tam=6.5)
    pdf.savefig(fig)
    plt.close(fig)


def pagina_revisar(pdf, descs, ms):
    fig = plt.figure(figsize=A4)
    fig.text(0.04, 0.95, "Descargas a revisar (no están en los 3 sensores)", fontsize=15, fontweight="bold")
    fig.text(0.04, 0.925, "Conteo de eventos por categoría. Detalle y figura temporal de cada uno en "
             "descargas_a_revisar.txt y la carpeta dudosas\\.", fontsize=8, color="#5f6b7a", va="top")
    cats = CATEGORIAS
    cortas = ["triple", "antenas\nresonancia", "antenas\nHFCT solapado", "antenas\nsin HFCT", "CH3+CH2",
              "CH4+CH2", "solo CH3", "solo CH4", "solo CH2"]
    filas = [[d["probeta"], f"{d['kv']:g}"] + [str(ms[i]["conteo"][k]) for k in cats] for i, d in enumerate(descs)]
    filas.append(["Total", ""] + [str(sum(m["conteo"][k] for m in ms)) for k in cats])
    ax = fig.add_axes((0.03, 0.03, 0.94, 0.86))
    git3._tabla(ax, filas, ["Set", "kV"] + cortas, tam=8)
    pdf.savefig(fig)
    plt.close(fig)


# ---------------- Figuras de dudosas ----------------

def _senales_disparo(d, rs, seg):
    """{canal: (t_abs, v)} del disparo; CH2 además con residuo y umbral dinámico."""
    t10 = app.t10_por_segmento(d["carpeta"])[seg - 1]
    out = {}
    for c in CANALES:
        t, v = app.cargar_segmento(d["carpeta"], c, seg)
        out[c] = (t - t10 - rs[c]["t_lag"], v)
    r2 = rs["ch2"]
    ta, v = out["ch2"]
    mod = (r2.get("modelo") or {}).get(int(seg))
    modelo = (np.interp(ta + r2["t_lag"], r2["malla"], mod.astype(float), left=0.0, right=0.0)
              if mod is not None else np.zeros_like(v))
    env = env_resonancia(r2, seg, ta + r2["t_lag"])
    out["ch2_res"] = (v - modelo, r2["umbral"] + git3.RESONANCIA["ch2"]["k_env"] * env)
    return out


def figura_dudosa(ruta, d, rs, m, seg, eventos, sen, ventana):
    """Figura temporal: contexto CH3 del disparo y CH3, CH4, CH2 en `ventana` (t_abs)."""
    fig, ejes = plt.subplots(4, 1, figsize=(8.5, 7.6), dpi=130,
                             gridspec_kw={"height_ratios": [0.8, 1.2, 1.2, 1.5]})
    ta, v = sen["ch3"]
    paso = max(1, ta.size // 6000)
    ax = ejes[0]
    ax.plot(ta[::paso], v[::paso], color=tema.COLORES_CANALES["ch3"], lw=0.5)
    ax.axvspan(*ventana, color="#fbe3c8", alpha=0.8, zorder=0)
    for e in m["eventos"]:
        if e["disparo"] == seg:
            ax.axvline(e["t_abs"], color="#2f8a4f" if e["categoria"] == "triple" else "#c0392b",
                       lw=0.6, alpha=0.7)
    ax.set_xlim(*git3.X_LIM)
    ax.set_ylabel("CH3 [mV]\n(disparo)", fontsize=7)
    ax.set_title(f"{d['ruta']} · disparo {seg} · "
                 + (f"t_abs = {eventos[0]['t_abs']:.3f} µs · {eventos[0]['categoria']}" if len(eventos) == 1
                    else f"{len(eventos)} eventos dudosos"),
                 fontsize=9, fontweight="bold", loc="left")
    for ax, c in zip(ejes[1:], CANALES):
        ta, v = sen[c]
        w = (ta >= ventana[0]) & (ta <= ventana[1])
        col = tema.COLORES_CANALES.get(c, tema.ACCENT)
        if c == "ch2":
            r, umb = sen["ch2_res"]
            ax.plot(ta[w], v[w], color="#c4cbd3", lw=0.6, label="CH2 filtrada")
            ax.plot(ta[w], r[w], color=col, lw=0.7, label="residuo (sin resonancia)")
            ax.plot(ta[w], umb[w], color="#5f6b7a", lw=0.8, ls="--", label="umbral dinámico")
            ax.legend(fontsize=6, loc="upper right", frameon=False, ncol=3)
        else:
            ax.plot(ta[w], v[w], color=col, lw=0.7)
            ax.axhline(rs[c]["umbral"], color="#5f6b7a", lw=0.8, ls="--")
        # detecciones del canal en la ventana
        rc = rs[c]
        sc = np.asarray(rc["cap"]["seg"], dtype=int) == seg
        for i in np.nonzero(sc)[0]:
            t = rc["t_abs"][i]
            if ventana[0] <= t <= ventana[1]:
                cat = m["cat_por_det"][c][i]["categoria"]
                ax.plot(t, rc["cap"]["v_peak"][i], marker="o", ms=5, mfc="none",
                        mec="#2f8a4f" if cat == "triple" else "#c0392b", mew=1.1)
        for e in eventos:
            ax.axvline(e["t_abs"], color="#c0392b", lw=0.6, ls=":")
        ax.set_xlim(*ventana)
        ax.set_ylabel(f"{NOMBRE_CANAL[c]}\n{c.upper()} [mV]", fontsize=7)
    ejes[-1].set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=8)
    for ax in ejes:
        ax.grid(True, color="#e5e7eb", lw=0.5)
        ax.tick_params(labelsize=7)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
    if len(eventos) == 1:
        fig.text(0.99, 0.005, _texto_vpp(eventos[0], rs), ha="right", va="bottom", fontsize=7, color="#5f6b7a")
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(ruta)
    plt.close(fig)


def _texto_vpp(e, rs):
    partes = []
    for c in CANALES:
        i = e["idx"].get(c)
        partes.append(f"{c.upper()} {rs[c]['cap']['vpp'][i]:.0f}" if i is not None else f"{c.upper()} —")
    txt = "Vpp [mV] " + " / ".join(partes)
    t = {c: rs[c]["cap"]["t_peak"][i] for c, i in e["idx"].items()}
    if "ch3" in t and "ch4" in t:
        txt += f"   Δt CH4−CH3 {1000 * (t['ch4'] - t['ch3']):+.1f} ns"
    if "ch3" in t and "ch2" in t:
        txt += f"   Δt CH2−CH3 {1000 * (t['ch2'] - t['ch3']):+.1f} ns"
    if "env_ch2" in e:
        txt += f"   resonancia CH2 {e['env_ch2']:.0f} mV"
    if e.get("hfct_cerca"):
        txt += "   (CH2 con otra descarga a < 0.5 µs)"
    if e["multiple"]:
        txt += "   (evento múltiple)"
    return txt


def figuras_dudosas(salida, d, rs, m):
    """Genera las figuras de los eventos dudosos y guarda en cada evento su ruta relativa."""
    dud = [e for e in m["eventos"] if e["categoria"] != "triple"]
    por_disparo = {}
    for e in dud:
        por_disparo.setdefault(e["disparo"], []).append(e)
    rel_dir = os.path.join("dudosas", d["ruta_rel"])
    os.makedirs(os.path.join(salida, rel_dir), exist_ok=True)
    for seg, evs in por_disparo.items():
        sen = _senales_disparo(d, rs, seg)
        if len(evs) > MAX_FIG_POR_DISPARO:
            t0 = min(e["t_abs"] for e in evs) - 0.3
            t1 = max(e["t_abs"] for e in evs) + 0.3
            rel = os.path.join(rel_dir, f"disp{seg:02d}_todas_{len(evs)}_dudosas.png")
            figura_dudosa(os.path.join(salida, rel), d, rs, m, seg, evs, sen, (t0, t1))
            for e in evs:
                e["figura"] = rel
            continue
        for e in evs:
            rel = os.path.join(rel_dir, f"disp{seg:02d}_t{e['t_abs']:.3f}us_{e['categoria']}.png")
            figura_dudosa(os.path.join(salida, rel), d, rs, m, seg, [e], sen,
                          (e["t_abs"] - VENTANA_FIG_US, e["t_abs"] + VENTANA_FIG_US))
            e["figura"] = rel


# ---------------- Tablas y txt ----------------

def escribir_eventos(ruta, rs, m):
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["evento_id", "disparo", "categoria", "t_abs_ref_us", "multiple"]
                   + [f"t_osc_{c}_us" for c in CANALES] + [f"vpp_{c}_mV" for c in CANALES]
                   + ["resonancia_ch2_mV", "figura"])
        for e in m["eventos"]:
            idx = e["idx"]
            w.writerow([e["id"], e["disparo"], e["categoria"], f"{e['t_abs']:.4f}", int(e["multiple"])]
                       + [f"{rs[c]['cap']['t_peak'][idx[c]]:.4f}" if c in idx else "" for c in CANALES]
                       + [f"{rs[c]['cap']['vpp'][idx[c]]:.1f}" if c in idx else "" for c in CANALES]
                       + [f"{e['env_ch2']:.1f}" if "env_ch2" in e else "", e.get("figura", "")])


def escribir_tabla_canal(ruta, r, m):
    """Tabla por detección del canal (todas), con N_PD triple del disparo, evento y categoría."""
    cap, t_abs, c = r["cap"], r["t_abs"], r["canal"]
    origen = np.asarray(cap.get("origen", np.zeros(cap["t_peak"].size, dtype=int)))
    n_pd = dict(zip(m["segs"], m["cuentas"]))
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["disparo", "n_pd_triple_disparo", "t_abs_us", "t_osc_us", "vmax_mV", "vpp_mV", "manual",
                    "evento_id", "categoria"])
        for s in m["segs"]:
            idx = np.nonzero(np.asarray(cap["seg"], dtype=int) == s)[0]
            if not idx.size:
                w.writerow([s, n_pd[s]] + [""] * 7)
            for i in idx:
                e = m["cat_por_det"][c][i]
                w.writerow([s, n_pd[s], f"{t_abs[i]:.4f}", f"{cap['t_peak'][i]:.4f}", f"{cap['v_peak'][i]:.1f}",
                            f"{cap['vpp'][i]:.1f}", int(origen[i] == 1), e["id"], e["categoria"]])


def retardo_medido(res, n):
    """Mediana (ns) de t_CH4 − t_CH3 en los eventos triples (pares a < 5 ns)."""
    dl = []
    for i in range(n):
        r3, r4 = res["ch3"][i], res["ch4"][i]
        for e in r3.get("_eventos", []):
            if e["categoria"] == "triple":
                x = 1000 * (r4["cap"]["t_peak"][e["idx"]["ch4"]] - r3["cap"]["t_peak"][e["idx"]["ch3"]])
                if abs(x) < 5:
                    dl.append(x)
    return (float(np.median(dl)), len(dl)) if dl else (None, 0)


def escribir_txt(ruta, descs, res, ms, ret):
    total = {k: sum(m["conteo"][k] for m in ms) for k in CATEGORIAS}
    L = ["DESCARGAS A REVISAR — Antena 1 (CH3) + Antena 2 (CH4) + HFCT (CH2)",
         f"Generado el {datetime.date.today().isoformat()} junto con informe_trpd_3v_4mm.pdf "
         "(TRPD_APP/generar_informe_trpd3.py)", "",
         "Criterio: una descarga cuenta solo si la ven los tres sensores en el mismo disparo, a "
         f"≤ {TOL_US * 1000:g} ns entre sí",
         f"tras corregir el retardo fijo (CH4 − CH3 = {RETARDO_US['ch4'] * 1000:g} ns, "
         f"CH2 − CH3 = {RETARDO_US['ch2'] * 1000:g} ns).",
         (f"Retardo CH4 − CH3 medido en las triples: mediana {ret[0]:+.2f} ns ({ret[1]} pares)."
          if ret[0] is not None else "Retardo CH4 − CH3: sin triples para medirlo."),
         f"Umbrales: CH3 {UMBRALES['ch3']:g} mV, CH4 {UMBRALES['ch4']:g} mV, CH2 {UMBRALES['ch2']:g} mV + "
         f"{git3.RESONANCIA['ch2']['k_env']:g}·envolvente de la resonancia",
         "  (CH2 a 65 mV porque estas mediciones se tomaron a ~0.5 V/div: el ruido del HFCT tras el HP 5 MHz",
         "   tiene máximos de 40-53 mV).",
         "3v_4mm_0: HFCT montado al revés en la medición; se usa med_proced_hfct_inv\\3v_4mm_0 (CH2 = −original,",
         "  copia hecha con TRPD_APP/invertir_canal.py). El original en med_proced no se modificó.",
         f"Detección desde t_abs = {git3.T_INI_US['ch3']:g} µs (CH3/CH4) y {git3.T_INI_US['ch2']:g} µs (CH2); "
         f"Δt CH3/CH4 {app.DIST_DEFECTO_US * 1000:g} ns, CH2 {git3.DIST_US['ch2'] * 1000:g} ns.", "",
         "Categorías (todas salvo 'triple' son dudosas y no cuentan en N_PD):"]
    L += [f"  {k:<22} {ETIQUETA_CAT[k]}" for k in CATEGORIAS]
    L += ["  'antenas_resonancia': la envolvente de la resonancia de CH2 ajustada en ese disparo es ≥ el umbral",
          "  de CH2 en el instante del evento: la descarga puede estar en el HFCT pero escondida en la resonancia.",
          "  '(CH2 con otra descarga a < 0.5 µs)': el HFCT se detecta con Δt = 0.5 µs, así que un segundo pulso",
          "  dentro de ese intervalo no se separa del primero (puede coincidir con la resonancia).",
          "  'evento múltiple': varias detecciones del mismo canal a ≤ 50 ns del ancla; se emparejó la más cercana.",
          "", "Totales: " + " · ".join(f"{k} {total[k]}" for k in CATEGORIAS), ""]
    L.append("Por medición: " + " | ".join(
        f"{d['ruta_rel']}: {ms[i]['conteo']['triple']} triples / "
        f"{len(ms[i]['eventos']) - ms[i]['conteo']['triple']} a revisar" for i, d in enumerate(descs)))
    L += ["", "Cada figura (carpeta dudosas\\) muestra el disparo completo de CH3 (arriba, con el evento",
          "en rojo y las triples en verde) y CH3, CH4 y CH2 (filtrada, residuo sin resonancia y umbral",
          "dinámico) en ±1 µs. Los círculos marcan las detecciones (verde: triple; rojo: dudosa).", ""]
    for i, d in enumerate(descs):
        m, rs = ms[i], {c: res[c][i] for c in CANALES}
        dud = [e for e in m["eventos"] if e["categoria"] != "triple"]
        L.append("=" * 100)
        L.append(f"{d['ruta']}  ({d['nsegs']} disparos · {m['conteo']['triple']} triples · "
                 f"{m['conteo']['antenas_resonancia']} en resonancia · "
                 f"{len(dud) - m['conteo']['antenas_resonancia']} otras dudosas)")
        L.append(f"  N_PD (triples) por disparo: {m['cuentas']}")
        if not dud:
            L.append("  (sin descargas dudosas)")
        fig_prev = None
        for e in dud:
            L.append(f"  disparo {e['disparo']:2d}  t_abs = {e['t_abs']:7.3f} µs  {e['categoria']:<22} "
                     + _texto_vpp(e, rs))
            if e.get("figura") != fig_prev:
                L.append(f"              figura: {e.get('figura', '')}")
                fig_prev = e.get("figura")
        L.append("")
    L += ["=" * 100, "OBSERVACIONES (automáticas, solo factuales)"] + observaciones(descs, ms)
    with open(ruta, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(L) + "\n")


def observaciones(descs, ms):
    L = []
    for probeta in sorted({d["probeta"] for d in descs}):
        filas = [(d["kv"], ms[i]) for i, d in enumerate(descs) if d["probeta"] == probeta]
        con = [kv for kv, m in filas if m["conteo"]["antenas_resonancia"]]
        if con:
            L.append(f"- {probeta}: hay eventos 'antenas_resonancia' desde {min(con):g} kV "
                     f"(en {len(con)} de {len(filas)} niveles).")
        tri = ", ".join(f"{kv:g} kV: {m['conteo']['triple']}" for kv, m in filas)
        L.append(f"- {probeta}: descargas triples por nivel → {tri}.")
        tmed = ", ".join(f"{kv:g} kV: {np.median([e['t_abs'] for e in m['eventos'] if e['categoria'] == 'triple']):.2f}"
                         for kv, m in filas if m["conteo"]["triple"])
        if tmed:
            L.append(f"- {probeta}: t_abs mediano de las triples (µs) → {tmed}.")
    # tiempos tardíos repetidos (interferencia a tiempo fijo, ver reportes/reporte1)
    tard = {}
    for i, d in enumerate(descs):
        for e in ms[i]["eventos"]:
            if e["categoria"] != "triple" and e["t_abs"] > 5:
                tard.setdefault(round(e["t_abs"], 1), set()).add(d["ruta_rel"])
    rep = {t: s for t, s in tard.items() if len(s) >= 3}
    if rep:
        L.append("- Dudosas tardías (t_abs > 5 µs) a tiempos repetidos en ≥ 3 mediciones: "
                 + "; ".join(f"{t:.1f} µs ({len(s)})" for t, s in sorted(rep.items())))
    for i, d in enumerate(descs):
        for s in ms[i]["segs"]:
            n = sum(1 for e in ms[i]["eventos"] if e["disparo"] == s)
            if n > 2 * MAX_FIG_POR_DISPARO:
                L.append(f"- {d['ruta_rel']} disparo {s}: {n} eventos en un solo disparo "
                         f"({ms[i]['cuentas'][s - 1]} triples). Registro anómalo (ráfaga continua / saturación): "
                         "revisar si se excluye, sus triples entran hoy en N_PD (columna > 4).")
    n_mult = sum(e["multiple"] for m in ms for e in m["eventos"])
    if n_mult:
        L.append(f"- {n_mult} eventos con varias detecciones de un mismo canal a ≤ 50 ns (marcados 'evento múltiple').")
    return L


# ---------------- Principal ----------------

def generar(raices, salida, solo=None, propios=None):
    propios = propios or {c: {} for c in CANALES}
    descs, res, _ = git3.calcular(raices, CANALES, dict(UMBRALES), solo, propios)
    for d in descs:
        completar_desc(d)
        d["ruta_rel"] = os.path.join(d["probeta"], os.path.basename(d["carpeta"]))
    orden = sorted(range(len(descs)), key=lambda i: (descs[i]["probeta"], descs[i]["kv"] or 0))
    descs = [descs[i] for i in orden]
    res = {c: [res[c][i] for i in orden] for c in CANALES}

    ms = []
    for i, d in enumerate(descs):
        rs = {c: res[c][i] for c in CANALES}
        m = analizar_medicion(d, rs)
        res["ch3"][i]["_eventos"] = m["eventos"]
        ms.append(m)
        print(f"{d['ruta_rel']}: " + " · ".join(f"{k} {v}" for k, v in m["conteo"].items() if v), flush=True)

    y_max = {}
    for c in CANALES:
        todos = np.concatenate([r["cap"]["vpp"] for r in res[c]]) / 1000.0
        y_max[c] = 1.05 * float(todos.max()) if todos.size else 1.0

    os.makedirs(salida, exist_ok=True)
    for i, d in enumerate(descs):
        rs = {c: res[c][i] for c in CANALES}
        print(f"figuras {i + 1}/{len(descs)}: {d['ruta_rel']}", flush=True)
        figuras_dudosas(salida, d, rs, ms[i])
        destino = os.path.join(salida, d["ruta_rel"])
        os.makedirs(destino, exist_ok=True)
        for c in CANALES:
            png_mapa(os.path.join(destino, f"trpd_{c}.png"), d, rs[c], ms[i], y_max[c])
            escribir_tabla_canal(os.path.join(destino, f"tabla_{c}.csv"), rs[c], ms[i])
        escribir_eventos(os.path.join(destino, "eventos.csv"), rs, ms[i])

    with open(os.path.join(salida, "resumen_trpd_3sensores.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ruta", "set", "canal", "umbral_mV"] + [k["name"] for k in app.COLUMNAS_DENSIDAD]
                   + ["disparos", "detecciones", "triples", "antenas_resonancia", "otras_dudosas"])
        for i, d in enumerate(descs):
            m = ms[i]
            for c in CANALES:
                r = res[c][i]
                w.writerow([d["ruta_rel"], d["probeta"], c, f"{r['umbral']:g}"]
                           + [m["filas"][c].get(k["id"], "") for k in app.COLUMNAS_DENSIDAD]
                           + [d["nsegs"], int(r["cap"]["t_peak"].size), m["conteo"]["triple"],
                              m["conteo"]["antenas_resonancia"],
                              len(m["eventos"]) - m["conteo"]["triple"] - m["conteo"]["antenas_resonancia"]])

    escribir_txt(os.path.join(salida, "descargas_a_revisar.txt"), descs, res, ms,
                 retardo_medido(res, len(descs)))

    titulo = "Patrones TRPD — CH3 + CH4 + HFCT (CH2) · solo descargas en los 3 sensores"
    ruta_pdf = os.path.join(salida, "informe_trpd_3v_4mm.pdf")
    git3._guardar_pdf(ruta_pdf, titulo,
                      [lambda pdf: pagina_resumen(pdf, titulo, descs, res, ms)]
                      + [lambda pdf, i=i: pagina_medicion(pdf, descs[i], {c: res[c][i] for c in CANALES},
                                                          ms[i], y_max)
                         for i in range(len(descs))]
                      + [lambda pdf: pagina_revisar(pdf, descs, ms)])
    print(f"Informe guardado: {ruta_pdf}")
    return descs, res, ms


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("raices", nargs="*", default=RAICES_DEFECTO)
    ap.add_argument("--salida", default=SALIDA_DEFECTO)
    ap.add_argument("--solo", default=None, help="solo las mediciones cuya ruta contenga este texto")
    ap.add_argument("--umbral-medicion", action="append", default=[], metavar="CANAL:RUTA=MV",
                    help="umbral propio de un canal para las mediciones cuya ruta contenga RUTA (repetible)")
    a = ap.parse_args()
    propios = {c: {} for c in CANALES}
    for par in a.umbral_medicion:
        canal, _, resto = par.partition(":")
        ruta, _, mv = resto.rpartition("=")
        propios[canal][ruta] = float(mv)
    generar(a.raices, a.salida, a.solo, propios)


if __name__ == "__main__":
    main()
