"""
App Dash - Visor de segmentos (ch1..ch4.h5)

Lee las mediciones de la carpeta ./Mediciones. Cada medicion es una subcarpeta
con los archivos ch1.h5, ch2.h5, ch3.h5 y ch4.h5. Se elige la medicion con un
selector de carpetas.

4 filas (una por canal), eje temporal compartido, cada senal normalizada por su
maximo (|pico| = 1). Selector de segmento. Render con WebGL (Scattergl).

Ejecutar:  python3 app.py   ->  abrir http://127.0.0.1:8050
"""
import os

import h5py
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import find_peaks, butter, sosfiltfilt, welch
from dash import Dash, dcc, html, Input, Output, State, no_update, ctx

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

# Impulso (CH1): filtro pasa-bajos aplicado a la señal de impulso promediada.
IMP_FCORTE = 20e6   # Hz, frecuencia de corte del pasa-bajos
IMP_ORDEN = 4       # orden del Butterworth (fase cero, sosfiltfilt)


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe en la carpeta, en orden."""
    ruta = os.path.join(MEDICIONES, carpeta)
    return [c for c in CANALES if os.path.exists(os.path.join(ruta, f"{c}.h5"))]


def listar_mediciones():
    """Carpetas con al menos un ch1..ch4.h5, directas en MEDICIONES o un nivel
    más abajo (carpetas de cadencia, p. ej. "cada_30s/7"; ver cadencia.py)."""
    if not os.path.isdir(MEDICIONES):
        return []
    carpetas = []
    for nombre in sorted(os.listdir(MEDICIONES)):
        ruta = os.path.join(MEDICIONES, nombre)
        if not os.path.isdir(ruta):
            continue
        if canales_presentes(nombre):
            carpetas.append(nombre)
            continue
        for sub in sorted(os.listdir(ruta)):
            rel = f"{nombre}/{sub}"
            if os.path.isdir(os.path.join(ruta, sub)) and canales_presentes(rel):
                carpetas.append(rel)
    return carpetas


def _ruta(carpeta, canal):
    return os.path.join(MEDICIONES, carpeta, f"{canal}.h5")


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


def cargar_segmento(carpeta, canal, seg, ventana=(T_MIN, T_MAX)):
    """Devuelve (t_us, v) para un canal y segmento, recortado a la ventana."""
    m = meta_medicion(carpeta)[canal]
    with h5py.File(_ruta(carpeta, canal), "r") as f:
        raw = f[f"Waveforms/{m['chan']}/{m['chan']} Seg{seg}Data"][:]
    v = (raw.astype(np.float64) * m["yinc"] + m["yorg"]) * 1e3  # milivoltios
    t = (m["xorg"] + np.arange(raw.size) * m["xinc"]) * 1e6  # microsegundos
    if ventana is not None:
        mask = (t >= ventana[0]) & (t <= ventana[1])
        t, v = t[mask], v[mask]
    return t, v


def figura(carpeta, seg, canal, umbral, dist_us, tmin, cap=None):
    canales = canales_presentes(carpeta)
    fig = make_subplots(
        rows=len(canales), cols=1,
        shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=[c for c in canales],
    )
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
                x=t, y=v, mode="lines", name=c, line=dict(width=0.7),
                hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>" + c + "</extra>",
            ),
            row=i, col=1,
        )
    # Umbral (linea movible) y marcado de peaks sobre el canal trigger
    if canal in canales and v_trig is not None:
        u0 = umbral if umbral is not None else (
            0.5 * float(np.max(np.abs(v_trig))) if v_trig.size else 0.0)
        fila = canales.index(canal) + 1
        fig.add_hline(
            y=u0, row=fila, col=1,
            line=dict(color="red", width=1.5, dash="dash"),
        )
        # Cruces de peaks. Si hay una captura del MISMO canal, se dibujan desde
        # ella (con customdata = índice global de ventana) para que sean
        # clicables y mapeen 1:1 a las señales/scatters. Si no, detección en vivo.
        if cap is not None and cap["W"].shape[0]:
            mask = cap["seg"] == seg
            tp, vp = cap["t_peak"][mask], cap["v_peak"][mask]
            # Lista Python (no ndarray): Plotly 7 serializa numpy como binario y
            # entonces customdata NO llega al clickData. Como lista sí llega.
            customdata = np.nonzero(mask)[0].tolist()  # índice global por cruz
        else:
            tp, vp = _detectar(t_trig, v_trig, u0, _muestras(carpeta, canal, dist_us), tmin)
            customdata = None
        # SVG (go.Scatter): pocos puntos y garantiza customdata en clickData,
        # a diferencia de Scattergl. Así las cruces son clicables de forma fiable.
        fig.add_trace(
            go.Scatter(
                x=tp, y=vp, mode="markers", name="peaks", customdata=customdata,
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
        # uirevision atado a medicion+canal: conserva zoom y la posicion de la
        # linea al cambiar de segmento; se reinicia al cambiar de canal/medicion.
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


def _muestras(carpeta, canal, dist_us):
    """Distancia en µs -> nº de muestras para find_peaks."""
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
    return max(1, int(round(dist_us / dt_us))) if dist_us else None


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
    """Nº de peaks del canal trigger por segmento (umbral=altura, t>=tmin)."""
    if canal not in canales_presentes(carpeta):
        return [], []
    distancia = _muestras(carpeta, canal, dist_us)
    segs, cuentas = [], []
    for s in range(1, n_segmentos(carpeta) + 1):
        t, v = cargar_segmento(carpeta, canal, s)
        tp, _ = _detectar(t, v, umbral, distancia, tmin)
        segs.append(s)
        cuentas.append(len(tp))
    return segs, cuentas


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


def capturar(carpeta, canal, umbral, dist_us, tmin, antes_us=0.2, desp_us=0.8):
    """Detecta los peaks del canal trigger y extrae, alrededor de cada uno, una
    ventana de 1 µs (20% antes / 80% después), alineada al peak (t=0).

    Unifica peaks y ventanas para que el scatter y el gráfico temporal compartan
    EXACTamente el mismo conjunto y orden (la selección del scatter mapea 1:1 a
    las ventanas). Cacheado por sesión. Devuelve un dict con:
      t_rel  : eje temporal relativo al peak (µs), común a todas las ventanas
      W      : matriz (n_ventanas × n_muestras) con las señales capturadas (mV)
      t_peak, v_peak : instante (µs) y amplitud (mV) de cada peak
      seg    : segmento de origen de cada ventana
      dt_us  : paso de muestreo (µs)
    Solo se conservan ventanas completas (peaks no pegados al borde).
    """
    key = (carpeta, canal, round(umbral, 6) if umbral is not None else None,
           dist_us, tmin, antes_us, desp_us)
    if key in _CAPTURA_CACHE:
        return _CAPTURA_CACHE[key]
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6 if canal in canales_presentes(carpeta) else 0.0
    if canal not in canales_presentes(carpeta):
        res = {"t_rel": np.array([]), "W": np.empty((0, 0)),
               "t_peak": np.array([]), "v_peak": np.array([]),
               "seg": np.array([]), "dt_us": dt_us}
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
                continue  # ventana incompleta (peak muy al borde)
            W.append(v[a:b])
            tpk.append(t[i])
            vpk.append(v[i])
            segs.append(s)
    res = {
        "t_rel": t_rel,
        "W": np.array(W) if W else np.empty((0, t_rel.size)),
        "t_peak": np.array(tpk), "v_peak": np.array(vpk),
        "seg": np.array(segs), "dt_us": dt_us,
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
        nperseg = min(W.shape[1], 1024)
        acc = None
        for i in filas:
            f, Pxx = welch(W[i], fs=fs, nperseg=nperseg, scaling="spectrum")
            acc = Pxx if acc is None else acc + Pxx
        fig.add_trace(go.Scattergl(
            x=f / 1e6, y=acc / n, mode="lines", line=dict(color="#1f77b4", width=1),
            hovertemplate="f=%{x:.1f} MHz<br>%{y:.3g} mV²<extra></extra>", showlegend=False,
        ))
    fig.update_layout(
        title=f"FFT (Welch) {canal.upper()} — {n} señales",
        xaxis_title="Frecuencia [MHz]", yaxis_title="Espectro [mV²]",
        height=430, margin=dict(t=50, r=20),
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


def figura_densidad(cuentas, canal):
    """Histograma: nº de segmentos que tienen cada nº de peaks (densidad de eventos)."""
    vals, freq = np.unique(np.asarray(cuentas), return_counts=True)
    fig = go.Figure(go.Bar(x=vals, y=freq, marker_color="#00cc96"))
    fig.update_layout(
        title=f"Densidad de eventos {canal.upper()} (segmentos por nº de peaks)",
        xaxis_title="N° de peaks", yaxis_title="N° de segmentos",
        height=415, margin=dict(t=50, r=20), xaxis=dict(dtick=1),
        plot_bgcolor="white", paper_bgcolor="white",
    )
    return fig


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


def impulso_filtrado(carpeta):
    """Impulso de referencia (promedio de CH1) con pasa-bajos de 50 MHz.

    El filtro se aplica una sola vez por experimento y el resultado queda en
    caché de sesión para no recalcularlo en cada render. Devuelve (t_us, s).
    """
    if carpeta not in _IMPULSO_FILT_CACHE:
        t, v = promedio_impulso(carpeta)
        if t is None:
            _IMPULSO_FILT_CACHE[carpeta] = (None, None)
        else:
            fs = 1.0 / meta_medicion(carpeta)["ch1"]["xinc"]  # Sa/s
            sos = butter(IMP_ORDEN, IMP_FCORTE, btype="lowpass", fs=fs, output="sos")
            _IMPULSO_FILT_CACHE[carpeta] = (t, sosfiltfilt(sos, v))
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


def figura_scatter(cap, t_ref, v_ref, canal, highlight=None, uirev=None):
    # Peaks SIEMPRE como curva 0 (la selección mapea por pointNumber = índice de
    # ventana). La referencia CH1 y el resaltado amarillo van como trazas extra.
    n = cap["t_peak"].size
    fig = go.Figure()
    fig.add_trace(go.Scattergl(
        x=cap["t_peak"], y=cap["v_peak"], mode="markers", name=f"Peaks {canal.upper()}",
        marker=dict(color="#EF553B", size=6, opacity=0.6),
        hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>peak</extra>",
    ))
    if t_ref is not None:
        fig.add_trace(go.Scattergl(
            x=t_ref, y=v_ref, mode="lines", name="CH1 promedio (ref.)",
            line=dict(color="#999", width=1), opacity=0.6,
            hovertemplate="t=%{x:.4f} µs<br>%{y:.2f} mV<extra>CH1</extra>",
        ))
    h = [i for i in (highlight or []) if 0 <= i < n]
    if h:
        fig.add_trace(go.Scattergl(
            x=cap["t_peak"][h], y=cap["v_peak"][h], mode="markers", name="sel",
            marker=dict(color="#FFD400", size=11, line=dict(color="black", width=1)),
            hoverinfo="skip", showlegend=False,
        ))
    fig.update_layout(
        title=f"Peaks {canal.upper()}",
        xaxis_title="Tiempo [µs]", yaxis_title="Valor del peak [mV]",
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
                html.Label("Trigger:"),
                dcc.Dropdown(
                    id="canal",
                    options=[{"label": c, "value": c} for c in TRIGGERS],
                    value="ch4", clearable=False, style={"width": "100px"},
                ),
                html.Label("Distancia (µs):"),
                dcc.Input(id="dist", type="number", value=1.0, min=0, step="any",
                          style={"width": "80px"}),
                html.Label("t mín (µs):"),
                dcc.Input(id="tmin", type="number", value=0.0, step="any",
                          style={"width": "80px"}),
                html.Button("Calcular peaks", id="btn", n_clicks=0),
                html.Span(id="umbral_txt"),
            ],
        ),
        html.Div(
            className="row",
            children=[
                html.Div(className="col card", children=[
                    dcc.Graph(
                        id="grafico",
                        config={"edits": {"shapePosition": True}, "displaylogo": False},
                    ),
                ]),
                html.Div(
                    className="col",
                    children=[
                        html.Div(className="card", children=[
                            dcc.Tabs(id="tabs_peaks", value="barras", children=[
                                dcc.Tab(label="Peaks por segmento", value="barras",
                                        children=[dcc.Graph(id="grafico_peaks")], **_TAB),
                                dcc.Tab(label="Densidad de eventos", value="densidad",
                                        children=[dcc.Graph(id="grafico_densidad")], **_TAB),
                            ]),
                        ]),
                        html.Div(className="card", children=[
                            dcc.Tabs(id="tabs_scatter", value="peaks", children=[
                                dcc.Tab(label="Peaks", value="peaks",
                                        children=[dcc.Graph(id="grafico_scatter")], **_TAB),
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
                html.Div(className="col card", children=[dcc.Graph(id="grafico_fft")]),
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
    Output("grafico", "figure"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
    Input("canal", "value"),
    Input("captura_params", "data"),
    State("dist", "value"),
    State("tmin", "value"),
    State("umbral", "data"),
)
def actualizar(carpeta, seg, canal, p, dist_us, tmin, umbral):
    # umbral, dist y tmin son State (no Input): mover la línea o cambiar esos
    # parámetros NO redibuja. Se redibuja al pulsar "Calcular peaks" (cambia
    # captura_params) o al cambiar de segmento/canal/medición. Las cruces del
    # canal trigger salen de la captura vigente (si es del mismo canal) para que
    # sean clicables y mapeen a las señales.
    if not carpeta or not seg:
        return go.Figure()
    if ctx.triggered_id in ("canal", "carpeta"):
        umbral = None
    cap = None
    if p and p["canal"] == canal and p["carpeta"] == carpeta:
        cap = capturar(carpeta, canal, p["umbral"], p["dist"], p["tmin"])
    return figura(carpeta, int(seg), canal, umbral, dist_us, tmin, cap=cap)


@app.callback(
    Output("umbral", "data"),
    Input("grafico", "relayoutData"),
    Input("canal", "value"),
    Input("carpeta", "value"),
)
def set_umbral(relayout, canal, carpeta):
    """Fuente de verdad del umbral: se mueve con la linea (drag) y se
    reinicia al valor por defecto al cambiar de canal o de medición."""
    if ctx.triggered_id == "grafico":
        u = umbral_desde_relayout(relayout, None)
        return u if u is not None else no_update
    return umbral_defecto(carpeta, canal) if carpeta else no_update


@app.callback(
    Output("umbral_txt", "children"),
    Input("umbral", "data"),
)
def mostrar_umbral(u):
    return "" if u is None else f"Umbral: {u:.4g} mV"


@app.callback(
    Output("captura_params", "data"),
    Input("btn", "n_clicks"),
    State("carpeta", "value"),
    State("canal", "value"),
    State("dist", "value"),
    State("tmin", "value"),
    State("umbral", "data"),
)
def fijar_captura(n_clicks, carpeta, canal, dist_us, tmin, umbral):
    """Fija el snapshot de parámetros al pulsar el botón. Todos los análisis
    derivan de aquí, garantizando que scatter y ventanas usan el mismo conjunto."""
    if not n_clicks or not carpeta:
        return no_update
    if umbral is None:
        umbral = umbral_defecto(carpeta, canal)
    return {"carpeta": carpeta, "canal": canal, "umbral": umbral,
            "dist": dist_us, "tmin": tmin}


@app.callback(
    Output("grafico_peaks", "figure"),
    Output("grafico_densidad", "figure"),
    Input("captura_params", "data"),
)
def calcular_peaks(p):
    if not p:
        return no_update, no_update
    segs, cuentas = contar_peaks(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    if not segs:
        fig = go.Figure()
        fig.update_layout(title=f"{p['canal'].upper()} no disponible en esta medición", height=415)
        return fig, fig
    return (figura_peaks(segs, cuentas, p["umbral"], p["canal"]),
            figura_densidad(cuentas, p["canal"]))


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
)
def actualizar_scatter(p, sel):
    """Scatters de Peaks y Vpp vs Energía, con los puntos seleccionados en
    amarillo (venga la selección de los scatters o de las cruces del trigger)."""
    if not p:
        return no_update, no_update
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"])
    t_ref, v_ref = promedio_impulso(p["carpeta"])
    # uirevision estable dentro de una captura: al pintar el amarillo no se
    # pierde zoom ni la caja de selección; cambia al hacer una captura nueva.
    rev = f"{p['carpeta']}|{p['canal']}|{p['umbral']}|{p['dist']}|{p['tmin']}"
    return (figura_scatter(cap, t_ref, v_ref, p["canal"], sel, rev),
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
    app.run(debug=True, host="127.0.0.1", port=8050)
