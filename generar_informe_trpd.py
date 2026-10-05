"""Informe PDF con los mapas TRPD y las tablas de uno o varios canales para todas las mediciones.

Cada medición (probeta × nivel de tensión) es un set de impulsos con su propio patrón
TRPD. Para cada una y cada canal se detectan los peaks, se dibuja el mapa TRPD (Vpp vs
t_abs) y se guarda una tabla por descarga, en <salida>/<raíz>/<probeta>/<X>kV/ (la misma
jerarquía que las mediciones). Además se escriben, por canal, una tabla resumen (formato
Tabla 1 del paper) y un PDF; con varios canales, también un PDF combinado con las dos
filas de la Tabla 1 por medición y los mapas de todos los sensores en la misma página.

Uso:
    python generar_informe_trpd.py [<raiz> ...] [--canales ch3 ch2] [--umbral <mV>]
                                   [--umbral-medicion <ruta>=<mV> ...] [--sin-umbrales-propios]
                                   [--salida <dir>] [--solo <subcadena de la ruta>]
--umbral y --umbral-medicion se aplican al primer canal de --canales. Una medición puede
usar un umbral propio (UMBRAL_POR_MEDICION o --umbral-medicion); el umbral usado aparece
en la tabla resumen y en cada mapa.

Detección (t_abs = t − t10 del impulso de cada disparo − t_lag):
  CH3/CH4: peaks del canal filtrado (como en la app), Δt = 50 ns, desde t_abs = 0.25 µs
    (antes llega el acoplamiento del frente del impulso, en t_abs ≈ −0.13 µs).
  CH2 (HFCT): el impulso excita la resonancia propia del sensor (~14.6 MHz, τ ≈ 250-285 ns),
    que tapa las descargas del primer µs. En cada disparo se le resta una plantilla de esa
    resonancia (mediana normalizada de los disparos sin descargas en CH3, sin el propio
    disparo), escalada y desplazada por mínimos cuadrados en t_abs = 0-0.3 µs; se detecta
    sobre el residuo con un umbral dinámico U + K·envolvente de la resonancia, desde
    t_abs = 0.2 µs, con Δt = 0.5 µs (el pulso de una descarga oscila: su segundo máximo, a
    ~75 ns, tiene ~75 % de la amplitud) y descartando los máximos que no superan al ciclo
    anterior (cola de una oscilación). Vpp se mide sobre el residuo.
  Coincidencias: dos descargas de canales distintos son la misma si están en el mismo
    disparo y a ≤ 50 ns una de otra, corregido el retardo fijo entre sensores (CH2 llega
    ~11 ns después que CH3).
Dependencias: matplotlib (requirements_reportes.txt).
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
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from scipy.ndimage import maximum_filter1d  # noqa: E402
from scipy.signal import find_peaks  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import app  # noqa: E402
import filtros  # noqa: E402
import generar_presentacion as gp  # noqa: E402  (descubrir / describir mediciones)
import tema  # noqa: E402

PROYECTO = os.path.dirname(AQUI)
RAICES_DEFECTO = [
    os.path.join(PROYECTO, "mediciones", "med_proced_confuse"),
    os.path.join(PROYECTO, "mediciones", "med_proced"),
]
SALIDA_DEFECTO = os.path.join(PROYECTO, "reportes")
NOMBRE_CANAL = {"ch2": "HFCT", "ch3": "Antena 1", "ch4": "Antena 2"}
X_LIM = (-1.0, 30.0)          # µs, común a todos los mapas

# Umbral propio (mV) por canal y medición (subcadena de la ruta relativa -> mV).
# CH3 vacío: se probó 120 mV en 1v_2mm_01 12/15/16kV, 3v_2mm3mm4mm_0 10kV y 3v_2mm3mm4mm_1
# 13/14kV, pero los pulsos extra (120-250 mV) no son descargas: el retardo CH4−CH3 es errático
# (+3…+52 ns, frente a +0.5…+0.6 ns de las descargas claras), el HFCT casi no los ve (SNR ~3)
# y su espectro no coincide con el de las descargas claras (correlación 0.5-0.7 frente a
# 0.99). Ver reportes/mediciones_a_revisar.txt.
# CH2: med_proced se midió con el HFCT a 0.5 V/div (ruido tras HP 5 MHz con máximos de
# 40-48 mV por cuantización) frente a 0.2 V/div en med_proced_confuse (5-10 mV); las
# descargas que ve la antena dan 80-125 mV y 56-200 mV respectivamente.
UMBRAL_POR_MEDICION = {
    "ch3": {},
    "ch2": {"med_proced\\1v_2mm_01": 65.0},
}
UMBRAL_DEFECTO = {"ch2": 40.0, "ch3": 250.0, "ch4": 250.0}   # mV
DIST_US = {"ch2": 0.5}                 # Δt (µs) por canal; el resto usa app.DIST_DEFECTO_US
# t_abs (µs) desde el que se detecta (relativo al t10 de cada medición, no al osciloscopio).
# CH3/CH4: el frente del impulso se acopla en t_abs ≈ −0.13 µs y oscila hasta ≈ 0; entre 0 y
# 0.25 µs solo aparecen 2 pulsos > 250 mV (1v_2mm_0 17.5kV, disparos 3 y 6, t_abs ≈ 0.07 µs)
# con espectro atípico (correlación 0.69-0.73 frente a ≥ 0.999 de las descargas claras).
# CH2: por debajo de 0.2 µs el residuo de la resta en el pico de la resonancia da falsos.
T_INI_US = {"ch2": 0.2, "ch3": 0.25, "ch4": 0.25}
# Resta de la resonancia (canales con resonancia propia excitada por el impulso).
RESONANCIA = {"ch2": {
    "ajuste_us": (0.0, 0.3),      # ventana t_abs del ajuste de escala y desplazamiento
    "malla_us": (-0.3, 3.0),      # t_abs donde se define la plantilla (fuera: residuo = señal)
    "desplaz_ns": 8.0,            # búsqueda de desplazamiento ± (paso 0.4 ns)
    "k_env": 0.1,                 # umbral = U + k_env · envolvente de la resonancia ajustada
    "min_limpios": 5,             # con menos disparos limpios se suman los del mismo set
}}
# Retardo fijo de cada sensor respecto de CH3 (µs) y tolerancia de coincidencia.
RETARDO_US = {"ch2": 0.011, "ch3": 0.0, "ch4": 0.0005}
TOL_COINC_US = 0.05
FRAC_CANDIDATO = 0.5      # candidatos bajo el umbral: máximos desde esta fracción del umbral
SIGMAS_CANDIDATO = 6.0    # ... y por encima de este nº de σ del ruido del disparo (CH2; med_proced
                          # tiene ruido de cuantización de ~40 mV, sobre 0.5 × 65 mV)
A4_APAISADO = (11.69, 8.27)
COLS_RESUMEN = ["Set", "Umbral\n(mV)", "Specimen", "d (mm)", "Voltage (kV)", "Sensor",
                "N_PD distribution\n[0, 1, 2, 3, 4, > 4]", "N_PD = N_cav", "V̄_pp (V)", "t̄_abs (µs)"]
ANCHOS_RESUMEN = [0.13, 0.06, 0.06, 0.07, 0.08, 0.07, 0.19, 0.08, 0.08, 0.08]
CLAVES_RESUMEN = ["specimen", "diametro", "voltage", "sensor", "distribucion", "n_coinc",
                  "vpp_media", "tabs_media"]


# ---------------- Cálculo ----------------

def tmin_osc(carpeta, canal):
    """t_mín (µs, tiempo del osciloscopio) equivalente a t_abs = T_INI_US del canal, con el
    t10 mediano de la medición (el t10 varía < 35 ns entre disparos)."""
    if canal not in T_INI_US:
        return app.TMIN_DEFECTO_US
    return float(np.median(app.t10_por_segmento(carpeta))) + T_INI_US[canal]


def _contar(cap, n_segs):
    segs = list(range(1, n_segs + 1))
    seg = np.asarray(cap["seg"], dtype=int)
    seg = seg[(seg >= 1) & (seg <= n_segs)]
    return segs, [int(c) for c in np.bincount(seg, minlength=n_segs + 1)[1:n_segs + 1]]


def fila_tabla1(carpeta, canal, cap, cuentas, t_lag, filtrado=True):
    """Fila Tabla 1 calculada sobre `cap` (misma regla que app.calcular_fila_densidad: V̄_pp y
    t̄_abs sobre las descargas de los disparos con N_PD = N_cav). Los campos descriptivos
    (Specimen, d, Voltage, Sensor) se toman de la app con un umbral infinito (sin peaks)."""
    fila = app.calcular_fila_densidad(carpeta, canal, np.inf, app.DIST_DEFECTO_US,
                                      app.TMIN_DEFECTO_US, filtrado=filtrado)
    c = np.asarray(cuentas)
    fila["distribucion"] = "[" + ", ".join(
        str(x) for x in [int(np.sum(c == k)) for k in range(5)] + [int(np.sum(c > 4))]) + "]"
    n_cav = fila.get("_n_cav")
    if n_cav:
        fila["n_coinc"] = str(int(np.sum(c == n_cav)))
        ok = {s for s, k in enumerate(cuentas, start=1) if k == n_cav}
        idx = [i for i, s in enumerate(cap["seg"]) if int(s) in ok]
    else:
        fila["n_coinc"] = "-"
        idx = list(range(cap["t_peak"].size))
    if idx:
        fila["vpp_media"] = f"{float(np.mean(cap['vpp'][idx])) / 1000.0:.3f}"
        fila["tabs_media"] = f"{float(np.mean(app.t_abs_captura(cap, t_lag)[idx])):.3f}"
    else:
        fila["vpp_media"] = fila["tabs_media"] = "-"
    return fila


def _sin_detectados(seg, t, v, cap):
    """Filtra (seg, t, v) quitando los que coinciden (mismo disparo, ≤ TOL_PEAK_US) con `cap`."""
    sc, tc = np.asarray(cap["seg"], dtype=int), np.asarray(cap["t_peak"], dtype=float)
    return [(int(s), float(ti), float(vi)) for s, ti, vi in zip(seg, t, v)
            if not np.any((sc == s) & (np.abs(tc - ti) <= app.TOL_PEAK_US))]


def analizar_estandar(carpeta, canal, umbral, filtrado=True):
    """Detección de la app (CH3/CH4): captura editada, fila Tabla 1, N_PD por disparo y
    candidatos bajo el umbral (máximos entre FRAC_CANDIDATO·umbral y el umbral)."""
    dist, tmin = DIST_US.get(canal, app.DIST_DEFECTO_US), tmin_osc(carpeta, canal)
    ed = app.ediciones_canal(carpeta, canal)
    cap = app.captura_editada(carpeta, canal, umbral, dist, tmin, filtrado=filtrado, ediciones=ed)
    t_lag = app.lag_canal(app.calibracion_desde_metadata(carpeta), carpeta, canal)
    fila = app.calcular_fila_densidad(carpeta, canal, umbral, dist, tmin, t_lag_us=t_lag,
                                      ediciones=ed, filtrado=filtrado)
    segs, cuentas = app.contar_peaks(carpeta, canal, umbral, dist, tmin, ediciones=ed, filtrado=filtrado)
    baja = app.capturar(carpeta, canal, FRAC_CANDIDATO * umbral, dist, tmin, filtrado=filtrado)
    cand = _sin_detectados(baja["seg"], baja["t_peak"], baja["v_peak"], cap)
    return {"canal": canal, "cap": cap, "t_abs": app.t_abs_captura(cap, t_lag), "fila": fila,
            "segs": segs, "cuentas": cuentas, "t_lag": t_lag, "umbral": umbral,
            "filtrado": filtrado, "candidatos": cand}


# --- Resta de la resonancia (CH2) ---

def malla_resonancia(carpeta, canal, filtrado=True):
    """Eje t_abs (paso de muestreo) y señales de todos los disparos interpoladas en él."""
    cfg = RESONANCIA[canal]
    dt = app.meta_medicion(carpeta)[canal]["xinc"] * 1e6
    malla = np.arange(cfg["malla_us"][0], cfg["malla_us"][1], dt)
    t10 = app.t10_por_segmento(carpeta)
    X = {}
    for s in range(1, app.n_segmentos(carpeta) + 1):
        t, v = app.cargar_segmento(carpeta, canal, s, filtrado=filtrado)
        X[s] = np.interp(malla, t - t10[s - 1], v)
    return malla, X


def _normalizar(x, malla, canal):
    a, b = RESONANCIA[canal]["ajuste_us"]
    m = (malla >= a) & (malla < b)
    return x / (float(np.max(np.abs(x[m]))) or 1.0)


def disparos_limpios(carpeta, cap_ref, t_lag_ref, malla):
    """Disparos sin descargas del canal de referencia dentro de la malla de la plantilla."""
    ta = app.t_abs_captura(cap_ref, t_lag_ref)
    sucios = {int(s) for s, t in zip(cap_ref["seg"], ta) if t < malla[-1]}
    return set(range(1, app.n_segmentos(carpeta) + 1)) - sucios


def plantilla(normalizadas, excluir=None):
    """Mediana de las señales normalizadas de los disparos limpios (sin `excluir`, salvo
    que sea el único disponible)."""
    L = [x for k, x in normalizadas if k != excluir] or [x for _, x in normalizadas]
    return np.median(np.array(L), axis=0)


def ajustar_resonancia(x, T, malla, canal):
    """(a, desplazamiento en muestras) que minimizan |x − a·T(t − d) − c|² en la ventana de ajuste."""
    cfg = RESONANCIA[canal]
    m = (malla >= cfg["ajuste_us"][0]) & (malla < cfg["ajuste_us"][1])
    dt = malla[1] - malla[0]
    paso = max(1, int(round(0.0004 / dt)))
    rango = int(round(cfg["desplaz_ns"] * 1e-3 / dt))
    mejor = None
    for d in range(-rango, rango + 1, paso):
        Ts = np.roll(T, d)[m]
        M = np.c_[Ts, np.ones(Ts.size)]
        coef, *_ = np.linalg.lstsq(M, x[m], rcond=None)
        e = float(np.sum((x[m] - M @ coef) ** 2))
        if mejor is None or e < mejor[0]:
            mejor = (e, d, float(coef[0]))
    return mejor[2], mejor[1]


def analizar_resonancia(carpeta, canal, umbral, normalizadas, limpios, malla, filtrado=True):
    """Detección sobre el residuo tras restar la resonancia (ver docstring del módulo).
    `normalizadas`: [(clave, señal normalizada)] de los disparos limpios disponibles
    (clave = (carpeta, seg)); `limpios`: disparos limpios de esta medición.
    Devuelve además `modelo` {seg: resonancia ajustada en `malla` (float32)} para poder
    reconstruir el residuo, y `candidatos` [(seg, t, v)] entre FRAC_CANDIDATO·umbral y el umbral."""
    cfg = RESONANCIA[canal]
    dist = DIST_US.get(canal, app.DIST_DEFECTO_US)
    t_ini = T_INI_US.get(canal, 0.0)
    t10 = app.t10_por_segmento(carpeta)
    dt = app.meta_medicion(carpeta)[canal]["xinc"] * 1e6
    n_antes = int(round(app.VENTANA_PD_ANTES_US / dt))
    n_desp = int(round(app.VENTANA_PD_DESP_US / dt))
    n_dist = max(1, int(round(dist / dt)))
    n_env = max(1, int(round(0.07 / dt)))          # ~1 periodo de la resonancia
    n_segs = app.n_segmentos(carpeta)
    T_comun = plantilla(normalizadas)
    W, tpk, vpk, segs, env_pk = [], [], [], [], []
    modelos, cand = {}, []
    n_colas = 0
    for s in range(1, n_segs + 1):
        t, v = app.cargar_segmento(carpeta, canal, s, filtrado=filtrado)
        ta = t - t10[s - 1]
        T = plantilla(normalizadas, (carpeta, s)) if s in limpios else T_comun
        x = np.interp(malla, ta, v)
        a, d = ajustar_resonancia(x, T, malla, canal)
        Td = np.roll(T, d)
        modelos[s] = (a * Td).astype(np.float32)
        modelo = a * np.interp(ta, malla, Td, left=0.0, right=0.0)
        env = abs(a) * np.interp(ta, malla, maximum_filter1d(np.abs(Td), n_env), left=0.0, right=0.0)
        r = v - modelo
        umb = umbral + cfg["k_env"] * env
        idx, _ = find_peaks(r, height=umb, distance=n_dist)
        tardio = r[ta >= 5.0] if np.any(ta >= 5.0) else r
        sigma = 1.4826 * float(np.median(np.abs(tardio - np.median(tardio))))
        baja, _ = find_peaks(r, height=np.maximum(FRAC_CANDIDATO * umb, SIGMAS_CANDIDATO * sigma),
                             distance=n_dist)
        cand += [(s, float(t[i]), float(r[i])) for i in baja[ta[baja] >= t_ini] if r[i] < umb[i]]
        for i in idx[ta[idx] >= t_ini]:
            a0, b0 = i - n_antes, i + n_desp + 1
            if a0 < 0 or b0 > r.size:
                continue
            previo = r[max(0, i - int(round(0.10 / dt))):max(0, i - int(round(0.03 / dt)))]
            if previo.size and previo.max() >= r[i]:
                n_colas += 1      # cola de una oscilación anterior, no un pulso nuevo
                continue
            W.append(r[a0:b0]); tpk.append(t[i]); vpk.append(r[i]); segs.append(s); env_pk.append(env[i])
    seg_arr = np.array(segs, dtype=int)
    W_arr = np.array(W) if W else np.empty((0, n_antes + n_desp + 1))
    cap = {"t_rel": np.arange(-n_antes, n_desp + 1) * dt, "W": W_arr,
           "t_peak": np.array(tpk), "v_peak": np.array(vpk),
           "vpp": np.ptp(W_arr, axis=1) if W_arr.size else np.array([]),
           "seg": seg_arr, "t10_seg": t10[seg_arr - 1] if seg_arr.size else np.array([]),
           "dt_us": dt, "env": np.array(env_pk)}
    ed = app.ediciones_canal(carpeta, canal)
    cap = app.aplicar_ediciones(cap, carpeta, canal, ed if app._hay_ediciones(ed) else None, filtrado)
    t_lag = app.lag_canal(app.calibracion_desde_metadata(carpeta), carpeta, canal)
    segs_l, cuentas = _contar(cap, n_segs)
    return {"canal": canal, "cap": cap, "t_abs": app.t_abs_captura(cap, t_lag),
            "fila": fila_tabla1(carpeta, canal, cap, cuentas, t_lag, filtrado), "segs": segs_l,
            "cuentas": cuentas, "t_lag": t_lag, "umbral": umbral, "n_colas": n_colas,
            "n_limpios": len(limpios), "filtrado": filtrado, "malla": malla, "modelo": modelos,
            "candidatos": _sin_detectados([c[0] for c in cand], [c[1] for c in cand],
                                          [c[2] for c in cand], cap)}


def coincidencias(ra, rb):
    """Máscara de las descargas de `ra` con pareja en `rb` (mismo disparo y
    |(t_a − ret_a) − (t_b − ret_b)| ≤ TOL_COINC_US, en tiempo del osciloscopio)."""
    ca, cb = ra["cap"], rb["cap"]
    ta = ca["t_peak"] - RETARDO_US.get(ra["canal"], 0.0)
    tb = cb["t_peak"] - RETARDO_US.get(rb["canal"], 0.0)
    sb = np.asarray(cb["seg"], dtype=int)
    return np.array([bool(np.any((sb == s) & (np.abs(tb - t) <= TOL_COINC_US)))
                     for s, t in zip(np.asarray(ca["seg"], dtype=int), ta)], dtype=bool)


def escribir_tabla_descargas(ruta, r):
    """CSV con una fila por descarga (y una fila vacía por disparo sin descargas)."""
    cap, t_abs = r["cap"], r["t_abs"]
    n = cap["t_peak"].size
    origen = np.asarray(cap.get("origen", np.zeros(n, dtype=int)))
    env = cap.get("env")
    otros = sorted(r.get("en", {}))
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["disparo", "n_pd_disparo", "t_abs_us", "t_osc_us", "vmax_mV", "vpp_mV", "manual"]
                   + (["resonancia_mV"] if env is not None else []) + [f"en_{o}" for o in otros])
        for s, k in zip(r["segs"], r["cuentas"]):
            idx = np.nonzero(cap["seg"] == s)[0]
            if not idx.size:
                w.writerow([s, 0, "", "", "", "", ""] + ([""] if env is not None else []) + [""] * len(otros))
            for i in idx:
                w.writerow([s, k, f"{t_abs[i]:.4f}", f"{cap['t_peak'][i]:.4f}", f"{cap['v_peak'][i]:.1f}",
                            f"{cap['vpp'][i]:.1f}", int(origen[i] == 1)]
                           + ([f"{env[i]:.1f}" if origen[i] != 1 and i < env.size else ""] if env is not None else [])
                           + [int(r["en"][o][i]) for o in otros])


# ---------------- Figuras ----------------

def dibujar_trpd(ax, carpeta, r, d, y_max, titulo=True):
    canal, cap, t_abs = r["canal"], r["cap"], r["t_abs"]
    color = tema.COLORES_CANALES.get(canal, tema.ACCENT)
    # Referencia: forma normalizada del impulso CH1 promedio, con t10 en t_abs = 0.
    t_ref, v_ref = app.promedio_impulso(carpeta)
    T = app.tiempos_impulso(carpeta)
    if t_ref is not None and v_ref is not None and v_ref.size:
        paso = max(1, t_ref.size // app.IMP_PUNTOS_PLOT)
        frac = v_ref[::paso] / (float(np.max(np.abs(v_ref))) or 1.0)
        ax.plot(t_ref[::paso] - ((T or {}).get("t10") or 0.0), frac * 0.9 * y_max,
                color="#c4cbd3", lw=1.0, zorder=1, label="CH1 (forma normalizada)")
    ax.axvline(0.0, color=tema.LINEA_T10, lw=0.8, ls=":", zorder=1)
    if canal in T_INI_US:
        ax.axvspan(X_LIM[0], T_INI_US[canal], color="#eef1f5", zorder=0,
                   label=f"sin detección (t_abs < {T_INI_US[canal]:g} µs)")
    vpp = cap["vpp"] / 1000.0
    manual = np.asarray(cap.get("origen", np.zeros(vpp.size, dtype=int))) == 1
    otros = sorted(r.get("en", {}))
    if vpp.size and otros:
        en_otro = np.any([r["en"][o] for o in otros], axis=0)
        nombres = "/".join(o.upper() for o in otros)
        for m, cara, etiqueta in ((en_otro & ~manual, color, f"Vpp {canal.upper()} (también en {nombres})"),
                                  (~en_otro & ~manual, "white", f"Vpp {canal.upper()} (solo {canal.upper()})")):
            if m.any():
                ax.scatter(t_abs[m], vpp[m], s=24, facecolor=cara, edgecolor=color, linewidth=0.9,
                           alpha=0.9, zorder=3, label=etiqueta)
    elif vpp.size:
        ax.scatter(t_abs[~manual], vpp[~manual], s=22, color=color, alpha=0.8, zorder=3,
                   edgecolor="white", linewidth=0.4, label=f"Vpp {canal.upper()}")
    if vpp.size and manual.any():
        ax.scatter(t_abs[manual], vpp[manual], s=34, marker="D", color=color, zorder=3,
                   edgecolor="black", linewidth=0.5, label="manual")
    if not vpp.size:
        ax.text(0.5, 0.5, "sin descargas", transform=ax.transAxes, ha="center", va="center",
                color="#9aa5b1", fontsize=12)
    ax.set_xlim(*X_LIM)
    ax.set_ylim(0, y_max)
    ax.set_xlabel("t_abs [µs] (t10 del impulso = 0)", fontsize=9)
    ax.set_ylabel(f"Vpp {canal.upper()} [V]", fontsize=9)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=8)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    sub = f"{NOMBRE_CANAL.get(canal, canal)} ({canal.upper()}) · {vpp.size} descargas · umbral {r['umbral']:g} mV"
    if canal in RESONANCIA:
        sub += f" + {RESONANCIA[canal]['k_env']:g}·resonancia"
    for o in otros:
        sub += f" · {int(r['en'][o].sum())} en {o.upper()}"
    if titulo:
        ax.set_title(f"{d['titulo']} · set {d['set']} · {d['nsegs']} disparos", fontsize=11,
                     fontweight="bold", loc="left", pad=16)
    ax.text(0.0, 1.01, sub, transform=ax.transAxes, ha="left", va="bottom", fontsize=8, color="#5f6b7a")
    ax.legend(fontsize=7, loc="upper right", frameon=False)


def png_trpd(ruta, carpeta, r, d, y_max):
    fig, ax = plt.subplots(figsize=(7.5, 4.4), dpi=150)
    dibujar_trpd(ax, carpeta, r, d, y_max)
    fig.tight_layout()
    fig.savefig(ruta)
    plt.close(fig)


def _tabla(ax, filas, columnas, tam=8, anchos=None):
    ax.axis("off")
    t = ax.table(cellText=filas, colLabels=columnas, loc="upper center", cellLoc="center",
                 colWidths=anchos)
    t.auto_set_font_size(False)
    t.set_fontsize(tam)
    t.scale(1, 1.35)
    for (i, _), celda in t.get_celld().items():
        celda.set_edgecolor("#d9dee5")
        if i == 0:
            celda.set_facecolor("#eef1f5")
            celda.set_text_props(fontweight="bold")
    return t


def _texto_coinc(r):
    """'a / n' por cada otro canal: a descargas de r con pareja en ese canal, de n."""
    n = r["cap"]["t_peak"].size
    return " · ".join(f"{int(r['en'][o].sum())} / {n}" for o in sorted(r.get("en", {})))


def _cols_resumen(res):
    otros = sorted(next((r["en"] for r in res if r.get("en")), {}))
    if not otros:
        return COLS_RESUMEN, ANCHOS_RESUMEN
    return (COLS_RESUMEN + [f"En {'/'.join(o.upper() for o in otros)}\n(a / n)*"],
            [0.12, 0.05, 0.06, 0.07, 0.07, 0.07, 0.18, 0.08, 0.07, 0.07, 0.08])


def _fila_resumen(d, r):
    fila = r["fila"]
    return ([d["probeta"], f"{r['umbral']:g}"] + [str(fila.get(k, "")) for k in CLAVES_RESUMEN]
            + ([_texto_coinc(r)] if r.get("en") else []))


def _texto_parametros(canal, res, umbral, t_lag_cero):
    """Líneas con los parámetros de detección de un canal (cabecera del resumen)."""
    propios = sorted({r["umbral"] for r in res if r["umbral"] != umbral})
    filtro = filtros.etiqueta(app.spec_filtro(res[0]["carpeta"], canal)) if res else ""
    txt = (f"{NOMBRE_CANAL.get(canal, canal)} ({canal.upper()}): umbral {umbral:g} mV"
           + (f" ({', '.join(f'{u:g}' for u in propios)} mV en "
              f"{sum(r['umbral'] != umbral for r in res)} mediciones)" if propios else "")
           + f" · Δt {DIST_US.get(canal, app.DIST_DEFECTO_US) * 1000:g} ns · {filtro} · ventana 70 ns"
           + f" · detección desde t_abs = {T_INI_US.get(canal, 0):g} µs")
    if canal in RESONANCIA:
        cfg = RESONANCIA[canal]
        txt += (f"\n    resonancia restada (plantilla ajustada en t_abs = {cfg['ajuste_us'][0]:g}-"
                f"{cfg['ajuste_us'][1]:g} µs) · umbral dinámico U + {cfg['k_env']:g}·envolvente · "
                f"{sum(r.get('n_colas', 0) for r in res)} colas de oscilación descartadas")
    return txt + (" · t_lag = 0 (sin calibrar)" if t_lag_cero else "")


FILAS_POR_PAGINA = 20


def pagina_resumen(pdf, titulo, descs, filas_por_canal, umbrales):
    """Tabla 1 con una fila por medición y canal (en el orden de `filas_por_canal`), en
    tantas páginas como hagan falta (sin partir una medición entre páginas)."""
    canales = list(filas_por_canal)
    lineas = [_texto_parametros(c, filas_por_canal[c], umbrales[c],
                                all(r["t_lag"] == 0.0 for r in filas_por_canal[c])) for c in canales]
    if any(r.get("en") for c in canales for r in filas_por_canal[c]):
        lineas.append(f"* a / n: de las n descargas del sensor, a tienen pareja en el otro (mismo disparo, "
                      f"≤ {TOL_COINC_US * 1000:g} ns tras corregir el retardo fijo; CH2 − CH3 = "
                      f"{RETARDO_US['ch2'] * 1000:g} ns)")
    texto = "\n".join(lineas + [datetime.date.today().isoformat()])
    cols, anchos = _cols_resumen([r for c in canales for r in filas_por_canal[c]])
    por_pagina = max(1, FILAS_POR_PAGINA // len(canales))
    for p0 in range(0, len(descs), por_pagina):
        fig = plt.figure(figsize=A4_APAISADO)
        fig.text(0.04, 0.95, titulo + (" (cont.)" if p0 else ""), fontsize=18, fontweight="bold")
        fig.text(0.04, 0.925, texto, fontsize=8, color="#5f6b7a", va="top", linespacing=1.45)
        filas = [_fila_resumen(d, filas_por_canal[c][i])
                 for i, d in enumerate(descs) if p0 <= i < p0 + por_pagina for c in canales]
        alto_texto = 0.018 * (texto.count("\n") + 1)
        ax = fig.add_axes((0.03, 0.02, 0.94, 0.89 - alto_texto))
        t = _tabla(ax, filas, cols, tam=8, anchos=anchos)
        if len(canales) > 1:   # separar visualmente las mediciones
            for (i, _), celda in t.get_celld().items():
                if i > 0 and ((i - 1) // len(canales)) % 2 == 1:
                    celda.set_facecolor("#f7f8fa")
        pdf.savefig(fig)
        plt.close(fig)


def pagina_medicion(pdf, carpeta, rs, d, y_max):
    """Una página por medición: un mapa TRPD por canal, la Tabla 1 y N_PD por disparo."""
    n = len(rs)
    fig = plt.figure(figsize=A4_APAISADO)
    alto_tablas = 0.13 + 0.05 * n
    alto_mapa = (0.90 - alto_tablas - 0.07 * n) / n
    for k, r in enumerate(rs):
        y0 = 0.93 - (k + 1) * alto_mapa - k * 0.07 - (0.02 if k == 0 else 0.0)
        ax = fig.add_axes((0.07, y0, 0.89, alto_mapa))
        dibujar_trpd(ax, carpeta, r, d, y_max[r["canal"]], titulo=(k == 0))
        if k < n - 1:
            ax.set_xlabel("")
    cols, anchos = _cols_resumen(rs)
    ax_t = fig.add_axes((0.04, 0.035 + 0.035 * (n + 1), 0.92, 0.035 * (n + 1)))
    _tabla(ax_t, [_fila_resumen(d, r) for r in rs], cols, tam=8, anchos=anchos)
    ax_d = fig.add_axes((0.04, 0.02, 0.92, 0.03 * (n + 1)))
    _tabla(ax_d, [[r["canal"].upper()] + [str(c) for c in r["cuentas"]] for r in rs],
           ["N_PD"] + [str(s) for s in rs[0]["segs"]], tam=7)
    pdf.savefig(fig)
    plt.close(fig)


def _guardar_pdf(ruta_pdf, titulo, paginas):
    tmp = ruta_pdf + ".tmp"
    with PdfPages(tmp) as pdf:
        for p in paginas:
            p(pdf)
        info = pdf.infodict()
        info["Title"] = titulo
        info["CreationDate"] = datetime.datetime.now()
    os.replace(tmp, ruta_pdf)   # sin archivos a medias si se interrumpe


# ---------------- Principal ----------------

def umbral_de(ruta, umbral, propios):
    """Umbral (mV) de una medición: el propio si su ruta contiene una clave de `propios`."""
    ruta = ruta.replace("/", "\\").lower()
    return next((float(u) for k, u in (propios or {}).items()
                 if k.replace("/", "\\").lower() in ruta), float(umbral))


def _referencia(canal, canales):
    """Canal cuyas descargas definen los disparos limpios para la plantilla de resonancia."""
    return next((c for c in canales if c != canal and c not in RESONANCIA), "ch3")


def calcular(raices, canales=("ch3", "ch2"), umbrales=None, solo=None, propios=None, filtrado=True):
    """Detección de todos los canales en todas las mediciones (sin escribir nada).
    Devuelve (descs, res, umbrales): descs de generar_presentacion.describir (+ 'carpeta') y
    res {canal: [resultado por medición]} con las coincidencias entre canales en r['en'].
    `umbrales` {canal: mV} y `propios` {canal: {ruta: mV}} sustituyen a los de defecto;
    `filtrado=False` detecta sobre la señal cruda del osciloscopio (sin filtros digitales)."""
    canales = list(canales)
    umbrales = {c: (umbrales or {}).get(c, UMBRAL_DEFECTO[c]) for c in canales}
    propios = propios if propios is not None else UMBRAL_POR_MEDICION
    meds = gp.descubrir(raices, solo)
    if not meds:
        raise SystemExit(f"No hay mediciones en {raices}" + (f" que contengan '{solo}'" if solo else ""))
    descs = []
    for probeta, _, carpeta, inf, raiz in meds:
        d = gp.describir(carpeta, inf, os.path.dirname(raiz) if raiz.endswith(probeta) else raiz)
        d["carpeta"] = carpeta
        descs.append(d)

    res = {c: [None] * len(descs) for c in canales}
    estandar = [c for c in canales if c not in RESONANCIA]
    for c in [c for c in canales if c in RESONANCIA]:
        ref = _referencia(c, canales)
        if ref not in estandar:
            estandar.append(ref)           # hace falta para elegir los disparos limpios
    aux = {c: [None] * len(descs) for c in estandar if c not in canales}
    for i, d in enumerate(descs, start=1):
        print(f"medición {i}/{len(descs)}: {d['ruta']}", flush=True)
        for c in estandar:
            r = analizar_estandar(d["carpeta"], c, umbral_de(d["ruta"], umbrales.get(c, UMBRAL_DEFECTO[c]),
                                                             propios.get(c)), filtrado)
            r["carpeta"] = d["carpeta"]
            (res if c in res else aux)[c][i - 1] = r

    for c in [c for c in canales if c in RESONANCIA]:
        ref = _referencia(c, canales)
        refs = res.get(ref) or aux[ref]
        datos = []    # (malla, X, limpios) por medición
        for d, rr in zip(descs, refs):
            malla, X = malla_resonancia(d["carpeta"], c, filtrado)
            datos.append((malla, X, disparos_limpios(d["carpeta"], rr["cap"], rr["t_lag"], malla)))
        for i, d in enumerate(descs):
            malla, X, limpios = datos[i]
            norm = [((d["carpeta"], s), _normalizar(X[s], malla, c)) for s in sorted(limpios)]
            if len(norm) < RESONANCIA[c]["min_limpios"]:   # completar con el mismo set
                for j, d2 in enumerate(descs):
                    m2, X2, l2 = datos[j]
                    if j != i and d2["probeta"] == d["probeta"] and m2.size == malla.size:
                        norm += [((d2["carpeta"], s), _normalizar(X2[s], m2, c)) for s in sorted(l2)]
            if not norm:   # sin disparos limpios: mediana de todos
                norm = [((d["carpeta"], s), _normalizar(x, malla, c)) for s, x in X.items()]
            u = umbral_de(d["ruta"], umbrales[c], propios.get(c))
            print(f"  {c} {d['ruta']}: resta de resonancia ({len(limpios)} disparos limpios, "
                  f"plantilla con {len(norm)})", flush=True)
            r = analizar_resonancia(d["carpeta"], c, u, norm, limpios, malla, filtrado)
            r["carpeta"] = d["carpeta"]
            res[c][i] = r

    if len(canales) > 1:
        for i in range(len(descs)):
            for a in canales:
                res[a][i]["en"] = {b: coincidencias(res[a][i], res[b][i]) for b in canales if b != a}
    return descs, res, umbrales


def generar(raices, salida, canales=("ch3", "ch2"), umbrales=None, solo=None, propios=None):
    """calcular() + PNG/CSV por medición y canal, PDF por canal y PDF combinado."""
    canales = list(canales)
    descs, res, umbrales = calcular(raices, canales, umbrales, solo, propios)
    y_max = {}
    for c in canales:
        todos = np.concatenate([r["cap"]["vpp"] for r in res[c]]) / 1000.0
        y_max[c] = 1.05 * float(todos.max()) if todos.size else 1.0

    for c in canales:
        for d, r in zip(descs, res[c]):
            destino = os.path.join(salida, d["ruta"])
            os.makedirs(destino, exist_ok=True)
            png_trpd(os.path.join(destino, f"trpd_{c}.png"), d["carpeta"], r, d, y_max[c])
            escribir_tabla_descargas(os.path.join(destino, f"tabla_{c}.csv"), r)
        with open(os.path.join(salida, f"resumen_trpd_{c}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            otros = [o for o in canales if o != c]
            w.writerow(["ruta", "set", "umbral_mV"] + [k["name"] for k in app.COLUMNAS_DENSIDAD]
                       + ["disparos", "descargas"] + [f"en_{o}" for o in otros])
            for d, r in zip(descs, res[c]):
                w.writerow([d["ruta"], d["probeta"], f"{r['umbral']:g}"]
                           + [r["fila"].get(k["id"], "") for k in app.COLUMNAS_DENSIDAD]
                           + [d["nsegs"], int(r["cap"]["t_peak"].size)]
                           + [int(r["en"][o].sum()) for o in otros])
        titulo = f"Patrones TRPD — {NOMBRE_CANAL.get(c, c)} ({c.upper()})"
        ruta_pdf = os.path.join(salida, f"informe_trpd_{c}.pdf")
        _guardar_pdf(ruta_pdf, titulo,
                     [lambda pdf, c=c, titulo=titulo: pagina_resumen(pdf, titulo, descs, {c: res[c]}, umbrales)]
                     + [lambda pdf, i=i, c=c: pagina_medicion(pdf, descs[i]["carpeta"], [res[c][i]], descs[i], y_max)
                        for i in range(len(descs))])
        print(f"Informe guardado: {ruta_pdf}")

    if len(canales) > 1:
        titulo = "Patrones TRPD — " + " + ".join(f"{NOMBRE_CANAL.get(c, c)} ({c.upper()})" for c in canales)
        ruta_pdf = os.path.join(salida, f"informe_trpd_{'_'.join(canales)}.pdf")
        _guardar_pdf(ruta_pdf, titulo,
                     [lambda pdf: pagina_resumen(pdf, titulo, descs, res, umbrales)]
                     + [lambda pdf, i=i: pagina_medicion(pdf, descs[i]["carpeta"], [res[c][i] for c in canales],
                                                         descs[i], y_max)
                        for i in range(len(descs))])
        print(f"Informe combinado guardado: {ruta_pdf}")
    return res


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("raices", nargs="*", default=RAICES_DEFECTO)
    ap.add_argument("--canales", nargs="+", default=["ch3", "ch2"], choices=["ch2", "ch3", "ch4"],
                    help="canales del informe; con varios se genera además el PDF combinado")
    ap.add_argument("--umbral", type=float, default=None,
                    help="umbral (mV) del primer canal (por defecto UMBRAL_DEFECTO)")
    ap.add_argument("--umbral-medicion", action="append", default=[], metavar="RUTA=MV",
                    help="umbral propio del primer canal para las mediciones cuya ruta contenga RUTA "
                         "(se suma a UMBRAL_POR_MEDICION; repetible)")
    ap.add_argument("--sin-umbrales-propios", action="store_true",
                    help="ignorar UMBRAL_POR_MEDICION (mismo umbral en todas)")
    ap.add_argument("--salida", default=SALIDA_DEFECTO)
    ap.add_argument("--solo", default=None, help="solo las mediciones cuya ruta contenga este texto")
    a = ap.parse_args()
    primero = a.canales[0]
    propios = {c: ({} if a.sin_umbrales_propios else dict(UMBRAL_POR_MEDICION.get(c, {})))
               for c in a.canales}
    for par in a.umbral_medicion:
        ruta, _, mv = par.rpartition("=")
        propios[primero][ruta] = float(mv)
    generar(a.raices, a.salida, a.canales, {primero: a.umbral} if a.umbral is not None else None,
            a.solo, propios)


if __name__ == "__main__":
    main()
