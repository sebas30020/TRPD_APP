"""Análisis adicionales sobre las descargas del reporte 4 (plan: archivos_md/plan_analisis_reporte4.md).

Lee las mismas mediciones que generar_reporte4.py (reportes/reporte4/mediciones_listas.txt),
reproducidas solo desde su metadata.yaml (trigger guardado, ediciones de peaks y segmentos
excluidos; t_abs = t_peak − t10 del disparo, t_lag = 0), y añade:

  A1  tensión instantánea de cada descarga (CH1 suavizado 50 ns, leído en t_peak) e incepción
  A2  emparejamiento entre sensores (CH3↔CH4 y HFCT) y localización exploratoria
  A3  probabilidad de descarga vs tensión de pico (logística y Weibull, IC 95 % por bootstrap)
  A4  intervalos entre descargas en disparos con N_PD = 3
  A5  tendencias disparo a disparo dentro de cada nivel (Spearman, con corrección BH)

Toda tensión del impulso se expresa en V a la salida del divisor (no hay razón del divisor);
V_p es el máximo de la señal del sensor en el peak marcado (no Vpp). No modifica el reporte 4.

Salidas en reportes/reporte4/analisis/:
  descargas.csv, disparos.csv, controles.csv
  informe_analisis.pdf (informe_analisis_parcial.pdf si se usa --solo)
  A1_tension_instantanea/  A2_emparejamiento/  A3_probabilidad/  A4_intervalos/  A5_tendencias/

Uso:
    python analisis_reporte4.py [--solo A1 A3 ...] [--reporte <dir>] [--salida <dir>] [--n-boot N]
"""

import argparse
import ast
import csv
import os
import sys
import textwrap
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
import numpy as np  # noqa: E402
from scipy import optimize, stats  # noqa: E402
from scipy.ndimage import uniform_filter1d  # noqa: E402
from scipy.special import expit  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

PROYECTO = os.path.dirname(AQUI)
REPORTE4 = os.path.join(PROYECTO, "reportes", "reporte4")
A4 = (11.69, 8.27)   # apaisado, pulgadas (como el reporte 4)

ANALISIS = ("A1", "A2", "A3", "A4", "A5")
ORDEN_EJECUCION = ("A1", "A5", "A3", "A2", "A4")
SUBCARPETAS = {"A1": "A1_tension_instantanea", "A2": "A2_emparejamiento", "A3": "A3_probabilidad",
               "A4": "A4_intervalos", "A5": "A5_tendencias"}
TITULOS = {"A1": "A1 · Tensión instantánea de cada descarga", "A2": "A2 · Emparejamiento entre sensores",
           "A3": "A3 · Probabilidad de descarga vs tensión", "A4": "A4 · Intervalos dentro del disparo",
           "A5": "A5 · Tendencias dentro del nivel"}

CANALES = ("ch2", "ch3", "ch4")
SENSORES = {"ch2": "HFCT", "ch3": "Antena 1", "ch4": "Antena 2"}
CANAL_REF = "ch3"            # Antena 1: la que más detecta, referencia para conclusiones
VENTANA_SUAV_NS = 50.0       # media móvil de CH1
VENTANA_ALT_NS = 20.0        # ventana alternativa (efecto del suavizado)
DUDOSO_REL = 0.05            # U_pico a más de 5 % de la mediana del nivel → ch1_dudoso
TOL34_NS = 5.0               # emparejamiento Antena 1 ↔ Antena 2
TOL2_NS = 15.0               # emparejamiento HFCT ↔ evento de antenas (tras restar el desfase)
MIN_INTERVALO_NS = 30.0      # intervalos menores: posibles duplicados de antena
N_BOOT = 1000
SEMILLA = 20261012
DECIMADO_CURVA = 10          # muestras de CH1 suavizado que se guardan para A1 (1 de cada 10)
FILAS_TABLA = 26


# =====================================================================================
# Funciones puras (sin datos reales; cubiertas por tests/test_analisis_reporte4.py)
# =====================================================================================

def suavizar(v, n):
    """Media móvil centrada de n muestras (bordes: valor más cercano)."""
    v = np.asarray(v, dtype=float)
    n = int(max(1, round(n)))
    return v.copy() if n <= 1 else uniform_filter1d(v, size=n, mode="nearest")


def pico_impulso(t, vs):
    """(U_pico, t_pico) del impulso suavizado."""
    i = int(np.argmax(vs))
    return float(vs[i]), float(t[i])


def tension_instantanea(t, vs, t_peak):
    """Tensión suavizada interpolada en los instantes t_peak (misma unidad que vs)."""
    return np.interp(np.asarray(t_peak, dtype=float), np.asarray(t, dtype=float), np.asarray(vs, dtype=float))


def tiempo_cruce(t, vs, u):
    """Primer instante del frente (antes del máximo) en que vs alcanza u; NaN si no llega."""
    t, vs = np.asarray(t, dtype=float), np.asarray(vs, dtype=float)
    i_max = int(np.argmax(vs))
    idx = np.nonzero(vs[:i_max + 1] >= u)[0]
    if not idx.size:
        return float("nan")
    i = int(idx[0])
    if i == 0:
        return float(t[0])
    return float(np.interp(u, [vs[i - 1], vs[i]], [t[i - 1], t[i]]))


def emparejar(ta, tb, tol):
    """Asignación húngara por cercanía temporal: maximiza el nº de parejas con |ta − tb| ≤ tol
    y, entre ellas, minimiza la suma de |ta − tb|. Devuelve [(i, j), ...] ordenado por i."""
    ta, tb = np.asarray(ta, dtype=float), np.asarray(tb, dtype=float)
    if not ta.size or not tb.size:
        return []
    c = np.abs(ta[:, None] - tb[None, :])
    grande = 1e6 * (float(c.max()) + tol + 1.0)
    fi, co = optimize.linear_sum_assignment(np.where(c <= tol, c, grande))
    return sorted((int(i), int(j)) for i, j in zip(fi, co) if c[i, j] <= tol)


def eventos_disparo(t, desfase2, tol34, tol2):
    """Agrupa las descargas de un disparo en eventos físicos.

    t: {canal: array de t_peak} (µs). 1) CH3↔CH4 por cercanía (tol34); 2) CH2 − desfase2 se
    empareja con el tiempo medio de antenas de cada evento (tol2). Lo no emparejado queda como
    evento de un solo sensor. Devuelve una lista ordenada por t_ref de dicts
    {"ch2": i|None, "ch3": i|None, "ch4": i|None, "t_ref": µs}."""
    vacio = np.array([], dtype=float)
    t3 = np.asarray(t.get("ch3", vacio), dtype=float)
    t4 = np.asarray(t.get("ch4", vacio), dtype=float)
    t2 = np.asarray(t.get("ch2", vacio), dtype=float)
    ev = []
    pares = emparejar(t3, t4, tol34)
    libres3, libres4 = set(range(t3.size)), set(range(t4.size))
    for i, j in pares:
        ev.append({"ch2": None, "ch3": i, "ch4": j})
        libres3.discard(i)
        libres4.discard(j)
    ev += [{"ch2": None, "ch3": i, "ch4": None} for i in sorted(libres3)]
    ev += [{"ch2": None, "ch3": None, "ch4": j} for j in sorted(libres4)]
    for e in ev:
        ts = ([t3[e["ch3"]]] if e["ch3"] is not None else []) + ([t4[e["ch4"]]] if e["ch4"] is not None else [])
        e["t_ref"] = float(np.mean(ts))
    t2c = t2 - desfase2
    libres2 = set(range(t2.size))
    for i, k in emparejar(t2c, [e["t_ref"] for e in ev], tol2):
        ev[k]["ch2"] = i
        libres2.discard(i)
    ev += [{"ch2": i, "ch3": None, "ch4": None, "t_ref": float(t2c[i])} for i in sorted(libres2)]
    return sorted(ev, key=lambda e: e["t_ref"])


def _logistica(x, a, b):
    return expit((np.asarray(x, dtype=float) - a) / b)


def _weibull(x, a, b):
    return -np.expm1(-np.power(np.clip(np.asarray(x, dtype=float) / a, 0.0, None), b))


MODELOS = {"logistica": _logistica, "weibull": _weibull}


def _parametros(modelo, theta, x_ref):
    """(a, b) desde theta con límites que evitan degeneraciones (datos separables)."""
    if modelo == "logistica":
        span = x_ref[1]
        return float(theta[0]), float(np.exp(np.clip(theta[1], np.log(1e-3 * span), np.log(10.0 * span))))
    xmax = x_ref[0]
    a = float(np.exp(np.clip(theta[0], np.log(1e-3 * xmax), np.log(100.0 * xmax))))
    return a, float(np.exp(np.clip(theta[1], np.log(0.3), np.log(300.0))))


def _nll(theta, modelo, x, k, n, x_ref):
    a, b = _parametros(modelo, theta, x_ref)
    p = np.clip(MODELOS[modelo](x, a, b), 1e-12, 1.0 - 1e-12)
    return float(-np.sum(k * np.log(p) + (n - k) * np.log1p(-p)))


def _resultado(modelo, theta, nll, x_ref):
    a, b = _parametros(modelo, theta, x_ref)
    if modelo == "logistica":
        u50, u10 = a, a - b * np.log(9.0)
    else:
        u50, u10 = a * np.log(2.0) ** (1.0 / b), a * (-np.log(0.9)) ** (1.0 / b)
    return {"modelo": modelo, "a": a, "b": b, "u10": float(u10), "u50": float(u50), "nll": float(nll),
            "theta": np.asarray(theta, dtype=float)}


def ajuste_binomial(x, k, n, modelo="logistica", theta0=None):
    """Máxima verosimilitud binomial de P(x): logística 1/(1+exp(−(x−U50)/s)) (a = U50, b = s) o
    Weibull 1 − exp(−(x/a)^b). k éxitos de n ensayos en cada x (n = 1: datos individuales).
    Devuelve {modelo, a, b, u10, u50, nll, theta}."""
    x, k, n = (np.asarray(v, dtype=float) for v in (x, k, n))
    x_ref = (max(float(np.max(np.abs(x))), 1e-9), max(float(np.ptp(x)), 1e-9))
    if theta0 is not None:
        inicios = [np.asarray(theta0, dtype=float)]
    else:
        p = np.where(n > 0, k / np.where(n > 0, n, 1.0), 0.5)
        orden = np.argsort(x)
        xs, ps = x[orden], np.maximum.accumulate(p[orden])
        a50 = float(np.interp(0.5, ps, xs)) if ps[0] < 0.5 < ps[-1] else float(np.median(x))
        if modelo == "logistica":
            inicios = [np.array([a50, np.log(x_ref[1] * f)]) for f in (0.05, 0.2)]
        else:
            a50 = max(a50, 1e-6)
            inicios = [np.array([np.log(a50 / np.log(2.0) ** (1.0 / b0)), np.log(b0)]) for b0 in (4.0, 12.0, 40.0)]
    mejor = None
    for t0 in inicios:
        r = optimize.minimize(_nll, t0, args=(modelo, x, k, n, x_ref), method="Nelder-Mead",
                              options={"xatol": 1e-7, "fatol": 1e-10, "maxiter": 4000})
        if mejor is None or r.fun < mejor.fun:
            mejor = r
    return _resultado(modelo, mejor.x, mejor.fun, x_ref)


def bootstrap_binomial(x, k, n, modelo, theta0, n_boot=N_BOOT, semilla=SEMILLA):
    """Bootstrap paramétrico-equivalente de remuestreo de disparos dentro de cada nivel:
    k* ~ Binomial(n, k/n). Devuelve (u10s, u50s) de las réplicas no degeneradas."""
    x, k, n = (np.asarray(v, dtype=float) for v in (x, k, n))
    rng = np.random.default_rng(semilla)
    p = np.where(n > 0, k / np.where(n > 0, n, 1.0), 0.0)
    u10, u50 = [], []
    for _ in range(int(n_boot)):
        kb = rng.binomial(n.astype(int), p).astype(float)
        if kb.sum() == 0 or np.all(kb == n):
            continue
        r = ajuste_binomial(x, kb, n, modelo, theta0=theta0)
        u10.append(r["u10"])
        u50.append(r["u50"])
    return np.array(u10), np.array(u50)


def bootstrap_individual(x, y, modelo, theta0, n_boot=N_BOOT, semilla=SEMILLA):
    """Bootstrap no paramétrico sobre datos individuales (x, y ∈ {0, 1})."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    rng = np.random.default_rng(semilla)
    u10, u50 = [], []
    for _ in range(int(n_boot)):
        i = rng.integers(0, x.size, x.size)
        if y[i].sum() == 0 or y[i].sum() == i.size:
            continue
        r = ajuste_binomial(x[i], y[i], np.ones(i.size), modelo, theta0=theta0)
        u10.append(r["u10"])
        u50.append(r["u50"])
    return np.array(u10), np.array(u50)


def ic95(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return (float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))) if v.size >= 20 else (np.nan, np.nan)


def spearman(x, y):
    """(ρ, p, n) de Spearman ignorando NaN; NaN si hay < 3 puntos o una serie constante."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    m = np.isfinite(x) & np.isfinite(y)
    n = int(m.sum())
    if n < 3 or np.ptp(x[m]) == 0 or np.ptp(y[m]) == 0:
        return float("nan"), float("nan"), n
    r = stats.spearmanr(x[m], y[m])
    return float(r.statistic), float(r.pvalue), n


def fdr_bh(p):
    """q-valores de Benjamini–Hochberg (NaN se conservan)."""
    p = np.asarray(p, dtype=float)
    q = np.full(p.shape, np.nan)
    m = np.isfinite(p)
    if not m.any():
        return q
    pv = p[m]
    orden = np.argsort(pv)
    r = pv[orden] * pv.size / np.arange(1, pv.size + 1)
    r = np.minimum.accumulate(r[::-1])[::-1]
    out = np.empty_like(pv)
    out[orden] = np.minimum(r, 1.0)
    q[m] = out
    return q


def _kmeans(X, k, rng, n_iter=100):
    """k-means con inicialización k-means++ (etiquetas)."""
    c = [X[rng.integers(X.shape[0])]]
    for _ in range(1, k):
        d2 = np.min(((X[:, None, :] - np.array(c)[None]) ** 2).sum(-1), axis=1)
        c.append(X[rng.choice(X.shape[0], p=d2 / d2.sum())] if d2.sum() > 0 else X[rng.integers(X.shape[0])])
    c = np.array(c)
    et = np.zeros(X.shape[0], dtype=int)
    for _ in range(n_iter):
        et_n = np.argmin(((X[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if np.any(et_n == j):
                c[j] = X[et_n == j].mean(0)
        if np.array_equal(et_n, et):
            break
        et = et_n
    return et


def ajustar_gmm(X, k, semilla=SEMILLA, n_init=10, max_iter=500, reg=1e-3):
    """Mezcla gaussiana de covarianza completa por EM (sin sklearn). X (n, d), idealmente
    estandarizado. Devuelve {k, pesos, medias, covs, ll, bic, etiquetas}."""
    X = np.asarray(X, dtype=float)
    n, d = X.shape
    rng = np.random.default_rng(semilla)
    mejor = None
    for _ in range(n_init if k > 1 else 1):
        et = _kmeans(X, k, rng) if k > 1 else np.zeros(n, dtype=int)
        resp = np.zeros((n, k))
        resp[np.arange(n), et] = 1.0
        ll_prev = -np.inf
        for _ in range(max_iter):
            nk = resp.sum(0) + 1e-10
            w = nk / n
            mu = resp.T @ X / nk[:, None]
            cov = np.array([((resp[:, j, None] * (X - mu[j])).T @ (X - mu[j])) / nk[j] + reg * np.eye(d)
                            for j in range(k)])
            logp = np.column_stack([np.log(w[j]) + stats.multivariate_normal.logpdf(X, mu[j], cov[j],
                                                                                     allow_singular=True)
                                    for j in range(k)])
            lse = np.logaddexp.reduce(logp, axis=1)
            ll = float(lse.sum())
            resp = np.exp(logp - lse[:, None])
            if abs(ll - ll_prev) < 1e-9 * max(1.0, abs(ll)):
                break
            ll_prev = ll
        if mejor is None or ll > mejor["ll"]:
            mejor = {"k": k, "pesos": w, "medias": mu, "covs": cov, "ll": ll, "etiquetas": np.argmax(resp, 1)}
    p = (k - 1) + k * d + k * d * (d + 1) / 2
    mejor["bic"] = float(-2.0 * mejor["ll"] + p * np.log(n))
    return mejor


def seleccionar_gmm(X, k_max=4, semilla=SEMILLA):
    """Ajusta 1..k_max componentes y elige por BIC mínimo. Devuelve (mejor, [ajustes])."""
    ajustes = [ajustar_gmm(X, k, semilla=semilla) for k in range(1, k_max + 1)]
    return min(ajustes, key=lambda a: a["bic"]), ajustes


def intervalos(t):
    """Intervalos consecutivos (misma unidad que t) de los tiempos ordenados."""
    return np.diff(np.sort(np.asarray(t, dtype=float)))


# =====================================================================================
# Utilidades
# =====================================================================================

def _col(filas, k):
    return np.array([np.nan if f.get(k) is None else f[k] for f in filas], dtype=float)


def _media(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return float(np.mean(v)) if v.size else float("nan")


def _sd(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return float(np.std(v, ddof=1)) if v.size > 1 else float("nan")


def _mediana(v):
    v = np.asarray(v, dtype=float)
    v = v[np.isfinite(v)]
    return float(np.median(v)) if v.size else float("nan")


def _fmt(v, nd=None):
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "sí" if v else "no"
    if isinstance(v, (float, np.floating)):
        if not np.isfinite(v):
            return ""
        return f"{float(v):.{nd}f}" if nd is not None else f"{float(v):.6g}"
    return str(v)


def escribir_csv(ruta, filas, campos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(campos)
        for fila in filas:
            w.writerow([_fmt(fila.get(c)) for c in campos])


def _colores():
    try:
        import tema
        c = dict(tema.COLORES_CANALES)
    except Exception:   # pragma: no cover
        c = {"ch1": "#444", "ch2": "#2f5d8a", "ch3": "#a8741a", "ch4": "#3f7d5c"}
    c["union"] = "#374151"
    return c


def _estilo(ax, x="", y=""):
    if x:
        ax.set_xlabel(x, fontsize=9)
    if y:
        ax.set_ylabel(y, fontsize=9)
    ax.grid(True, color="#e5e7eb", lw=0.6)
    ax.tick_params(labelsize=8)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)


def _figura(nf=1, nc=1, titulo="", **kw):
    fig, ejes = plt.subplots(nf, nc, figsize=A4, layout="constrained", squeeze=False, **kw)
    if titulo:
        fig.suptitle(titulo, fontsize=12, fontweight="bold", x=0.01, ha="left")
    return fig, ejes


def _guardar(fig, ruta):
    fig.savefig(ruta, dpi=150)
    print(f"Figura: {ruta}")


X_NIVEL = "Nivel de tensión [kV, AC secundario]"
Y_DIV = "Tensión [V del divisor]"


# =====================================================================================
# Paso 0 — carga común
# =====================================================================================

CAMPOS_DESCARGA = ["probeta", "kv", "sensor", "canal", "seg", "t_peak_us", "t_abs_us", "vp_v", "n_pd_disparo",
                   "orden_en_disparo", "cav", "origen", "t10_us", "u_pico_v", "t_pico_us", "u_inst_v",
                   "u_inst_20ns_v", "u_rel", "fase", "ch1_dudoso"]
CAMPOS_DISPARO = ["probeta", "kv", "seg", "t10_us", "u_pico_v", "t_pico_us", "u_pico_crudo_v", "ch1_dudoso",
                  "n_ch2", "n_ch3", "n_ch4", "t_cruce_uref_us"]


def cargar_descargas(reporte=REPORTE4, ventana_ns=VENTANA_SUAV_NS, ventana_alt_ns=VENTANA_ALT_NS):
    """Una fila por descarga (y por disparo) de todas las mediciones de la lista del reporte 4.
    Calcula además, por disparo, U_pico (CH1 suavizado) y u_inst de cada descarga."""
    import app
    import generar_reporte4 as g4
    import reproducir_trpd
    import rutas

    lista = g4.leer_lista(os.path.join(reporte, "mediciones_listas.txt"))
    descargas, disparos, niveles, curvas = [], [], [], {}
    for m in lista:
        carpeta = g4.absoluta(m)
        if not rutas.canales_presentes(carpeta):
            print(f"Aviso: {m} no es una medición; se omite.")
            continue
        res = reproducir_trpd.resultado_medicion(carpeta, calibrado=False)
        if not res:
            continue
        g4.medias_vp(carpeta, res)
        d = g4.describir(carpeta)
        meta = app.obtener_metadata(carpeta) or {}
        circ, cad = meta.get("circuito_impulso") or {}, meta.get("cadencia") or {}
        kv, prob = d["kv"], d["probeta"]
        excl = set(d["excluidos"])
        validos = [s for s in range(1, d["nsegs"] + 1) if s not in excl]
        t10 = np.asarray(app.t10_por_segmento(carpeta), dtype=float)
        npd = {c: {int(s): int(k) for s, k in zip(r["segs"], r["cuentas"])} for c, r in res.items()}
        u = {c: np.full(np.asarray(r["cap"]["t_peak"]).size, np.nan) for c, r in res.items()}
        u2 = {c: v.copy() for c, v in u.items()}
        disp_nivel = {}
        for s in validos:
            t, v = app.cargar_segmento(carpeta, "ch1", s, filtrado=False)
            t = np.asarray(t, dtype=float)
            v = np.asarray(v, dtype=float) / 1000.0            # mV → V del divisor
            dt_ns = float(np.median(np.diff(t[:2000]))) * 1e3
            vs = suavizar(v, ventana_ns / dt_ns)
            vs2 = suavizar(v, ventana_alt_ns / dt_ns)
            U, tp = pico_impulso(t, vs)
            for c, r in res.items():
                mk = np.asarray(r["cap"]["seg"]) == s
                if mk.any():
                    tpk = np.asarray(r["cap"]["t_peak"], dtype=float)[mk]
                    u[c][mk] = tension_instantanea(t, vs, tpk)
                    u2[c][mk] = tension_instantanea(t, vs2, tpk)
            curvas[(kv, s)] = (t[::DECIMADO_CURVA].copy(), vs[::DECIMADO_CURVA].copy())
            fila = {"probeta": prob, "kv": kv, "seg": s, "t10_us": float(t10[s - 1]) if s - 1 < t10.size else np.nan,
                    "u_pico_v": U, "t_pico_us": tp, "u_pico_crudo_v": float(np.max(v))}
            for c in CANALES:
                fila[f"n_{c}"] = npd[c].get(s, 0) if c in npd else None
            disp_nivel[s] = fila
        med = _mediana([f["u_pico_v"] for f in disp_nivel.values()])
        for f in disp_nivel.values():
            f["ch1_dudoso"] = bool(abs(f["u_pico_v"] - med) > DUDOSO_REL * med)
        disparos += [disp_nivel[s] for s in validos]

        for c, r in res.items():
            cap = r["cap"]
            tpk = np.asarray(cap["t_peak"], dtype=float)
            seg = np.asarray(cap["seg"], dtype=int)
            tab = np.asarray(r["t_abs"], dtype=float)
            org = np.asarray(cap.get("origen", np.zeros(seg.size)), dtype=int)
            orden = np.zeros(seg.size, dtype=int)
            for s in np.unique(seg):
                idx = np.nonzero(seg == s)[0]
                orden[idx[np.argsort(tpk[idx])]] = np.arange(1, idx.size + 1)
            for i in range(seg.size):
                dd = disp_nivel.get(int(seg[i]))
                U = dd["u_pico_v"] if dd else np.nan
                ui = float(u[c][i])
                descargas.append({
                    "probeta": prob, "kv": kv, "sensor": r["fila"].get("sensor", SENSORES.get(c, c)), "canal": c,
                    "seg": int(seg[i]), "t_peak_us": float(tpk[i]), "t_abs_us": float(tab[i]),
                    "vp_v": float(r["vp"][i]), "n_pd_disparo": npd[c].get(int(seg[i]), 0),
                    "orden_en_disparo": int(orden[i]), "cav": bool(r["cav"][i]), "origen": int(org[i]),
                    "t10_us": dd["t10_us"] if dd else np.nan, "u_pico_v": U,
                    "t_pico_us": dd["t_pico_us"] if dd else np.nan, "u_inst_v": ui,
                    "u_inst_20ns_v": float(u2[c][i]), "u_rel": ui / U if np.isfinite(U) and U else np.nan,
                    "fase": ("frente" if tpk[i] < dd["t_pico_us"] else "cola") if dd else "",
                    "ch1_dudoso": dd["ch1_dudoso"] if dd else None})
        niveles.append({"probeta": prob, "kv": kv, "carpeta": carpeta, "nsegs": d["nsegs"], "excluidos": d["excluidos"],
                        "v_pico_meta": circ.get("v_pico_divisor_media_v"), "anomalias": cad.get("anomalias") or [],
                        "canales": [c for c in CANALES if c in res],
                        "sensores": {c: r["fila"].get("sensor", SENSORES[c]) for c, r in res.items()}})
        print(f"{prob} {kv:g} kV: {len(validos)} disparos, "
              + ", ".join(f"{SENSORES.get(c, c)} {int(np.sum(r['cuentas']))}" for c, r in res.items()))
    niveles.sort(key=lambda n: (n["probeta"], n["kv"]))
    descargas.sort(key=lambda f: (f["probeta"], f["kv"], f["canal"], f["seg"], f["t_peak_us"]))
    disparos.sort(key=lambda f: (f["probeta"], f["kv"], f["seg"]))
    uref = u_inc_ref(descargas)
    for p in disparos:
        cur = curvas.get((p["kv"], p["seg"]))
        p["t_cruce_uref_us"] = (tiempo_cruce(cur[0], cur[1], uref) - p["t10_us"]) if cur is not None else np.nan
    return {"descargas": descargas, "disparos": disparos, "niveles": niveles, "curvas": curvas, "u_inc_ref": uref}


def incepciones(descargas):
    return [f for f in descargas if f["orden_en_disparo"] == 1]


def u_inc_ref(descargas, canal=CANAL_REF):
    """Mediana global de U_inc (u_inst de la 1.ª descarga del disparo) del sensor de referencia."""
    v = [f["u_inst_v"] for f in incepciones(descargas) if f["canal"] == canal]
    if not v:
        v = [f["u_inst_v"] for f in incepciones(descargas)]
    return _mediana(v)


def canales_de(dat):
    return [c for c in CANALES if any(c in n["canales"] for n in dat["niveles"])]


def controles(dat, reporte):
    """Controles deterministas del plan (§5.3). Devuelve lista de filas {control, detalle, ok}."""
    D, P, N = dat["descargas"], dat["disparos"], dat["niveles"]
    out = []
    ruta = os.path.join(reporte, "tabla_trpd.csv")
    cuenta = defaultdict(int)
    for f in D:
        cuenta[(f["kv"], f["sensor"])] += 1
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as fh:
            filas = list(csv.reader(fh))[1:]
        for row in filas:
            kv, sensor, dist = float(row[2]), row[3], ast.literal_eval(row[4])
            esperado = sum(i * n for i, n in enumerate(dist[:5]))
            n = cuenta.get((kv, sensor), 0)
            ok = (n == esperado) if dist[5] == 0 else (n >= esperado + 5 * dist[5])
            out.append({"control": "conteo descargas = tabla_trpd.csv", "detalle": f"{kv:g} kV {sensor}: {n} vs {esperado}",
                        "ok": ok})
    else:
        out.append({"control": "conteo descargas = tabla_trpd.csv", "detalle": "no existe tabla_trpd.csv", "ok": False})
    ur = _col(D, "u_rel")
    fuera = int(np.sum(~((ur > 0) & (ur <= 1.02))))
    out.append({"control": "0 < u_rel ≤ 1.02", "detalle": f"{fuera} de {ur.size} descargas fuera de rango"
                + (f" (min {np.nanmin(ur):.3f}, max {np.nanmax(ur):.3f})" if ur.size else ""), "ok": fuera == 0})
    for n in N:
        Pk = [p for p in P if p["kv"] == n["kv"]]
        um = _mediana(_col(Pk, "u_pico_v"))
        if n["excluidos"]:
            ref, txt = _media(_col(Pk, "u_pico_crudo_v")), "máx. crudo medio sin segmentos excluidos"
        else:
            ref, txt = n["v_pico_meta"], "v_pico_divisor_media_v"
        dif = 100.0 * (um / ref - 1.0) if ref else float("nan")
        out.append({"control": "U_pico mediano ≈ referencia (±2 %)",
                    "detalle": f"{n['kv']:g} kV: {um:.4f} V vs {ref:.4f} V ({txt}); {dif:+.2f} %",
                    "ok": bool(np.isfinite(dif) and abs(dif) <= 2.0)})
    return out


# =====================================================================================
# A2 (núcleo) — eventos físicos por disparo; lo usan A2, A3 y A4
# =====================================================================================

CAMPOS_EVENTO = ["id", "probeta", "kv", "seg", "orden_evento", "n_eventos_disparo", "n_sensores", "t_ref_us",
                 "t_abs_ref_us", "t_ch2_us", "vp_ch2_v", "t_ch3_us", "vp_ch3_v", "t_ch4_us", "vp_ch4_v",
                 "dt34_ns", "r34", "u_inst_v", "grupo"]


def construir_eventos(dat, tol34_ns=TOL34_NS, tol2_ns=TOL2_NS):
    D, P = dat["descargas"], dat["disparos"]
    grupos = defaultdict(list)
    for f in D:
        grupos[(f["kv"], f["seg"], f["canal"])].append(f)
    for g in grupos.values():
        g.sort(key=lambda f: f["t_peak_us"])
    dif, dif_niv = [], defaultdict(list)
    for p in P:
        k = (p["kv"], p["seg"])
        ns = [len(grupos.get(k + (c,), [])) for c in CANALES]
        if ns[0] > 0 and len(set(ns)) == 1:
            dd = (np.array([f["t_peak_us"] for f in grupos[k + ("ch2",)]])
                  - np.array([f["t_peak_us"] for f in grupos[k + ("ch3",)]])) * 1e3
            dif += list(dd)
            dif_niv[p["kv"]] += list(dd)
    desfase = _mediana(dif) if dif else 0.0
    eventos = []
    for p in P:
        k = (p["kv"], p["seg"])
        fs = {c: grupos.get(k + (c,), []) for c in CANALES}
        evs = eventos_disparo({c: [f["t_peak_us"] for f in fs[c]] for c in CANALES}, desfase / 1e3,
                              tol34_ns / 1e3, tol2_ns / 1e3)
        for j, e in enumerate(evs, 1):
            row = {"id": len(eventos) + 1, "probeta": p["probeta"], "kv": p["kv"], "seg": p["seg"], "orden_evento": j,
                   "n_eventos_disparo": len(evs), "t_ref_us": e["t_ref"], "t_abs_ref_us": e["t_ref"] - p["t10_us"]}
            u_inst = None
            for c in CANALES:
                f = fs[c][e[c]] if e[c] is not None else None
                row[f"t_{c}_us"] = f["t_peak_us"] if f else None
                row[f"vp_{c}_v"] = f["vp_v"] if f else None
                row[f"_{c}"] = f
            for c in ("ch3", "ch4", "ch2"):
                if row[f"_{c}"] is not None:
                    u_inst = row[f"_{c}"]["u_inst_v"]
                    break
            row["u_inst_v"] = u_inst
            row["n_sensores"] = sum(row[f"_{c}"] is not None for c in CANALES)
            ambas = row["t_ch3_us"] is not None and row["t_ch4_us"] is not None
            row["dt34_ns"] = (row["t_ch3_us"] - row["t_ch4_us"]) * 1e3 if ambas else None
            row["r34"] = row["vp_ch3_v"] / row["vp_ch4_v"] if ambas and row["vp_ch4_v"] else None
            row["grupo"] = ""
            eventos.append(row)
    dat["eventos"] = eventos
    dat["desfase_hfct_ns"] = desfase
    dat["desfase_hfct_niv"] = {kv: (_mediana(v), len(v)) for kv, v in dif_niv.items()}
    dat["dif_hfct_ns"] = np.array(dif)
    return eventos


# =====================================================================================
# A1 — tensión instantánea
# =====================================================================================

def analisis_A1(dat, out):
    D, P, N = dat["descargas"], dat["disparos"], dat["niveles"]
    col, chs = _colores(), canales_de(dat)
    figs, textos, tablas = [], [], []
    uref = dat["u_inc_ref"]
    inc = incepciones(D)
    escribir_csv(os.path.join(out, "tension_por_descarga.csv"), D, CAMPOS_DESCARGA)
    campos_inc = ["probeta", "kv", "sensor", "canal", "seg", "u_inst_v", "u_pico_v", "u_rel", "fase", "t_abs_us",
                  "vp_v", "n_pd_disparo", "ch1_dudoso"]
    escribir_csv(os.path.join(out, "incepcion_por_disparo.csv"), inc, campos_inc)

    resumen = []
    for n in N:
        kv = n["kv"]
        Pk = [p for p in P if p["kv"] == kv]
        um, ucr = _mediana(_col(Pk, "u_pico_v")), _media(_col(Pk, "u_pico_crudo_v"))
        meta = n["v_pico_meta"]
        tcr = _col(Pk, "t_cruce_uref_us")
        for c in n["canales"]:
            Dk = [f for f in D if f["kv"] == kv and f["canal"] == c]
            Ik = [f for f in inc if f["kv"] == kv and f["canal"] == c]
            ui = _col(Ik, "u_inst_v")
            resumen.append({
                "kv": kv, "sensor": SENSORES[c], "n_disparos": len(Pk), "n_ch1_dudoso": sum(p["ch1_dudoso"] for p in Pk),
                "n_descargas": len(Dk), "u_pico_mediana_v": um, "u_pico_crudo_media_v": ucr,
                "v_pico_meta_v": meta, "dif_meta_pct": 100 * (um / meta - 1) if meta else None,
                "u_inc_media_v": _media(ui), "u_inc_sd_v": _sd(ui), "n_inc": int(np.isfinite(ui).sum()),
                "u_inc_rel_media": _media(_col(Ik, "u_rel")), "u_rel_media": _media(_col(Dk, "u_rel")),
                "frac_frente": (sum(f["fase"] == "frente" for f in Dk) / len(Dk)) if Dk else None,
                "t_abs_1a_media_us": _media(_col(Ik, "t_abs_us")), "t_cruce_uref_media_us": _media(tcr)})
    campos_res = ["kv", "sensor", "n_disparos", "n_ch1_dudoso", "n_descargas", "u_pico_mediana_v", "u_pico_crudo_media_v",
                  "v_pico_meta_v", "dif_meta_pct", "u_inc_media_v", "u_inc_sd_v", "n_inc", "u_inc_rel_media",
                  "u_rel_media", "frac_frente", "t_abs_1a_media_us", "t_cruce_uref_media_us"]
    escribir_csv(os.path.join(out, "resumen_A1.csv"), resumen, campos_res)

    # Efecto de la ventana de suavizado (50 vs 20 ns)
    efecto = []
    for n in N:
        Dk = [f for f in D if f["kv"] == n["kv"]]
        dd = (_col(Dk, "u_inst_v") - _col(Dk, "u_inst_20ns_v")) * 1e3
        fr = np.array([f["fase"] == "frente" for f in Dk], dtype=bool)
        efecto.append({"kv": n["kv"], "n": len(Dk), "dif_media_mv": _media(dd), "dif_abs_media_mv": _media(np.abs(dd)),
                       "dif_abs_max_mv": float(np.nanmax(np.abs(dd))) if dd.size else None,
                       "dif_abs_media_frente_mv": _media(np.abs(dd[fr])) if fr.any() else None})
    escribir_csv(os.path.join(out, "efecto_ventana_suavizado.csv"), efecto,
                 ["kv", "n", "dif_media_mv", "dif_abs_media_mv", "dif_abs_max_mv", "dif_abs_media_frente_mv"])

    kvs = [n["kv"] for n in N]
    upico = [_mediana(_col([p for p in P if p["kv"] == kv], "u_pico_v")) for kv in kvs]

    # (a) U_inc por nivel
    fig, ejes = _figura(1, 2, "A1 (a) · Tensión de incepción (u_inst de la 1.ª descarga del disparo)")
    ax, ax2 = ejes[0]
    ax.plot(kvs, upico, color="#111", ls="--", marker="s", ms=4, lw=1.0, label="U_pico (mediana del nivel)")
    ax.axhline(uref, color="#9aa3ad", ls=":", lw=1.0, label=f"U_inc ref. = {uref:.3f} V (mediana Antena 1)")
    for k, c in enumerate(chs):
        m, s, m2, s2 = [], [], [], []
        for kv in kvs:
            ik = [f for f in inc if f["kv"] == kv and f["canal"] == c]
            m.append(_media(_col(ik, "u_inst_v")))
            s.append(_sd(_col(ik, "u_inst_v")))
            m2.append(_media(_col(ik, "u_rel")))
            s2.append(_sd(_col(ik, "u_rel")))
        dx = (k - 1) * 0.08
        ax.errorbar(np.array(kvs) + dx, m, yerr=s, color=col[c], marker="o", ms=4, capsize=3, lw=1.2, label=SENSORES[c])
        ax2.errorbar(np.array(kvs) + dx, m2, yerr=s2, color=col[c], marker="o", ms=4, capsize=3, lw=1.2,
                     label=SENSORES[c])
    _estilo(ax, X_NIVEL, "U_inc [V del divisor]")
    _estilo(ax2, X_NIVEL, "U_inc / U_pico")
    ax.set_xticks(kvs)
    ax2.set_xticks(kvs)
    ax.set_title("U_inc media ± σ por nivel y sensor", fontsize=10, loc="left")
    ax2.set_title("U_inc relativa al pico del disparo", fontsize=10, loc="left")
    ax.legend(fontsize=8, frameon=False)
    _guardar(fig, os.path.join(out, "a_incepcion_por_nivel.png"))
    figs.append(fig)

    # (b) V_p vs u_inst ; (d) V_p vs ΔU
    rho_b, rho_d = {}, {}
    for clave, nombre, eti, xl in (("u_inst_v", "b_vp_vs_u_inst", "A1 (b) · V_p vs tensión instantánea",
                                    "u_inst [V del divisor]"),
                                   ("du", "d_vp_vs_sobretension", "A1 (d) · V_p vs sobretensión ΔU = u_inst − U_inc ref.",
                                    "ΔU [V del divisor]")):
        fig, ejes = _figura(1, len(chs), eti)
        sc = None
        for ax, c in zip(ejes[0], chs):
            Dc = [f for f in D if f["canal"] == c]
            x = _col(Dc, "u_inst_v") - (uref if clave == "du" else 0.0)
            y = _col(Dc, "vp_v")
            sc = ax.scatter(x, y, c=_col(Dc, "kv"), cmap="viridis", s=12, vmin=min(kvs), vmax=max(kvs),
                            edgecolor="none", alpha=0.85)
            r, p, nn = spearman(x, y)
            (rho_b if clave == "u_inst_v" else rho_d)[c] = (r, p, nn)
            ax.set_title(f"{SENSORES[c]} · ρ Spearman = {r:.2f} (p = {p:.1g}, n = {nn})", fontsize=9, loc="left")
            if clave == "du":
                ax.axvline(0, color="#9aa3ad", lw=0.8, ls=":")
            _estilo(ax, xl, "V_p [V]")
        if sc is not None:
            fig.colorbar(sc, ax=ejes[0].tolist(), label="Nivel [kV]", shrink=0.8)
        _guardar(fig, os.path.join(out, f"{nombre}.png"))
        figs.append(fig)

    # (c) histograma de u_rel
    fig, ejes = _figura(1, len(chs), "A1 (c) · Distribución de u_rel = u_inst / U_pico del disparo")
    bins = np.arange(0.0, 1.04, 0.02)
    for ax, c in zip(ejes[0], chs):
        Dc = [f for f in D if f["canal"] == c]
        ur = _col(Dc, "u_rel")
        fr = np.array([f["fase"] == "frente" for f in Dc], dtype=bool)
        ax.hist([ur[fr], ur[~fr]], bins=bins, stacked=True, color=[col[c], "#c4cbd3"],
                label=[f"frente ({fr.sum()})", f"cola ({(~fr).sum()})"])
        ax.set_title(SENSORES[c], fontsize=10, loc="left")
        ax.legend(fontsize=8, frameon=False, loc="upper left")
        _estilo(ax, "u_rel", "Nº de descargas")
    _guardar(fig, os.path.join(out, "c_histograma_u_rel.png"))
    figs.append(fig)

    # (e) ¿el frente explica la caída de t_abs? t_abs de la 1.ª descarga vs tiempo de cruce de U_inc ref.
    fig, ejes = _figura(1, 2, "A1 (e) · t_abs de la 1.ª descarga vs instante en que el frente alcanza U_inc ref.")
    ax, ax2 = ejes[0]
    tcr_m = [_media(_col([p for p in P if p["kv"] == kv], "t_cruce_uref_us")) for kv in kvs]
    tcr_s = [_sd(_col([p for p in P if p["kv"] == kv], "t_cruce_uref_us")) for kv in kvs]
    ax.errorbar(kvs, tcr_m, yerr=tcr_s, color="#111", ls="--", marker="s", ms=4, capsize=3,
                label=f"t de cruce de {uref:.3f} V (CH1 suavizado)")
    for k, c in enumerate(chs):
        m = [_media(_col([f for f in inc if f["kv"] == kv and f["canal"] == c], "t_abs_us")) for kv in kvs]
        s = [_sd(_col([f for f in inc if f["kv"] == kv and f["canal"] == c], "t_abs_us")) for kv in kvs]
        ax.errorbar(np.array(kvs) + (k - 1) * 0.08, m, yerr=s, color=col[c], marker="o", ms=4, capsize=3,
                    label=f"t_abs 1.ª descarga · {SENSORES[c]}")
    ax.set_xticks(kvs)
    _estilo(ax, X_NIVEL, "t [µs] (t10 = 0)")
    ax.legend(fontsize=8, frameon=False)
    idx_p = {(p["kv"], p["seg"]): p for p in P}
    ir = [f for f in inc if f["canal"] == CANAL_REF]
    xt = np.array([idx_p[(f["kv"], f["seg"])]["t_cruce_uref_us"] for f in ir], dtype=float)
    yt = _col(ir, "t_abs_us")
    ax2.scatter(xt, yt, c=_col(ir, "kv"), cmap="viridis", s=14, vmin=min(kvs), vmax=max(kvs))
    mm = np.isfinite(xt) & np.isfinite(yt)
    if mm.any():
        lim = [min(np.nanmin(xt[mm]), np.nanmin(yt[mm])), max(np.nanmax(xt[mm]), np.nanmax(yt[mm]))]
        ax2.plot(lim, lim, color="#9aa3ad", lw=0.8, ls="--", label="y = x")
        ax2.legend(fontsize=8, frameon=False)
    ax2.set_title(f"Por disparo · {SENSORES[CANAL_REF]}", fontsize=10, loc="left")
    _estilo(ax2, "t de cruce de U_inc ref. [µs]", "t_abs 1.ª descarga [µs]")
    _guardar(fig, os.path.join(out, "e_tabs_vs_cruce_frente.png"))
    figs.append(fig)

    # Textos
    ui_r = np.array([f["u_inst_v"] for f in ir], dtype=float)
    up_r = np.array([idx_p[(f["kv"], f["seg"])]["u_pico_v"] for f in ir], dtype=float)
    medias_niv = [r["u_inc_media_v"] for r in resumen if r["sensor"] == SENSORES[CANAL_REF]]
    textos.append(f"U_inc de referencia (mediana global de la 1.ª descarga, {SENSORES[CANAL_REF]}): {uref:.3f} V del "
                  f"divisor (n = {ui_r.size} disparos con descarga).")
    if medias_niv:
        textos.append(f"U_inc media por nivel ({SENSORES[CANAL_REF]}): {np.nanmin(medias_niv):.3f}–{np.nanmax(medias_niv):.3f} V; "
                      f"U_pico mediano: {min(upico):.3f}–{max(upico):.3f} V.")
    m = np.isfinite(ui_r) & np.isfinite(up_r)
    if m.sum() > 3:
        lr = stats.linregress(up_r[m], ui_r[m])
        compat = abs(lr.slope) < 2 * lr.stderr
        textos.append(f"Regresión U_inc vs U_pico por disparo ({SENSORES[CANAL_REF]}): pendiente {lr.slope:.3f} ± "
                      f"{2 * lr.stderr:.3f} (±2 e.e.), r = {lr.rvalue:.2f}. "
                      + ("Pendiente compatible con 0: U_inc ~constante entre niveles."
                         if compat else ("U_inc crece con la tensión aplicada." if lr.slope > 0 else
                                         "U_inc decrece con la tensión aplicada.")))
    mm = np.isfinite(xt) & np.isfinite(yt)
    if mm.sum() > 3:
        dif = yt[mm] - xt[mm]
        rr = stats.pearsonr(xt[mm], yt[mm])
        textos.append(f"t_abs de la 1.ª descarga − t de cruce de U_inc ref.: media {np.mean(dif):+.3f} µs, σ "
                      f"{np.std(dif, ddof=1):.3f} µs; Pearson r = {rr.statistic:.2f} (n = {mm.sum()}). "
                      "Si r es alto y la media pequeña, la caída de t̄_abs con el nivel se explica porque el frente "
                      "alcanza antes la misma tensión.")
    fr_tot = [f for f in D if f["canal"] == CANAL_REF]
    if fr_tot:
        textos.append(f"Fracción de descargas en el frente ({SENSORES[CANAL_REF]}): "
                      f"{sum(f['fase'] == 'frente' for f in fr_tot) / len(fr_tot):.1%} "
                      "(t_pico = máximo del CH1 suavizado; el máximo es ancho, la frontera frente/cola es imprecisa).")
    textos.append("V_p vs u_inst (ρ Spearman): " + "; ".join(f"{SENSORES[c]} {rho_b[c][0]:.2f} (p = {rho_b[c][1]:.1g})"
                                                         for c in chs if c in rho_b))
    textos.append("V_p vs ΔU (ρ Spearman): " + "; ".join(f"{SENSORES[c]} {rho_d[c][0]:.2f} (p = {rho_d[c][1]:.1g})"
                                                     for c in chs if c in rho_d))
    ef = [e["dif_abs_media_mv"] for e in efecto if e["dif_abs_media_mv"] is not None]
    if ef:
        textos.append(f"Efecto del suavizado (50 vs 20 ns): |Δu_inst| medio {np.nanmean(ef):.1f} mV, máximo "
                      f"{np.nanmax([e['dif_abs_max_mv'] or 0 for e in efecto]):.1f} mV "
                      "(ver efecto_ventana_suavizado.csv).")
    n_dud = sum(p["ch1_dudoso"] for p in P)
    textos.append(f"Disparos con CH1 dudoso (U_pico a > 5 % de la mediana del nivel): {n_dud}.")
    filas = [[_fmt(r["kv"], 0), r["sensor"], str(r["n_disparos"]), str(r["n_descargas"]), _fmt(r["u_pico_mediana_v"], 3),
              _fmt(r["v_pico_meta_v"], 3), _fmt(r["u_inc_media_v"], 3), _fmt(r["u_inc_sd_v"], 3),
              _fmt(r["u_inc_rel_media"], 3), _fmt(r["frac_frente"], 2), _fmt(r["t_abs_1a_media_us"], 3),
              _fmt(r["t_cruce_uref_media_us"], 3)] for r in resumen]
    tablas.append(("Resumen A1 por nivel y sensor (tensiones en V del divisor)",
                   ["kV", "Sensor", "Disparos", "Descargas", "U_pico\nmediana", "U_pico\nmetadata", "U_inc\nmedia",
                    "U_inc\nσ", "U_inc /\nU_pico", "Frac.\nfrente", "t_abs 1.ª\n(µs)", "t cruce\nU_inc ref (µs)"], filas))
    dat["A1"] = {"u_inc_ref": uref}
    return {"figs": figs, "textos": textos, "tablas": tablas}


# =====================================================================================
# A2 — emparejamiento
# =====================================================================================

def analisis_A2(dat, out):
    N, E = dat["niveles"], dat["eventos"]
    col, chs = _colores(), canales_de(dat)
    figs, textos, tablas = [], [], []
    kvs = [n["kv"] for n in N]
    des = dat["desfase_hfct_ns"]

    # Detección
    det = []
    for kv in kvs + ["total"]:
        Ek = E if kv == "total" else [e for e in E if e["kv"] == kv]
        fila = {"kv": kv, "n_eventos": len(Ek),
                "n_ambas_antenas": sum(e["t_ch3_us"] is not None and e["t_ch4_us"] is not None for e in Ek),
                "n_tres_sensores": sum(e["n_sensores"] == 3 for e in Ek),
                "n_solo_hfct": sum(e["n_sensores"] == 1 and e["t_ch2_us"] is not None for e in Ek)}
        for c in chs:
            fila[f"det_{c}"] = (sum(e[f"t_{c}_us"] is not None for e in Ek) / len(Ek)) if Ek else None
        if kv != "total":
            fila["desfase_hfct_nivel_ns"], fila["n_desfase"] = dat["desfase_hfct_niv"].get(kv, (None, 0))
        det.append(fila)
    campos_det = ["kv", "n_eventos", "n_ambas_antenas", "n_tres_sensores", "n_solo_hfct"] + [f"det_{c}" for c in chs] \
        + ["desfase_hfct_nivel_ns", "n_desfase"]
    escribir_csv(os.path.join(out, "deteccion_A2.csv"), det, campos_det)

    # Curva de detección HFCT vs V_p de Antena 1
    Ea = [e for e in E if e["vp_ch3_v"] is not None]
    xa = _col(Ea, "vp_ch3_v")
    ya = np.array([e["t_ch2_us"] is not None for e in Ea], dtype=float)
    fit_h, ic_h = None, (np.nan, np.nan)
    if xa.size > 10 and 0 < ya.sum() < ya.size:
        fit_h = ajuste_binomial(xa, ya, np.ones(xa.size), "logistica")
        _, b50 = bootstrap_individual(xa, ya, "logistica", fit_h["theta"], n_boot=dat["n_boot"])
        ic_h = ic95(b50)

    # Localización: R y Δt34
    Eb = [e for e in E if e["dt34_ns"] is not None and e["r34"] is not None and e["r34"] > 0]
    dt34, r34 = _col(Eb, "dt34_ns"), _col(Eb, "r34")
    mejor, ajustes = None, []
    if len(Eb) >= 20:
        X = np.column_stack([np.log10(r34), dt34])
        Xs = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1.0)
        mejor, ajustes = seleccionar_gmm(Xs, 4)
        et = mejor["etiquetas"]
        orden_g = np.argsort([np.mean(np.log10(r34)[et == j]) if np.any(et == j) else np.inf for j in range(mejor["k"])])
        nombre = {int(j): "ABCD"[i] for i, j in enumerate(orden_g)}
        for e, j in zip(Eb, et):
            e["grupo"] = nombre[int(j)]
    escribir_csv(os.path.join(out, "eventos.csv"), E, CAMPOS_EVENTO)
    filas_bic = [{"k": a["k"], "log_verosimilitud": a["ll"], "bic": a["bic"], "elegido": mejor is not None and a["k"] == mejor["k"]}
                 for a in ajustes]
    escribir_csv(os.path.join(out, "bic_gmm.csv"), filas_bic, ["k", "log_verosimilitud", "bic", "elegido"])
    grupos_res = []
    if mejor is not None:
        for g in sorted({e["grupo"] for e in Eb}):
            Eg = [e for e in Eb if e["grupo"] == g]
            inc_g = [e for e in Eg if e["orden_evento"] == 1]
            fila = {"grupo": g, "n": len(Eg), "r34_mediana": _mediana(_col(Eg, "r34")),
                    "dt34_mediana_ns": _mediana(_col(Eg, "dt34_ns")), "vp_ch3_media_v": _media(_col(Eg, "vp_ch3_v")),
                    "u_inst_media_v": _media(_col(Eg, "u_inst_v")), "u_inc_media_v": _media(_col(inc_g, "u_inst_v")),
                    "n_inc": len(inc_g)}
            for o in (1, 2, 3):
                fila[f"n_orden_{o}"] = sum(e["orden_evento"] == o for e in Eg)
            fila["n_orden_4+"] = sum(e["orden_evento"] >= 4 for e in Eg)
            fila["kv_medio"] = _media(_col(Eg, "kv"))
            grupos_res.append(fila)
    escribir_csv(os.path.join(out, "resumen_grupos_A2.csv"), grupos_res,
                 ["grupo", "n", "r34_mediana", "dt34_mediana_ns", "vp_ch3_media_v", "u_inst_media_v", "u_inc_media_v",
                  "n_inc", "n_orden_1", "n_orden_2", "n_orden_3", "n_orden_4+", "kv_medio"])

    # Figura 1: detección
    fig, ejes = _figura(1, 2, "A2 (a) · Detección de cada sensor sobre los eventos emparejados")
    ax, ax2 = ejes[0]
    for c in chs:
        ax.plot(kvs, [f[f"det_{c}"] for f in det[:-1]], color=col[c], marker="o", ms=4, lw=1.2,
                label=f"{SENSORES[c]} ({det[-1][f'det_{c}']:.1%} total)")
    ax.set_xticks(kvs)
    ax.set_ylim(0, 1.05)
    _estilo(ax, X_NIVEL, "Fracción de eventos detectados")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    if xa.size:
        bordes = np.unique(np.quantile(xa, np.linspace(0, 1, 11)))
        cen, fr, err = [], [], []
        for lo, hi in zip(bordes[:-1], bordes[1:]):
            mk = (xa >= lo) & (xa <= hi)
            if mk.sum():
                p_ = ya[mk].mean()
                cen.append(xa[mk].mean())
                fr.append(p_)
                err.append(np.sqrt(p_ * (1 - p_) / mk.sum()))
        ax2.errorbar(cen, fr, yerr=err, color=col["ch2"], marker="o", ls="none", capsize=3, label="Fracción por decil")
        if fit_h:
            xx = np.linspace(xa.min(), xa.max(), 300)
            ax2.plot(xx, _logistica(xx, fit_h["a"], fit_h["b"]), color=col["ch2"], lw=1.2,
                     label=f"Logística: V_p50 = {fit_h['u50']:.3f} V [{ic_h[0]:.3f}, {ic_h[1]:.3f}]")
            ax2.axvline(fit_h["u50"], color="#9aa3ad", lw=0.8, ls=":")
    ax2.set_ylim(-0.03, 1.05)
    ax2.set_title("Detección del HFCT vs V_p de Antena 1", fontsize=10, loc="left")
    _estilo(ax2, "V_p Antena 1 [V]", "P(detección HFCT)")
    ax2.legend(fontsize=8, frameon=False, loc="lower right")
    _guardar(fig, os.path.join(out, "a_deteccion.png"))
    figs.append(fig)

    # Figura 2: tiempos y razón
    fig, ejes = _figura(1, 3, "A2 (b) · Diferencias de llegada y razón de amplitudes entre sensores")
    ax0, ax, ax2 = ejes[0]
    dh = dat["dif_hfct_ns"]
    if dh.size:
        ax0.hist(dh, bins=np.arange(np.floor(dh.min()) - 0.5, np.ceil(dh.max()) + 1.0, 1.0), color=col["ch2"])
        ax0.axvline(des, color="#111", ls="--", lw=1.0, label=f"mediana = {des:.1f} ns")
        ax0.legend(fontsize=8, frameon=False)
    ax0.set_title("t_HFCT − t_Antena 1 (disparos con igual N_PD)", fontsize=9, loc="left")
    _estilo(ax0, "Δt [ns]", "Nº de pares")
    if dt34.size:
        lim = max(3.0, float(np.ceil(np.max(np.abs(dt34)))) + 0.5)
        ax.hist(dt34, bins=np.arange(-lim, lim + 0.1, 0.1), color=col["ch3"])
        for x in (-2.4, 2.4):
            ax.axvline(x, color="#9aa3ad", lw=0.8, ls=":")
    ax.set_title("Δt34 = t_Antena 1 − t_Antena 2 (líneas: ±2.4 ns)", fontsize=9, loc="left")
    _estilo(ax, "Δt34 [ns]", "Nº de eventos")
    oe = _col(Eb, "orden_evento")
    for o, cc in ((1, "#2f5d8a"), (2, "#a8741a"), (3, "#3f7d5c"), (4, "#8b1e3f")):
        mk = (oe == o) if o < 4 else (oe >= 4)
        if mk.any():
            ax2.scatter(dt34[mk], r34[mk], s=12, color=cc, label=f"{o}.ª descarga" if o < 4 else "4.ª o más")
    ax2.set_yscale("log")
    ax2.set_title("R = V_p Antena 1 / V_p Antena 2 vs Δt34", fontsize=9, loc="left")
    _estilo(ax2, "Δt34 [ns]", "R (escala log)")
    ax2.legend(fontsize=8, frameon=False)
    _guardar(fig, os.path.join(out, "b_tiempos_y_razon.png"))
    figs.append(fig)

    # Figura 3: mezcla gaussiana
    if mejor is not None:
        fig, ejes = _figura(1, 2, "A2 (c) · Agrupamiento exploratorio (mezcla gaussiana sobre log R y Δt34)")
        ax, ax2 = ejes[0]
        ax.plot([a["k"] for a in ajustes], [a["bic"] for a in ajustes], marker="o", color="#111")
        ax.axvline(mejor["k"], color="#9aa3ad", ls=":")
        ax.set_xticks([a["k"] for a in ajustes])
        _estilo(ax, "Nº de componentes", "BIC (menor es mejor)")
        ax.set_title(f"Selección por BIC: k = {mejor['k']}", fontsize=10, loc="left")
        paleta = {"A": "#2f5d8a", "B": "#a8741a", "C": "#3f7d5c", "D": "#8b1e3f"}
        for g in sorted({e["grupo"] for e in Eb}):
            mk = np.array([e["grupo"] == g for e in Eb])
            ax2.scatter(dt34[mk], r34[mk], s=12, color=paleta.get(g, "#555"), label=f"Grupo {g} ({mk.sum()})")
        ax2.set_yscale("log")
        _estilo(ax2, "Δt34 [ns]", "R (escala log)")
        ax2.legend(fontsize=8, frameon=False)
        _guardar(fig, os.path.join(out, "c_agrupamiento_gmm.png"))
        figs.append(fig)

    tot = det[-1]
    textos.append(f"Eventos emparejados: {tot['n_eventos']} (ambas antenas {tot['n_ambas_antenas']}, tres sensores "
                  f"{tot['n_tres_sensores']}, solo HFCT {tot['n_solo_hfct']}). Tolerancias: ±{TOL34_NS:g} ns entre "
                  f"antenas, ±{TOL2_NS:g} ns HFCT tras restar el desfase.")
    textos.append(f"Desfase HFCT − Antena 1: mediana {des:.1f} ns sobre {dh.size} pares de disparos con igual N_PD en "
                  "los tres sensores.")
    textos.append("Tasa de detección total: " + "; ".join(f"{SENSORES[c]} {tot[f'det_{c}']:.1%}" for c in chs) + ".")
    if fit_h:
        textos.append(f"HFCT: V_p de Antena 1 con 50 % de detección = {fit_h['u50']:.3f} V (IC 95 % "
                      f"{ic_h[0]:.3f}–{ic_h[1]:.3f} V; s = {fit_h['b']:.3f} V). Ojo: el umbral del HFCT cambia entre niveles.")
    if dt34.size:
        textos.append(f"Δt34: mediana {np.median(dt34):+.2f} ns, RIC {np.subtract(*np.percentile(dt34, [75, 25])):.2f} ns; "
                      f"{np.mean(np.abs(dt34) > 1.2):.1%} de los eventos con |Δt34| > 1.2 ns (posible ciclo distinto, "
                      "~2.4 ns).")
    if mejor is not None:
        txt = (f"Mezcla gaussiana (1–4 componentes, BIC): k = {mejor['k']}. "
               + ("Aparecen 3 grupos, candidatos a las 3 cavidades (ver resumen_grupos_A2.csv: U_inc y orden por grupo)."
                  if mejor["k"] == 3 else
                  "No aparecen 3 grupos: con R y Δt34 no se separan las 3 cavidades (resultado negativo válido)."))
        textos.append(txt)
        for g in grupos_res:
            textos.append(f"  Grupo {g['grupo']}: n = {g['n']}, R mediana {g['r34_mediana']:.2f}, Δt34 mediana "
                          f"{g['dt34_mediana_ns']:+.2f} ns, U_inc media {_fmt(g['u_inc_media_v'], 3)} V, orden 1/2/3: "
                          f"{g['n_orden_1']}/{g['n_orden_2']}/{g['n_orden_3']}.")
    filas = [[str(f["kv"]) if f["kv"] == "total" else _fmt(f["kv"], 0), str(f["n_eventos"]), str(f["n_ambas_antenas"]),
              str(f["n_tres_sensores"]), str(f["n_solo_hfct"])] + [_fmt(f[f"det_{c}"], 3) for c in chs]
             + [_fmt(f.get("desfase_hfct_nivel_ns"), 1)] for f in det]
    tablas.append(("Detección por nivel (fracción de eventos emparejados)",
                   ["kV", "Eventos", "Ambas\nantenas", "Tres\nsensores", "Solo\nHFCT"]
                   + [f"Det.\n{SENSORES[c]}" for c in chs] + ["Desfase HFCT\n(ns)"], filas))
    dat["A2"] = {"det": det, "mejor_k": mejor["k"] if mejor else None}
    return {"figs": figs, "textos": textos, "tablas": tablas}


# =====================================================================================
# A3 — probabilidad vs tensión
# =====================================================================================

def analisis_A3(dat, out):
    P, N, E = dat["disparos"], dat["niveles"], dat["eventos"]
    col, chs = _colores(), canales_de(dat)
    figs, textos, tablas = [], [], []
    n_ev = defaultdict(int)
    for e in E:
        n_ev[(e["kv"], e["seg"])] += 1
    series = chs + ["union"]
    nombre = dict(SENSORES, union="Unión (eventos A2)")
    prob = []
    for n in N:
        Pk = [p for p in P if p["kv"] == n["kv"]]
        U = _mediana(_col(Pk, "u_pico_v"))
        for s in series:
            cnt = np.array([n_ev[(p["kv"], p["seg"])] if s == "union" else (p[f"n_{s}"] or 0) for p in Pk])
            prob.append({"kv": n["kv"], "u_pico_v": U, "serie": nombre[s], "_s": s, "n_disparos": cnt.size,
                         "k_ge1": int((cnt >= 1).sum()), "p_ge1": float((cnt >= 1).mean()) if cnt.size else None,
                         "n_pd_medio": float(cnt.mean()) if cnt.size else None, "k_ge3": int((cnt >= 3).sum()),
                         "p_ge3": float((cnt >= 3).mean()) if cnt.size else None,
                         "p_eq3": float((cnt == 3).mean()) if cnt.size else None})
    escribir_csv(os.path.join(out, "probabilidad_por_nivel.csv"), prob,
                 ["kv", "u_pico_v", "serie", "n_disparos", "k_ge1", "p_ge1", "n_pd_medio", "k_ge3", "p_ge3", "p_eq3"])
    resumen, ajustes = [], {}
    for s in series:
        ps = [f for f in prob if f["_s"] == s]
        x, n = _col(ps, "u_pico_v"), _col(ps, "n_disparos")
        for crit in ("ge1", "ge3"):
            k = _col(ps, f"k_{crit}")
            if k.sum() == 0 or np.all(k == n):
                continue
            for modelo in ("logistica", "weibull"):
                r = ajuste_binomial(x, k, n, modelo)
                b10, b50 = bootstrap_binomial(x, k, n, modelo, r["theta"], n_boot=dat["n_boot"],
                                              semilla=SEMILLA + len(resumen))
                i10, i50 = ic95(b10), ic95(b50)
                ajustes[(s, crit, modelo)] = r
                resumen.append({"serie": nombre[s], "criterio": "N_PD ≥ 1" if crit == "ge1" else "N_PD ≥ 3",
                                "modelo": "logística" if modelo == "logistica" else "Weibull",
                                "u10_v": r["u10"], "u10_ic_inf": i10[0], "u10_ic_sup": i10[1], "u50_v": r["u50"],
                                "u50_ic_inf": i50[0], "u50_ic_sup": i50[1], "a": r["a"], "b": r["b"],
                                "nll": r["nll"], "n_boot_validas": int(b50.size)})
    escribir_csv(os.path.join(out, "resumen_A3.csv"), resumen,
                 ["serie", "criterio", "modelo", "u10_v", "u10_ic_inf", "u10_ic_sup", "u50_v", "u50_ic_inf", "u50_ic_sup",
                  "a", "b", "nll", "n_boot_validas"])

    fig, ejes = _figura(1, 3, "A3 · Probabilidad de descarga vs tensión de pico (U_pico mediano del nivel)")
    xs = _col([f for f in prob if f["_s"] == series[0]], "u_pico_v")
    kvl = [f["kv"] for f in prob if f["_s"] == series[0]]
    xx = np.linspace(np.nanmin(xs) - 0.25, np.nanmax(xs) + 0.1, 400)
    for ax, (clave, eti, crit) in zip(ejes[0], (("p_ge1", "P(N_PD ≥ 1)", "ge1"), ("n_pd_medio", "N̄_PD", None),
                                                 ("p_ge3", "P(N_PD ≥ 3)", "ge3"))):
        for k, s in enumerate(series):
            ps = [f for f in prob if f["_s"] == s]
            cc = col[s]
            ax.plot(_col(ps, "u_pico_v") + (k - 1.5) * 0.008, _col(ps, clave), color=cc, marker="o", ms=4,
                    ls="none" if crit else "-", lw=1.0, label=nombre[s])
            if crit:
                for modelo, ls in (("logistica", "-"), ("weibull", "--")):
                    r = ajustes.get((s, crit, modelo))
                    if r:
                        ax.plot(xx, MODELOS[modelo](xx, r["a"], r["b"]), color=cc, ls=ls, lw=1.0)
        ax.set_xticks(xs)
        ax.set_xticklabels([f"{x:.2f}\n{kv:g} kV" for x, kv in zip(xs, kvl)], fontsize=6)
        _estilo(ax, "U_pico [V del divisor] / nivel", eti)
        if crit:
            ax.set_ylim(-0.03, 1.05)
    ejes[0][0].legend(fontsize=7, frameon=False, loc="lower right", title="línea: logística · trazos: Weibull",
                      title_fontsize=7)
    _guardar(fig, os.path.join(out, "probabilidad_vs_tension.png"))
    figs.append(fig)

    uref = dat["u_inc_ref"]
    for r in resumen:
        if r["criterio"] == "N_PD ≥ 1" and r["serie"] in (SENSORES[CANAL_REF], nombre["union"]):
            textos.append(f"{r['serie']} · {r['modelo']}: U50 = {r['u50_v']:.3f} V [{_fmt(r['u50_ic_inf'], 3)}, "
                          f"{_fmt(r['u50_ic_sup'], 3)}], U10 = {r['u10_v']:.3f} V [{_fmt(r['u10_ic_inf'], 3)}, "
                          f"{_fmt(r['u10_ic_sup'], 3)}] (IC 95 %, {r['n_boot_validas']} réplicas bootstrap).")
    for r in resumen:
        if r["criterio"] == "N_PD ≥ 3" and r["serie"] == SENSORES[CANAL_REF] and r["modelo"] == "logística":
            textos.append(f"{r['serie']} · N_PD ≥ 3 (las 3 cavidades en el mismo disparo): U50 = {r['u50_v']:.3f} V "
                          f"[{_fmt(r['u50_ic_inf'], 3)}, {_fmt(r['u50_ic_sup'], 3)}].")
    ref = ajustes.get((CANAL_REF, "ge1", "logistica"))
    if ref:
        textos.append(f"Comparación con A1: U_inc ref. (tensión instantánea de la 1.ª descarga) = {uref:.3f} V frente a "
                      f"U50 (tensión de pico) = {ref['u50']:.3f} V. U50 es un valor de pico del impulso y U_inc un valor "
                      "instantáneo (U_inc ≤ U_pico siempre).")
    textos.append("Con 10 niveles y ~15 disparos por nivel los IC son anchos; el bootstrap remuestrea disparos dentro "
                  "de cada nivel.")
    filas = [[r["serie"], r["criterio"], r["modelo"], _fmt(r["u10_v"], 3),
              f"[{_fmt(r['u10_ic_inf'], 3)}, {_fmt(r['u10_ic_sup'], 3)}]", _fmt(r["u50_v"], 3),
              f"[{_fmt(r['u50_ic_inf'], 3)}, {_fmt(r['u50_ic_sup'], 3)}]", _fmt(r["b"], 3), _fmt(r["nll"], 2)]
             for r in resumen]
    tablas.append(("Umbrales estadísticos (V del divisor; IC 95 % por bootstrap)",
                   ["Serie", "Criterio", "Modelo", "U10", "IC U10", "U50", "IC U50", "b (s o forma)", "−log L"], filas))
    return {"figs": figs, "textos": textos, "tablas": tablas}


# =====================================================================================
# A4 — intervalos dentro del disparo
# =====================================================================================

def analisis_A4(dat, out):
    D, P, N, E = dat["descargas"], dat["disparos"], dat["niveles"], dat["eventos"]
    col, chs = _colores(), canales_de(dat)
    figs, textos, tablas = [], [], []
    por = defaultdict(list)
    for f in D:
        por[(f["kv"], f["seg"], f["canal"])].append(f)
    for e in E:
        por[(e["kv"], e["seg"], "union")].append(e)
    fuentes = ["union"] + chs
    nombre = dict(SENSORES, union="Eventos A2")
    filas_int = []
    for p in P:
        for s in fuentes:
            g = por.get((p["kv"], p["seg"], s), [])
            if len(g) != 3:
                continue
            if s == "union":
                g = sorted(g, key=lambda e: e["t_ref_us"])
                t = [e["t_ref_us"] for e in g]
                vp = [e["vp_ch3_v"] for e in g]
            else:
                g = sorted(g, key=lambda f: f["t_peak_us"])
                t = [f["t_peak_us"] for f in g]
                vp = [f["vp_v"] for f in g]
            u = [e["u_inst_v"] for e in g]
            dt = intervalos(t)
            filas_int.append({"kv": p["kv"], "seg": p["seg"], "fuente": nombre[s], "_s": s,
                              "t1_abs_us": t[0] - p["t10_us"], "dt12_us": float(dt[0]), "dt23_us": float(dt[1]),
                              "vp1_v": vp[0], "vp2_v": vp[1], "vp3_v": vp[2], "u1_v": u[0], "u2_v": u[1], "u3_v": u[2],
                              "min_intervalo_ns": float(dt.min()) * 1e3,
                              "con_intervalo_corto": bool(dt.min() * 1e3 < MIN_INTERVALO_NS)})
    escribir_csv(os.path.join(out, "intervalos_por_disparo.csv"), filas_int,
                 ["kv", "seg", "fuente", "t1_abs_us", "dt12_us", "dt23_us", "vp1_v", "vp2_v", "vp3_v", "u1_v", "u2_v",
                  "u3_v", "min_intervalo_ns", "con_intervalo_corto"])
    variantes = (("todas", lambda f: True), (f"sin intervalos < {MIN_INTERVALO_NS:g} ns",
                                             lambda f: not f["con_intervalo_corto"]))
    resumen = []
    kvs = [n["kv"] for n in N]
    for var, filtro in variantes:
        for s in fuentes:
            for kv in kvs:
                F = [f for f in filas_int if f["_s"] == s and f["kv"] == kv and filtro(f)]
                fila = {"kv": kv, "fuente": nombre[s], "_s": s, "variante": var, "n_disparos": len(F)}
                for k in ("dt12_us", "dt23_us", "vp1_v", "vp2_v", "vp3_v", "u1_v", "u2_v", "u3_v"):
                    fila[f"{k}_media"] = _media(_col(F, k))
                    fila[f"{k}_sd"] = _sd(_col(F, k))
                resumen.append(fila)
    campos = ["kv", "fuente", "variante", "n_disparos"] + [f"{k}_{e}" for k in
                                                          ("dt12_us", "dt23_us", "vp1_v", "vp2_v", "vp3_v", "u1_v",
                                                           "u2_v", "u3_v") for e in ("media", "sd")]
    escribir_csv(os.path.join(out, "resumen_A4.csv"), resumen, campos)

    cfuente = dict(col)
    fig, ejes = _figura(2, 2, "A4 (a) · Intervalos entre descargas en disparos con N_PD = 3 (media ± σ)")
    for jc, (var, _) in enumerate(variantes):
        for ir, k in enumerate(("dt12_us", "dt23_us")):
            ax = ejes[ir][jc]
            for m, s in enumerate(fuentes):
                R = [r for r in resumen if r["_s"] == s and r["variante"] == var]
                ax.errorbar(np.array([r["kv"] for r in R]) + (m - 1.5) * 0.07, [r[f"{k}_media"] for r in R],
                            yerr=[r[f"{k}_sd"] for r in R], color=cfuente[s], marker="o", ms=4, capsize=3, lw=1.0,
                            label=nombre[s])
            ax.set_xticks(kvs)
            ax.set_title(f"{'Δt12' if k == 'dt12_us' else 'Δt23'} · {var}", fontsize=10, loc="left")
            _estilo(ax, X_NIVEL if ir == 1 else "", f"{'Δt12' if k == 'dt12_us' else 'Δt23'} [µs]")
    ejes[0][0].legend(fontsize=8, frameon=False)
    _guardar(fig, os.path.join(out, "a_intervalos_vs_nivel.png"))
    figs.append(fig)

    for pref, eti, nom, tit in (("vp", "V_p [V]", "b_vp_por_orden", "A4 (b) · V_p de la 1.ª, 2.ª y 3.ª descarga (N_PD = 3)"),
                                ("u", "u_inst [V del divisor]", "c_u_inst_por_orden",
                                 "A4 (c) · Tensión instantánea de la 1.ª, 2.ª y 3.ª descarga (N_PD = 3)")):
        fig, ejes = _figura(1, len(fuentes), tit)
        for ax, s in zip(ejes[0], fuentes):
            R = [r for r in resumen if r["_s"] == s and r["variante"] == "todas"]
            for o, cc in ((1, "#2f5d8a"), (2, "#a8741a"), (3, "#3f7d5c")):
                ax.errorbar(np.array([r["kv"] for r in R]) + (o - 2) * 0.08, [r[f"{pref}{o}_v_media"] for r in R],
                            yerr=[r[f"{pref}{o}_v_sd"] for r in R], color=cc, marker="o", ms=4, capsize=3, lw=1.0,
                            label=f"{o}.ª")
            ax.set_xticks(kvs)
            ax.tick_params(axis="x", labelsize=6)
            ax.set_title(nombre[s] + (" (V_p de Antena 1)" if s == "union" and pref == "vp" else ""), fontsize=9,
                         loc="left")
            _estilo(ax, X_NIVEL, eti)
        ejes[0][0].legend(fontsize=8, frameon=False, title="Descarga", title_fontsize=8)
        _guardar(fig, os.path.join(out, f"{nom}.png"))
        figs.append(fig)

    for s in fuentes:
        F = [f for f in filas_int if f["_s"] == s]
        if not F:
            continue
        nc = sum(f["con_intervalo_corto"] for f in F)
        textos.append(f"{nombre[s]}: {len(F)} disparos con 3 descargas; Δt12 medio {_media(_col(F, 'dt12_us')):.3f} µs, "
                      f"Δt23 medio {_media(_col(F, 'dt23_us')):.3f} µs; {nc} con algún intervalo < {MIN_INTERVALO_NS:g} ns.")
    F = [f for f in filas_int if f["_s"] == "union" and not f["con_intervalo_corto"]]
    if len(F) > 3:
        v = np.array([[f["vp1_v"], f["vp2_v"], f["vp3_v"]] for f in F], dtype=float)
        v = v[np.all(np.isfinite(v), axis=1)]
        if v.shape[0] > 3:
            fr = stats.friedmanchisquare(v[:, 0], v[:, 1], v[:, 2])
            textos.append(f"Eventos A2 sin intervalos cortos: V_p medio de Antena 1 por orden 1.ª/2.ª/3.ª = "
                          f"{v[:, 0].mean():.3f}/{v[:, 1].mean():.3f}/{v[:, 2].mean():.3f} V; Friedman p = {fr.pvalue:.2g} "
                          f"(n = {v.shape[0]}).")
        dd = np.array([[f["dt12_us"], f["dt23_us"]] for f in F])
        w = stats.wilcoxon(dd[:, 0], dd[:, 1])
        textos.append(f"Δt12 vs Δt23 pareados (Eventos A2, sin cortos): mediana {np.median(dd[:, 0]):.3f} vs "
                      f"{np.median(dd[:, 1]):.3f} µs; Wilcoxon p = {w.pvalue:.2g}.")
    filas = [[_fmt(r["kv"], 0), r["fuente"], r["variante"], str(r["n_disparos"]), _fmt(r["dt12_us_media"], 3),
              _fmt(r["dt23_us_media"], 3), _fmt(r["vp1_v_media"], 3), _fmt(r["vp2_v_media"], 3), _fmt(r["vp3_v_media"], 3),
              _fmt(r["u1_v_media"], 3), _fmt(r["u2_v_media"], 3), _fmt(r["u3_v_media"], 3)]
             for r in resumen if r["_s"] in ("union", CANAL_REF) and r["n_disparos"]]
    tablas.append(("Resumen A4 (Eventos A2 y Antena 1; medias)",
                   ["kV", "Fuente", "Variante", "Disparos", "Δt12\n(µs)", "Δt23\n(µs)", "V_p 1.ª", "V_p 2.ª", "V_p 3.ª",
                    "u 1.ª", "u 2.ª", "u 3.ª"], filas))
    return {"figs": figs, "textos": textos, "tablas": tablas}


# =====================================================================================
# A5 — tendencias dentro del nivel
# =====================================================================================

VARIABLES_A5 = (("vp_media", "V̄_p del disparo [V]"), ("n_pd", "N_PD"), ("t_abs_1a", "t_abs 1.ª descarga [µs]"))


def analisis_A5(dat, out):
    D, P, N = dat["descargas"], dat["disparos"], dat["niveles"]
    col, chs = _colores(), canales_de(dat)
    figs, textos, tablas = [], [], []
    por = defaultdict(list)
    for f in D:
        por[(f["kv"], f["canal"], f["seg"])].append(f)
    series, filas_s = {}, []
    for n in N:
        Pk = [p for p in P if p["kv"] == n["kv"]]
        for c in n["canales"]:
            segs, vpm, npd, t1 = [], [], [], []
            for p in Pk:
                g = por.get((n["kv"], c, p["seg"]), [])
                segs.append(p["seg"])
                vpm.append(_media([f["vp_v"] for f in g]) if g else np.nan)
                npd.append(p[f"n_{c}"] or 0)
                t1.append(min(g, key=lambda f: f["t_peak_us"])["t_abs_us"] if g else np.nan)
                filas_s.append({"kv": n["kv"], "sensor": SENSORES[c], "seg": p["seg"], "vp_media_v": vpm[-1],
                                "n_pd": npd[-1], "t_abs_1a_us": t1[-1]})
            series[(n["kv"], c)] = {"seg": np.array(segs, float), "vp_media": np.array(vpm, float),
                                    "n_pd": np.array(npd, float), "t_abs_1a": np.array(t1, float)}
    escribir_csv(os.path.join(out, "series_por_disparo.csv"), filas_s,
                 ["kv", "sensor", "seg", "vp_media_v", "n_pd", "t_abs_1a_us"])
    resumen = []
    for (kv, c), sr in series.items():
        for v, _ in VARIABLES_A5:
            r, p, nn = spearman(sr["seg"], sr[v])
            resumen.append({"kv": kv, "sensor": SENSORES[c], "_c": c, "variable": v, "n": nn, "rho": r, "p": p})
    q = fdr_bh([r["p"] for r in resumen])
    for r, qq in zip(resumen, q):
        r["q_bh"] = qq
        r["p_lt_005"] = bool(np.isfinite(r["p"]) and r["p"] < 0.05)
        r["q_lt_005"] = bool(np.isfinite(qq) and qq < 0.05)
    anom = {n["kv"]: n["anomalias"] for n in N}
    for r in resumen:
        r["anomalias_cadencia"] = "; ".join(f"{a.get('desde_seg')}→{a.get('hasta_seg')}: {a.get('dt_s')} s"
                                            for a in anom.get(r["kv"], []))
    escribir_csv(os.path.join(out, "resumen_A5.csv"), resumen,
                 ["kv", "sensor", "variable", "n", "rho", "p", "p_lt_005", "q_bh", "q_lt_005", "anomalias_cadencia"])
    rix = {(r["kv"], r["_c"], r["variable"]): r for r in resumen}

    kvs = [n["kv"] for n in N]
    for parte, trozo in enumerate([kvs[i:i + 5] for i in range(0, len(kvs), 5)], 1):
        fig, ejes = _figura(len(trozo), 3, f"A5 · Evolución disparo a disparo ({parte}/{(len(kvs) + 4) // 5})")
        for i, kv in enumerate(trozo):
            for j, (v, eti) in enumerate(VARIABLES_A5):
                ax = ejes[i][j]
                txt = []
                for c in chs:
                    sr = series.get((kv, c))
                    if sr is None:
                        continue
                    ax.plot(sr["seg"], sr[v], color=col[c], marker="o", ms=3, lw=0.9, label=SENSORES[c])
                    r = rix[(kv, c, v)]
                    if np.isfinite(r["rho"]):
                        txt.append(f"{SENSORES[c][0]}{SENSORES[c][-1] if c != 'ch2' else ''} {r['rho']:+.2f}"
                                   + ("*" if r["p_lt_005"] else ""))
                for a in anom.get(kv, []):
                    if a.get("hasta_seg") is not None:
                        ax.axvline(a["hasta_seg"] - 0.5, color="#c0392b", lw=0.8, ls=":")
                ax.text(0.99, 0.95, "ρ: " + " · ".join(txt), transform=ax.transAxes, ha="right", va="top", fontsize=6,
                        color="#555")
                if i == 0:
                    ax.set_title(eti, fontsize=9, loc="left")
                _estilo(ax, "Nº de disparo" if i == len(trozo) - 1 else "", f"{kv:g} kV" if j == 0 else "")
                ax.tick_params(labelsize=6)
        ejes[0][0].legend(fontsize=6, frameon=False, loc="lower left", ncol=3)
        _guardar(fig, os.path.join(out, f"tendencias_{parte}.png"))
        figs.append(fig)

    fig, ejes = _figura(1, len(chs), "A5 · ρ de Spearman vs nº de disparo (* p < 0.05, ** q_BH < 0.05)")
    im = None
    for ax, c in zip(ejes[0], chs):
        M = np.array([[rix.get((kv, c, v), {}).get("rho", np.nan) for v, _ in VARIABLES_A5] for kv in kvs])
        im = ax.imshow(M, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        for i, kv in enumerate(kvs):
            for j, (v, _) in enumerate(VARIABLES_A5):
                r = rix.get((kv, c, v))
                if r and np.isfinite(r["rho"]):
                    ax.text(j, i, f"{r['rho']:+.2f}" + ("**" if r["q_lt_005"] else "*" if r["p_lt_005"] else ""),
                            ha="center", va="center", fontsize=7)
        ax.set_xticks(range(len(VARIABLES_A5)))
        ax.set_xticklabels(["V̄_p", "N_PD", "t_abs 1.ª"], fontsize=8)
        ax.set_yticks(range(len(kvs)))
        ax.set_yticklabels([f"{kv:g} kV" for kv in kvs], fontsize=8)
        ax.set_title(SENSORES[c], fontsize=10, loc="left")
    if im is not None:
        fig.colorbar(im, ax=ejes[0].tolist(), label="ρ", shrink=0.8)
    _guardar(fig, os.path.join(out, "mapa_rho.png"))
    figs.append(fig)

    nt = sum(np.isfinite(r["p"]) for r in resumen)
    ns = [r for r in resumen if r["p_lt_005"]]
    nq = [r for r in resumen if r["q_lt_005"]]
    textos.append(f"{nt} pruebas de Spearman válidas; {len(ns)} con p < 0.05 (esperables por azar ≈ {0.05 * nt:.1f}); "
                  f"{len(nq)} siguen significativas con corrección de Benjamini–Hochberg (q < 0.05).")
    for r in sorted(ns, key=lambda r: r["p"]):
        textos.append(f"  {r['kv']:g} kV · {r['sensor']} · {r['variable']}: ρ = {r['rho']:+.2f}, p = {r['p']:.2g}, "
                      f"q = {r['q_bh']:.2g}")
    for kv, a in anom.items():
        if a:
            textos.append(f"Cadencia anómala en {kv:g} kV: " + "; ".join(
                f"disparos {x.get('desde_seg')}→{x.get('hasta_seg')} a {x.get('dt_s')} s" for x in a)
                + " (línea roja punteada en las figuras).")
    filas = [[_fmt(r["kv"], 0), r["sensor"], r["variable"], str(r["n"]), _fmt(r["rho"], 2), _fmt(r["p"], 3),
              _fmt(r["q_bh"], 3), "sí" if r["p_lt_005"] else ""] for r in resumen if r["_c"] == CANAL_REF]
    tablas.append((f"Spearman vs nº de disparo · {SENSORES[CANAL_REF]} (todas las filas en resumen_A5.csv)",
                   ["kV", "Sensor", "Variable", "n", "ρ", "p", "q_BH", "p < 0.05"], filas))
    return {"figs": figs, "textos": textos, "tablas": tablas}


# =====================================================================================
# Informe
# =====================================================================================

def pagina_texto(pdf, titulo, lineas, subtitulo=""):
    envueltas = []
    for ln in lineas:
        sangria = "    " if ln.startswith("  ") else ""
        envueltas += textwrap.wrap(ln.strip(), 150, initial_indent="• " if not sangria else sangria + "– ",
                                   subsequent_indent="   " + sangria) or [""]
    por_pag = 34
    trozos = [envueltas[i:i + por_pag] for i in range(0, max(len(envueltas), 1), por_pag)]
    for n, tr in enumerate(trozos, 1):
        fig = plt.figure(figsize=A4)
        fig.text(0.04, 0.94, titulo + (f" ({n}/{len(trozos)})" if len(trozos) > 1 else ""), fontsize=14,
                 fontweight="bold")
        if subtitulo:
            fig.text(0.04, 0.905, subtitulo, fontsize=8, color="#555")
        for i, ln in enumerate(tr):
            fig.text(0.05, 0.86 - i * 0.024, ln, fontsize=9, family="DejaVu Sans")
        pdf.savefig(fig)
        plt.close(fig)


def paginas_tabla(pdf, titulo, cabecera, filas):
    if not filas:
        return
    largo = np.array([max(len(str(h).split("\n")[0]), *(len(str(f[i])) for f in filas)) for i, h in enumerate(cabecera)],
                     dtype=float)
    anchos = np.maximum(largo, 4)
    trozos = [filas[i:i + FILAS_TABLA] for i in range(0, len(filas), FILAS_TABLA)]
    for n, tr in enumerate(trozos, 1):
        fig = plt.figure(figsize=A4)
        fig.text(0.04, 0.95, titulo + (f" ({n}/{len(trozos)})" if len(trozos) > 1 else ""), fontsize=12,
                 fontweight="bold")
        ax = fig.add_axes((0.03, 0.03, 0.94, 0.88))
        ax.axis("off")
        t = ax.table(cellText=tr, colLabels=cabecera, loc="upper center", cellLoc="center",
                     colWidths=list(anchos / anchos.sum()))
        t.auto_set_font_size(False)
        t.set_fontsize(7)
        t.scale(1, 1.3)
        for (i, _), celda in t.get_celld().items():
            celda.set_edgecolor("#d9dee5")
            if i == 0:
                celda.set_facecolor("#eef1f5")
                celda.set_text_props(fontweight="bold")
                celda.set_height(celda.get_height() * 1.9)
            elif i % 2 == 0:
                celda.set_facecolor("#f7f8fa")
        pdf.savefig(fig)
        plt.close(fig)


def escribir_informe(ruta, dat, ctrl, secciones):
    tmp = ruta[:-4] + ".tmp.pdf"
    N = dat["niveles"]
    with PdfPages(tmp) as pdf:
        probetas = ", ".join(sorted({n["probeta"] for n in N}))
        lista_kv = ", ".join(f"{n['kv']:g}" for n in N)
        portada = [f"Probeta(s): {probetas} · niveles: {lista_kv} kV (tensión AC del secundario del generador).",
                   f"{len(dat['disparos'])} disparos válidos, {len(dat['descargas'])} descargas (todos los sensores).",
                   "Tensiones del impulso en V a la salida del divisor (no hay razón del divisor); V_p = máximo de la "
                   "señal del sensor en el peak marcado; t_abs = t_peak − t10 del disparo.",
                   f"CH1 suavizado con media móvil de {VENTANA_SUAV_NS:g} ns; sensor de referencia: {SENSORES[CANAL_REF]}.",
                   f"Controles: {sum(c['ok'] for c in ctrl)} de {len(ctrl)} correctos (detalle en controles.csv)."]
        portada += [f"  CONTROL FALLIDO · {c['control']}: {c['detalle']}" for c in ctrl if not c["ok"]]
        for k in ANALISIS:
            if k in secciones and secciones[k]["textos"]:
                portada.append(f"{TITULOS[k]}: {secciones[k]['textos'][0]}")
        pagina_texto(pdf, "Análisis adicionales del reporte 4", portada,
                     "Generado por analisis_reporte4.py · plan: archivos_md/plan_analisis_reporte4.md")
        for k in ANALISIS:
            if k not in secciones:
                continue
            s = secciones[k]
            pagina_texto(pdf, TITULOS[k], s["textos"])
            for tit, cab, filas in s["tablas"]:
                paginas_tabla(pdf, tit, cab, filas)
            for fig in s["figs"]:
                pdf.savefig(fig)
    os.replace(tmp, ruta)
    print(f"Informe: {ruta}")


# =====================================================================================
# Principal
# =====================================================================================

FUNCIONES = {"A1": analisis_A1, "A2": analisis_A2, "A3": analisis_A3, "A4": analisis_A4, "A5": analisis_A5}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo", nargs="+", type=str.upper, choices=ANALISIS, help="ejecutar solo estos análisis")
    ap.add_argument("--reporte", default=REPORTE4, help="carpeta del reporte 4 (con mediciones_listas.txt)")
    ap.add_argument("--salida", default=None, help="carpeta de salida (por defecto <reporte>/analisis)")
    ap.add_argument("--n-boot", type=int, default=N_BOOT, help="réplicas bootstrap (A2, A3)")
    a = ap.parse_args(argv)
    sel = set(a.solo or ANALISIS)
    salida = a.salida or os.path.join(a.reporte, "analisis")
    os.makedirs(salida, exist_ok=True)

    dat = cargar_descargas(a.reporte)
    dat["n_boot"] = a.n_boot
    if not dat["descargas"]:
        print("No hay descargas: revise mediciones_listas.txt.")
        return 1
    escribir_csv(os.path.join(salida, "descargas.csv"), dat["descargas"], CAMPOS_DESCARGA)
    escribir_csv(os.path.join(salida, "disparos.csv"), dat["disparos"], CAMPOS_DISPARO)
    ctrl = controles(dat, a.reporte)
    escribir_csv(os.path.join(salida, "controles.csv"), ctrl, ["control", "detalle", "ok"])
    for c in ctrl:
        print(f"[{'OK' if c['ok'] else 'FALLA'}] {c['control']}: {c['detalle']}")
    if sel & {"A2", "A3", "A4"}:
        construir_eventos(dat)

    secciones = {}
    for k in ORDEN_EJECUCION:
        if k in sel:
            sub = os.path.join(salida, SUBCARPETAS[k])
            os.makedirs(sub, exist_ok=True)
            print(f"--- {TITULOS[k]}")
            secciones[k] = FUNCIONES[k](dat, sub)
            for t in secciones[k]["textos"]:
                print("   " + t)
    nombre = "informe_analisis.pdf" if sel == set(ANALISIS) else "informe_analisis_parcial.pdf"
    escribir_informe(os.path.join(salida, nombre), dat, ctrl, secciones)
    plt.close("all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
