"""
App Dash - Visor de segmentos (ch1..ch4.h5)

Lee las mediciones de la carpeta ./Mediciones. Cada medicion es una subcarpeta
con los archivos ch1.h5, ch2.h5, ch3.h5 y ch4.h5. Se elige la medicion con un
selector de carpetas.

4 filas (una por canal), eje temporal compartido, cada senal normalizada por su
maximo (|pico| = 1). Selector de segmento. Render con WebGL (Scattergl).

Ejecutar:  python3 app.py   ->  abrir http://127.0.0.1:8050
"""
import datetime
import functools
import os
import re

import h5py
import numpy as np
import plotly.graph_objects as go
import scipy.fft as sfft
import yaml
from plotly.subplots import make_subplots
from scipy.signal import find_peaks, butter, sosfiltfilt, welch
from dash import Dash, dcc, html, dash_table, Input, Output, State, no_update, ctx

from generate_metadata import plantilla_metadata, inferir_parametros, inferir_diametros, bloque_calibracion_retardo

AQUI = os.path.dirname(os.path.abspath(__file__))
# Carpeta de datos: vive fuera del repo, en la carpeta hermana "mediciones/Mediciones"
# (../mediciones/Mediciones respecto a este archivo). Antes se accedía via un
# symlink "Mediciones" dentro del repo, pero git en Windows no lo versiona
# correctamente (core.symlinks=false), así que se referencia por ruta directa.
MEDICIONES = os.path.abspath(os.path.join(AQUI, os.pardir, "mediciones", "Mediciones"))
CANALES = ["ch1", "ch2", "ch3", "ch4"]
TRIGGERS = ["ch2", "ch3", "ch4"]  # canales seleccionables como trigger

# Ventana temporal a graficar (microsegundos)
T_MIN, T_MAX = -5, 30.0

# Ventana normalizada de captura alrededor de cada descarga de DP
VENTANA_PD_TOTAL_US = 0.070    # 70 ns de duración total
VENTANA_PD_ANTES_US = 0.007    # 10% antes del peak (7 ns)
VENTANA_PD_DESP_US = 0.063     # 90% después del peak (63 ns)

# Impulso (CH1): filtro pasa-bajos aplicado a la señal de impulso promediada.
IMP_FCORTE = 20e6   # Hz, frecuencia de corte del pasa-bajos
IMP_ORDEN = 4       # orden del Butterworth (fase cero, sosfiltfilt)

# Transformada S: nº de frecuencias (bins lineales entre 0 y f máx) y de
# columnas de tiempo con que se dibuja cada mapa de calor.
ST_NFREQ = 250
ST_NT_VENTANA = 350     # ventana de 70 ns (captura punto a punto)
ST_NT_SEGMENTO = 1000   # segmento completo (-5..30 µs)
ST_FMAX_MHZ = 2500      # por defecto, Nyquist a Fs = 5 GSa/s


_CHAN_RE = re.compile(r"^(.*?)(ch[1-4])(.*?)\.h5$", re.IGNORECASE)


def _orden_natural(s):
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", s)]


def _ruta(carpeta, canal):
    canal = canal.lower()
    if os.path.isabs(carpeta):
        if os.path.isfile(carpeta):
            d, fname = os.path.split(carpeta)
            m = _CHAN_RE.match(fname)
            if m:
                pref, suff = m.group(1), m.group(3)
                p = os.path.join(d, f"{pref}{canal}{suff}.h5")
                if os.path.isfile(p):
                    return p
            return carpeta if canal in fname.lower() else None
        elif os.path.isdir(carpeta):
            carpeta = os.path.relpath(carpeta, MEDICIONES).replace("\\", "/")

    # 1. Caso directo estándar: carpeta/canal.h5
    p = os.path.join(MEDICIONES, carpeta, f"{canal}.h5")
    if os.path.isfile(p):
        return p

    # 2. Si carpeta es un directorio existente (ej. Mediciones/otros/4 o subcarpeta con archivos)
    dir_directo = os.path.join(MEDICIONES, carpeta)
    if os.path.isdir(dir_directo):
        for f in os.listdir(dir_directo):
            m = _CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                return os.path.join(dir_directo, f)
        return None

    # 3. Si carpeta es de la forma 'categoria/stem' (ej. 'otros/1v2-30s')
    # donde los archivos están sueltos en MEDICIONES/categoria con nombre '1v2chX-30s.h5'
    parent, stem = os.path.split(carpeta)
    parent_dir = os.path.join(MEDICIONES, parent)
    if os.path.isdir(parent_dir):
        stem_clean = re.sub(r"\.h5$", "", stem, flags=re.IGNORECASE)
        stem_clean = re.sub(r"ch[1-4]", "", stem_clean, flags=re.IGNORECASE)
        for f in os.listdir(parent_dir):
            m = _CHAN_RE.match(f)
            if m and m.group(2).lower() == canal:
                pref, suff = m.group(1), m.group(3)
                if f"{pref}{suff}" == stem_clean or stem_clean in f:
                    return os.path.join(parent_dir, f)

    return None


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe para la medición dada, en orden."""
    return [c for c in CANALES if _ruta(carpeta, c) is not None and os.path.isfile(_ruta(carpeta, c))]


def listar_mediciones():
    """Carpetas o mediciones con al menos un ch1..ch4.h5, directas en MEDICIONES,
    en subcarpetas de cadencia (p. ej. 'cada_30s/7') o archivos agrupados por prefijo/sufijo
    (p. ej. 'otros/1v2-30s')."""
    if not os.path.isdir(MEDICIONES):
        return []
    mediciones = set()
    for root, dirs, files in os.walk(MEDICIONES):
        h5_files = [f for f in files if f.lower().endswith(".h5")]
        if not h5_files:
            continue
        rel_dir = os.path.relpath(root, MEDICIONES).replace("\\", "/")
        grupos = {}
        for f in h5_files:
            m = _CHAN_RE.match(f)
            if m:
                pref, ch, suff = m.group(1), m.group(2).lower(), m.group(3)
                grupos.setdefault((pref, suff), {})[ch] = f

        for (pref, suff), chans in grupos.items():
            if not chans:
                continue
            if not pref and not suff:
                if rel_dir != ".":
                    mediciones.add(rel_dir)
            else:
                stem = f"{pref}{suff}"
                if rel_dir.endswith(stem):
                    mediciones.add(rel_dir)
                elif rel_dir != ".":
                    mediciones.add(f"{rel_dir}/{stem}")
                else:
                    mediciones.add(stem)
    return sorted(mediciones, key=_orden_natural)


def _meta(carpeta, canal):
    """Lee una sola vez el nombre del canal, escalas y numero de segmentos."""
    with h5py.File(_ruta(carpeta, canal), "r") as f:
        chan = list(f["Waveforms"].keys())[0]
        ch = f["Waveforms/" + chan]
        return {
            "chan": chan,
            "yinc": float(ch.attrs["YInc"]),
            "yorg": float(ch.attrs["YOrg"]),
            "xinc": float(ch.attrs["XInc"]),
            "xorg": float(ch.attrs["XOrg"]),
            "nsegs": int(ch.attrs["NumSegments"]),
        }


_META_CACHE = {}


def meta_medicion(carpeta):
    """Devuelve {canal: meta} para los canales presentes, cacheado."""
    if carpeta not in _META_CACHE:
        _META_CACHE[carpeta] = {c: _meta(carpeta, c) for c in canales_presentes(carpeta)}
    return _META_CACHE[carpeta]


def n_segmentos(carpeta):
    metas = meta_medicion(carpeta)
    return min(m["nsegs"] for m in metas.values())


def _cargar_segmento_leer(carpeta, canal, seg, ventana=(T_MIN, T_MAX)):
    """Devuelve (t_us, v) para un canal y segmento, recortado a la ventana.

    Sólo se leen del HDF5 las muestras de la ventana (el segmento completo es ~6x
    mayor que la ventana -5..30 us que usa la app).
    """
    m = meta_medicion(carpeta)[canal]
    with h5py.File(_ruta(carpeta, canal), "r") as f:
        dset = f[f"Waveforms/{m['chan']}/{m['chan']} Seg{seg}Data"]
        n = dset.shape[0]
        if ventana is None:
            i0, i1 = 0, n
        else:
            # Mismos índices que daba la máscara (t >= v0) & (t <= v1).
            i0 = int(np.ceil((ventana[0] * 1e-6 - m["xorg"]) / m["xinc"]))
            i1 = int(np.floor((ventana[1] * 1e-6 - m["xorg"]) / m["xinc"])) + 1
            i0, i1 = max(i0, 0), min(i1, n)
            if i1 <= i0:
                return np.array([]), np.array([])
        raw = dset[i0:i1]
    v = (raw.astype(np.float64) * m["yinc"] + m["yorg"]) * 1e3  # milivoltios
    t = (m["xorg"] + np.arange(i0, i1) * m["xinc"]) * 1e6  # microsegundos
    return t, v


@functools.lru_cache(maxsize=48)
def _cargar_segmento_cache(carpeta, canal, seg, ventana):
    t, v = _cargar_segmento_leer(carpeta, canal, seg, ventana)
    t.flags.writeable = False   # evita que un consumidor mute la copia cacheada
    v.flags.writeable = False
    return t, v


def cargar_segmento(carpeta, canal, seg, ventana=(T_MIN, T_MAX)):
    """Devuelve (t_us, v) para un canal y segmento, recortado a la ventana."""
    return _cargar_segmento_cache(carpeta, canal, seg, tuple(ventana) if ventana else None)


_COLORES_CANALES = {
    "ch1": "#1f77b4",
    "ch2": "#2563eb",  # azul
    "ch3": "#059669",  # verde
    "ch4": "#d97706",  # naranja
}


def config_sensores_defecto(carpeta):
    """Genera la configuración de trigger (umbral, dist, tmin) para los canales
    trigger (ch2, ch3, ch4), leyendo de metadata.yaml si existen o calculando valores iniciales."""
    defaults = {
        "ch2": {"umbral": None, "dist": 1.0, "tmin": 0.0},
        "ch3": {"umbral": None, "dist": 0.5, "tmin": 0.0},
        "ch4": {"umbral": None, "dist": 0.5, "tmin": 0.0},
    }
    if not carpeta:
        return defaults

    meta = obtener_metadata(carpeta)
    canales_meta = meta.get("canales", {}) if isinstance(meta, dict) else {}

    cfg = {}
    for ch in TRIGGERS:
        cfg[ch] = dict(defaults[ch])
        meta_ch = canales_meta.get(ch, {})
        trig_meta = meta_ch.get("trigger", {}) if isinstance(meta_ch, dict) else {}
        if isinstance(trig_meta, dict):
            if trig_meta.get("umbral_mv") is not None:
                cfg[ch]["umbral"] = float(trig_meta["umbral_mv"])
            if trig_meta.get("distancia_us") is not None:
                cfg[ch]["dist"] = float(trig_meta["distancia_us"])
            if trig_meta.get("tmin_us") is not None:
                cfg[ch]["tmin"] = float(trig_meta["tmin_us"])

        if cfg[ch]["umbral"] is None:
            cfg[ch]["umbral"] = umbral_defecto(carpeta, ch)
    return cfg


def figura(carpeta, seg, canal, cfg_sensores=None, cap=None):
    canales = canales_presentes(carpeta)
    fig = make_subplots(
        rows=len(canales), cols=1,
        shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=[c for c in canales],
    )
    if cfg_sensores is None:
        cfg_sensores = config_sensores_defecto(carpeta)

    t_trig = v_trig = None
    for i, c in enumerate(canales, start=1):
        fig.update_yaxes(title_text="mV", row=i, col=1)
        if c == "ch1":
            continue  # CH1 muestra la señal promedio filtrada (se dibuja aparte)
        t, v = cargar_segmento(carpeta, c, seg)
        if c == canal:
            t_trig, v_trig = t, v
        fig.add_trace(
            go.Scattergl(
                x=t.astype(np.float32), y=v.astype(np.float32),
                mode="lines", name=c, line=dict(width=0.7),
                hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>" + c + "</extra>",
            ),
            row=i, col=1,
        )

    # Añadir líneas de umbral para cada canal trigger presente (ch2, ch3, ch4)
    for ch in TRIGGERS:
        if ch in canales:
            fila = canales.index(ch) + 1
            u_ch = cfg_sensores.get(ch, {}).get("umbral")
            if u_ch is None:
                u_ch = umbral_defecto(carpeta, ch, seg)
            es_activo = (ch == canal)
            color_linea = "#dc2626" if es_activo else _COLORES_CANALES.get(ch, "#666")
            ancho_linea = 2.0 if es_activo else 1.3
            dash_linea = "dash" if es_activo else "dot"
            fig.add_hline(
                y=u_ch, row=fila, col=1,
                line=dict(color=color_linea, width=ancho_linea, dash=dash_linea),
            )

    # Cruces de peaks sobre el canal activo inspeccionado
    if canal in canales and v_trig is not None:
        fila = canales.index(canal) + 1
        cfg_act = cfg_sensores.get(canal, {})
        u0 = cfg_act.get("umbral")
        if u0 is None:
            u0 = 0.5 * float(np.max(np.abs(v_trig))) if v_trig.size else 0.0
        dist_act = cfg_act.get("dist", 1.0)
        tmin_act = cfg_act.get("tmin", 0.0)

        if cap is not None:
            mask = cap["seg"] == seg
            tp, vp = cap["t_peak"][mask], cap["v_peak"][mask]
            customdata = np.nonzero(mask)[0].tolist()
        else:
            tp, vp = _detectar_con_ventana(carpeta, canal, t_trig, v_trig, u0,
                                           _muestras(carpeta, canal, dist_act), tmin_act)
            customdata = None

        fig.add_trace(
            go.Scatter(
                x=tp, y=vp, mode="markers", name=f"peaks {canal.upper()}", customdata=customdata,
                marker=dict(symbol="x", color="black", size=9, line=dict(width=1)),
                hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>peak</extra>",
                showlegend=False,
            ),
            row=fila, col=1,
        )

    # Impulso CH1 filtrado (50 MHz) + líneas verticales de tiempos sobre CH1.
    if "ch1" in canales:
        _dibujar_impulso_ch1(fig, carpeta, canales.index("ch1") + 1)
    fig.update_xaxes(title_text="Tiempo [µs]", row=len(canales), col=1)
    fig.update_xaxes(range=[T_MIN, T_MAX])
    fig.update_layout(
        height=850, showlegend=False, margin=dict(t=70, r=20),
        title=f"{carpeta} — Segmento {seg}",
        plot_bgcolor="white", paper_bgcolor="white",
        uirevision=f"{carpeta}-{canal}",
    )
    return fig


def umbral_defecto(carpeta, canal="ch4", seg=1):
    """Umbral por defecto: 50% del |pico| del canal trigger en el segmento dado."""
    if canal not in canales_presentes(carpeta):
        return 0.0
    _, v = cargar_segmento(carpeta, canal, seg)
    return 0.5 * float(np.max(np.abs(v))) if v.size else 0.0


def _detectar(t, v, umbral, distancia, tmin):
    """find_peaks acotado a t >= tmin. Devuelve (t_peak, v_peak)."""
    if tmin is not None:
        mask = t >= tmin
        t, v = t[mask], v[mask]
    idx, _ = find_peaks(v, height=umbral, distance=distancia)
    return t[idx], v[idx]


def _detectar_con_ventana(carpeta, canal, t, v, umbral, distancia, tmin,
                          antes_us=VENTANA_PD_ANTES_US, desp_us=VENTANA_PD_DESP_US):
    """find_peaks acotado a t >= tmin que descarta descargas que no quepan en la ventana."""
    if tmin is not None:
        mask = t >= tmin
        t, v = t[mask], v[mask]
    if not v.size:
        return np.array([]), np.array([])
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
    n_antes = int(round(antes_us / dt_us))
    n_desp = int(round(desp_us / dt_us))
    idx, _ = find_peaks(v, height=umbral, distance=distancia)
    validos = [i for i in idx if (i - n_antes >= 0 and i + n_desp + 1 <= v.size)]
    if not validos:
        return np.array([]), np.array([])
    validos = np.array(validos)
    return t[validos], v[validos]


def _muestras(carpeta, canal, dist_us):
    """Distancia en µs -> nº de muestras para find_peaks."""
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
    return max(1, int(round(dist_us / dt_us))) if dist_us else None


def umbrales_desde_relayout(relayout, canales):
    """Extrae las posiciones 'y' de las líneas de umbral movibles (shapes) desde relayoutData,
    mapeando cada shape a su canal trigger (ch2, ch3, ch4) en el orden en que fueron agregadas."""
    if not relayout:
        return {}
    trigs_presentes = [c for c in TRIGGERS if c in canales]
    cambios = {}
    for k, val in relayout.items():
        if k.startswith("shapes[") and k.endswith(".y0"):
            try:
                idx_str = k.split("[")[1].split("]")[0]
                idx = int(idx_str)
                if 0 <= idx < len(trigs_presentes):
                    ch = trigs_presentes[idx]
                    cambios[ch] = float(val)
            except (TypeError, ValueError, IndexError):
                pass
    return cambios


def umbral_desde_relayout(relayout, fallback):
    """Extrae la posicion 'y' de la linea movible desde relayoutData."""
    if relayout:
        for k, val in relayout.items():
            if k.startswith("shapes[") and k.endswith(".y0"):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return fallback


def contar_peaks(carpeta, canal, umbral, dist_us, tmin):
    """Nº de peaks válidos (con ventana completa de 70 ns) del canal trigger por segmento."""
    cap = capturar(carpeta, canal, umbral, dist_us, tmin)
    n_segs = n_segmentos(carpeta)
    segs = list(range(1, n_segs + 1))
    if cap["seg"].size:
        conteos = {s: int(np.sum(cap["seg"] == s)) for s in segs}
    else:
        conteos = {s: 0 for s in segs}
    return segs, [conteos[s] for s in segs]


def figura_peaks(segs, cuentas, umbral, canal):
    fig = go.Figure(go.Bar(x=segs, y=cuentas, marker_color="#636efa"))
    fig.update_layout(
        title=f"Peaks {canal.upper()} por segmento (umbral = {umbral:.4g} mV)",
        xaxis_title="Segmento", yaxis_title="N° de peaks",
        height=415, margin=dict(t=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


_CAPTURA_CACHE = {}


def capturar(carpeta, canal, umbral, dist_us, tmin,
             antes_us=VENTANA_PD_ANTES_US, desp_us=VENTANA_PD_DESP_US):
    """Detecta los peaks del canal trigger y extrae, alrededor de cada uno, una
    ventana de 70 ns (10% antes = 7 ns / 90% después = 63 ns), alineada al peak (t=0).

    Las descargas cuya ventana sobrepase los bordes de la señal se descartan completamente.
    Unifica peaks y ventanas para que el scatter y el gráfico temporal compartan
    EXACTamente el mismo conjunto y orden (la selección del scatter mapea 1:1 a
    las ventanas). Cacheado por sesión. Devuelve un dict con:
      t_rel  : eje temporal relativo al peak (µs), común a todas las ventanas
      W      : matriz (n_ventanas × n_muestras) con las señales capturadas (mV)
      t_peak, v_peak : instante (µs) y amplitud (mV) de cada peak con ventana completa
      vpp    : amplitud peak-to-peak calculada en la ventana de 70 ns (mV)
      seg    : segmento de origen de cada ventana
      dt_us  : paso de muestreo (µs)
    """
    key = (carpeta, canal, round(umbral, 6) if umbral is not None else None,
           dist_us, tmin, antes_us, desp_us)
    if key in _CAPTURA_CACHE:
        return _CAPTURA_CACHE[key]
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6 if canal in canales_presentes(carpeta) else 0.0
    if canal not in canales_presentes(carpeta):
        res = {"t_rel": np.array([]), "W": np.empty((0, 0)),
               "t_peak": np.array([]), "v_peak": np.array([]), "vpp": np.array([]),
               "seg": np.array([]), "t10_seg": np.array([]),
               "t_peak_borde": np.array([]), "v_peak_borde": np.array([]),
               "seg_borde": np.array([]), "dt_us": dt_us}
        _CAPTURA_CACHE[key] = res
        return res
    n_antes = int(round(antes_us / dt_us))
    n_desp = int(round(desp_us / dt_us))
    distancia = _muestras(carpeta, canal, dist_us)
    t_rel = np.arange(-n_antes, n_desp + 1) * dt_us
    W, tpk, vpk, segs = [], [], [], []
    for s in range(1, n_segmentos(carpeta) + 1):
        t, v = cargar_segmento(carpeta, canal, s)
        if tmin is not None:
            mask = t >= tmin
            t, v = t[mask], v[mask]
        idx, _ = find_peaks(v, height=umbral, distance=distancia)
        for i in idx:
            a, b = i - n_antes, i + n_desp + 1
            if a < 0 or b > v.size:
                continue  # Descartar: no cabe íntegramente en la ventana de 70 ns
            W.append(v[a:b])
            tpk.append(t[i])
            vpk.append(v[i])
            segs.append(s)
    W_arr = np.array(W) if W else np.empty((0, t_rel.size))
    vpp_arr = np.ptp(W_arr, axis=1) if W_arr.size else np.array([])
    seg_arr = np.array(segs, dtype=int)
    t10_all = t10_por_segmento(carpeta)
    t10_seg = t10_all[seg_arr - 1] if seg_arr.size else np.array([])
    res = {
        "t_rel": t_rel,
        "W": W_arr,
        "t_peak": np.array(tpk), "v_peak": np.array(vpk), "vpp": vpp_arr,
        "seg": seg_arr,
        "t10_seg": t10_seg,
        "t_peak_borde": np.array([]), "v_peak_borde": np.array([]),
        "seg_borde": np.array([]), "dt_us": dt_us,
    }
    _CAPTURA_CACHE[key] = res
    return res


def _idx_scatter(datos, n):
    """Índices desde un scatter (Peaks o Vpp/Energía): la curva 0 es 1:1 con las
    ventanas, así que se usa pointNumber (siempre presente, también en Scattergl).
    Devuelve None si no hay puntos válidos de la curva 0."""
    if not datos or not datos.get("points"):
        return None
    idx = [p.get("pointNumber", p.get("pointIndex"))
           for p in datos["points"] if p.get("curveNumber") == 0]
    idx = [int(i) for i in idx if i is not None and 0 <= int(i) < n]
    return sorted(set(idx)) if idx else None


def _idx_cruces(datos, n):
    """Índices desde las cruces del canal trigger (traza SVG): el índice GLOBAL
    de ventana viaja en customdata (fiable en go.Scatter). Devuelve None si no
    hay puntos con customdata (p.ej. clic sobre una línea de canal)."""
    if not datos or not datos.get("points"):
        return None
    idx = []
    for p in datos["points"]:
        cd = p.get("customdata")
        if cd is None:
            continue
        if isinstance(cd, (list, tuple)):
            cd = cd[0]
        idx.append(int(cd))
    idx = [i for i in idx if 0 <= i < n]
    return sorted(set(idx)) if idx else None


def _fig_sin_seleccion(canal):
    """Figura vacía con aviso cuando no hay puntos elegidos en los scatters."""
    fig = go.Figure()
    fig.update_layout(
        height=430, margin=dict(t=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        annotations=[dict(
            text="Selecciona señales en los scatters o en las cruces del trigger",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=13, color="#888"),
        )],
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    return fig


def figura_ventanas(cap, sel, canal):
    """Ventanas capturadas (mV) alineadas al peak, SOLO las de sel (lista)."""
    if not sel:
        return _fig_sin_seleccion(canal)
    W, t_rel = cap["W"], cap["t_rel"]
    paso = max(1, t_rel.size // 300)  # decimado para dibujar
    tr = t_rel[::paso]
    nan = np.array([np.nan])
    xs, ys = [], []
    for i in sel:
        xs.extend((tr, nan))
        ys.extend((W[i][::paso], nan))
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=np.concatenate(xs), y=np.concatenate(ys), mode="lines",
        line=dict(color="#EF553B", width=0.7), opacity=0.5,
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_vline(x=0, line=dict(color="#333", width=1, dash="dash"),
                  annotation_text="peak", annotation_position="top")
    fig.update_layout(
        title=f"Señales {canal.upper()} — {len(sel)} seleccionadas",
        xaxis_title="Tiempo relativo al peak [µs]", yaxis_title="mV",
        height=430, margin=dict(t=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


def figura_fft(cap, sel, canal):
    """FFT (scipy.signal.welch, spectrum, lineal) promediando SOLO las ventanas
    de sel (lista)."""
    if not sel:
        return _fig_sin_seleccion(canal)
    W = cap["W"]
    filas = list(sel)
    fig = go.Figure()
    n = len(filas)
    if n and W.shape[1] > 1:
        fs = 1.0 / (cap["dt_us"] * 1e-6)  # Hz
        nperseg = min(W.shape[1], 256)
        f, Pxx = welch(W[filas], fs=fs, nperseg=nperseg, scaling="spectrum", axis=-1)
        fig.add_trace(go.Scattergl(
            x=f / 1e6, y=Pxx.mean(axis=0), mode="lines", line=dict(color="#1f77b4", width=1),
            hovertemplate="f=%{x:.1f} MHz<br>%{y:.3g} mV²<extra></extra>", showlegend=False,
        ))
    fig.update_layout(
        title=f"FFT (Welch) {canal.upper()} — {n} señales",
        xaxis_title="Frecuencia [MHz]", yaxis_title="Espectro [mV²]",
        height=430, margin=dict(t=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


def transformada_s(x, t_us, dt_us, fmax_mhz=ST_FMAX_MHZ, nfreq=ST_NFREQ,
                    n_t=ST_NT_VENTANA, bloque=16):
    """Magnitud de la transformada S (Stockwell) de x, algoritmo rápido vía FFT
    (Stockwell 1996): S_j[n] = IFFT{ X[(m+j) mod N] · exp(-2π²m²/j²) }[n], con
    m = índice de frecuencia centrado (-N/2..N/2-1) y j = índice de frecuencia
    de la fila (bin lineal, f_j = j/(N·dt_us) MHz). La fila f=0 es |media(x)|.
    Un tono de amplitud A da |S| ≈ A/2 en su frecuencia (mismas unidades que x,
    p.ej. mV). f máx se recorta a Nyquist (N//2). La gaussiana solo se evalúa
    en su soporte (|m| <= 1.2·j) para evitar aritmética de subnormales, que
    ralentiza mucho el cálculo cuando f máx es baja.

    Devuelve (t_dec, f_mhz, A): eje de tiempo decimado a ~n_t puntos (recorte
    de t_us), eje de frecuencia [MHz] (nfreq+1 filas) y la matriz de magnitud.
    """
    N = x.size
    X = sfft.fft(x, workers=-1)
    m = sfft.fftfreq(N) * N
    jmax = max(1, min(N // 2, int(round(fmax_mhz * 1e6 * N * dt_us * 1e-6))))
    js = np.unique(np.linspace(1, jmax, min(nfreq, jmax)).round().astype(int))
    paso = max(1, N // n_t)
    t_dec = t_us[::paso]
    A = np.empty((js.size + 1, t_dec.size))
    A[0, :] = abs(float(x.mean()))
    for a in range(0, js.size, bloque):
        jb = js[a:a + bloque]
        idx = (np.arange(N)[None, :] + jb[:, None]) % N
        soporte = np.abs(m)[None, :] <= 1.2 * jb[:, None]
        G = np.where(soporte, np.exp(-2 * np.pi ** 2 * m[None, :] ** 2 / jb[:, None] ** 2), 0.0)
        A[a + 1:a + 1 + jb.size] = np.abs(sfft.ifft(X[idx] * G, axis=1, workers=-1))[:, ::paso]
    f_mhz = np.concatenate(([0.0], js / (N * dt_us)))
    return t_dec, f_mhz, A


def figura_st_ventana(cap, sel, canal, fmax_mhz=ST_FMAX_MHZ):
    """Transformada S (magnitud, mV) de la ventana de 70 ns alrededor del peak,
    promediando SOLO las ventanas de sel (lista), igual que figura_fft."""
    if not sel:
        return _fig_sin_seleccion(canal)
    W, t_rel = cap["W"], cap["t_rel"]
    filas = list(sel)
    n = len(filas)
    acc = t_dec = f_mhz = None
    for i in filas:
        t_dec, f_mhz, A = transformada_s(W[i], t_rel, cap["dt_us"], fmax_mhz)
        acc = A if acc is None else acc + A
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=t_dec, y=f_mhz, z=acc / n, colorscale="Viridis",
        colorbar=dict(title="mV"),
        hovertemplate="t=%{x:.4f} µs<br>f=%{y:.1f} MHz<br>%{z:.3g} mV<extra></extra>",
    ))
    fig.add_vline(x=0, line=dict(color="white", width=1, dash="dash"),
                  annotation_text="peak", annotation_position="top")
    fig.update_layout(
        title=f"Transformada S {canal.upper()} — {n} señales (promedio |S|)",
        xaxis_title="Tiempo relativo al peak [µs]", yaxis_title="Frecuencia [MHz]",
        height=430, margin=dict(t=50, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


_ST_SEG_CACHE = {}


def st_segmento(carpeta, seg, canal, fmax_mhz=ST_FMAX_MHZ):
    """Transformada S del segmento completo (-5..30 µs) de un canal, con su
    señal cruda (cargar_segmento; también para CH1). Cacheada por sesión."""
    key = (carpeta, seg, canal, fmax_mhz)
    if key not in _ST_SEG_CACHE:
        t, v = cargar_segmento(carpeta, canal, seg)
        dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
        _ST_SEG_CACHE[key] = transformada_s(v, t, dt_us, fmax_mhz, ST_NFREQ, ST_NT_SEGMENTO)
    return _ST_SEG_CACHE[key]


def figura_st_segmento(carpeta, seg, fmax_mhz=ST_FMAX_MHZ):
    """Transformada S del segmento completo, una fila por canal (ch1..ch4),
    eje temporal compartido con la fila de figura()."""
    canales = canales_presentes(carpeta)
    n = len(canales)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=canales,
    )
    for i, c in enumerate(canales, start=1):
        t_dec, f_mhz, A = st_segmento(carpeta, seg, c, fmax_mhz)
        fig.add_trace(
            go.Heatmap(
                x=t_dec, y=f_mhz, z=A, colorscale="Viridis",
                colorbar=dict(title="mV", len=0.85 / n, y=1 - (i - 0.5) / n, thickness=14),
                hovertemplate="t=%{x:.4f} µs<br>f=%{y:.1f} MHz<br>%{z:.3g} mV<extra>" + c + "</extra>",
            ),
            row=i, col=1,
        )
        fig.update_yaxes(title_text="MHz", row=i, col=1)
    fig.update_xaxes(title_text="Tiempo [µs]", row=n, col=1)
    fig.update_xaxes(range=[T_MIN, T_MAX])
    fig.update_layout(
        height=850, margin=dict(t=70, r=20),
        title=f"{carpeta} — Segmento {seg} — Transformada S",
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


def _vpp_energia(cap):
    """Vpp (mV) y Energía (mV²·µs) por señal capturada."""
    W = cap["W"]
    if not W.shape[0]:
        return np.array([]), np.array([])
    return np.ptp(W, axis=1), np.sum(W ** 2, axis=1) * cap["dt_us"]


def figura_vpp_energia(cap, canal, highlight=None, uirev=None):
    """Scatter Vpp vs Energía (una marca por señal capturada, curva 0 = 1:1 con
    las ventanas). Los puntos de `highlight` se marcan en amarillo."""
    vpp, energia = _vpp_energia(cap)
    n = vpp.size
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=vpp, y=energia, mode="markers",
        marker=dict(color="#AB63FA", size=7, opacity=0.7),
        hovertemplate="Vpp=%{x:.2f} mV<br>E=%{y:.3g} mV²·µs<extra></extra>",
        showlegend=False,
    ))
    h = [i for i in (highlight or []) if 0 <= i < n]
    if h:
        fig.add_trace(go.Scattergl(
            x=vpp[h], y=energia[h], mode="markers",
            marker=dict(color="#FFD400", size=11, line=dict(color="black", width=1)),
            hoverinfo="skip", showlegend=False,
        ))
    fig.update_layout(
        title=f"Vpp vs Energía {canal.upper()}",
        xaxis_title="Vpp [mV]", yaxis_title="Energía [mV²·µs]",
        height=415, margin=dict(t=50, r=20), dragmode="select",
        plot_bgcolor="white", paper_bgcolor="white", uirevision=uirev,
    )
    return fig


def _dir_medicion(carpeta):
    """Encuentra el directorio físico que contiene los archivos de la medición."""
    for c in CANALES:
        p = _ruta(carpeta, c)
        if p and os.path.isfile(p):
            return os.path.dirname(p)
    p_dir = os.path.join(MEDICIONES, carpeta)
    if os.path.isdir(p_dir):
        return p_dir
    parent, _ = os.path.split(carpeta)
    p_parent = os.path.join(MEDICIONES, parent)
    if os.path.isdir(p_parent):
        return p_parent
    return p_dir


def obtener_metadata(carpeta):
    """Carga metadata.yaml si existe en la carpeta de medición; de lo contrario,
    genera la estructura enriquecida en memoria a partir de los HDF5 y parámetros inferidos."""
    if not carpeta:
        return {}
    d = _dir_medicion(carpeta)
    meta_path = os.path.join(d, "metadata.yaml")
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    data["_ruta_yaml"] = meta_path
                    data["_existe_en_disco"] = True
                    return data
        except Exception as e:
            print(f"Advertencia: no se pudo leer {meta_path} ({e})")
    try:
        data = plantilla_metadata(carpeta, d)
        data["_ruta_yaml"] = meta_path
        data["_existe_en_disco"] = False
        return data
    except Exception as e:
        print(f"Advertencia: error al generar plantilla de metadata para {carpeta} ({e})")
        return {
            "experimento": {"id": carpeta},
            "_ruta_yaml": meta_path,
            "_existe_en_disco": False,
        }


def guardar_metadata_archivo(carpeta, contenido_yaml_str):
    """Guarda una cadena YAML en metadata.yaml en la carpeta física de la medición."""
    if not carpeta or not contenido_yaml_str:
        return False, "No hay contenido para guardar."
    d = _dir_medicion(carpeta)
    meta_path = os.path.join(d, "metadata.yaml")
    try:
        yaml.safe_load(contenido_yaml_str)  # validar sintaxis YAML
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(contenido_yaml_str)
        return True, f"Guardado exitoso en {os.path.basename(meta_path)}"
    except Exception as e:
        return False, f"Error al guardar: {e}"


COLUMNAS_DENSIDAD = [
    {"name": "Specimen", "id": "specimen"},
    {"name": "Voltage (kV)", "id": "voltage"},
    {"name": "Sensor", "id": "sensor"},
    {"name": "N_PD distribution [0, 1, 2, 3, 4, > 4]", "id": "distribucion"},
    {"name": "Media de N_PD", "id": "media_npd"},
    {"name": "d (mm)", "id": "diametro"},
    {"name": "V̄_max (V)", "id": "vmax_media"},
    {"name": "V̄_pp (V)", "id": "vpp_media"},
    {"name": "t_lag (ns)", "id": "tlag"},
    {"name": "t̄_abs (µs)", "id": "tabs_media"},
]


def calcular_fila_densidad(carpeta, canal, umbral, dist_us, tmin, t_lag_us=0.0):
    """Calcula la fila de la tabla de densidad para la medición y canal dados,
    inspirada en la tabla experimental de resumen (Specimen, Voltage, Sensor,
    N_PD distribution [0, 1, 2, 3, 4, > 4], Media de N_PD, d (mm), V̄_max (V), V̄_pp (V), t_lag (ns), t̄_abs (µs))."""
    meta = obtener_metadata(carpeta)
    prob = meta.get("probeta", {})
    circ = meta.get("circuito_impulso", {})
    canales_cfg = meta.get("canales", {})

    codigo_prob = prob.get("codigo") or ""
    tipo_geom = prob.get("tipo_geometria") or ""
    if codigo_prob and tipo_geom:
        specimen = f"{codigo_prob} ({tipo_geom})"
    elif codigo_prob:
        specimen = codigo_prob
    else:
        specimen = prob.get("descripcion") or "Pressboard"

    v_dc = circ.get("tension_dc_condensador_kv")
    if v_dc is not None:
        voltage = f"{v_dc} kV"
    else:
        inf = inferir_parametros(carpeta)
        voltage = f"{inf['tension_dc']} kV" if inf.get("tension_dc") else "-"

    sens_info = canales_cfg.get(canal, {})
    sens_nom = sens_info.get("sensor") or canal.upper()
    sensor = f"{sens_nom} ({canal.upper()})"

    segs, cuentas = contar_peaks(carpeta, canal, umbral, dist_us, tmin)
    cuentas_arr = np.asarray(cuentas)
    if cuentas_arr.size > 0:
        c0 = int(np.sum(cuentas_arr == 0))
        c1 = int(np.sum(cuentas_arr == 1))
        c2 = int(np.sum(cuentas_arr == 2))
        c3 = int(np.sum(cuentas_arr == 3))
        c4 = int(np.sum(cuentas_arr == 4))
        c_mas = int(np.sum(cuentas_arr > 4))
        distribucion = f"[{c0}, {c1}, {c2}, {c3}, {c4}, {c_mas}]"
        media_npd = f"{np.mean(cuentas_arr):.2f}"
    else:
        distribucion = "[0, 0, 0, 0, 0, 0]"
        media_npd = "0.00"

    diametro = inferir_diametros(prob, codigo_prob)

    cap = capturar(carpeta, canal, umbral, dist_us, tmin)
    todos_vp = cap["v_peak"]
    todos_vpp = cap["vpp"]

    if todos_vp.size > 0:
        vp_mean_mv = float(np.mean(np.abs(todos_vp)))
        vp_mean_v = vp_mean_mv / 1000.0
        vmax_str = f"{vp_mean_v:.4f} V ({vp_mean_mv:.1f} mV)"
    else:
        vmax_str = "-"

    if todos_vpp.size > 0:
        vpp_mean_mv = float(np.mean(todos_vpp))
        vpp_mean_v = vpp_mean_mv / 1000.0
        vpp_str = f"{vpp_mean_v:.4f} V ({vpp_mean_mv:.1f} mV)"
    else:
        vpp_str = "-"

    t_abs_arr = t_abs_captura(cap, t_lag_us)
    if t_abs_arr.size > 0:
        tabs_mean = float(np.mean(t_abs_arr))
        tabs_str = f"{tabs_mean:.3f} µs"
    else:
        tabs_str = "-"

    return {
        "id": f"{carpeta}_{canal}",
        "specimen": specimen,
        "voltage": voltage,
        "sensor": sensor,
        "distribucion": distribucion,
        "media_npd": media_npd,
        "diametro": diametro,
        "vmax_media": vmax_str,
        "vpp_media": vpp_str,
        "tlag": f"{(t_lag_us or 0.0)*1e3:.2f}",
        "tabs_media": tabs_str,
        "_carpeta": carpeta,
        "_canal": canal,
    }



_IMPULSO_CACHE = {}


def promedio_impulso(carpeta):
    """Señal de impulso de referencia: promedio de CH1 sobre todos los segmentos."""
    if "ch1" not in canales_presentes(carpeta):
        return None, None
    if carpeta not in _IMPULSO_CACHE:
        acc, t0, cnt = None, None, 0
        for s in range(1, n_segmentos(carpeta) + 1):
            t, v = cargar_segmento(carpeta, "ch1", s)
            if acc is None:
                acc, t0 = np.zeros_like(v), t
            if v.shape == acc.shape:
                acc += v
                cnt += 1
        _IMPULSO_CACHE[carpeta] = (t0, acc / cnt if cnt else acc)
    return _IMPULSO_CACHE[carpeta]


_IMPULSO_FILT_CACHE = {}


def _filtrar_impulso(carpeta, v):
    """Pasa-bajos Butterworth (IMP_ORDEN, IMP_FCORTE) de fase cero sobre una señal de CH1."""
    fs = 1.0 / meta_medicion(carpeta)["ch1"]["xinc"]  # Sa/s
    sos = butter(IMP_ORDEN, IMP_FCORTE, btype="lowpass", fs=fs, output="sos")
    return sosfiltfilt(sos, v)


def impulso_filtrado(carpeta):
    """Impulso de referencia (promedio de CH1) con pasa-bajos de 20 MHz.

    El filtro se aplica una sola vez por experimento y el resultado queda en
    caché de sesión para no recalcularlo en cada render. Devuelve (t_us, s).
    """
    if carpeta not in _IMPULSO_FILT_CACHE:
        t, v = promedio_impulso(carpeta)
        if t is None:
            _IMPULSO_FILT_CACHE[carpeta] = (None, None)
        else:
            _IMPULSO_FILT_CACHE[carpeta] = (t, _filtrar_impulso(carpeta, v))
    return _IMPULSO_FILT_CACHE[carpeta]


def _cruce_subida(t, s, thr, i_pico):
    """Primer tiempo (interpolado) en que s alcanza thr en el flanco de subida."""
    ss = s[:i_pico + 1]
    idx = np.nonzero((ss[:-1] < thr) & (ss[1:] >= thr))[0]
    if idx.size == 0:
        return None
    i = idx[0]
    return t[i] + (thr - s[i]) * (t[i + 1] - t[i]) / (s[i + 1] - s[i])


def _cruce_bajada(t, s, thr, i_pico):
    """Primer tiempo (interpolado) tras el pico en que s cae por debajo de thr."""
    ss = s[i_pico:]
    idx = np.nonzero((ss[:-1] >= thr) & (ss[1:] < thr))[0]
    if idx.size == 0:
        return None
    i = i_pico + idx[0]
    return t[i] + (thr - s[i]) * (t[i + 1] - t[i]) / (s[i + 1] - s[i])


def tiempos_impulso(carpeta):
    """Tiempos característicos del impulso filtrado (µs). Claves None si no existen.

    t_pico/vmax: instante y valor del máximo. t10/t30/t90 en el flanco de
    subida, t50 en la cola (t>t_pico). t0_lin y tmax_lin son los cortes con 0 y
    con vmax de la recta que pasa por (t30, 0.3·vmax) y (t90, 0.9·vmax).
    """
    t, s = impulso_filtrado(carpeta)
    if t is None:
        return None
    i_pico = int(np.argmax(s))
    vmax = float(s[i_pico])
    T = {
        "vmax": vmax,
        "t_pico": float(t[i_pico]),
        "t10": _cruce_subida(t, s, 0.10 * vmax, i_pico),
        "t30": _cruce_subida(t, s, 0.30 * vmax, i_pico),
        "t90": _cruce_subida(t, s, 0.90 * vmax, i_pico),
        "t50": _cruce_bajada(t, s, 0.50 * vmax, i_pico),
        "t0_lin": None,
        "tmax_lin": None,
    }
    t30, t90 = T["t30"], T["t90"]
    if t30 is not None and t90 is not None and t90 != t30:
        m = (0.9 * vmax - 0.3 * vmax) / (t90 - t30)  # pendiente de la recta 30–90
        T["t0_lin"] = t30 - (0.3 * vmax) / m          # y = 0
        T["tmax_lin"] = t30 + (vmax - 0.3 * vmax) / m  # y = vmax
    return T


# ---------------- Calibración de retardo / TRPD ----------------

_T10_SEG_CACHE = {}
_T10_FALLBACK_COUNT = {}


def t10_por_segmento(carpeta):
    """t10 (µs) del impulso CH1 filtrado en cada segmento (índice k-1 = segmento k).

    Si falla en un segmento, usa el t10 del impulso promedio. Sin CH1: ceros.
    """
    if carpeta in _T10_SEG_CACHE:
        return _T10_SEG_CACHE[carpeta]

    nsegs = n_segmentos(carpeta) if ("ch1" in canales_presentes(carpeta)) else 0
    if nsegs == 0 or ("ch1" not in canales_presentes(carpeta)):
        arr = np.zeros(nsegs, dtype=np.float64)
        arr.flags.writeable = False
        _T10_SEG_CACHE[carpeta] = arr
        _T10_FALLBACK_COUNT[carpeta] = 0
        return arr

    T_prom = tiempos_impulso(carpeta)
    t10_fallback = T_prom["t10"] if (T_prom and T_prom.get("t10") is not None) else 0.0

    t10_arr = np.empty(nsegs, dtype=np.float64)
    n_fb = 0
    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, "ch1", s)
        if v.size == 0:
            t10_arr[s - 1] = t10_fallback
            n_fb += 1
            continue
        sf = _filtrar_impulso(carpeta, v)
        i_pico = int(np.argmax(sf))
        vmax = float(sf[i_pico])
        if vmax <= 0:
            t10_val = None
        else:
            t10_val = _cruce_subida(t, sf, 0.10 * vmax, i_pico)

        if t10_val is None:
            t10_arr[s - 1] = t10_fallback
            n_fb += 1
        else:
            t10_arr[s - 1] = t10_val

    t10_arr.flags.writeable = False
    _T10_SEG_CACHE[carpeta] = t10_arr
    _T10_FALLBACK_COUNT[carpeta] = n_fb
    return t10_arr


def n_fallback_t10(carpeta):
    """Número de segmentos en que se usó el t10 fallback en lugar del calculado."""
    if carpeta not in _T10_FALLBACK_COUNT:
        t10_por_segmento(carpeta)
    return _T10_FALLBACK_COUNT.get(carpeta, 0)


def _t_arribo(t, v, umbral, distancia, tmin):
    """Instante t_ant (µs) por primer cruce del umbral en el frente de subida de |v|.

    Aplica máscara t >= tmin. Busca peaks en |v| con distancia mínima para que
    pequeños precursores EMI a menos de dist_us queden absorbidos en el peak mayor.
    Luego retrocede desde el primer peak hasta la última muestra por debajo del
    umbral e interpola linealmente el cruce sub-muestra. Devuelve None si no hay
    cruce observable en la ventana.
    """
    if tmin is not None:
        mask = t >= tmin
        t, v = t[mask], v[mask]
    if v.size < 2:
        return None
    a = np.abs(v)
    idx, _ = find_peaks(a, height=umbral, distance=distancia)
    if idx.size == 0:
        return None
    i_p = idx[0]
    # Retroceder desde i_p hasta la última muestra j < i_p con a[j] < umbral
    j_candidates = np.nonzero(a[:i_p] < umbral)[0]
    if j_candidates.size == 0:
        return None  # Señal ya superaba el umbral desde el inicio de la ventana
    j = j_candidates[-1]
    da = a[j + 1] - a[j]
    if da <= 0:
        return float(t[j])
    return float(t[j] + (umbral - a[j]) * (t[j + 1] - t[j]) / da)


_CALIB_CACHE = {}
MAD_K = 5.0   # atípico si |t_lag - mediana| > MAD_K · 1.4826 · MAD


def calibrar_retardo(carpeta, canal, umbral, dist_us, tmin):
    """Calcula el retardo t_lag = t_ant - t10 para cada segmento de un canal.

    Filtra atípicos con el criterio MAD (k=5.0) y promedia los válidos.
    Cacheado por sesión. Retorna un diccionario serializable a JSON.
    """
    key = (carpeta, canal, round(float(umbral), 6) if umbral is not None else None,
           dist_us, tmin)
    if key in _CALIB_CACHE:
        return _CALIB_CACHE[key]

    nsegs = n_segmentos(carpeta) if canal in canales_presentes(carpeta) else 0
    if nsegs == 0 or canal not in canales_presentes(carpeta):
        res = {
            "canal": canal,
            "segs": [],
            "t_ant": [],
            "t_lag": [],
            "valido": [],
            "atipico": [],
            "t_lag_us": None,
            "sigma_us": None,
            "n_valid": 0,
            "n_total": 0,
            "criterio": "primer_cruce_umbral",
            "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin},
        }
        _CALIB_CACHE[key] = res
        return res

    distancia = _muestras(carpeta, canal, dist_us)
    t10 = t10_por_segmento(carpeta)

    t_ant_list = []
    t_lag_arr = np.full(nsegs, np.nan, dtype=np.float64)

    for s in range(1, nsegs + 1):
        t, v = cargar_segmento(carpeta, canal, s)
        ta = _t_arribo(t, v, umbral, distancia, tmin)
        t_ant_list.append(ta)
        if ta is not None:
            t_lag_arr[s - 1] = ta - t10[s - 1]

    valido = ~np.isnan(t_lag_arr)
    atipico = np.zeros(nsegs, dtype=bool)
    n_val_inicial = int(np.sum(valido))

    if n_val_inicial >= 3:
        med = float(np.median(t_lag_arr[valido]))
        mad = float(np.median(np.abs(t_lag_arr[valido] - med)))
        if mad > 0:
            umbral_mad = MAD_K * 1.4826 * mad
            atipico = valido & (np.abs(t_lag_arr - med) > umbral_mad)
            valido = valido & ~atipico

    n_valid = int(np.sum(valido))
    if n_valid > 0:
        t_lag_us = float(np.mean(t_lag_arr[valido]))
        sigma_us = float(np.std(t_lag_arr[valido], ddof=1)) if n_valid >= 2 else None
    else:
        t_lag_us = None
        sigma_us = None

    res = {
        "canal": canal,
        "segs": list(range(1, nsegs + 1)),
        "t_ant": [float(x) if x is not None else None for x in t_ant_list],
        "t_lag": [float(x) if not np.isnan(x) else None for x in t_lag_arr],
        "valido": [bool(x) for x in valido],
        "atipico": [bool(x) for x in atipico],
        "t_lag_us": t_lag_us,
        "sigma_us": sigma_us,
        "n_valid": n_valid,
        "n_total": nsegs,
        "criterio": "primer_cruce_umbral",
        "params": {"umbral_mv": umbral, "distancia_us": dist_us, "tmin_us": tmin},
    }
    _CALIB_CACHE[key] = res
    return res


def t_abs_captura(cap, t_lag_us=0.0):
    """t_abs (µs) = t_peak − t10 del segmento − t_lag del canal. Traslación O(N)."""
    if not cap or "t_peak" not in cap or not cap["t_peak"].size:
        return np.array([])
    t10_seg = cap.get("t10_seg")
    if t10_seg is None or t10_seg.size != cap["t_peak"].size:
        return cap["t_peak"] - (t_lag_us or 0.0)
    return cap["t_peak"] - t10_seg - (t_lag_us or 0.0)


def calibracion_desde_metadata(carpeta):
    """Dict para calibracion_store a partir de metadata.yaml (ns -> µs).

    Sin bloque 'calibracion_retardo': calibrado=False y t_lag_us=0.0 por canal.
    """
    if not carpeta:
        return {
            "carpeta": "", "calibrado": False, "fuente": None, "fecha": None,
            "canales": {ch: {"t_lag_us": 0.0, "sigma_us": None, "n_valid": None, "n_total": None, "calibrado": False} for ch in TRIGGERS}
        }
    meta = obtener_metadata(carpeta)
    bloque = meta.get("calibracion_retardo") if isinstance(meta, dict) else None
    canales_res = {}
    calibrado_global = False
    fuente = None
    fecha = None

    if isinstance(bloque, dict):
        fuente = bloque.get("fuente_calibracion")
        fecha = bloque.get("fecha")
        for ch in TRIGGERS:
            b_ch = bloque.get(ch)
            if isinstance(b_ch, dict) and b_ch.get("t_lag_ns") is not None:
                t_lag_ns = float(b_ch["t_lag_ns"])
                sigma_ns = float(b_ch["sigma_ns"]) if b_ch.get("sigma_ns") is not None else None
                canales_res[ch] = {
                    "t_lag_us": t_lag_ns * 1e-3,
                    "sigma_us": sigma_ns * 1e-3 if sigma_ns is not None else None,
                    "n_valid": b_ch.get("n_valid"),
                    "n_total": b_ch.get("n_total"),
                    "calibrado": True,
                }
                calibrado_global = True
            else:
                canales_res[ch] = {
                    "t_lag_us": 0.0,
                    "sigma_us": None,
                    "n_valid": None,
                    "n_total": None,
                    "calibrado": False,
                }
    else:
        for ch in TRIGGERS:
            canales_res[ch] = {
                "t_lag_us": 0.0,
                "sigma_us": None,
                "n_valid": None,
                "n_total": None,
                "calibrado": False,
            }

    return {
        "carpeta": carpeta,
        "calibrado": calibrado_global,
        "fuente": fuente,
        "fecha": fecha,
        "canales": canales_res,
    }


def lag_canal(cal, carpeta, canal):
    """t_lag (µs) del canal si el store corresponde a la carpeta; 0.0 en otro caso."""
    if not cal or cal.get("carpeta") != carpeta:
        return 0.0
    ch_data = cal.get("canales", {}).get(canal, {})
    return float(ch_data.get("t_lag_us", 0.0) or 0.0)


def guardar_calibracion_metadata(carpeta, bloque):
    """Inserta/reemplaza 'calibracion_retardo' preservando el resto de metadata.yaml."""
    meta = obtener_metadata(carpeta)
    meta = {k: v for k, v in meta.items() if not k.startswith("_")}
    meta["calibracion_retardo"] = bloque
    return guardar_metadata_archivo(carpeta, yaml.safe_dump(meta, sort_keys=False, allow_unicode=True))


def mediciones_con_calibracion():
    """Mediciones cuyo metadata.yaml en disco contiene 'calibracion_retardo'."""
    res = []
    for m in listar_mediciones():
        d = _dir_medicion(m)
        meta_path = os.path.join(d, "metadata.yaml")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict) and "calibracion_retardo" in data:
                        res.append(m)
            except Exception:
                pass
    return res


def figura_calibracion(resultado):
    """make_subplots(1, 2): izq. t_lag^(k) [ns] vs segmento por canal; der. histograma.

    Válidos con marcador del canal, atípicos/inválidos con 'x' gris.
    Líneas horizontales de media ± sigma.
    """
    if not resultado:
        fig = go.Figure()
        fig.update_layout(
            height=300, margin=dict(t=40, b=20, l=40, r=20),
            plot_bgcolor="white", paper_bgcolor="white",
            annotations=[dict(
                text="Pulsa '▶ Calcular desde set actual' para ver la dispersión de t_lag",
                xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
                font=dict(size=12, color="#888"),
            )],
            xaxis=dict(visible=False), yaxis=dict(visible=False),
        )
        return fig

    fig = make_subplots(rows=1, cols=2, subplot_titles=["t_lag por segmento", "Distribución de t_lag válidos"],
                        column_widths=[0.6, 0.4])

    colores = {"ch2": "#2563eb", "ch3": "#059669", "ch4": "#d97706"}

    for ch in TRIGGERS:
        r = resultado.get(ch)
        if not r or r.get("n_total", 0) == 0:
            continue
        segs = np.array(r["segs"])
        t_lag = np.array([x if x is not None else np.nan for x in r["t_lag"]]) * 1e3  # ns
        val = np.array(r["valido"], dtype=bool)
        color = colores.get(ch, "#64748b")
        nombre_ch = ch.upper()

        # Válidos
        if np.any(val):
            fig.add_trace(
                go.Scatter(
                    x=segs[val], y=t_lag[val], mode="markers",
                    name=f"{nombre_ch} ({r.get('n_valid')}/{r.get('n_total')})",
                    marker=dict(color=color, size=6),
                    hovertemplate=f"Seg %{{x}}<br>t_lag=%{{y:.2f}} ns<extra>{nombre_ch}</extra>",
                ),
                row=1, col=1,
            )
            # Línea horizontal media
            t_mean = r.get("t_lag_us")
            if t_mean is not None:
                m_ns = t_mean * 1e3
                fig.add_hline(y=m_ns, line=dict(color=color, width=1, dash="dash"),
                              annotation_text=f"{nombre_ch}: {m_ns:.1f} ns",
                              annotation_position="bottom right", row=1, col=1)

            # Histograma en col 2
            fig.add_trace(
                go.Histogram(
                    x=t_lag[val], name=f"Hist {nombre_ch}",
                    marker=dict(color=color), opacity=0.6,
                    showlegend=False,
                ),
                row=1, col=2,
            )

        # Inválidos / atípicos
        inval = ~val & ~np.isnan(t_lag)
        if np.any(inval):
            fig.add_trace(
                go.Scatter(
                    x=segs[inval], y=t_lag[inval], mode="markers",
                    name=f"{nombre_ch} atípico",
                    marker=dict(color="#94a3b8", symbol="x", size=7),
                    hovertemplate=f"Seg %{{x}}<br>t_lag=%{{y:.2f}} ns (atípico)<extra>{nombre_ch}</extra>",
                    showlegend=False,
                ),
                row=1, col=1,
            )

    fig.update_layout(
        height=300, margin=dict(t=40, b=30, l=40, r=20),
        plot_bgcolor="white", paper_bgcolor="white",
        barmode="overlay",
        legend=dict(orientation="h", y=1.12, x=0),
    )
    fig.update_xaxes(title_text="Segmento", row=1, col=1)
    fig.update_yaxes(title_text="t_lag [ns]", row=1, col=1)
    fig.update_xaxes(title_text="t_lag [ns]", row=1, col=2)
    fig.update_yaxes(title_text="Conteo", row=1, col=2)
    return fig


# Líneas verticales de tiempos: (clave, etiqueta, color).
_IMP_LINEAS = [
    ("t10", "t10 (10%)", "#2ca02c"),
    ("t30", "t30 (30%)", "#2ca02c"),
    ("t90", "t90 (90%)", "#2ca02c"),
    ("t50", "t50 (50% cola)", "#9467bd"),
    ("t_pico", "t_pico", "#ff7f0e"),
    ("t0_lin", "t0_lin", "#d62728"),
    ("tmax_lin", "tmax_lin", "#d62728"),
]


# Nº de puntos con que se dibuja el impulso (curva suave: no necesita 175k).
IMP_PUNTOS_PLOT = 6000


def _dibujar_impulso_ch1(fig, carpeta, fila):
    """Superpone el impulso CH1 filtrado (50 MHz) y las líneas verticales de
    tiempos sobre la fila de CH1 del gráfico principal.

    Solo se decima el trazo para dibujar; los tiempos se calculan a resolución
    completa en tiempos_impulso(). Todo se mantiene en WebGL (sin capas SVG) y
    los valores van en una anotación estática para no penalizar el pan/zoom.
    """
    t, s = impulso_filtrado(carpeta)
    if t is None:
        return
    paso = max(1, t.size // IMP_PUNTOS_PLOT)
    fig.add_trace(
        go.Scattergl(
            x=t[::paso], y=s[::paso], mode="lines",
            name=f"CH1 impulso (LP {IMP_FCORTE/1e6:.0f} MHz)",
            line=dict(color="#1f77b4", width=1.6),
            hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>impulso</extra>",
            showlegend=False,
        ),
        row=fila, col=1,
    )
    T = tiempos_impulso(carpeta)
    # Recta 30–90 que origina t0_lin y tmax_lin (contexto visual, en WebGL).
    if T["t0_lin"] is not None:
        fig.add_trace(
            go.Scattergl(
                x=[T["t0_lin"], T["tmax_lin"]], y=[0.0, T["vmax"]],
                mode="lines", name="recta 30–90",
                line=dict(color="#d62728", width=1, dash="dash"),
                hoverinfo="skip", showlegend=False,
            ),
            row=fila, col=1,
        )
    # Líneas verticales (shapes, baratas) sin anotación por línea.
    resumen = []
    for clave, etiqueta, color in _IMP_LINEAS:
        x = T.get(clave)
        if x is None:
            continue
        fig.add_vline(x=x, row=fila, col=1,
                      line=dict(color=color, width=1, dash="dot"))
        resumen.append(f"<span style='color:{color}'>{etiqueta} = {x:.3f} µs</span>")
    # Valores en una caja estática anclada al dominio del subplot de CH1.
    if resumen:
        fig.add_annotation(
            xref=f"x{fila} domain" if fila > 1 else "x domain",
            yref=f"y{fila} domain" if fila > 1 else "y domain",
            x=0.995, y=0.97, xanchor="right", yanchor="top",
            text="<br>".join(resumen), showarrow=False, align="left",
            font=dict(size=10), bgcolor="rgba(255,255,255,0.8)",
            bordercolor="#ccc", borderwidth=1,
        )


def figura_scatter(cap, t_ref, v_ref, canal, highlight=None, uirev=None, modo="vmax",
                   t_abs=None, t10_ref=None, t_lag_us=0.0, calibrado=False):
    # Peaks SIEMPRE como curva 0 (la selección mapea por pointNumber = índice de
    # ventana). La referencia CH1 y el resaltado amarillo van como trazas extra.
    n = cap["t_peak"].size
    fig = go.Figure()
    es_vpp = (modo == "vpp")
    y_val = cap["vpp"] if es_vpp else cap["v_peak"]
    y_label = "Vpp [mV]" if es_vpp else "Vmax [mV]"
    traza_nombre = f"Vpp {canal.upper()}" if es_vpp else f"Vmax {canal.upper()}"

    x = t_abs if (t_abs is not None and t_abs.size == n) else cap["t_peak"]

    cd = np.stack([cap["v_peak"], cap["vpp"], cap["t_peak"], cap["seg"], x * 1e3], axis=1) if n > 0 else None

    fig.add_trace(go.Scattergl(
        x=x, y=y_val, mode="markers", name=traza_nombre,
        customdata=cd,
        marker=dict(color="#EF553B", size=6, opacity=0.6),
        hovertemplate="t_abs=%{x:.4f} µs (%{customdata[4]:.2f} ns)<br>t_osc=%{customdata[2]:.4f} µs<br>Vmax=%{customdata[0]:.2f} mV<br>Vpp=%{customdata[1]:.2f} mV<br>Seg %{customdata[3]:.0f}<extra>" + canal.upper() + "</extra>",
    ))
    if t_ref is not None and not es_vpp:
        paso_ref = max(1, t_ref.size // IMP_PUNTOS_PLOT)
        x_ref = t_ref[::paso_ref] - (t10_ref or 0.0)
        fig.add_trace(go.Scattergl(
            x=x_ref, y=v_ref[::paso_ref], mode="lines", name="CH1 promedio (ref.)",
            line=dict(color="#999", width=1), opacity=0.6,
            hovertemplate="t_abs=%{x:.4f} µs<br>%{y:.2f} mV<extra>CH1</extra>",
        ))
        fig.add_vline(x=0, line=dict(color="#2ca02c", width=1, dash="dot"),
                      annotation_text="t10", annotation_position="top")
    h = [i for i in (highlight or []) if 0 <= i < n]
    if h and y_val.size > 0:
        fig.add_trace(go.Scattergl(
            x=x[h], y=y_val[h], mode="markers", name="sel",
            marker=dict(color="#FFD400", size=11, line=dict(color="black", width=1)),
            hoverinfo="skip", showlegend=False,
        ))
    tlag_ns_val = (t_lag_us or 0.0) * 1e3
    sufijo_cal = "" if calibrado else " (sin calibrar)"
    titulo_patron = f"Patrón TRPD ({'Vpp' if es_vpp else 'Vmax'}) — {canal.upper()} · t_lag = {tlag_ns_val:.2f} ns{sufijo_cal}"
    fig.update_layout(
        title=titulo_patron,
        xaxis_title="Tiempo relativo al impulso t_abs [µs] (t10 = 0)", yaxis_title=y_label,
        height=415, margin=dict(t=50, r=20), showlegend=True, dragmode="select",
        legend=dict(orientation="h", y=1.02, yanchor="bottom"),
        plot_bgcolor="white", paper_bgcolor="white", uirevision=uirev,
    )
    return fig


MEDICIONES_INICIAL = listar_mediciones()
CARPETA_INICIAL = MEDICIONES_INICIAL[0] if MEDICIONES_INICIAL else None

app = Dash(__name__)
app.title = "Análisis de Vacuolas"

_TAB = {"className": "tab", "selected_className": "tab--selected"}

app.layout = html.Div(
    className="app",
    children=[
        dcc.Store(id="umbral"),
        dcc.Store(id="captura_params"),
        dcc.Store(id="seleccion", data=[]),
        dcc.Store(id="densidad_store", data=[]),
        dcc.Store(id="calibracion_store"),
        dcc.Store(id="calibracion_resultado"),
        html.Div(
            className="header",
            children=[
                html.H1("Análisis de Vacuolas"),
                html.Span("Impulsos, peaks y señales por experimento", className="sub"),
            ],
        ),
        html.Div(
            className="controls",
            children=[
                html.Label("Medición:"),
                dcc.Dropdown(
                    id="carpeta",
                    options=[{"label": c, "value": c} for c in MEDICIONES_INICIAL],
                    value=CARPETA_INICIAL, clearable=False, style={"width": "260px"},
                ),
                html.Label("Segmento:"),
                dcc.Dropdown(id="segmento", value=1, clearable=False, style={"width": "110px"}),
                html.Label("Trigger activo:"),
                dcc.Dropdown(
                    id="canal",
                    options=[
                        {"label": "CH2 (HFCT)", "value": "ch2"},
                        {"label": "CH3 (Vivaldi)", "value": "ch3"},
                        {"label": "CH4 (Bioinspirada)", "value": "ch4"},
                    ],
                    value="ch4", clearable=False, style={"width": "175px"},
                ),
                html.Button("⚡ Calcular peaks", id="btn", n_clicks=0,
                            style={"backgroundColor": "#2563eb", "color": "white", "fontWeight": "600"}),
                html.Label("f máx ST (MHz):"),
                dcc.Input(id="st_fmax", type="number", value=ST_FMAX_MHZ, min=1,
                          step="any", debounce=True, style={"width": "80px"}),
            ],
        ),
        html.Div(
            style={
                "display": "flex", "gap": "10px", "alignItems": "center",
                "padding": "6px 12px", "backgroundColor": "#f8fafc",
                "border": "1px solid #e2e8f0", "borderRadius": "6px",
                "margin": "0 12px 10px 12px", "flexWrap": "wrap",
            },
            children=[
                html.Span("🎯 Configuración Multi-Trigger:",
                          style={"fontSize": "11px", "fontWeight": "bold", "color": "#1e293b", "marginRight": "4px"}),
                # CH2: HFCT
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": "white",
                        "border": "1px solid #bfdbfe", "borderLeft": "4px solid #2563eb",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH2 (HFCT):", style={"fontWeight": "bold", "color": "#1d4ed8"}),
                        html.Span("u (mV):"),
                        dcc.Input(id="umbral_ch2", type="number", step="any", style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):"),
                        dcc.Input(id="dist_ch2", type="number", step="any", min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):"),
                        dcc.Input(id="tmin_ch2", type="number", step="any", style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
                # CH3: Vivaldi
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": "white",
                        "border": "1px solid #a7f3d0", "borderLeft": "4px solid #059669",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH3 (Vivaldi):", style={"fontWeight": "bold", "color": "#047857"}),
                        html.Span("u (mV):"),
                        dcc.Input(id="umbral_ch3", type="number", step="any", style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):"),
                        dcc.Input(id="dist_ch3", type="number", step="any", min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):"),
                        dcc.Input(id="tmin_ch3", type="number", step="any", style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
                # CH4: Bioinspirada
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": "white",
                        "border": "1px solid #fde68a", "borderLeft": "4px solid #d97706",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH4 (Bioinspirada):", style={"fontWeight": "bold", "color": "#b45309"}),
                        html.Span("u (mV):"),
                        dcc.Input(id="umbral_ch4", type="number", step="any", style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):"),
                        dcc.Input(id="dist_ch4", type="number", step="any", min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):"),
                        dcc.Input(id="tmin_ch4", type="number", step="any", style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
            ],
        ),
        # Barra de estado de Calibración
        html.Div(
            style={
                "display": "flex", "gap": "10px", "alignItems": "center",
                "padding": "6px 12px", "backgroundColor": "#f8fafc",
                "border": "1px solid #e2e8f0", "borderRadius": "6px",
                "margin": "0 12px 10px 12px", "flexWrap": "wrap",
            },
            children=[
                html.Span("⏱ Retardo instrumental:",
                          style={"fontSize": "11px", "fontWeight": "bold", "color": "#1e293b", "marginRight": "4px"}),
                html.Span(
                    id="cal_badge_estado",
                    style={
                        "display": "inline-block", "fontSize": "11px", "padding": "2px 8px",
                        "borderRadius": "10px", "fontWeight": "600",
                        "backgroundColor": "#fef3c7", "color": "#92400e",
                    },
                    children="Sin calibrar — retardo 0 ns",
                ),
                html.Span(id="cal_badge_ch2", style={
                    "display": "inline-block", "fontSize": "11px", "padding": "2px 6px",
                    "backgroundColor": "white", "border": "1px solid #bfdbfe",
                    "borderLeft": "4px solid #2563eb", "borderRadius": "3px", "fontWeight": "600",
                }, children="CH2: 0.00 ns"),
                html.Span(id="cal_badge_ch3", style={
                    "display": "inline-block", "fontSize": "11px", "padding": "2px 6px",
                    "backgroundColor": "white", "border": "1px solid #a7f3d0",
                    "borderLeft": "4px solid #059669", "borderRadius": "3px", "fontWeight": "600",
                }, children="CH3: 0.00 ns"),
                html.Span(id="cal_badge_ch4", style={
                    "display": "inline-block", "fontSize": "11px", "padding": "2px 6px",
                    "backgroundColor": "white", "border": "1px solid #fde68a",
                    "borderLeft": "4px solid #d97706", "borderRadius": "3px", "fontWeight": "600",
                }, children="CH4: 0.00 ns"),
                html.Button("⚙️ Calibrar Retardos", id="btn_toggle_calibracion", n_clicks=0,
                            style={"marginLeft": "auto", "fontSize": "11px", "fontWeight": "600",
                                   "padding": "4px 10px", "backgroundColor": "#f1f5f9",
                                   "border": "1px solid #cbd5e1", "borderRadius": "4px", "cursor": "pointer"}),
            ],
        ),
        # Panel desplegable de Calibración
        html.Div(
            id="panel_calibracion",
            hidden=True,
            style={
                "margin": "0 12px 12px 12px", "padding": "12px",
                "backgroundColor": "#ffffff", "border": "1px solid #cbd5e1",
                "borderRadius": "6px", "boxShadow": "0 1px 3px rgba(0,0,0,0.05)",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "10px"},
                    children=[
                        html.Span("Herramienta de Calibración de Retardo Instrumental (t_lag = t_ant − t10)",
                                  style={"fontSize": "13px", "fontWeight": "bold", "color": "#0f172a"}),
                        html.Div(id="cal_msg_feedback", style={"fontSize": "12px", "fontWeight": "bold"}),
                    ],
                ),
                # Tarjetas de parámetros por canal
                html.Div(
                    style={"display": "flex", "gap": "10px", "flexWrap": "wrap", "marginBottom": "10px"},
                    children=[
                        # CH2
                        html.Div(
                            style={"flex": "1", "minWidth": "220px", "padding": "8px", "border": "1px solid #bfdbfe",
                                   "borderLeft": "4px solid #2563eb", "borderRadius": "4px", "backgroundColor": "#f8fafc"},
                            children=[
                                html.Div("CH2 (HFCT) - Trigger calibración", style={"fontWeight": "bold", "color": "#1d4ed8", "fontSize": "11px", "marginBottom": "4px"}),
                                html.Div(style={"display": "flex", "gap": "6px", "fontSize": "11px", "alignItems": "center"}, children=[
                                    html.Span("u (mV):"), dcc.Input(id="ucal_ch2", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                                    html.Span("Δt (µs):"), dcc.Input(id="dtcal_ch2", type="number", step="any", min=0, style={"width": "45px", "fontSize": "11px"}),
                                    html.Span("t_mín:"), dcc.Input(id="tmincal_ch2", type="number", step="any", style={"width": "45px", "fontSize": "11px"}),
                                ]),
                            ],
                        ),
                        # CH3
                        html.Div(
                            style={"flex": "1", "minWidth": "220px", "padding": "8px", "border": "1px solid #a7f3d0",
                                   "borderLeft": "4px solid #059669", "borderRadius": "4px", "backgroundColor": "#f8fafc"},
                            children=[
                                html.Div("CH3 (Vivaldi) - Trigger calibración", style={"fontWeight": "bold", "color": "#047857", "fontSize": "11px", "marginBottom": "4px"}),
                                html.Div(style={"display": "flex", "gap": "6px", "fontSize": "11px", "alignItems": "center"}, children=[
                                    html.Span("u (mV):"), dcc.Input(id="ucal_ch3", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                                    html.Span("Δt (µs):"), dcc.Input(id="dtcal_ch3", type="number", step="any", min=0, style={"width": "45px", "fontSize": "11px"}),
                                    html.Span("t_mín:"), dcc.Input(id="tmincal_ch3", type="number", step="any", style={"width": "45px", "fontSize": "11px"}),
                                ]),
                            ],
                        ),
                        # CH4
                        html.Div(
                            style={"flex": "1", "minWidth": "220px", "padding": "8px", "border": "1px solid #fde68a",
                                   "borderLeft": "4px solid #d97706", "borderRadius": "4px", "backgroundColor": "#f8fafc"},
                            children=[
                                html.Div("CH4 (Bioinspirada) - Trigger calibración", style={"fontWeight": "bold", "color": "#b45309", "fontSize": "11px", "marginBottom": "4px"}),
                                html.Div(style={"display": "flex", "gap": "6px", "fontSize": "11px", "alignItems": "center"}, children=[
                                    html.Span("u (mV):"), dcc.Input(id="ucal_ch4", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                                    html.Span("Δt (µs):"), dcc.Input(id="dtcal_ch4", type="number", step="any", min=0, style={"width": "45px", "fontSize": "11px"}),
                                    html.Span("t_mín:"), dcc.Input(id="tmincal_ch4", type="number", step="any", style={"width": "45px", "fontSize": "11px"}),
                                ]),
                            ],
                        ),
                    ],
                ),
                # Botones de acción y retardo manual
                html.Div(
                    style={"display": "flex", "gap": "12px", "alignItems": "center", "flexWrap": "wrap", "marginBottom": "10px"},
                    children=[
                        html.Button("▶ Calcular desde set actual", id="btn_calcular_calibracion", n_clicks=0,
                                    style={"backgroundColor": "#2563eb", "color": "white", "fontWeight": "bold", "fontSize": "11px", "padding": "5px 12px", "borderRadius": "4px", "cursor": "pointer"}),
                        html.Button("✔ Aplicar (sesión)", id="btn_aplicar_calibracion", n_clicks=0,
                                    style={"backgroundColor": "#059669", "color": "white", "fontWeight": "bold", "fontSize": "11px", "padding": "5px 12px", "borderRadius": "4px", "cursor": "pointer"}),
                        html.Button("💾 Guardar en metadata.yaml", id="btn_guardar_calibracion", n_clicks=0,
                                    style={"backgroundColor": "#0284c7", "color": "white", "fontWeight": "bold", "fontSize": "11px", "padding": "5px 12px", "borderRadius": "4px", "cursor": "pointer"}),
                        html.Span("│", style={"color": "#cbd5e1"}),
                        html.Span("Retardo manual (ns):", style={"fontSize": "11px", "fontWeight": "bold"}),
                        html.Span("CH2:"), dcc.Input(id="tlag_manual_ch2", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                        html.Span("CH3:"), dcc.Input(id="tlag_manual_ch3", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                        html.Span("CH4:"), dcc.Input(id="tlag_manual_ch4", type="number", step="any", style={"width": "60px", "fontSize": "11px"}),
                        html.Span("│", style={"color": "#cbd5e1"}),
                        html.Span("Importar de:", style={"fontSize": "11px", "fontWeight": "bold"}),
                        dcc.Dropdown(id="cal_import_carpeta", options=[], placeholder="Seleccionar medición...", style={"width": "200px", "fontSize": "11px"}),
                        html.Button("📥 Importar", id="btn_importar_calibracion", n_clicks=0,
                                    style={"fontSize": "11px", "fontWeight": "600", "padding": "4px 10px", "cursor": "pointer"}),
                    ],
                ),
                # Gráfico y tabla resumen
                html.Div(
                    style={"display": "flex", "gap": "12px", "flexWrap": "wrap"},
                    children=[
                        html.Div(style={"flex": "2", "minWidth": "350px"}, children=[
                            dcc.Loading(dcc.Graph(id="grafico_calibracion", config={"displaylogo": False})),
                        ]),
                        html.Div(id="cal_tabla_resumen", style={"flex": "1", "minWidth": "250px", "fontSize": "11px"}),
                    ],
                ),
            ],
        ),
        html.Div(
            className="row",
            children=[
                html.Div(className="col card", children=[
                    dcc.Tabs(id="tabs_principal", value="senales", children=[
                        dcc.Tab(label="Señales", value="senales", **_TAB),
                        dcc.Tab(label="Transformada S", value="st", **_TAB),
                        dcc.Tab(label="Metadata", value="metadata", **_TAB),
                    ]),
                    html.Div(id="panel_senales", children=[
                        dcc.Graph(
                            id="grafico",
                            config={"edits": {"shapePosition": True}, "displaylogo": False},
                        ),
                    ]),
                    html.Div(id="panel_st_segmento", hidden=True, children=[
                        dcc.Loading(dcc.Graph(id="grafico_st_segmento")),
                    ]),
                    html.Div(id="panel_metadata", hidden=True, style={"padding": "10px 4px"}, children=[
                        html.Div(
                            style={
                                "display": "flex", "justifyContent": "space-between",
                                "alignItems": "center", "marginBottom": "12px", "flexWrap": "wrap",
                                "gap": "8px", "borderBottom": "1px solid #e2e8f0", "paddingBottom": "8px",
                            },
                            children=[
                                html.Div([
                                    html.H3(id="meta_titulo", style={"margin": "0 0 4px 0", "fontSize": "15px", "color": "#0f172a"}),
                                    html.Span(id="meta_badge_estado", style={
                                        "display": "inline-block", "fontSize": "11px", "padding": "2px 8px",
                                        "borderRadius": "10px", "fontWeight": "600",
                                    }),
                                ]),
                                html.Div(style={"display": "flex", "gap": "6px", "alignItems": "center"}, children=[
                                    html.Button("💾 Guardar metadata.yaml", id="btn_guardar_metadata",
                                                style={"backgroundColor": "#10b981", "color": "white", "border": "none",
                                                       "padding": "6px 12px", "borderRadius": "6px", "fontWeight": "600",
                                                       "cursor": "pointer", "fontSize": "12px"}),
                                ]),
                            ],
                        ),
                        html.Div(id="meta_msg_feedback", style={"marginBottom": "8px", "fontSize": "12px"}),
                        html.Div(
                            style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(200px, 1fr))", "gap": "10px", "marginBottom": "12px"},
                            children=[
                                html.Div(className="card", style={"padding": "8px 10px"}, children=[
                                    html.H4("🔬 Experimento", style={"margin": "0 0 6px 0", "fontSize": "12px", "color": "#1e293b", "borderBottom": "1px solid #f1f5f9", "paddingBottom": "3px"}),
                                    html.Div(id="meta_card_experimento", style={"fontSize": "11px", "lineHeight": "1.5"}),
                                ]),
                                html.Div(className="card", style={"padding": "8px 10px"}, children=[
                                    html.H4("⚡ Circuito de Impulso (LI)", style={"margin": "0 0 6px 0", "fontSize": "12px", "color": "#1e293b", "borderBottom": "1px solid #f1f5f9", "paddingBottom": "3px"}),
                                    html.Div(id="meta_card_circuito", style={"fontSize": "11px", "lineHeight": "1.5"}),
                                ]),
                                html.Div(className="card", style={"padding": "8px 10px"}, children=[
                                    html.H4("🧪 Probeta / Espécimen", style={"margin": "0 0 6px 0", "fontSize": "12px", "color": "#1e293b", "borderBottom": "1px solid #f1f5f9", "paddingBottom": "3px"}),
                                    html.Div(id="meta_card_probeta", style={"fontSize": "11px", "lineHeight": "1.5"}),
                                ]),
                                html.Div(className="card", style={"padding": "8px 10px"}, children=[
                                    html.H4("📊 Osciloscopio & Adquisición", style={"margin": "0 0 6px 0", "fontSize": "12px", "color": "#1e293b", "borderBottom": "1px solid #f1f5f9", "paddingBottom": "3px"}),
                                    html.Div(id="meta_card_osc", style={"fontSize": "11px", "lineHeight": "1.5"}),
                                ]),
                            ],
                        ),
                        html.Div(className="card", style={"padding": "8px 10px", "marginBottom": "12px"}, children=[
                            html.H4("📡 Asignación de Sensores y Canales de Adquisición", style={"margin": "0 0 6px 0", "fontSize": "12px", "color": "#1e293b"}),
                            html.Div(id="meta_tabla_canales"),
                        ]),
                        html.Details([
                            html.Summary("Ver / Editar YAML crudo", style={"cursor": "pointer", "fontSize": "12px", "fontWeight": "600", "color": "#475569", "padding": "4px 0"}),
                            html.Div(style={"marginTop": "6px"}, children=[
                                dcc.Textarea(
                                    id="meta_yaml_text",
                                    style={"width": "100%", "height": "200px", "fontFamily": "monospace",
                                           "fontSize": "11px", "padding": "6px", "border": "1px solid #cbd5e1",
                                           "borderRadius": "6px", "boxSizing": "border-box"},
                                ),
                                html.Div(style={"marginTop": "4px", "textAlign": "right"}, children=[
                                    html.Button("Guardar cambios del texto YAML", id="btn_guardar_yaml_texto",
                                                style={"backgroundColor": "#3b82f6", "color": "white", "border": "none",
                                                       "padding": "4px 10px", "borderRadius": "4px", "fontWeight": "600",
                                                       "cursor": "pointer", "fontSize": "11px"}),
                                ]),
                            ]),
                        ]),
                    ]),
                ]),
                html.Div(
                    className="col",
                    children=[
                        html.Div(className="card", children=[
                            dcc.Tabs(id="tabs_peaks", value="barras", children=[
                                dcc.Tab(label="Peaks por segmento", value="barras",
                                        children=[dcc.Graph(id="grafico_peaks")], **_TAB),
                                dcc.Tab(label="Densidad de eventos", value="densidad",
                                        children=[
                                            html.Div(style={"display": "flex", "gap": "8px", "marginTop": "6px", "marginBottom": "4px", "alignItems": "center", "flexWrap": "wrap"}, children=[
                                                html.Button("⚡ Calcular todos los sensores (CH2..CH4)", id="btn_calc_todos_sensores",
                                                            style={"fontSize": "11px", "padding": "4px 8px", "backgroundColor": "#2563eb",
                                                                   "color": "white", "border": "none", "borderRadius": "4px", "cursor": "pointer"}),
                                                html.Button("🗑 Limpiar tabla", id="btn_limpiar_densidad",
                                                            style={"fontSize": "11px", "padding": "4px 8px", "backgroundColor": "#64748b",
                                                                   "color": "white", "border": "none", "borderRadius": "4px", "cursor": "pointer"}),
                                            ]),
                                            dash_table.DataTable(
                                                id="tabla_densidad",
                                                columns=COLUMNAS_DENSIDAD,
                                                data=[],
                                                export_format="csv",
                                                style_table={"overflowX": "auto", "maxHeight": "360px", "marginTop": "4px"},
                                                style_cell={"textAlign": "center",
                                                            "padding": "5px 8px",
                                                            "fontSize": "11px",
                                                            "fontFamily": "inherit"},
                                                style_header={"fontWeight": "bold",
                                                              "backgroundColor": "#f1f5f9",
                                                              "color": "#1e293b"},
                                                style_data_conditional=[
                                                    {"if": {"row_index": "odd"}, "backgroundColor": "#f8fafc"},
                                                    {"if": {"column_id": "sensor"}, "fontWeight": "600"},
                                                    {"if": {"column_id": "distribucion"}, "fontFamily": "monospace"},
                                                ],
                                            ),
                                        ], **_TAB),
                            ]),
                        ]),
                        html.Div(className="card", children=[
                            dcc.Tabs(id="tabs_scatter", value="peaks", children=[
                                dcc.Tab(label="Patrón TRPD", value="peaks",
                                        children=[
                                            html.Div(
                                                style={
                                                    "display": "flex", "alignItems": "center", "gap": "10px",
                                                    "padding": "4px 8px", "backgroundColor": "#f8fafc",
                                                    "borderBottom": "1px solid #e2e8f0", "marginBottom": "4px",
                                                    "flexWrap": "wrap",
                                                },
                                                children=[
                                                    html.Span("Magnitud TRPD:", style={"fontSize": "11px", "fontWeight": "bold", "color": "#334155"}),
                                                    dcc.RadioItems(
                                                        id="modo_magnitud_trpd",
                                                        options=[
                                                            {"label": " Vmax (pico máximo)", "value": "vmax"},
                                                            {"label": " Vpp (peak-to-peak en 70 ns)", "value": "vpp"},
                                                        ],
                                                        value="vmax",
                                                        inline=True,
                                                        style={"fontSize": "11px"},
                                                        inputStyle={"marginRight": "4px"},
                                                        labelStyle={"marginRight": "12px", "cursor": "pointer", "fontWeight": "500"},
                                                    ),
                                                ],
                                            ),
                                            dcc.Graph(id="grafico_scatter"),
                                        ], **_TAB),
                                dcc.Tab(label="Vpp vs Energía", value="vpp",
                                        children=[dcc.Graph(id="grafico_vpp_energia")], **_TAB),
                            ]),
                        ]),
                    ],
                ),
            ],
        ),
        html.Div(
            className="row",
            children=[
                html.Div(className="col card", children=[dcc.Graph(id="grafico_ventanas")]),
                html.Div(className="col card", children=[
                    dcc.Tabs(id="tabs_espectro", value="fft", children=[
                        dcc.Tab(label="FFT", value="fft",
                                children=[dcc.Graph(id="grafico_fft")], **_TAB),
                        dcc.Tab(label="Transformada S", value="st",
                                children=[dcc.Loading(dcc.Graph(id="grafico_st_ventana"))], **_TAB),
                    ]),
                ]),
            ],
        ),
    ],
)


@app.callback(
    Output("segmento", "options"),
    Output("segmento", "value"),
    Input("carpeta", "value"),
)
def actualizar_segmentos(carpeta):
    if not carpeta:
        return [], None
    n = n_segmentos(carpeta)
    return [{"label": str(s), "value": s} for s in range(1, n + 1)], 1


@app.callback(
    Output("umbral_ch2", "value"),
    Output("dist_ch2", "value"),
    Output("tmin_ch2", "value"),
    Output("umbral_ch3", "value"),
    Output("dist_ch3", "value"),
    Output("tmin_ch3", "value"),
    Output("umbral_ch4", "value"),
    Output("dist_ch4", "value"),
    Output("tmin_ch4", "value"),
    Input("carpeta", "value"),
    Input("grafico", "relayoutData"),
    prevent_initial_call=False,
)
def sincronizar_parametros_sensores(carpeta, relayout):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None

    if trig == "grafico" and relayout and carpeta:
        cambios = umbrales_desde_relayout(relayout, canales_presentes(carpeta))
        if not cambios:
            return (no_update,) * 9
        u2 = round(cambios["ch2"], 4) if "ch2" in cambios else no_update
        u3 = round(cambios["ch3"], 4) if "ch3" in cambios else no_update
        u4 = round(cambios["ch4"], 4) if "ch4" in cambios else no_update
        return u2, no_update, no_update, u3, no_update, no_update, u4, no_update, no_update

    if not carpeta:
        return (no_update,) * 9
    cfg = config_sensores_defecto(carpeta)
    return (
        round(cfg["ch2"]["umbral"], 4) if cfg["ch2"]["umbral"] is not None else None,
        cfg["ch2"]["dist"], cfg["ch2"]["tmin"],
        round(cfg["ch3"]["umbral"], 4) if cfg["ch3"]["umbral"] is not None else None,
        cfg["ch3"]["dist"], cfg["ch3"]["tmin"],
        round(cfg["ch4"]["umbral"], 4) if cfg["ch4"]["umbral"] is not None else None,
        cfg["ch4"]["dist"], cfg["ch4"]["tmin"],
    )


@app.callback(
    Output("grafico", "figure"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
    Input("canal", "value"),
    Input("captura_params", "data"),
    State("umbral_ch2", "value"),
    State("dist_ch2", "value"),
    State("tmin_ch2", "value"),
    State("umbral_ch3", "value"),
    State("dist_ch3", "value"),
    State("tmin_ch3", "value"),
    State("umbral_ch4", "value"),
    State("dist_ch4", "value"),
    State("tmin_ch4", "value"),
)
def actualizar(carpeta, seg, canal, p, u2, d2, t2, u3, d3, t3, u4, d4, t4):
    if not carpeta or not seg:
        return go.Figure()

    cfg_sensores = {
        "ch2": {"umbral": float(u2) if u2 is not None else None,
                "dist": float(d2) if d2 is not None else 1.0,
                "tmin": float(t2) if t2 is not None else 0.0},
        "ch3": {"umbral": float(u3) if u3 is not None else None,
                "dist": float(d3) if d3 is not None else 0.5,
                "tmin": float(t3) if t3 is not None else 0.0},
        "ch4": {"umbral": float(u4) if u4 is not None else None,
                "dist": float(d4) if d4 is not None else 0.5,
                "tmin": float(t4) if t4 is not None else 0.0},
    }
    cap = None
    if p and p["canal"] == canal and p["carpeta"] == carpeta:
        cap = capturar(carpeta, canal, p["umbral"], p["dist"], p["tmin"])
    return figura(carpeta, int(seg), canal, cfg_sensores=cfg_sensores, cap=cap)


@app.callback(
    Output("panel_senales", "hidden"),
    Output("panel_st_segmento", "hidden"),
    Output("panel_metadata", "hidden"),
    Input("tabs_principal", "value"),
)
def alternar_panel_principal(tab):
    """Alterna Señales / Transformada S / Metadata sin desmontar `grafico`: así
    se conserva la posición de la línea de umbral arrastrada, el zoom y los
    clics en cruces al volver a la pestaña de Señales."""
    return tab != "senales", tab != "st", tab != "metadata"


@app.callback(
    Output("grafico_st_segmento", "figure"),
    Input("tabs_principal", "value"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
    Input("st_fmax", "value"),
)
def actualizar_st_segmento(tab, carpeta, seg, fmax):
    """Transformada S del segmento completo (4 filas ch1..ch4). Solo se
    calcula si la pestaña está visible."""
    if tab != "st" or not carpeta or not seg:
        return no_update
    return figura_st_segmento(carpeta, int(seg), fmax or ST_FMAX_MHZ)


@app.callback(
    Output("captura_params", "data"),
    Input("btn", "n_clicks"),
    State("carpeta", "value"),
    State("canal", "value"),
    State("umbral_ch2", "value"),
    State("dist_ch2", "value"),
    State("tmin_ch2", "value"),
    State("umbral_ch3", "value"),
    State("dist_ch3", "value"),
    State("tmin_ch3", "value"),
    State("umbral_ch4", "value"),
    State("dist_ch4", "value"),
    State("tmin_ch4", "value"),
)
def fijar_captura(n_clicks, carpeta, canal, u2, d2, t2, u3, d3, t3, u4, d4, t4):
    """Fija el snapshot de parámetros al pulsar el botón. Todos los análisis
    derivan de aquí, garantizando que scatter y ventanas usan el mismo conjunto."""
    if not n_clicks or not carpeta:
        return no_update
    cfg_sensores = {
        "ch2": {"umbral": float(u2) if u2 is not None else umbral_defecto(carpeta, "ch2"),
                "dist": float(d2) if d2 is not None else 1.0,
                "tmin": float(t2) if t2 is not None else 0.0},
        "ch3": {"umbral": float(u3) if u3 is not None else umbral_defecto(carpeta, "ch3"),
                "dist": float(d3) if d3 is not None else 0.5,
                "tmin": float(t3) if t3 is not None else 0.0},
        "ch4": {"umbral": float(u4) if u4 is not None else umbral_defecto(carpeta, "ch4"),
                "dist": float(d4) if d4 is not None else 0.5,
                "tmin": float(t4) if t4 is not None else 0.0},
    }
    cfg_act = cfg_sensores.get(canal, cfg_sensores["ch4"])
    return {
        "carpeta": carpeta,
        "canal": canal,
        "umbral": cfg_act["umbral"],
        "dist": cfg_act["dist"],
        "tmin": cfg_act["tmin"],
        "cfg_sensores": cfg_sensores,
    }


@app.callback(
    Output("grafico_peaks", "figure"),
    Input("captura_params", "data"),
)
def calcular_peaks(p):
    if not p:
        return no_update
    segs, cuentas = contar_peaks(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    if not segs:
        fig = go.Figure()
        fig.update_layout(title=f"{p['canal'].upper()} no disponible en esta medición", height=415)
        return fig
    return figura_peaks(segs, cuentas, p["umbral"], p["canal"])


@app.callback(
    Output("panel_calibracion", "hidden"),
    Input("btn_toggle_calibracion", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_panel_calibracion(n):
    return (n % 2 == 0)


@app.callback(
    Output("ucal_ch2", "value"),
    Output("dtcal_ch2", "value"),
    Output("tmincal_ch2", "value"),
    Output("ucal_ch3", "value"),
    Output("dtcal_ch3", "value"),
    Output("tmincal_ch3", "value"),
    Output("ucal_ch4", "value"),
    Output("dtcal_ch4", "value"),
    Output("tmincal_ch4", "value"),
    Output("cal_import_carpeta", "options"),
    Input("carpeta", "value"),
)
def init_params_calibracion(carpeta):
    cfg = config_sensores_defecto(carpeta)
    opts = [{"label": m, "value": m} for m in mediciones_con_calibracion() if m != carpeta]
    return (
        cfg["ch2"]["umbral"], cfg["ch2"]["dist"] or 0.5, cfg["ch2"]["tmin"] if cfg["ch2"]["tmin"] is not None else 0.0,
        cfg["ch3"]["umbral"], cfg["ch3"]["dist"] or 0.5, cfg["ch3"]["tmin"] if cfg["ch3"]["tmin"] is not None else 0.0,
        cfg["ch4"]["umbral"], cfg["ch4"]["dist"] or 0.5, cfg["ch4"]["tmin"] if cfg["ch4"]["tmin"] is not None else 0.0,
        opts,
    )


@app.callback(
    Output("calibracion_resultado", "data"),
    Output("tlag_manual_ch2", "value"),
    Output("tlag_manual_ch3", "value"),
    Output("tlag_manual_ch4", "value"),
    Output("cal_msg_feedback", "children"),
    Input("btn_calcular_calibracion", "n_clicks"),
    State("carpeta", "value"),
    State("ucal_ch2", "value"), State("dtcal_ch2", "value"), State("tmincal_ch2", "value"),
    State("ucal_ch3", "value"), State("dtcal_ch3", "value"), State("tmincal_ch3", "value"),
    State("ucal_ch4", "value"), State("dtcal_ch4", "value"), State("tmincal_ch4", "value"),
    prevent_initial_call=True,
)
def ejecutar_calibracion(n, carpeta, u2, dt2, tm2, u3, dt3, tm3, u4, dt4, tm4):
    if not n or not carpeta:
        return no_update, no_update, no_update, no_update, no_update
    params = {
        "ch2": (u2, dt2, tm2),
        "ch3": (u3, dt3, tm3),
        "ch4": (u4, dt4, tm4),
    }
    presentes = canales_presentes(carpeta)
    res = {}
    m_ch2, m_ch3, m_ch4 = no_update, no_update, no_update
    msg_partes = []

    for ch in TRIGGERS:
        if ch not in presentes:
            continue
        u, dt, tm = params[ch]
        if u is None:
            continue
        try:
            r = calibrar_retardo(carpeta, ch, float(u), float(dt) if dt is not None else 0.5, float(tm) if tm is not None else 0.0)
            res[ch] = r
            val_ns = round(r["t_lag_us"] * 1e3, 3) if r.get("t_lag_us") is not None else None
            if ch == "ch2" and val_ns is not None:
                m_ch2 = val_ns
            elif ch == "ch3" and val_ns is not None:
                m_ch3 = val_ns
            elif ch == "ch4" and val_ns is not None:
                m_ch4 = val_ns
            msg_partes.append(f"{ch.upper()}: {r['n_valid']}/{r['n_total']} válidos")
        except Exception as e:
            msg_partes.append(f"{ch.upper()}: Error ({e})")

    feedback = html.Span("Calibrado: " + " · ".join(msg_partes) if msg_partes else "Sin canales seleccionados", style={"color": "#2563eb"})
    return res, m_ch2, m_ch3, m_ch4, feedback


@app.callback(
    Output("grafico_calibracion", "figure"),
    Output("cal_tabla_resumen", "children"),
    Input("calibracion_resultado", "data"),
)
def mostrar_calibracion(resultado):
    fig = figura_calibracion(resultado)
    if not resultado:
        return fig, html.Div()

    filas = []
    for ch in TRIGGERS:
        r = resultado.get(ch)
        if not r or r.get("n_total", 0) == 0:
            continue
        t_lag = r.get("t_lag_us")
        sig = r.get("sigma_us")
        t_str = f"{t_lag*1e3:.2f} ns" if t_lag is not None else "-"
        sig_str = f"±{sig*1e3:.2f} ns" if sig is not None else "-"
        nv, nt = r.get("n_valid", 0), r.get("n_total", 0)
        pct = f"{(nv/nt*100):.1f} %" if nt > 0 else "-"
        filas.append(html.Tr([
            html.Td(ch.upper(), style={"fontWeight": "bold", "padding": "4px 8px"}),
            html.Td(t_str, style={"padding": "4px 8px"}),
            html.Td(sig_str, style={"padding": "4px 8px"}),
            html.Td(f"{nv} / {nt}", style={"padding": "4px 8px"}),
            html.Td(pct, style={"padding": "4px 8px"}),
        ]))

    tabla = html.Table(
        style={"width": "100%", "borderCollapse": "collapse", "border": "1px solid #e2e8f0"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style={"textAlign": "left", "padding": "4px 8px", "backgroundColor": "#f8fafc"}),
                html.Th("t̄_lag", style={"textAlign": "left", "padding": "4px 8px", "backgroundColor": "#f8fafc"}),
                html.Th("σ", style={"textAlign": "left", "padding": "4px 8px", "backgroundColor": "#f8fafc"}),
                html.Th("Válidos", style={"textAlign": "left", "padding": "4px 8px", "backgroundColor": "#f8fafc"}),
                html.Th("%", style={"textAlign": "left", "padding": "4px 8px", "backgroundColor": "#f8fafc"}),
            ])),
            html.Tbody(filas),
        ],
    )
    return fig, html.Div([
        html.Div("Resumen estadístico:", style={"fontWeight": "bold", "marginBottom": "6px"}),
        tabla,
    ])


@app.callback(
    Output("calibracion_store", "data"),
    Output("cal_msg_feedback", "children", allow_duplicate=True),
    Input("carpeta", "value"),
    Input("btn_aplicar_calibracion", "n_clicks"),
    Input("btn_guardar_calibracion", "n_clicks"),
    Input("btn_importar_calibracion", "n_clicks"),
    State("tlag_manual_ch2", "value"),
    State("tlag_manual_ch3", "value"),
    State("tlag_manual_ch4", "value"),
    State("calibracion_resultado", "data"),
    State("cal_import_carpeta", "value"),
    prevent_initial_call="initial_duplicate",
)
def gestionar_calibracion_store(carpeta, n_apl, n_guard, n_imp, m2, m3, m4, res_calc, carpeta_imp):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if not carpeta:
        return no_update, no_update

    manuals = {"ch2": m2, "ch3": m3, "ch4": m4}

    if trig == "btn_importar_calibracion" and carpeta_imp:
        st = calibracion_desde_metadata(carpeta_imp)
        st["carpeta"] = carpeta
        st["fuente"] = f"importado de {carpeta_imp}"
        fb = html.Span(f"Calibración importada desde {carpeta_imp}", style={"color": "#059669"})
        return st, fb

    if trig in ("btn_aplicar_calibracion", "btn_guardar_calibracion"):
        canales_dict = {}
        res_calc = res_calc or {}
        algun_cal = False
        es_manual = False

        for ch in TRIGGERS:
            val_ns = manuals.get(ch)
            r = res_calc.get(ch)
            if val_ns is not None:
                algun_cal = True
                calc_ns = (r["t_lag_us"] * 1e3) if (r and r.get("t_lag_us") is not None) else None
                if calc_ns is not None and abs(float(val_ns) - calc_ns) < 1e-4:
                    canales_dict[ch] = {
                        "t_lag_us": r["t_lag_us"],
                        "sigma_us": r.get("sigma_us"),
                        "n_valid": r.get("n_valid"),
                        "n_total": r.get("n_total"),
                        "params": r.get("params"),
                        "calibrado": True,
                    }
                else:
                    es_manual = True
                    canales_dict[ch] = {
                        "t_lag_us": float(val_ns) * 1e-3,
                        "sigma_us": None,
                        "n_valid": None,
                        "n_total": None,
                        "params": None,
                        "calibrado": True,
                    }
            else:
                canales_dict[ch] = {
                    "t_lag_us": 0.0, "sigma_us": None, "n_valid": None, "n_total": None, "calibrado": False,
                }

        fuente = "manual" if es_manual else (carpeta if algun_cal else None)
        fecha = datetime.date.today().isoformat()
        store_data = {
            "carpeta": carpeta,
            "calibrado": algun_cal,
            "fuente": fuente,
            "fecha": fecha,
            "canales": canales_dict,
        }

        if trig == "btn_guardar_calibracion":
            bloque = bloque_calibracion_retardo(canales_dict, fuente, fecha=fecha)
            ok, msg = guardar_calibracion_metadata(carpeta, bloque)
            fb_color = "#10b981" if ok else "#ef4444"
            fb = html.Span(f"{msg}", style={"color": fb_color})
            return store_data, fb
        else:
            fb = html.Span("Calibración aplicada a la sesión actual.", style={"color": "#059669"})
            return store_data, fb

    # Disparo por cambio de carpeta (o carga inicial)
    store_data = calibracion_desde_metadata(carpeta)
    return store_data, ""


@app.callback(
    Output("tlag_manual_ch2", "value", allow_duplicate=True),
    Output("tlag_manual_ch3", "value", allow_duplicate=True),
    Output("tlag_manual_ch4", "value", allow_duplicate=True),
    Input("calibracion_store", "data"),
    prevent_initial_call=True,
)
def rellenar_manual_desde_store(cal):
    if not cal:
        return None, None, None
    chs = cal.get("canales", {})
    def get_ns(ch):
        c = chs.get(ch, {})
        if c.get("calibrado") and c.get("t_lag_us") is not None:
            return round(c["t_lag_us"] * 1e3, 3)
        return None
    return get_ns("ch2"), get_ns("ch3"), get_ns("ch4")


@app.callback(
    Output("cal_badge_estado", "children"),
    Output("cal_badge_estado", "style"),
    Output("cal_badge_ch2", "children"),
    Output("cal_badge_ch3", "children"),
    Output("cal_badge_ch4", "children"),
    Input("calibracion_store", "data"),
)
def badges_calibracion(cal):
    base_style = {
        "display": "inline-block", "fontSize": "11px", "padding": "2px 8px",
        "borderRadius": "10px", "fontWeight": "600",
    }
    if not cal or not cal.get("calibrado"):
        st_txt = "Sin calibrar — retardo 0 ns"
        st_style = {**base_style, "backgroundColor": "#fef3c7", "color": "#92400e"}
        return st_txt, st_style, "CH2: 0.00 ns", "CH3: 0.00 ns", "CH4: 0.00 ns"

    fuente = cal.get("fuente") or "actual"
    fecha = cal.get("fecha") or ""
    st_txt = f"Calibrado · {fuente}" + (f" · {fecha}" if fecha else "")
    st_style = {**base_style, "backgroundColor": "#d1fae5", "color": "#065f46"}

    chs = cal.get("canales", {})
    def fmt_ch(ch):
        info = chs.get(ch, {})
        if info.get("calibrado"):
            ns = info.get("t_lag_us", 0.0) * 1e3
            return f"{ch.upper()}: {ns:.2f} ns"
        return f"{ch.upper()}: 0 ns (sin cal.)"

    return st_txt, st_style, fmt_ch("ch2"), fmt_ch("ch3"), fmt_ch("ch4")


@app.callback(
    Output("densidad_store", "data"),
    Input("captura_params", "data"),
    Input("btn_calc_todos_sensores", "n_clicks"),
    Input("btn_limpiar_densidad", "n_clicks"),
    State("densidad_store", "data"),
    State("umbral_ch2", "value"),
    State("dist_ch2", "value"),
    State("tmin_ch2", "value"),
    State("umbral_ch3", "value"),
    State("dist_ch3", "value"),
    State("tmin_ch3", "value"),
    State("umbral_ch4", "value"),
    State("dist_ch4", "value"),
    State("tmin_ch4", "value"),
    State("calibracion_store", "data"),
    prevent_initial_call=True,
)
def actualizar_densidad_store(p, n_todos, n_limpiar, data_actual,
                              u2, d2, t2, u3, d3, t3, u4, d4, t4, cal_store):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if trig == "btn_limpiar_densidad":
        return []

    filas = list(data_actual) if data_actual else []
    def _upsert(fila):
        idx = next((i for i, r in enumerate(filas) if r.get("id") == fila["id"]), None)
        if idx is not None:
            filas[idx] = fila
        else:
            filas.append(fila)

    cfg_inputs = {
        "ch2": {"umbral": u2, "dist": d2, "tmin": t2},
        "ch3": {"umbral": u3, "dist": d3, "tmin": t3},
        "ch4": {"umbral": u4, "dist": d4, "tmin": t4},
    }

    if trig == "btn_calc_todos_sensores" and p:
        carpeta = p["carpeta"]
        cfg_p = p.get("cfg_sensores", {})
        for ch in ["ch2", "ch3", "ch4"]:
            if ch in canales_presentes(carpeta):
                cfg_ch = cfg_p.get(ch) or cfg_inputs.get(ch, {})
                u_ch = cfg_ch.get("umbral")
                if u_ch is None:
                    u_ch = umbral_defecto(carpeta, ch)
                dist_ch = cfg_ch.get("dist") or 1.0
                tmin_ch = cfg_ch.get("tmin") if cfg_ch.get("tmin") is not None else 0.0
                t_lag = lag_canal(cal_store, carpeta, ch)
                f = calcular_fila_densidad(carpeta, ch, float(u_ch), float(dist_ch), float(tmin_ch), t_lag_us=t_lag)
                _upsert(f)
        return filas

    if trig == "captura_params" and p:
        t_lag = lag_canal(cal_store, p["carpeta"], p["canal"])
        f = calcular_fila_densidad(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], t_lag_us=t_lag)
        _upsert(f)
        return filas

    return filas


@app.callback(
    Output("tabla_densidad", "data"),
    Input("densidad_store", "data"),
)
def sincronizar_tabla_densidad(data):
    return data or []


@app.callback(
    Output("meta_titulo", "children"),
    Output("meta_badge_estado", "children"),
    Output("meta_badge_estado", "style"),
    Output("meta_msg_feedback", "children"),
    Output("meta_card_experimento", "children"),
    Output("meta_card_circuito", "children"),
    Output("meta_card_probeta", "children"),
    Output("meta_card_osc", "children"),
    Output("meta_tabla_canales", "children"),
    Output("meta_yaml_text", "value"),
    Input("carpeta", "value"),
    Input("btn_guardar_metadata", "n_clicks"),
    Input("btn_guardar_yaml_texto", "n_clicks"),
    Input("calibracion_store", "data"),
    State("meta_yaml_text", "value"),
)
def actualizar_panel_metadata(carpeta, n_guardar, n_guardar_txt, cal_store, yaml_txt_state):
    if not carpeta:
        return "", "", {}, "", "", "", "", "", "", ""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    msg_fb = ""

    if trig == "btn_guardar_yaml_texto" and yaml_txt_state:
        ok, msg = guardar_metadata_archivo(carpeta, yaml_txt_state)
        color = "#10b981" if ok else "#ef4444"
        msg_fb = html.Span(msg, style={"color": color, "fontWeight": "600"})
    elif trig == "btn_guardar_metadata":
        meta_act = obtener_metadata(carpeta)
        meta_clean = {k: v for k, v in meta_act.items() if not k.startswith("_")}
        meta_str = yaml.safe_dump(meta_clean, sort_keys=False, allow_unicode=True)
        ok, msg = guardar_metadata_archivo(carpeta, meta_str)
        color = "#10b981" if ok else "#ef4444"
        msg_fb = html.Span(msg, style={"color": color, "fontWeight": "600"})

    meta = obtener_metadata(carpeta)
    existe = meta.get("_existe_en_disco", False)
    badge_txt = "Archivo en disco: metadata.yaml" if existe else "Autogenerado desde HDF5 (no guardado)"
    badge_style = {
        "display": "inline-block", "fontSize": "11px", "padding": "2px 8px",
        "borderRadius": "10px", "fontWeight": "600",
        "backgroundColor": "#d1fae5" if existe else "#fef3c7",
        "color": "#065f46" if existe else "#92400e",
    }

    exp = meta.get("experimento", {})
    circ = meta.get("circuito_impulso", {})
    prob = meta.get("probeta", {})
    osc = meta.get("osciloscopio", {})
    canales_cfg = meta.get("canales", {})

    card_exp = [
        html.Div([html.Strong("ID: "), str(exp.get("id") or carpeta)]),
        html.Div([html.Strong("Fecha/Hora: "), str(exp.get("fecha_hora") or "N/D")]),
        html.Div([html.Strong("Temperatura: "), f"{exp.get('temperatura_c')} °C" if exp.get("temperatura_c") is not None else "N/D"]),
        html.Div([html.Strong("Humedad: "), f"{exp.get('humedad_relativa_pct')} %" if exp.get("humedad_relativa_pct") is not None else "N/D"]),
    ]

    card_circ = [
        html.Div([html.Strong("Forma de onda: "), str(circ.get("forma_onda_nominal") or "1.2/50 µs")]),
        html.Div([html.Strong("Tensión DC (carga): "), f"{circ.get('tension_dc_condensador_kv')} kV" if circ.get("tension_dc_condensador_kv") is not None else "N/D"]),
        html.Div([html.Strong("Polaridad: "), str(circ.get("polaridad") or "positiva")]),
        html.Div([html.Strong("Disparos programados: "), str(circ.get("nro_disparos_programados") or 50)]),
        html.Div([html.Strong("Intervalo entre disparos: "), f"{circ.get('intervalo_entre_disparos_s')} s" if circ.get("intervalo_entre_disparos_s") is not None else "30 s"]),
    ]

    diam = inferir_diametros(prob, prob.get("codigo"))
    card_prob = [
        html.Div([html.Strong("Código: "), str(prob.get("codigo") or "N/D")]),
        html.Div([html.Strong("Geometría: "), str(prob.get("tipo_geometria") or "N/D")]),
        html.Div([html.Strong("N° vacuolas: "), str(prob.get("nro_vacuolas") or "N/D")]),
        html.Div([html.Strong("Diámetros (d): "), diam]),
        html.Div([html.Strong("Capas / Espesor: "), f"{prob.get('nro_capas_total', 4)} capas ({prob.get('espesor_capa_mm', 0.48)} mm)"]),
    ]

    fs_val = osc.get("frecuencia_muestreo_gsas")
    pts_val = osc.get("puntos_por_segmento")
    card_osc = [
        html.Div([html.Strong("Modelo: "), str(osc.get("modelo") or "DSOS804A")]),
        html.Div([html.Strong("Serial: "), str(osc.get("serial") or "N/D")]),
        html.Div([html.Strong("Frecuencia muestreo: "), f"{fs_val} GSa/s" if fs_val else "5.0 GSa/s"]),
        html.Div([html.Strong("Ventana / Puntos: "), f"{pts_val} pts ({osc.get('tiempo_total_ventana_us', 35)} µs)" if pts_val else "35 µs"]),
        html.Div([html.Strong("N° segmentos: "), str(osc.get("num_segmentos_capturados") or n_segmentos(carpeta))]),
    ]

    cal_ret = meta.get("calibracion_retardo", {})
    filas_ch = []
    for c in CANALES:
        cfg = canales_cfg.get(c, {})
        t_lag_ns = cal_ret.get(c, {}).get("t_lag_ns") if isinstance(cal_ret, dict) else None
        t_lag_str = f"{t_lag_ns:.2f} ns" if t_lag_ns is not None else "-"
        filas_ch.append(html.Tr([
            html.Td(c.upper(), style={"fontWeight": "bold", "padding": "4px 8px"}),
            html.Td(cfg.get("sensor", "-"), style={"padding": "4px 8px"}),
            html.Td(cfg.get("funcion", "-"), style={"padding": "4px 8px"}),
            html.Td(f"{cfg.get('escala_v_div', '-')} V/div" if cfg.get("escala_v_div") else "-", style={"padding": "4px 8px"}),
            html.Td(cfg.get("unidad", "V"), style={"padding": "4px 8px"}),
            html.Td(cfg.get("filtro", "-") if cfg.get("filtro") else f"-{cfg.get('atenuacion_db')} dB" if cfg.get("atenuacion_db") else "-", style={"padding": "4px 8px"}),
            html.Td(t_lag_str, style={"padding": "4px 8px"}),
        ]))

    tabla_ch = html.Table(
        style={"width": "100%", "borderCollapse": "collapse", "fontSize": "11px", "marginTop": "4px"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("Sensor", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("Función", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("Escala V/div", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("Unidad", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("Filtro / Atenuación", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
                html.Th("t_lag (ns)", style={"textAlign": "left", "padding": "4px 8px", "borderBottom": "1px solid #cbd5e1"}),
            ])),
            html.Tbody(filas_ch),
        ],
    )

    meta_clean = {k: v for k, v in meta.items() if not k.startswith("_")}
    yaml_dump = yaml.safe_dump(meta_clean, sort_keys=False, allow_unicode=True)

    return (
        f"Medición: {carpeta}",
        badge_txt,
        badge_style,
        msg_fb,
        card_exp,
        card_circ,
        card_prob,
        card_osc,
        tabla_ch,
        yaml_dump,
    )


@app.callback(
    Output("seleccion", "data"),
    Input("captura_params", "data"),
    Input("grafico_scatter", "selectedData"),
    Input("grafico_scatter", "clickData"),
    Input("grafico_vpp_energia", "selectedData"),
    Input("grafico_vpp_energia", "clickData"),
    Input("grafico", "clickData"),
    State("captura_params", "data"),
)
def set_seleccion(_cap_in, sel_pk, click_pk, sel_ve, click_ve, click_g, p):
    """Fuente única de la selección (índices globales de ventana). La alimentan
    los clics/cajas de los dos scatters y los clics en las cruces del canal
    trigger. Una nueva captura la limpia; los reset a None (por redibujo) se
    ignoran para no romper el ciclo."""
    trg = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
    if trg.startswith("captura_params"):
        return []  # nueva captura: limpiar selección
    if not p:
        return no_update
    n = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])["W"].shape[0]
    if trg == "grafico.clickData":            # cruces del trigger (customdata)
        idx = _idx_cruces(click_g, n)
    elif trg == "grafico_scatter.selectedData":
        idx = _idx_scatter(sel_pk, n)
    elif trg == "grafico_scatter.clickData":
        idx = _idx_scatter(click_pk, n)
    elif trg == "grafico_vpp_energia.selectedData":
        idx = _idx_scatter(sel_ve, n)
    elif trg == "grafico_vpp_energia.clickData":
        idx = _idx_scatter(click_ve, n)
    else:
        idx = None
    # None = reset por redibujo o clic sin punto válido: no cambiar la selección.
    return no_update if idx is None else idx


@app.callback(
    Output("grafico_scatter", "figure"),
    Output("grafico_vpp_energia", "figure"),
    Input("captura_params", "data"),
    Input("seleccion", "data"),
    Input("modo_magnitud_trpd", "value"),
    Input("calibracion_store", "data"),
)
def actualizar_scatter(p, sel, modo_trpd, cal):
    """Scatters de Peaks y Vpp vs Energía, con los puntos seleccionados en
    amarillo (venga la selección de los scatters o de las cruces del trigger)."""
    if not p:
        return no_update, no_update
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    t_ref, v_ref = promedio_impulso(p["carpeta"])
    modo = modo_trpd or "vmax"
    t_lag = lag_canal(cal, p["carpeta"], p["canal"])
    t_abs = t_abs_captura(cap, t_lag)
    T = tiempos_impulso(p["carpeta"])
    t10_ref = T["t10"] if T else None
    calibrado = bool(cal and cal.get("carpeta") == p["carpeta"] and cal.get("canales", {}).get(p["canal"], {}).get("calibrado"))
    # uirevision estable dentro de una captura: al pintar el amarillo no se
    # pierde zoom ni la caja de selección; cambia al hacer una captura nueva o cambiar modo.
    rev = f"{p['carpeta']}|{p['canal']}|{p['umbral']}|{p['dist']}|{p['tmin']}|{modo}"
    return (figura_scatter(cap, t_ref, v_ref, p["canal"], sel, rev, modo=modo,
                           t_abs=t_abs, t10_ref=t10_ref, t_lag_us=t_lag, calibrado=calibrado),
            figura_vpp_energia(cap, p["canal"], sel, rev))


@app.callback(
    Output("grafico_ventanas", "figure"),
    Output("grafico_fft", "figure"),
    Input("seleccion", "data"),
    State("captura_params", "data"),
)
def actualizar_temporal(sel, p):
    """Ventanas y FFT de SOLO las señales seleccionadas (store `seleccion`)."""
    if not p:
        return no_update, no_update
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    sel = sel or []
    return figura_ventanas(cap, sel, p["canal"]), figura_fft(cap, sel, p["canal"])


@app.callback(
    Output("grafico_st_ventana", "figure"),
    Input("seleccion", "data"),
    Input("tabs_espectro", "value"),
    Input("st_fmax", "value"),
    State("captura_params", "data"),
)
def actualizar_st_ventana(sel, tab, fmax, p):
    """Transformada S de la ventana de 70 ns (solo si su pestaña está visible),
    promediando SOLO las señales seleccionadas (store `seleccion`)."""
    if tab != "st" or not p:
        return no_update
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    return figura_st_ventana(cap, sel or [], p["canal"], fmax or ST_FMAX_MHZ)


@app.callback(
    Output("segmento", "value", allow_duplicate=True),
    Input("grafico_peaks", "clickData"),
    prevent_initial_call=True,
)
def seleccionar_segmento(click):
    """Al hacer clic en una barra, grafica ese segmento en el panel izquierdo."""
    if not click:
        return no_update
    return int(click["points"][0]["x"])


if __name__ == "__main__":
    app.run(debug=True, dev_tools_props_check=False, host="127.0.0.1", port=8050)
