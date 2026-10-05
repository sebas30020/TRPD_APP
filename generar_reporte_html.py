"""Página HTML local para revisar cómo se construye cada mapa TRPD (Antena 1 CH3 + HFCT CH2).

Por cada medición se ven los dos mapas TRPD y, al hacer clic en un punto, las cuatro señales del
disparo que lo originó (CH1..CH4) con la descarga marcada y una ventana de detalle a alta
resolución. Todo se calcula dos veces: con los filtros digitales de cada canal (HP 200 MHz en
CH3/CH4, HP 5 MHz en CH2) y sobre la señal cruda del osciloscopio. La detección es la de
generar_informe_trpd.calcular() (sin cambios); además se muestran los candidatos entre
FRAC_CANDIDATO·umbral y el umbral. En la página se marca "no es DP" / "es DP" y se exporta un
JSON (revision_trpd.json) que `--aplicar` convierte en ediciones manuales de metadata.yaml
(ediciones_peaks.<canal>.historial, en tiempo del osciloscopio: valen con y sin filtro).

Uso:
    python generar_reporte_html.py [<raiz> ...] [--salida <dir>] [--solo <subcadena de la ruta>]
    python generar_reporte_html.py --aplicar revision_trpd.json [--respaldo <dir>]
Salida (por defecto reportes/reporte2): index.html, assets/ (Plotly local, visor.js, visor.css)
y data/ (indice.js + m<NN>.js por medición, cargados con <script>: funciona con file://).
"""

import argparse
import base64
import datetime
import json
import os
import shutil
import sys

import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import app  # noqa: E402
import filtros  # noqa: E402
import generar_informe_trpd as gi  # noqa: E402
import tema  # noqa: E402

SALIDA_DEFECTO = os.path.join(gi.PROYECTO, "reportes", "reporte2")
CANALES_MAPA = ["ch3", "ch2"]
CANALES_SENAL = ["ch1", "ch2", "ch3", "ch4"]
NOMBRES = {"ch1": "Impulso CH1 [V]", "ch2": "HFCT CH2 [mV]", "ch3": "Antena 1 CH3 [mV]",
           "ch4": "Antena 2 CH4 [mV]", "ch2r": "HFCT − resonancia [mV]"}
BINS_TRAZA = 3000            # traza completa: min-max en 3000 intervalos (~12 ns)
DETALLE_US = 0.25            # ventana de detalle ± (µs) alrededor de cada punto
PASO_DETALLE = 2             # 1 de cada 2 muestras (0.2 ns con muestreo de 0.1 ns)
MAX_DETALLE_CAND = 400       # candidatos con ventana de detalle por canal y estado (los mayores)
AVISO_MB = 15.0
PLOTLY = os.path.join(os.path.dirname(os.path.dirname(np.__file__)), "plotly", "package_data",
                      "plotly.min.js")
ESTADOS = {"F": True, "C": False}


# ---------------- Codificación ----------------

def _b64_i16(v):
    """(base64 de Int16 little-endian, escala) con v ≈ i16 · escala."""
    v = np.asarray(v, dtype=np.float64)
    m = float(np.max(np.abs(v))) if v.size else 0.0
    esc = (m / 32000.0) or 1.0
    q = np.round(v / esc).astype("<i2")
    return base64.b64encode(q.tobytes()).decode("ascii"), esc


def _minmax(t, v, n):
    """Traza diezmada en n intervalos uniformes: (t0, ancho, base64 [min, max]·n, escala)."""
    k = max(1, v.size // n)
    m = v.size // k
    bloques = v[:m * k].reshape(m, k)
    par = np.empty(2 * m)
    par[0::2], par[1::2] = bloques.min(axis=1), bloques.max(axis=1)
    b, esc = _b64_i16(par)
    return {"t0": float(t[0]), "w": float((t[1] - t[0]) * k), "y": b, "s": esc}


def _uniforme(t, v):
    b, esc = _b64_i16(v)
    return {"t0": float(t[0]), "dt": float(t[1] - t[0]) if t.size > 1 else 0.0, "y": b, "s": esc}


# ---------------- Señales ----------------

class Senales:
    """Señales de un disparo y estado, cacheadas mientras se procesa una medición."""

    def __init__(self, carpeta, filtrado, r_ch2):
        self.carpeta, self.filtrado, self.r2 = carpeta, filtrado, r_ch2
        self.presentes = app.canales_presentes(carpeta)
        self.t10 = app.t10_por_segmento(carpeta)
        self._cache = {}

    def get(self, seg, ch):
        clave = (seg, ch)
        if clave not in self._cache:
            if ch == "ch2r":
                t, v = self.get(seg, "ch2")
                mod = self.r2["modelo"].get(seg) if self.r2 else None
                if mod is None:
                    res = (t, v)
                else:
                    ta = t - self.t10[seg - 1]
                    res = (t, v - np.interp(ta, self.r2["malla"], mod, left=0.0, right=0.0))
            elif ch not in self.presentes:
                res = (np.array([]), np.array([]))
            else:
                t, v = app.cargar_segmento(self.carpeta, ch, seg, filtrado=self.filtrado)
                res = (t, v / 1000.0 if ch == "ch1" else v)
            self._cache[clave] = res
        return self._cache[clave]

    def limpiar(self):
        self._cache.clear()


def _detalle(sen, seg, t_osc):
    """Ventanas ±DETALLE_US (cada PASO_DETALLE muestras) de CH2, CH2−resonancia, CH3 y CH4."""
    out = {}
    for ch in ("ch3", "ch4", "ch2", "ch2r"):
        t, v = sen.get(seg, ch)
        if not t.size:
            continue
        a, b = np.searchsorted(t, [t_osc - DETALLE_US, t_osc + DETALLE_US])
        if b - a > 2:
            out[ch] = _uniforme(t[a:b:PASO_DETALLE], v[a:b:PASO_DETALLE])
    return out


# ---------------- Datos por medición ----------------

def _estado(mid, letra, rs, sen, d):
    """Detecciones, candidatos, Tabla 1, señales y detalles de una medición en un estado."""
    t10 = sen.t10
    det, cand, fila, cuentas, detalle = {}, {}, {}, {}, {}
    for ch in CANALES_MAPA:
        r = rs[ch]
        cap = r["cap"]
        n = cap["t_peak"].size
        origen = np.asarray(cap.get("origen", np.zeros(n, dtype=int)))
        otro = [o for o in CANALES_MAPA if o != ch][0]
        en = r.get("en", {}).get(otro, np.zeros(n, dtype=bool))
        env = cap.get("env")
        filas = []
        for i in range(n):
            pid = f"{mid}-{ch}-{letra}-{i + 1}"
            s = int(cap["seg"][i])
            filas.append([pid, s, round(float(cap["t_peak"][i]), 5), round(float(r["t_abs"][i]), 5),
                          round(float(cap["v_peak"][i]), 2), round(float(cap["vpp"][i]), 2),
                          int(bool(en[i])), int(origen[i] == 1),
                          round(float(env[i]), 2) if env is not None and i < env.size and origen[i] != 1 else None])
            detalle[pid] = _detalle(sen, s, float(cap["t_peak"][i]))
        det[ch] = filas
        lista = sorted(r.get("candidatos", []), key=lambda c: (c[0], c[1]))
        con_det = set(sorted(range(len(lista)), key=lambda k: -lista[k][2])[:MAX_DETALLE_CAND])
        cf = []
        for k, (s, t, v) in enumerate(lista):
            pid = f"{mid}-{ch}-{letra}-c{k + 1}"
            ts, vs = sen.get(s, "ch2r" if ch in gi.RESONANCIA else ch)   # Vpp como en la detección
            a, b = np.searchsorted(ts, [t - app.VENTANA_PD_ANTES_US, t + app.VENTANA_PD_DESP_US])
            vpp = float(np.ptp(vs[a:b])) if b > a else 0.0
            cf.append([pid, s, round(t, 5), round(t - float(t10[s - 1]) - r["t_lag"], 5), round(v, 2), round(vpp, 2)])
            if k in con_det:
                detalle[pid] = _detalle(sen, s, t)
        cand[ch] = cf
        fila[ch] = {k: r["fila"].get(k, "") for k in gi.CLAVES_RESUMEN}
        cuentas[ch] = r["cuentas"]
    senal = {}
    for s in range(1, d["nsegs"] + 1):
        senal[s] = {}
        for ch in CANALES_SENAL + ["ch2r"]:
            t, v = sen.get(s, ch)
            if t.size:
                senal[s][ch] = _minmax(t, v, BINS_TRAZA)
        sen.limpiar()
    return {"det": det, "cand": cand, "fila": fila, "cuentas": cuentas, "senal": senal,
            "detalle": detalle,
            "umbral": {ch: rs[ch]["umbral"] for ch in CANALES_MAPA},
            "filtro": {ch: (filtros.etiqueta(app.spec_filtro(d["carpeta"], ch)) if ESTADOS[letra] else "sin filtro")
                       for ch in CANALES_SENAL[1:]}}


def _resumen_estado(e):
    return {ch: {"n": len(e["det"][ch]), "coinc": sum(f[6] for f in e["det"][ch]),
                 "cand": len(e["cand"][ch])} for ch in CANALES_MAPA}


# ---------------- Escritura ----------------

def _js(nombre_var, clave, obj):
    txt = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if clave is None:
        return f"window.{nombre_var}={txt};\n"
    return f"window.{nombre_var}=window.{nombre_var}||{{}};window.{nombre_var}[{json.dumps(clave)}]={txt};\n"


def generar(raices, salida, solo=None):
    res_e, descs = {}, None
    for letra, filtrado in ESTADOS.items():
        print(f"== Detección {'con filtros' if filtrado else 'sin filtros (señal cruda)'}", flush=True)
        descs, res_e[letra], _ = gi.calcular(raices, CANALES_MAPA, solo=solo, filtrado=filtrado)
    os.makedirs(os.path.join(salida, "data"), exist_ok=True)
    os.makedirs(os.path.join(salida, "assets"), exist_ok=True)
    indice, total = [], 0.0
    for i, d in enumerate(descs):
        mid = f"m{i + 1:02d}"
        carpeta = d["carpeta"]
        meta = {"id": mid, "titulo": d["titulo"], "ruta": d["ruta"], "set": d["set"],
                "probeta": d["probeta"], "nsegs": d["nsegs"],
                "t10": [round(float(x), 6) for x in app.t10_por_segmento(carpeta)],
                "t_ini": {ch: gi.T_INI_US.get(ch, 0.0) for ch in CANALES_MAPA},
                "t_lag": {ch: res_e["F"][ch][i]["t_lag"] for ch in CANALES_MAPA}}
        datos = {"meta": meta, "est": {}}
        for letra, filtrado in ESTADOS.items():
            rs = {ch: res_e[letra][ch][i] for ch in CANALES_MAPA}
            sen = Senales(carpeta, filtrado, rs.get("ch2"))
            datos["est"][letra] = _estado(mid, letra, rs, sen, d)
        ruta_js = os.path.join(salida, "data", f"{mid}.js")
        with open(ruta_js, "w", encoding="utf-8") as f:
            f.write(_js("TRPD_DATA", mid, datos))
        mb = os.path.getsize(ruta_js) / 1e6
        total += mb
        print(f"  {mid} {d['ruta']}: {mb:.1f} MB" + ("  <-- supera el aviso" if mb > AVISO_MB else ""), flush=True)
        indice.append({"id": mid, "titulo": d["titulo"], "ruta": d["ruta"], "set": d["set"],
                       "probeta": d["probeta"], "nsegs": d["nsegs"],
                       "res": {e: _resumen_estado(datos["est"][e]) for e in ESTADOS}})
        for letra in ESTADOS:          # liberar la resonancia ajustada de la medición ya escrita
            for ch in CANALES_MAPA:
                res_e[letra][ch][i].pop("modelo", None)
    config = {
        "generado": datetime.datetime.now().isoformat(timespec="minutes"),
        "colores": {ch: tema.COLORES_CANALES.get(ch, "#555") for ch in CANALES_SENAL},
        "nombres": NOMBRES, "retardo": gi.RETARDO_US, "tol_coinc": gi.TOL_COINC_US,
        "frac_cand": gi.FRAC_CANDIDATO, "k_env": gi.RESONANCIA["ch2"]["k_env"],
        "dist": {ch: gi.DIST_US.get(ch, app.DIST_DEFECTO_US) for ch in CANALES_MAPA},
        "detalle_us": DETALLE_US, "x_lim": list(gi.X_LIM), "t_lim": [app.T_MIN, app.T_MAX],
    }
    with open(os.path.join(salida, "data", "indice.js"), "w", encoding="utf-8") as f:
        f.write(_js("TRPD_INDICE", None, indice) + _js("TRPD_CONFIG", None, config))
    shutil.copyfile(PLOTLY, os.path.join(salida, "assets", "plotly.min.js"))
    for nombre in ("index.html", "visor.js", "visor.css"):
        origen = os.path.join(AQUI, "reporte_html", nombre)
        destino = os.path.join(salida, nombre if nombre == "index.html" else os.path.join("assets", nombre))
        shutil.copyfile(origen, destino)
    print(f"Página guardada: {os.path.join(salida, 'index.html')} (datos {total:.1f} MB)")


# ---------------- Aplicar la revisión ----------------

def aplicar(ruta_json, raices, respaldo):
    """Añade las marcas de la revisión como pasos del historial de ediciones de cada medición."""
    with open(ruta_json, encoding="utf-8") as f:
        marcas = json.load(f)
    rutas = {}
    for raiz in raices:
        base = os.path.dirname(raiz)
        for dirpath, _, files in os.walk(raiz):
            if "metadata.yaml" in files:
                rutas[os.path.relpath(dirpath, base)] = dirpath
    grupos = {}
    for m in marcas:
        clave = (m["ruta"], m["canal"], m["accion"])
        grupos.setdefault(clave, []).append({"seg": int(m["seg"]), "t_us": float(m["t_us"])})
    os.makedirs(respaldo, exist_ok=True)
    for (ruta, canal, accion), puntos in grupos.items():
        carpeta = rutas.get(ruta)
        if not carpeta:
            print(f"Aviso: no se encuentra la medición {ruta}; se omite")
            continue
        destino = os.path.join(respaldo, ruta.replace(os.sep, "__") + "__metadata.yaml")
        if not os.path.exists(destino):
            shutil.copyfile(os.path.join(carpeta, "metadata.yaml"), destino)
        ed = app.ediciones_canal(carpeta, canal)
        ed["historial"].append({"accion": accion, "puntos": puntos,
                                "origen": f"revision_trpd {datetime.date.today().isoformat()}"})
        app.guardar_ediciones_canal(carpeta, canal, ed)
        print(f"{ruta} {canal}: {accion} {len(puntos)} punto(s)")
    print(f"Respaldo de los metadata.yaml en {respaldo}")


def main():
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("raices", nargs="*", default=gi.RAICES_DEFECTO)
    ap.add_argument("--salida", default=SALIDA_DEFECTO)
    ap.add_argument("--solo", default=None, help="solo las mediciones cuya ruta contenga este texto")
    ap.add_argument("--aplicar", default=None, metavar="JSON",
                    help="aplicar una revisión exportada desde la página (ediciones en metadata.yaml)")
    ap.add_argument("--respaldo", default=os.path.join(SALIDA_DEFECTO, "respaldo_metadata"),
                    help="carpeta para copiar los metadata.yaml antes de modificarlos")
    a = ap.parse_args()
    if a.aplicar:
        aplicar(a.aplicar, a.raices, a.respaldo)
    else:
        generar(a.raices, a.salida, a.solo)


if __name__ == "__main__":
    main()
