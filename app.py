"""
App Dash - Visor de segmentos (ch1..ch4.h5)

Lee las mediciones de la carpeta ./Mediciones. Cada medicion es una subcarpeta
con los archivos ch1.h5, ch2.h5, ch3.h5 y ch4.h5. Se elige la medicion con un
selector de carpetas.

4 filas (una por canal), eje temporal compartido, cada senal normalizada por su
maximo (|pico| = 1). Selector de segmento. Render con WebGL (Scattergl).

Ejecutar:  python3 app.py   ->  abrir http://127.0.0.1:8051
"""
import base64
import urllib.parse
import copy
import os
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import plotly.graph_objects as go
import scipy.fft as sfft
import yaml
from plotly.subplots import make_subplots
from scipy.signal import find_peaks, butter, sosfiltfilt, welch
from dash import Dash, dcc, html, Input, Output, State, no_update, ctx, ALL, Patch

from generate_metadata import (plantilla_metadata, inferir_parametros, inferir_diametros,
                               normalizar_diametros, nombre_corto_sensor)

import datos_h5
import filtros
import rutas
import tema

AQUI = os.path.dirname(os.path.abspath(__file__))
# No hay carpeta de datos fija: las mediciones se eligen con el explorador de
# carpetas y se identifican por su ruta absoluta (ver rutas.py).
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
# Resolución de la imagen: ST_NFREQ = filas de frecuencia (vertical); ST_NT_* =
# columnas de tiempo (horizontal). Más filas/columnas = imagen más fina y cálculo
# más lento (el segmento completo escala ~lineal con ST_NFREQ).
ST_NFREQ = 500
ST_NT_VENTANA = 700     # ventana de 70 ns: todas las muestras a 10 GSa/s (sin decimar)
ST_NT_SEGMENTO = 2000   # segmento completo (-5..30 µs): ~17.5 ns por columna
ST_FMAX_MHZ = 3000      # f máx por defecto y tope de la Transformada S (3 GHz)
FFT_FMAX_MHZ = 3000     # la FFT se muestra solo hasta 3 GHz

# Gráfico de señales: diezmado min-max (conserva picos y valles) a DEC_BUCKETS
# tramos por traza; si el tramo visible dura <= SIN_DIEZMADO_US se envían todas
# las muestras. Al hacer zoom se recalcula solo el tramo visible.
DEC_BUCKETS = 2000
SIN_DIEZMADO_US = 1.0

URL_CALIBRAR = "http://127.0.0.1:8052"   # calibrar_app (pestaña Calibración)

# Parámetros de detección por defecto cuando un campo queda vacío
DIST_DEFECTO_US = 0.035
TMIN_DEFECTO_US = 0.15


def _ruta(carpeta, canal):
    """Ruta absoluta al .h5 del canal (la medición es una ruta absoluta en disco)."""
    return datos_h5.ruta_canal(carpeta, canal)


def canales_presentes(carpeta):
    """Canales (ch1..ch4) cuyo archivo existe para la medición dada, en orden (cacheado)."""
    return datos_h5.canales_presentes(carpeta)


listar_subcarpetas = rutas.listar_subcarpetas


def meta_medicion(carpeta):
    """Devuelve {canal: meta} para los canales presentes, cacheado (datos_h5)."""
    return datos_h5.meta_medicion(carpeta)


def n_segmentos(carpeta):
    return datos_h5.n_segmentos(carpeta)


def _cargar_segmento_leer(carpeta, canal, seg, ventana=(T_MIN, T_MAX), spec=None):
    """(t_us, v) leídos del disco sin caché (ver datos_h5.leer_crudo)."""
    return datos_h5.leer_crudo(carpeta, canal, seg, ventana, spec)


_SPEC_CACHE = {}


def spec_filtro(carpeta, canal):
    """Filtro digital del canal según metadata.yaml (o el de defecto), cacheado."""
    clave = (carpeta, canal)
    if clave not in _SPEC_CACHE:
        _SPEC_CACHE[clave] = filtros.filtro_canal(obtener_metadata(carpeta), canal)
    return _SPEC_CACHE[clave]


def cargar_segmento(carpeta, canal, seg, ventana=(T_MIN, T_MAX), filtrado=True):
    """Devuelve (t_us, v) para un canal y segmento, recortado a la ventana.
    Con `filtrado` se aplica el filtro del canal (CH2..CH4; CH1 nunca).
    Cacheado en datos_h5 (handles reutilizados, eje temporal compartido)."""
    spec = spec_filtro(carpeta, canal) if filtrado and canal != "ch1" else None
    return datos_h5.cargar(carpeta, canal, seg, tuple(ventana) if ventana else None, spec)


_COLORES_CANALES = tema.COLORES_CANALES


def config_sensores_defecto(carpeta, filtrado=True):
    """Genera la configuración de trigger (umbral, dist, tmin) para los canales
    trigger (ch2, ch3, ch4), leyendo de metadata.yaml si existen o calculando valores iniciales."""
    defaults = {
        "ch2": {"umbral": None, "dist": 0.035, "tmin": 0.15},
        "ch3": {"umbral": None, "dist": 0.035, "tmin": 0.15},
        "ch4": {"umbral": None, "dist": 0.035, "tmin": 0.15},
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
            cfg[ch]["umbral"] = umbral_defecto(carpeta, ch, filtrado=filtrado)
    return cfg


def decimar_minmax(t, v, n_buckets=DEC_BUCKETS):
    """Diezmado min-max: divide la señal en n_buckets tramos contiguos y conserva,
    de cada uno, la muestra mínima y la máxima en su orden temporal. Así ningún
    pico ni valle desaparece del dibujo. Si hay pocas muestras, las devuelve tal cual."""
    n = v.size
    if n <= 2 * n_buckets:
        return t, v
    largo = int(np.ceil(n / n_buckets))
    pad = largo * n_buckets - n
    vv = np.pad(v, (0, pad), mode="edge") if pad else v
    bloques = vv.reshape(n_buckets, largo)
    base = np.arange(n_buckets) * largo
    i_min = np.minimum(base + np.argmin(bloques, axis=1), n - 1)
    i_max = np.minimum(base + np.argmax(bloques, axis=1), n - 1)
    idx = np.unique(np.concatenate((i_min, i_max)))   # ordenados en el tiempo
    return t[idx], v[idx]


def tramo_visible(t, v, x0=None, x1=None, n_buckets=DEC_BUCKETS):
    """Muestras a dibujar en [x0, x1] (µs): crudas si el tramo dura <= SIN_DIEZMADO_US,
    si no diezmado min-max. Incluye un tramo de margen a cada lado para que el
    trazo no se corte al borde al hacer pan."""
    if t.size == 0:
        return t, v
    x0 = t[0] if x0 is None else max(float(x0), float(t[0]))
    x1 = t[-1] if x1 is None else min(float(x1), float(t[-1]))
    if x1 <= x0:
        return t[:0], v[:0]
    margen = (x1 - x0) / n_buckets
    i0 = max(int(np.searchsorted(t, x0 - margen, side="left")) - 1, 0)
    i1 = min(int(np.searchsorted(t, x1 + margen, side="right")) + 1, t.size)
    t, v = t[i0:i1], v[i0:i1]
    if x1 - x0 <= SIN_DIEZMADO_US:
        return t, v
    return decimar_minmax(t, v, n_buckets)


def _arreglo_tipado(a):
    """Arreglo float32 codificado como typed array de plotly ({dtype, bdata} base64),
    el mismo formato que usa plotly.py al serializar figuras: ~4× más compacto que
    una lista JSON en los Patch del zoom."""
    a = np.ascontiguousarray(a, dtype=np.float32)
    return {"dtype": "f4", "bdata": base64.b64encode(a.tobytes()).decode("ascii")}


def _canales_senal(carpeta):
    """Canales dibujados como traza de señal (ch1 va aparte): su posición es el
    índice de la traza en figura() y en los Patch de redecimar_zoom."""
    return [c for c in canales_presentes(carpeta) if c != "ch1"]


def figura(carpeta, seg, canal, cfg_sensores=None, cap=None, filtrado=True, rango_x=None):
    canales = canales_presentes(carpeta)
    fig = make_subplots(
        rows=len(canales), cols=1,
        shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=[c for c in canales],
    )
    if cfg_sensores is None:
        cfg_sensores = config_sensores_defecto(carpeta, filtrado=filtrado)

    t_trig = v_trig = None
    for i, c in enumerate(canales, start=1):
        fig.update_yaxes(title_text="mV", row=i, col=1)
        if c == "ch1":
            continue  # CH1 muestra la señal promedio filtrada (se dibuja aparte)
        t, v = cargar_segmento(carpeta, c, seg, filtrado=filtrado)
        if c == canal:
            t_trig, v_trig = t, v
        color_traza = _COLORES_CANALES.get(c, tema.ACCENT)
        td, vd = tramo_visible(t, v, *(rango_x or (None, None)))
        fig.add_trace(
            go.Scattergl(
                x=td.astype(np.float32), y=vd.astype(np.float32), uid=f"sig-{c}",
                mode="lines", name=c, line=dict(color=color_traza, width=0.9),
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
                u_ch = umbral_defecto(carpeta, ch, seg, filtrado=filtrado)
            es_activo = (ch == canal)
            color_linea = tema.LINEA_ACTIVO if es_activo else _COLORES_CANALES.get(ch, tema.MUTED)
            ancho_linea = 2.0 if es_activo else 1.3
            dash_linea = "dash" if es_activo else "dot"
            fig.add_hline(
                y=u_ch, row=fila, col=1, editable=True,   # solo los umbrales se arrastran
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
            go.Scattergl(
                x=tp, y=vp, mode="markers", name=f"peaks {canal.upper()}", customdata=customdata,
                marker=dict(symbol="x", color=tema.LINEA_ACTIVO, size=9, line=dict(width=1.5)),
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
        template="trpd",
        height=850, showlegend=False, margin=dict(t=70, r=20),
        title=f"{carpeta} — Segmento {seg}",
        hovermode="closest", hoverdistance=20, dragmode="zoom",
        uirevision=f"{carpeta}-{canal}",
        editrevision=f"{carpeta}-{canal}-" + "-".join(
            str(cfg_sensores.get(ch, {}).get("umbral")) for ch in TRIGGERS),
    )
    return fig


def umbral_defecto(carpeta, canal="ch4", seg=1, filtrado=True):
    """Umbral por defecto: 50% del |pico| del canal trigger en el segmento dado."""
    if canal not in canales_presentes(carpeta):
        return 0.0
    _, v = cargar_segmento(carpeta, canal, seg, filtrado=filtrado)
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


def _obtener_excluidos(excl_dict, key):
    """Obtiene la lista de índices excluidos para una clave 'carpeta|canal'."""
    val = (excl_dict or {}).get(key, [])
    if isinstance(val, dict):
        return val.get("excluidos", [])
    if isinstance(val, (list, set)):
        return list(val)
    return []


def _obtener_historial(excl_dict, key):
    """Obtiene el historial de pasos de exclusión para una clave 'carpeta|canal'."""
    val = (excl_dict or {}).get(key, {})
    if isinstance(val, dict):
        return val.get("historial", [])
    return []


def parsear_lista_disparos(texto_o_num, n_max_segs=None):
    """Parsea una entrada como '5', '1, 3, 5', '2-6' a una lista de enteros (1-indexed)."""
    if texto_o_num is None or texto_o_num == "":
        return []
    if isinstance(texto_o_num, (int, float)):
        val = int(texto_o_num)
        return [val] if val >= 1 and (n_max_segs is None or val <= n_max_segs) else []
    segs = set()
    partes = str(texto_o_num).replace(";", ",").replace(" ", ",").split(",")
    for p in partes:
        p = p.strip()
        if not p:
            continue
        if "-" in p:
            sub = p.split("-")
            if len(sub) == 2 and sub[0].strip().isdigit() and sub[1].strip().isdigit():
                i0, i1 = int(sub[0].strip()), int(sub[1].strip())
                for s in range(min(i0, i1), max(i0, i1) + 1):
                    if s >= 1 and (n_max_segs is None or s <= n_max_segs):
                        segs.add(s)
        elif p.isdigit():
            s = int(p)
            if s >= 1 and (n_max_segs is None or s <= n_max_segs):
                segs.add(s)
    return sorted(segs)


def contar_peaks(carpeta, canal, umbral, dist_us, tmin, excluidos=None, filtrado=True):
    """Nº de peaks válidos (con ventana completa de 70 ns) del canal trigger por segmento,
    omitiendo los índices de descargas excluidas si se proporcionan."""
    cap = capturar(carpeta, canal, umbral, dist_us, tmin, filtrado=filtrado)
    n_segs = n_segmentos(carpeta)
    segs = list(range(1, n_segs + 1))
    seg_arr = np.asarray(cap["seg"], dtype=int)
    if excluidos:
        activo = np.ones(seg_arr.size, dtype=bool)
        idx = np.fromiter((i for i in excluidos if 0 <= i < seg_arr.size), dtype=int)
        activo[idx] = False
        seg_arr = seg_arr[activo]
    seg_arr = seg_arr[(seg_arr >= 1) & (seg_arr <= n_segs)]
    conteos = np.bincount(seg_arr, minlength=n_segs + 1)[1:n_segs + 1]
    return segs, [int(c) for c in conteos]


def figura_peaks(segs, cuentas, umbral, canal):
    fig = go.Figure(go.Bar(x=segs, y=cuentas, marker_color=tema.ACCENT))
    fig.update_layout(
        template="trpd",
        title=f"Peaks {canal.upper()} por segmento (umbral = {umbral:.4g} mV)",
        xaxis_title="Segmento", yaxis_title="N° de peaks",
        height=415, margin=dict(t=50, r=20),
    )
    return fig


_CAPTURA_CACHE = OrderedDict()
CAPTURAS_EN_CACHE = 64


def capturar(carpeta, canal, umbral, dist_us, tmin,
             antes_us=VENTANA_PD_ANTES_US, desp_us=VENTANA_PD_DESP_US, filtrado=True):
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
    spec = spec_filtro(carpeta, canal) if filtrado else None
    key = (carpeta, canal, round(umbral, 6) if umbral is not None else None,
           dist_us, tmin, antes_us, desp_us, spec)
    return datos_h5.calcular_una_vez(
        _CAPTURA_CACHE, key,
        lambda: _capturar(carpeta, canal, umbral, dist_us, tmin, antes_us, desp_us, filtrado),
        maxsize=CAPTURAS_EN_CACHE)


def _capturar(carpeta, canal, umbral, dist_us, tmin, antes_us, desp_us, filtrado):
    dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6 if canal in canales_presentes(carpeta) else 0.0
    if canal not in canales_presentes(carpeta):
        res = {"t_rel": np.array([]), "W": np.empty((0, 0)),
               "t_peak": np.array([]), "v_peak": np.array([]), "vpp": np.array([]),
               "seg": np.array([]), "t10_seg": np.array([]),
               "dt_us": dt_us}
        return res
    n_antes = int(round(antes_us / dt_us))
    n_desp = int(round(desp_us / dt_us))
    distancia = _muestras(carpeta, canal, dist_us)
    t_rel = np.arange(-n_antes, n_desp + 1) * dt_us
    W, tpk, vpk, segs = [], [], [], []
    for s in range(1, n_segmentos(carpeta) + 1):
        t, v = cargar_segmento(carpeta, canal, s, filtrado=filtrado)
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
        "dt_us": dt_us,
    }
    return res


def _idx_scatter(datos, n, activos=None):
    """Índices desde un scatter (Peaks o Vpp/Energía): la curva 0 es 1:1 con las
    ventanas activas. Se intenta extraer el índice global desde customdata (columna 5)
    o se mapea pointNumber a través de la lista de índices activos.
    Devuelve None si no hay puntos válidos de la curva 0."""
    if not datos or not datos.get("points"):
        return None
    idx = []
    for p in datos["points"]:
        if p.get("curveNumber") != 0:
            continue
        cd = p.get("customdata")
        if cd is not None and len(cd) > 5:
            try:
                g_idx = int(cd[5])
                if 0 <= g_idx < n:
                    idx.append(g_idx)
                    continue
            except (ValueError, TypeError, IndexError):
                pass
        pt = p.get("pointNumber", p.get("pointIndex"))
        if pt is not None:
            pt = int(pt)
            if activos is not None:
                if 0 <= pt < len(activos):
                    idx.append(activos[pt])
            elif 0 <= pt < n:
                idx.append(pt)
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


def _fig_vacia(mensaje, altura=430):
    """Figura sin datos con un mensaje centrado (estados vacíos)."""
    fig = go.Figure()
    fig.update_layout(
        template="trpd", height=altura, margin=dict(t=50, r=20),
        annotations=[dict(text=mensaje, xref="paper", yref="paper", x=0.5, y=0.5,
                          showarrow=False, font=dict(size=13, color=tema.MUTED))],
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    return fig


def _fig_error(titulo, exc, altura=430):
    """Figura que muestra un error en lugar de dejar la figura anterior sin avisar.
    El detalle completo va a la consola del servidor."""
    import traceback
    traceback.print_exc()
    fig = _fig_vacia(f"⚠ {titulo}: {type(exc).__name__}: {exc}", altura)
    fig.update_annotations(font=dict(color=tema.ERROR))
    return fig


def _fig_sin_seleccion(canal):
    """Figura vacía con aviso cuando no hay puntos elegidos en los scatters."""
    fig = go.Figure()
    fig.update_layout(
        template="trpd",
        height=430, margin=dict(t=50, r=20),
        annotations=[dict(
            text="Selecciona señales en los scatters o en las cruces del trigger",
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
            font=dict(size=13, color=tema.MUTED),
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
        line=dict(color=tema.SCATTER_PUNTOS, width=0.8), opacity=0.5,
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_vline(x=0, line=dict(color=tema.LINEA_ACTIVO, width=1, dash="dash"),
                  annotation_text="peak", annotation_position="top")
    fig.update_layout(
        template="trpd",
        title=f"Señales {canal.upper()} — {len(sel)} seleccionadas",
        xaxis_title="Tiempo relativo al peak [µs]", yaxis_title="mV",
        height=430, margin=dict(t=50, r=20),
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
        hasta = f <= FFT_FMAX_MHZ * 1e6
        fig.add_trace(go.Scattergl(
            x=f[hasta] / 1e6, y=Pxx.mean(axis=0)[hasta], mode="lines", line=dict(color=tema.ACCENT, width=1.2),
            hovertemplate="f=%{x:.1f} MHz<br>%{y:.3g} mV²<extra></extra>", showlegend=False,
        ))
    fig.update_layout(
        template="trpd",
        title=f"FFT (Welch) {canal.upper()} — {n} señales",
        xaxis_title="Frecuencia [MHz]", yaxis_title="Espectro [mV²]",
        xaxis_range=[0, FFT_FMAX_MHZ],
        height=430, margin=dict(t=50, r=20),
    )
    return fig


def _paso_st(N, n_t):
    """Paso de decimado temporal de la ST: el mayor divisor de N en [p/2, p] con
    p = N // n_t (plegado exacto); si no hay, p (se recortan < p muestras finales)."""
    p = max(1, N // max(1, n_t))
    for d in range(p, max(1, p // 2) - 1, -1):
        if N % d == 0:
            return d
    return p


def transformada_s(x, t_us, dt_us, fmax_mhz=ST_FMAX_MHZ, nfreq=ST_NFREQ,
                    n_t=ST_NT_VENTANA, bloque=64):
    """Magnitud de la transformada S (Stockwell) de x, algoritmo rápido vía FFT
    (Stockwell 1996): S_j[n] = IFFT{ X[(m+j) mod N] · exp(-2π²m²/j²) }[n], con
    m = índice de frecuencia centrado (-N/2..N/2-1) y j = índice de frecuencia
    de la fila (bin lineal, f_j = j/(N·dt_us) MHz). La fila f=0 es |media(x)|.
    Un tono de amplitud A da |S| ≈ A/2 en su frecuencia (mismas unidades que x,
    p.ej. mV). f máx se limita a ST_FMAX_MHZ y a Nyquist (N//2).

    Plegado espectral: solo se dibuja una columna cada `paso` muestras, y
    s[paso·k] = (1/paso)·IFFT_L{ Σ_r Y[q + r·L] } con L = N/paso, de modo que cada
    fila cuesta una suma sobre el soporte de la gaussiana (|m| <= 1.2·j, fuera de
    él vale < 1e-12) más una IFFT de longitud L, en vez de una IFFT de longitud N.
    Resultado idéntico al cálculo directo (error ~1e-8 relativo). Si `paso` no
    divide a N se descartan las últimas (< paso) muestras.

    Devuelve (t_dec, f_mhz, A): eje de tiempo decimado a ~n_t puntos (recorte
    de t_us), eje de frecuencia [MHz] (nfreq+1 filas) y la matriz de magnitud
    (float32).
    """
    fmax_mhz = min(float(fmax_mhz or ST_FMAX_MHZ), ST_FMAX_MHZ)   # nunca más de 3 GHz
    paso = _paso_st(x.size, n_t)
    N = (x.size // paso) * paso
    L = N // paso
    x = np.asarray(x[:N], dtype=np.float64)
    X = sfft.fft(x, workers=-1)
    jmax = max(1, min(N // 2, int(round(fmax_mhz * 1e6 * N * dt_us * 1e-6))))
    js = np.unique(np.linspace(1, jmax, min(nfreq, jmax)).round().astype(int))
    t_dec = t_us[:N:paso]
    A = np.empty((js.size + 1, L), dtype=np.float32)
    A[0, :] = abs(float(x.mean()))
    m_min, m_max = -(N // 2), (N - 1) // 2          # rango de fftfreq(N)·N
    for a in range(0, js.size, bloque):
        jb = js[a:a + bloque]
        F = np.empty((jb.size, L), dtype=np.complex128)
        for k, j in enumerate(jb):
            sop = int(np.ceil(1.2 * j))
            m = np.arange(max(-sop, m_min), min(sop, m_max) + 1)
            val = X[(m + j) % N] * np.exp(-2 * np.pi ** 2 * (m / j) ** 2)
            q = (m % N) % L
            F[k] = (np.bincount(q, weights=val.real, minlength=L)
                    + 1j * np.bincount(q, weights=val.imag, minlength=L))
        A[a + 1:a + 1 + jb.size] = np.abs(sfft.ifft(F, axis=1, workers=-1)) / paso
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
        x=t_dec, y=f_mhz, z=acc / n, colorscale=tema.COLORMAP_ST, zsmooth="best",
        colorbar=dict(title="mV"),
        hovertemplate="t=%{x:.4f} µs<br>f=%{y:.1f} MHz<br>%{z:.3g} mV<extra></extra>",
    ))
    fig.add_vline(x=0, line=dict(color="white", width=1, dash="dash"),
                  annotation_text="peak", annotation_position="top")
    fig.update_layout(
        template="trpd",
        title=f"Transformada S {canal.upper()} — {n} señales (promedio |S|)",
        xaxis_title="Tiempo relativo al peak [µs]", yaxis_title="Frecuencia [MHz]",
        height=430, margin=dict(t=50, r=20),
    )
    return fig


_ST_SEG_CACHE = OrderedDict()
ST_SEGMENTOS_EN_CACHE = 8    # ~16 MB por entrada (4 canales × 501×2000 float32)


def st_segmento(carpeta, seg, canal, fmax_mhz=ST_FMAX_MHZ, filtrado=True):
    """Transformada S del segmento completo (-5..30 µs) de un canal, con la
    misma señal que el gráfico (cargar_segmento; CH1 sin filtro). Cacheada por sesión."""
    key = (carpeta, seg, canal, fmax_mhz, filtrado)

    def calcular():
        t, v = cargar_segmento(carpeta, canal, seg, filtrado=filtrado)
        dt_us = meta_medicion(carpeta)[canal]["xinc"] * 1e6
        return transformada_s(v, t, dt_us, fmax_mhz, ST_NFREQ, ST_NT_SEGMENTO)
    return datos_h5.calcular_una_vez(_ST_SEG_CACHE, key, calcular, maxsize=ST_SEGMENTOS_EN_CACHE * 4)


def figura_st_segmento(carpeta, seg, fmax_mhz=ST_FMAX_MHZ, filtrado=True):
    """Transformada S del segmento completo, una fila por canal (ch1..ch4),
    eje temporal compartido con la fila de figura()."""
    canales = canales_presentes(carpeta)
    n = len(canales)
    fig = make_subplots(
        rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.04,
        subplot_titles=canales,
    )
    # Los canales son independientes: FFT/IFFT y bincount liberan el GIL, así que
    # calcularlos en hilos reduce ~2.5× el tiempo (11 s -> ~4 s con 4 canales).
    with ThreadPoolExecutor(max_workers=max(1, n)) as ex:
        resultados = list(ex.map(
            lambda c: st_segmento(carpeta, seg, c, fmax_mhz, filtrado=filtrado), canales))
    for i, (c, (t_dec, f_mhz, A)) in enumerate(zip(canales, resultados), start=1):
        fig.add_trace(
            go.Heatmap(
                x=t_dec, y=f_mhz, z=A, colorscale=tema.COLORMAP_ST, zsmooth="best",
                colorbar=dict(title="mV", len=0.85 / n, y=1 - (i - 0.5) / n, thickness=14),
                hovertemplate="t=%{x:.4f} µs<br>f=%{y:.1f} MHz<br>%{z:.3g} mV<extra>" + c + "</extra>",
            ),
            row=i, col=1,
        )
        fig.update_yaxes(title_text="MHz", row=i, col=1)
    fig.update_xaxes(title_text="Tiempo [µs]", row=n, col=1)
    fig.update_xaxes(range=[T_MIN, T_MAX])
    fig.update_layout(
        template="trpd",
        height=850, margin=dict(t=70, r=20),
        title=f"{carpeta} — Segmento {seg} — Transformada S",
    )
    return fig



def _dir_medicion(carpeta):
    """Encuentra el directorio físico que contiene los archivos de la medición."""
    return datos_h5.dir_medicion(carpeta) or os.path.abspath(carpeta)


def obtener_metadata(carpeta):
    """metadata.yaml de la medición (o la plantilla generada si no existe), como copia
    que el llamador puede modificar. Cacheada mientras no cambie el archivo."""
    if not carpeta:
        return {}
    meta_path = os.path.join(_dir_medicion(carpeta), "metadata.yaml")
    return copy.deepcopy(datos_h5.cacheado_por_archivo(
        meta_path, ("app", carpeta), lambda: _leer_metadata(carpeta)))


def _leer_metadata(carpeta):
    """Lee metadata.yaml si existe en la carpeta de medición; de lo contrario,
    genera la estructura enriquecida en memoria a partir de los HDF5 y parámetros inferidos."""
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
        datos_h5.invalidar_archivo(meta_path)
        for clave in [k for k in _SPEC_CACHE if k[0] == carpeta]:
            del _SPEC_CACHE[clave]   # el filtro de cada canal puede haber cambiado
        return True, f"Guardado exitoso en {os.path.basename(meta_path)}"
    except Exception as e:
        return False, f"Error al guardar: {e}"


def guardar_diametros(carpeta, texto):
    """Normaliza los diámetros escritos ('2, 2, 3' -> '2mm-2mm-3mm'), los valida contra
    el código de probeta y los guarda en probeta.diametros sin tocar el resto del YAML.
    Si metadata.yaml aún no existe, se escribe la plantilla completa con ese campo."""
    meta = obtener_metadata(carpeta)
    prob = meta.get("probeta") if isinstance(meta.get("probeta"), dict) else {}
    # mo/mi se lee del código: con sufijo H, tipo_geometria es 'asimetrica' y lo oculta.
    m = re.search(r"V(mo|mi)", str(prob.get("codigo") or ""), re.IGNORECASE)
    tipo = {"mo": "monodiametro", "mi": "mixta"}[m.group(1).lower()] if m else prob.get("tipo_geometria")
    norm, error = normalizar_diametros(texto, prob.get("nro_vacuolas"), tipo)
    if error:
        return False, f"Diámetros no guardados: {error}"
    prob["diametros"] = norm
    meta["probeta"] = prob
    meta_clean = {k: v for k, v in meta.items() if not k.startswith("_")}
    ok, msg = guardar_metadata_archivo(
        carpeta, yaml.safe_dump(meta_clean, sort_keys=False, allow_unicode=True))
    return ok, f"Diámetros {norm} — {msg}" if ok else msg


COLUMNAS_DENSIDAD = [
    {"name": "Specimen", "id": "specimen"},
    {"name": "d (mm)", "id": "diametro"},
    {"name": "Voltage (kV)", "id": "voltage"},
    {"name": "Sensor", "id": "sensor"},
    {"name": "N_PD distribution [0, 1, 2, 3, 4, > 4]", "id": "distribucion"},
    {"name": "N_PD = N_cav", "id": "n_coinc"},
    {"name": "V̄_pp (V)", "id": "vpp_media"},
    {"name": "t̄_abs (µs)", "id": "tabs_media"},
]


def _tension_kv(carpeta, meta):
    """Tensión (kV) de la medición: carpeta '<X>kV' de la ruta y, si no hay,
    circuito_impulso.tension_kv_ac_sec del metadata.yaml. None si no se conoce."""
    kv = inferir_parametros(carpeta).get("tension_sec_kv")
    if kv is None:
        kv = (meta.get("circuito_impulso") or {}).get("tension_kv_ac_sec")
    try:
        return float(kv) if kv is not None else None
    except (TypeError, ValueError):
        return None


def calcular_fila_densidad(carpeta, canal, umbral, dist_us, tmin, t_lag_us=0.0, excluidos=None,
                           filtrado=True):
    """Fila de la tabla de estadística con el formato de la Tabla 1 del paper:
    Specimen (Nv), d (mm), Voltage (kV), Sensor, N_PD distribution [0, 1, 2, 3, 4, > 4],
    N_PD = N_cav, V̄_pp (V) y t̄_abs (µs).

    V̄_pp y t̄_abs se promedian solo sobre las descargas de los disparos con
    N_PD == N_cav (si no se conoce N_cav, sobre todas las descargas activas).
    Si se proporciona `excluidos`, omite dichos índices globales del cálculo."""
    meta = obtener_metadata(carpeta)
    prob = meta.get("probeta") or {}
    inf = inferir_parametros(carpeta)

    n_cav = prob.get("nro_vacuolas") or inf.get("nro_vacuolas")
    try:
        n_cav = int(n_cav) if n_cav is not None else None
    except (TypeError, ValueError):
        n_cav = None
    specimen = f"{n_cav}v" if n_cav else (prob.get("codigo") or "-")

    diam = inferir_diametros(prob, prob.get("codigo") or inf.get("codigo_probeta"))
    diametro = "-" if diam == "N/D" else ", ".join(
        x[:-2] if x.lower().endswith("mm") else x for x in str(diam).split("-"))

    voltage_kv = _tension_kv(carpeta, meta)
    voltage = f"{voltage_kv:g}" if voltage_kv is not None else "-"

    sens_info = (meta.get("canales") or {}).get(canal) or {}
    sensor = nombre_corto_sensor(sens_info.get("sensor"), canal)

    cap = capturar(carpeta, canal, umbral, dist_us, tmin, filtrado=filtrado)
    n_total = cap["t_peak"].size
    excl_set = set(excluidos or [])
    activos = [i for i in range(n_total) if i not in excl_set]

    segs, cuentas = contar_peaks(carpeta, canal, umbral, dist_us, tmin, excluidos=excl_set,
                                 filtrado=filtrado)
    cuentas_arr = np.asarray(cuentas)
    if cuentas_arr.size > 0:
        c = [int(np.sum(cuentas_arr == k)) for k in range(5)] + [int(np.sum(cuentas_arr > 4))]
        distribucion = "[" + ", ".join(str(x) for x in c) + "]"
    else:
        distribucion = "[0, 0, 0, 0, 0, 0]"

    if n_cav:
        n_coinc = str(int(np.sum(cuentas_arr == n_cav))) if cuentas_arr.size else "0"
        segs_ok = {s for s, k in zip(segs, cuentas) if k == n_cav}
        idx = [i for i in activos if int(cap["seg"][i]) in segs_ok]
    else:
        n_coinc = "-"
        idx = activos

    if idx:
        vpp_media = f"{float(np.mean(cap['vpp'][idx])) / 1000.0:.3f}"
        tabs_media = f"{float(np.mean(t_abs_captura(cap, t_lag_us)[idx])):.3f}"
    else:
        vpp_media = tabs_media = "-"

    return {
        "id": f"{carpeta}_{canal}",
        "specimen": specimen,
        "diametro": diametro,
        "voltage": voltage,
        "sensor": sensor,
        "distribucion": distribucion,
        "n_coinc": n_coinc,
        "vpp_media": vpp_media,
        "tabs_media": tabs_media,
        "_carpeta": carpeta,
        "_canal": canal,
        "_n_cav": n_cav,
        "_voltage_kv": voltage_kv,
        "_filtrado": bool(filtrado),
        "_filtro": filtros.etiqueta(spec_filtro(carpeta, canal)) if filtrado else "sin filtro",
    }


def _cabecera_tabla_paper():
    """Cabecera con la notación de la Tabla 1 (subíndices y barra de media)."""
    return html.Tr([
        html.Th("Specimen"),
        html.Th("d (mm)"),
        html.Th("Voltage (kV)"),
        html.Th("Sensor"),
        html.Th(["N", html.Sub("PD"), " distribution", html.Br(), "[0, 1, 2, 3, 4, > 4]"]),
        html.Th(["N", html.Sub("PD"), " = N", html.Sub("cav")]),
        html.Th(["V̄", html.Sub("pp"), " (V)"]),
        html.Th(["t̄", html.Sub("abs"), " (µs)"]),
    ])


def construir_tabla_paper(filas):
    """Tabla HTML con el formato de la Tabla 1 del paper: Specimen, d (mm) y
    Voltage combinados (rowSpan) por medición; una fila por sensor."""
    if not filas:
        return html.Div("Sin datos: pulse 'Calcular todos los sensores'.",
                        className="tabla-paper-vacia")
    orden_ch = {"ch2": 0, "ch3": 1, "ch4": 2}
    grupos = {}
    for f in filas:
        grupos.setdefault(f.get("_carpeta"), []).append(f)

    def clave_grupo(item):
        f0 = item[1][0]
        n, v = f0.get("_n_cav"), f0.get("_voltage_kv")
        return (n is None, n or 0, v is None, v or 0.0, str(item[0]))

    cuerpo = []
    for _, grupo in sorted(grupos.items(), key=clave_grupo):
        grupo = sorted(grupo, key=lambda f: orden_ch.get(f.get("_canal"), 9))
        span = len(grupo)
        for k, f in enumerate(grupo):
            celdas = []
            if k == 0:
                celdas += [
                    html.Td(f.get("specimen"), rowSpan=span, className="tp-specimen"),
                    html.Td(f.get("diametro"), rowSpan=span),
                    html.Td(f.get("voltage"), rowSpan=span),
                ]
            celdas += [
                html.Td(f.get("sensor")),
                html.Td(f.get("distribucion"), className="tp-distribucion"),
                html.Td(f.get("n_coinc")),
                html.Td(f.get("vpp_media")),
                html.Td(f.get("tabs_media")),
            ]
            cuerpo.append(html.Tr(celdas, className="tp-inicio-grupo" if k == 0 else None))
    tabla = html.Table([html.Thead(_cabecera_tabla_paper()), html.Tbody(cuerpo)],
                       className="tabla-paper")
    return html.Div([tabla, html.Div(nota_filtros_tabla(filas), className="tabla-paper-nota")])


def nota_filtros_tabla(filas):
    """Nota al pie con los filtros digitales aplicados a cada sensor de la tabla."""
    por_sensor = {}
    for f in sorted(filas, key=lambda f: str(f.get("_canal"))):
        por_sensor.setdefault(f.get("sensor"), set()).add(f.get("_filtro") or "sin filtro")
    if all(not f.get("_filtrado", True) for f in filas):
        return "Señal sin filtrar."
    partes = [f"{s}: {' / '.join(sorted(v))}" for s, v in por_sensor.items()]
    mezcla = len({bool(f.get("_filtrado", True)) for f in filas}) > 1
    return ("Filtros digitales (Butterworth orden 4, fase cero) — " + " · ".join(partes)
            + (". Atención: la tabla mezcla filas con y sin filtro." if mezcla else "."))


def csv_tabla_densidad(filas):
    """CSV de la tabla (columnas visibles de COLUMNAS_DENSIDAD, sin claves internas)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([c["name"] for c in COLUMNAS_DENSIDAD])
    for f in filas or []:
        w.writerow([f.get(c["id"], "") for c in COLUMNAS_DENSIDAD])
    return buf.getvalue()



_PASADA_CH1 = {}


def _pasada_ch1(carpeta):
    """Lee cada segmento de CH1 UNA vez y devuelve (t0, promedio, t10_por_seg),
    con t10_por_seg[k] = t10 del segmento k+1 o None si no se pudo calcular.
    Lo usan promedio_impulso y t10_por_segmento (antes recorrían CH1 por separado)."""
    def calcular():
        acc, t0, cnt, t10s = None, None, 0, []
        for s in range(1, n_segmentos(carpeta) + 1):
            t, v = cargar_segmento(carpeta, "ch1", s)
            if acc is None:
                acc, t0 = np.zeros_like(v), t
            if v.shape == acc.shape:
                acc += v
                cnt += 1
            if v.size == 0:
                t10s.append(None)
                continue
            sf = _filtrar_impulso(carpeta, v)
            i_pico = int(np.argmax(sf))
            vmax = float(sf[i_pico])
            t10s.append(_cruce_subida(t, sf, 0.10 * vmax, i_pico) if vmax > 0 else None)
        return t0, (acc / cnt if cnt else acc), t10s
    return datos_h5.calcular_una_vez(_PASADA_CH1, carpeta, calcular)


def promedio_impulso(carpeta):
    """Señal de impulso de referencia: promedio de CH1 sobre todos los segmentos."""
    if "ch1" not in canales_presentes(carpeta):
        return None, None
    t0, prom, _ = _pasada_ch1(carpeta)
    return t0, prom


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
    def calcular():
        t, v = promedio_impulso(carpeta)
        return (None, None) if t is None else (t, _filtrar_impulso(carpeta, v))
    return datos_h5.calcular_una_vez(_IMPULSO_FILT_CACHE, carpeta, calcular)


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
    return datos_h5.calcular_una_vez(_T10_SEG_CACHE, carpeta, lambda: _t10_por_segmento(carpeta))


def _t10_por_segmento(carpeta):
    nsegs = n_segmentos(carpeta) if ("ch1" in canales_presentes(carpeta)) else 0
    if nsegs == 0 or ("ch1" not in canales_presentes(carpeta)):
        arr = np.zeros(nsegs, dtype=np.float64)
        arr.flags.writeable = False
        _T10_FALLBACK_COUNT[carpeta] = 0
        return arr

    T_prom = tiempos_impulso(carpeta)
    t10_fallback = T_prom["t10"] if (T_prom and T_prom.get("t10") is not None) else 0.0

    t10s = _pasada_ch1(carpeta)[2]
    t10_arr = np.empty(nsegs, dtype=np.float64)
    n_fb = 0
    for k in range(nsegs):
        t10_val = t10s[k] if k < len(t10s) else None
        if t10_val is None:
            t10_arr[k] = t10_fallback
            n_fb += 1
        else:
            t10_arr[k] = t10_val

    t10_arr.flags.writeable = False
    _T10_FALLBACK_COUNT[carpeta] = n_fb
    return t10_arr


def n_fallback_t10(carpeta):
    """Número de segmentos en que se usó el t10 fallback en lugar del calculado."""
    if carpeta not in _T10_FALLBACK_COUNT:
        t10_por_segmento(carpeta)
    return _T10_FALLBACK_COUNT.get(carpeta, 0)


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
    Normaliza retardos con referencia O1 al ancla t10 mediante delta_t10_menos_O1_ns.
    """
    if not carpeta:
        return {
            "carpeta": "", "calibrado": False, "fuente": None, "fecha": None,
            "referencia_impulso": None, "delta_t10_O1_us": None, "aviso": None,
            "canales": {ch: {"t_lag_us": 0.0, "sigma_us": None, "n_valid": None, "n_total": None, "calibrado": False} for ch in TRIGGERS}
        }
    meta = obtener_metadata(carpeta)
    bloque = meta.get("calibracion_retardo") if isinstance(meta, dict) else None
    canales_res = {}
    calibrado_global = False
    fuente = None
    fecha = None
    ref = None
    delta_us = None
    aviso = None

    if isinstance(bloque, dict):
        fuente = bloque.get("fuente_calibracion")
        fecha = bloque.get("fecha")
        ref = bloque.get("referencia_impulso")
        if ref is None:  # compatibilidad con bloques ya escritos
            leg = str(bloque.get("referencia") or "")
            ref = "origen_virtual_IEC60060" if "origen_virtual" in leg else "t10"

        ancla_bloque = bloque.get("ancla") or {}
        delta_ns = ancla_bloque.get("t10_menos_O1_ns")
        if delta_ns is not None:
            delta_us = float(delta_ns) * 1e-3

        es_o1 = (ref == "origen_virtual_IEC60060")
        if es_o1 and delta_us is None:
            aviso = "Bloque de referencia O1 sin ancla (t10_menos_O1_ns no disponible). No se puede normalizar al ancla t10."

        for ch in TRIGGERS:
            b_ch = bloque.get(ch)
            if isinstance(b_ch, dict) and b_ch.get("t_lag_ns") is not None:
                t_lag_ns = float(b_ch["t_lag_ns"])
                sigma_ns = float(b_ch["sigma_ns"]) if b_ch.get("sigma_ns") is not None else None

                if es_o1:
                    if delta_us is not None:
                        t_lag_us = (t_lag_ns * 1e-3) - delta_us
                        canal_calibrado = True
                    else:
                        t_lag_us = 0.0
                        canal_calibrado = False
                else:
                    t_lag_us = t_lag_ns * 1e-3
                    canal_calibrado = True

                canales_res[ch] = {
                    "t_lag_us": t_lag_us,
                    "sigma_us": sigma_ns * 1e-3 if sigma_ns is not None else None,
                    "n_valid": b_ch.get("n_valid"),
                    "n_total": b_ch.get("n_total"),
                    "calibrado": canal_calibrado,
                }
                if canal_calibrado:
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
        "referencia_impulso": ref,
        "delta_t10_O1_us": delta_us,
        "aviso": aviso,
        "canales": canales_res,
    }


def lag_canal(cal, carpeta, canal):
    """t_lag (µs) del canal si el store corresponde a la carpeta; 0.0 en otro caso."""
    if not cal or cal.get("carpeta") != carpeta:
        return 0.0
    ch_data = cal.get("canales", {}).get(canal, {})
    return float(ch_data.get("t_lag_us", 0.0) or 0.0)


# Líneas verticales de tiempos: (clave, etiqueta, color).
_IMP_LINEAS = [
    ("t10", "t10 (10%)", tema.LINEA_T10),
    ("t30", "t30 (30%)", tema.LINEA_T30_T90),
    ("t90", "t90 (90%)", tema.LINEA_T30_T90),
    ("t50", "t50 (50% cola)", tema.LINEA_T50),
    ("t_pico", "t_pico", tema.WARN),
    ("t0_lin", "t0_lin", tema.LINEA_O1),
    ("tmax_lin", "tmax_lin", tema.LINEA_O1),
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
            line=dict(color=_COLORES_CANALES["ch1"], width=1.6),
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
                line=dict(color=tema.LINEA_O1, width=1, dash="dash"),
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
            font=dict(size=10, color=tema.INK), bgcolor="rgba(255,255,255,0.9)",
            bordercolor=tema.BORDER, borderwidth=1,
        )


def figura_scatter(cap, t_ref, v_ref, canal, highlight=None, uirev=None, modo="vmax",
                   t_abs=None, t10_ref=None, t_lag_us=0.0, calibrado=False, excluidos=None):
    # Peaks SIEMPRE como curva 0 (la selección mapea por pointNumber o customdata).
    # La referencia CH1 y el resaltado van como trazas extra.
    n = cap["t_peak"].size
    excl_set = set(excluidos or [])
    activos = [i for i in range(n) if i not in excl_set]

    fig = go.Figure()
    es_vpp = (modo == "vpp")
    y_val = cap["vpp"] if es_vpp else cap["v_peak"]
    y_label = "Vpp [mV]" if es_vpp else "Vmax [mV]"
    traza_nombre = f"Vpp {canal.upper()}" if es_vpp else f"Vmax {canal.upper()}"

    x = t_abs if (t_abs is not None and t_abs.size == n) else cap["t_peak"]

    # customdata incluye el índice global i en la columna 5
    if n > 0:
        indices_arr = np.arange(n)
        cd = np.stack([cap["v_peak"], cap["vpp"], cap["t_peak"], cap["seg"], x * 1e3, indices_arr], axis=1)
    else:
        cd = None

    x_act = x[activos] if n > 0 else np.array([])
    y_act = y_val[activos] if n > 0 else np.array([])
    cd_act = cd[activos] if cd is not None else None

    fig.add_trace(go.Scattergl(
        x=x_act, y=y_act, mode="markers", name=traza_nombre,
        customdata=cd_act,
        marker=dict(color=tema.SCATTER_PUNTOS, size=6, opacity=0.6),
        hovertemplate="t_abs=%{x:.4f} µs (%{customdata[4]:.2f} ns)<br>t_osc=%{customdata[2]:.4f} µs<br>Vmax=%{customdata[0]:.2f} mV<br>Vpp=%{customdata[1]:.2f} mV<br>Seg %{customdata[3]:.0f}<extra>" + canal.upper() + "</extra>",
    ))
    if t_ref is not None and v_ref is not None and v_ref.size:
        paso = max(1, t_ref.size // IMP_PUNTOS_PLOT)
        x_ref = t_ref[::paso] - (t10_ref or 0.0)
        v_r = v_ref[::paso]
        frac = v_r / (float(np.max(np.abs(v_r))) or 1.0)  # adimensional, -1..1
        esc = float(np.percentile(y_val, 95)) if y_val.size >= 20 else (float(np.max(y_val)) if y_val.size else 1.0)
        y_r, cd_ref = frac * esc, frac
        nombre = "CH1 promedio (forma normalizada)"
        htmpl = "t_abs=%{x:.4f} µs<br>%{customdata:.1%} de la cresta CH1<extra>CH1</extra>"
        fig.add_trace(go.Scattergl(x=x_ref, y=y_r, customdata=cd_ref, mode="lines",
                                   name=nombre, line=dict(color=tema.MUTED_LIGHT, width=1),
                                   opacity=0.6, hovertemplate=htmpl))
        fig.add_vline(x=0, line=dict(color=tema.LINEA_T10, width=1, dash="dot"),
                      annotation_text="t10", annotation_position="top")
    h = [i for i in (highlight or []) if 0 <= i < n and i not in excl_set]
    if h and y_val.size > 0:
        fig.add_trace(go.Scattergl(
            x=x[h], y=y_val[h], mode="markers", name="sel",
            marker=dict(color=tema.SCATTER_SEL, size=10, line=dict(color="white", width=1.5)),
            hoverinfo="skip", showlegend=False,
        ))
    fig.update_layout(
        template="trpd",
        xaxis_title="Tiempo relativo al impulso t_abs [µs] (t10 = 0)", yaxis_title=y_label,
        height=415, margin=dict(t=40, r=20), showlegend=True, dragmode="select",
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0.5, xanchor="center"),
        uirevision=uirev,
    )
    return fig


app = Dash(__name__)
app.title = "Análisis de Vacuolas"

_TAB = tema.TAB_PROPS

app.layout = html.Div(
    className="app",
    children=[
        dcc.Store(id="rango_x"),            # zoom vigente del gráfico de señales
        dcc.Store(id="captura_params"),
        dcc.Store(id="seleccion", data=[]),
        dcc.Store(id="descargas_excluidas", data={}, storage_type="local"),
        dcc.Store(id="densidad_store", data=[], storage_type="local"),
        dcc.Store(id="ultima_carpeta", storage_type="local"),
        dcc.Store(id="calibracion_store"),
        dcc.Store(id="explorador_ruta_actual", data=rutas.ruta_inicial()),
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
                    options=[], value=None, clearable=False,
                    placeholder="Elija una carpeta con Examinar…", style={"width": "260px"},
                ),
                html.Button("Examinar…", id="btn_examinar", n_clicks=0,
                            style=tema.ESTILO_BOTON_SECONDARY),
                html.Label("Segmento:"),
                html.Button("◀", id="segmento_prev", n_clicks=0, title="Segmento anterior (tecla ←)",
                            style=tema.ESTILO_BOTON_STEPPER),
                dcc.Input(id="segmento", type="number", min=1, max=1, step=1, value=1,
                          debounce=True, style={"width": "64px", "textAlign": "center"}),
                html.Span(id="segmento_total", children="/ 1",
                          style={"fontSize": "12px", "color": tema.MUTED}),
                html.Button("▶", id="segmento_next", n_clicks=0, title="Segmento siguiente (tecla →)",
                            style=tema.ESTILO_BOTON_STEPPER),
                html.Label("Trigger activo:"),
                dcc.Dropdown(
                    id="canal",
                    options=[
                        {"label": "CH2", "value": "ch2"},
                        {"label": "CH3", "value": "ch3"},
                        {"label": "CH4", "value": "ch4"},
                    ],
                    value="ch4", clearable=False, style={"width": "120px"},
                    persistence=True, persistence_type="local",
                ),
                html.Button("Calcular peaks", id="btn", n_clicks=0,
                            style=tema.ESTILO_BOTON_PRIMARY),
                html.Div(
                    dcc.Checklist(
                        id="switch_filtros",
                        options=[{"label": " Filtros del paper", "value": "on"}],
                        value=["on"], inline=True,
                        persistence=True, persistence_type="local",
                    ),
                    title=("Butterworth orden 4, fase cero: CH2 HP 5 MHz · CH3 HP 200 MHz · "
                           "CH4 HP 200 MHz (configurable en metadata: canales.chX.filtro)"),
                ),
                html.Label("f máx ST (MHz):"),
                html.Span(dcc.Input(id="st_fmax", type="number", value=ST_FMAX_MHZ, min=1, max=ST_FMAX_MHZ,
                                    step="any", debounce=True, style={"width": "80px"},
                                    persistence=True, persistence_type="local"),
                          title="Frecuencia máxima de la Transformada S (tope 3000 MHz)"),
            ],
        ),
        html.Div(
            id="explorador_panel",
            hidden=False,
            style={
                **tema.ESTILO_CARD,
                "margin": "0 0 12px 0",
                "backgroundColor": tema.BG,
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "10px"},
                    children=[
                        html.Button("Subir nivel", id="explorador_subir", n_clicks=0,
                                    style=tema.ESTILO_BOTON_SECONDARY),
                        html.Span(id="explorador_ruta_label", style={"fontWeight": "bold", "fontSize": "13px",
                                                                     "color": tema.INK, "wordBreak": "break-all"}),
                    ],
                ),
                html.Div(
                    id="explorador_listado",
                    style={
                        "maxHeight": "240px",
                        "overflowY": "auto",
                        "border": f"1px solid {tema.BORDER}",
                        "borderRadius": "4px",
                        "backgroundColor": tema.CARD,
                        "padding": "6px",
                        "marginBottom": "10px",
                    },
                ),
                html.Div(
                    style={"display": "flex", "gap": "10px"},
                    children=[
                        html.Button("Seleccionar esta carpeta", id="explorador_confirmar", disabled=True, n_clicks=0,
                                    style=tema.ESTILO_BOTON_PRIMARY),
                        html.Button("Cancelar", id="explorador_cancelar", n_clicks=0,
                                    style={"backgroundColor": tema.MUTED_LIGHT, "color": "white",
                                           "border": "none", "borderRadius": "4px", "padding": "6px 14px", "cursor": "pointer"}),
                    ],
                ),
            ],
        ),
        html.Div(
            style={
                "display": "flex", "gap": "10px", "alignItems": "center",
                "padding": "8px 12px", "backgroundColor": tema.BG,
                "border": f"1px solid {tema.BORDER}", "borderRadius": "6px",
                "margin": "0 0 12px 0", "flexWrap": "wrap",
            },
            children=[
                html.Span("Configuración Multi-Trigger:",
                          style={"fontSize": "11px", "fontWeight": "bold", "color": tema.INK, "marginRight": "4px"}),
                # CH2
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": tema.CARD,
                        "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch2']}",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH2:", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch2"]}),
                        html.Span("u (mV):", title="Umbral de detección de peaks (mV); también se ajusta arrastrando la línea del gráfico"),
                        dcc.Input(id="umbral_ch2", debounce=True, type="number", step=0.1, style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):", title="Distancia mínima entre peaks consecutivos (µs)"),
                        dcc.Input(id="dist_ch2", debounce=True, type="number", step=0.005, min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):", title="Se ignoran los peaks anteriores a este instante (µs)"),
                        dcc.Input(id="tmin_ch2", debounce=True, type="number", step=0.005, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
                # CH3
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": tema.CARD,
                        "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch3']}",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH3:", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch3"]}),
                        html.Span("u (mV):", title="Umbral de detección de peaks (mV); también se ajusta arrastrando la línea del gráfico"),
                        dcc.Input(id="umbral_ch3", debounce=True, type="number", step=0.1, style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):", title="Distancia mínima entre peaks consecutivos (µs)"),
                        dcc.Input(id="dist_ch3", debounce=True, type="number", step=0.005, min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):", title="Se ignoran los peaks anteriores a este instante (µs)"),
                        dcc.Input(id="tmin_ch3", debounce=True, type="number", step=0.005, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
                # CH4
                html.Div(
                    style={
                        "display": "flex", "alignItems": "center", "gap": "6px",
                        "padding": "4px 8px", "backgroundColor": tema.CARD,
                        "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch4']}",
                        "borderRadius": "4px", "fontSize": "11px",
                    },
                    children=[
                        html.Span("CH4:", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch4"]}),
                        html.Span("u (mV):", title="Umbral de detección de peaks (mV); también se ajusta arrastrando la línea del gráfico"),
                        dcc.Input(id="umbral_ch4", debounce=True, type="number", step=0.1, style={"width": "65px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("Δt (µs):", title="Distancia mínima entre peaks consecutivos (µs)"),
                        dcc.Input(id="dist_ch4", debounce=True, type="number", step=0.005, min=0, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                        html.Span("t_mín (µs):", title="Se ignoran los peaks anteriores a este instante (µs)"),
                        dcc.Input(id="tmin_ch4", debounce=True, type="number", step=0.005, style={"width": "50px", "fontSize": "11px", "padding": "2px"}),
                    ],
                ),
            ],
        ),
        # Barra de estado de Calibración
        html.Div(
            style={
                "display": "flex", "gap": "10px", "alignItems": "center",
                "padding": "8px 12px", "backgroundColor": tema.BG,
                "border": f"1px solid {tema.BORDER}", "borderRadius": "6px",
                "margin": "0 0 12px 0", "flexWrap": "wrap",
            },
            children=[
                html.Span("Retardo instrumental:",
                          style={"fontSize": "11px", "fontWeight": "bold", "color": tema.INK, "marginRight": "4px"}),
                html.Span(
                    id="cal_badge_estado",
                    style=tema.BADGE_WARN,
                    children="Sin calibrar — retardo 0 ns",
                ),
                html.Span(id="cal_badge_ch2", style=tema.badge_canal("ch2"), children="CH2: 0.00 ns"),
                html.Span(id="cal_badge_ch3", style=tema.badge_canal("ch3"), children="CH3: 0.00 ns"),
                html.Span(id="cal_badge_ch4", style=tema.badge_canal("ch4"), children="CH4: 0.00 ns"),
                html.Button("Detalle del retardo", id="btn_toggle_calibracion", n_clicks=0,
                            style={**tema.ESTILO_BOTON_SECONDARY, "marginLeft": "auto", "fontSize": "11px", "padding": "3px 8px"}),
                html.Button("Calibración instrumental", id="btn_ir_a_calibracion", n_clicks=0,
                            style={**tema.ESTILO_BOTON_PRIMARY, "fontSize": "11px", "padding": "3px 8px", "marginLeft": "4px"}),
            ],
        ),
        # Panel desplegable de Calibración (solo lectura)
        html.Div(
            id="panel_calibracion",
            hidden=True,
            style={
                **tema.ESTILO_CARD,
                "margin": "0 0 12px 0",
            },
            children=[
                html.Div(
                    style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "marginBottom": "6px"},
                    children=[
                        html.Span("Retardo instrumental almacenado en metadata.yaml (solo lectura)",
                                  style={"fontSize": "13px", "fontWeight": "bold", "color": tema.INK}),
                    ],
                ),
                html.Div(id="cal_detalle"),
                html.Button("Recargar desde disco", id="btn_recargar_calibracion", n_clicks=0,
                            style={**tema.ESTILO_BOTON_SECONDARY, "marginTop": "10px"}),
            ],
        ),
        # Pestañas Principales
        html.Div(
            style={"marginBottom": "14px"},
            children=[
                dcc.Tabs(id="tabs_principal", value="senales", persistence=True, persistence_type="local", children=[
                    dcc.Tab(label="Análisis", value="senales", **_TAB),
                    dcc.Tab(label="Estadística", value="estadistica", **_TAB),
                    dcc.Tab(label="Metadata", value="metadata", **_TAB),
                    dcc.Tab(label="Calibración", value="calibracion", **_TAB),
                ]),
            ],
        ),
        # Panel 1: Análisis (Señales, Peaks, TRPD, Ventanas, Espectro)
        html.Div(
            id="panel_analisis",
            children=[
                html.Div(
                    className="row",
                    children=[
                        html.Div(className="col card", children=[
                            dcc.Tabs(id="tabs_dominio", value="senales", persistence=True, persistence_type="local", children=[
                                dcc.Tab(label="Señales", value="senales", **_TAB),
                                dcc.Tab(label="Transformada S", value="st", **_TAB),
                            ]),
                            html.Div(id="panel_senales", children=[
                                dcc.Loading(type="circle", delay_show=300, color=tema.ACCENT, children=dcc.Graph(
                                    id="grafico",
                                    # Solo las shapes con editable=True (umbrales) se arrastran;
                                    # rueda = zoom, doble clic = volver a -5..30 µs.
                                    config={"displaylogo": False, "scrollZoom": True,
                                            "doubleClick": "reset",
                                            "edits": {"shapePosition": False}},
                                )),
                            ]),
                            html.Div(id="panel_st_segmento", hidden=True, children=[
                                dcc.Loading(dcc.Graph(id="grafico_st_segmento"), type="circle", delay_show=300, color=tema.ACCENT),
                            ]),
                        ]),
                        html.Div(
                            className="col",
                            children=[
                                html.Div(className="card", children=[
                                    dcc.Tabs(id="tabs_peaks", value="barras", children=[
                                        dcc.Tab(label="Peaks por segmento", value="barras",
                                                children=[dcc.Loading(dcc.Graph(id="grafico_peaks"), type="circle", delay_show=300, color=tema.ACCENT)], **_TAB),
                                    ]),
                                ]),
                                html.Div(className="card", children=[
                                    dcc.Tabs(id="tabs_scatter", value="peaks", children=[
                                        dcc.Tab(label="Patrón TRPD", value="peaks",
                                                children=[
                                                    html.Div(
                                                        style={
                                                            "display": "flex", "alignItems": "center", "gap": "6px",
                                                            "padding": "6px 8px", "backgroundColor": tema.BG,
                                                            "borderBottom": f"1px solid {tema.BORDER}", "marginBottom": "4px",
                                                            "flexWrap": "wrap",
                                                        },
                                                        children=[
                                                            html.Span("Magnitud:", style={"fontSize": "11px", "fontWeight": "bold", "color": tema.INK}),
                                                            dcc.RadioItems(
                                                                id="modo_magnitud_trpd",
                                                                options=[
                                                                    {"label": " Vmax", "value": "vmax"},
                                                                    {"label": " Vpp", "value": "vpp"},
                                                                ],
                                                                value="vmax",
                                                                inline=True,
                                                                style={"fontSize": "11px"},
                                                                inputStyle={"marginRight": "3px"},
                                                                labelStyle={"marginRight": "8px", "cursor": "pointer", "fontWeight": "500"},
                                                            ),
                                                            html.Span("|", style={"color": tema.MUTED_LIGHT, "margin": "0 2px"}),
                                                            html.Button("Quitar selección", id="btn_excluir_seleccion", n_clicks=0, disabled=True,
                                                                        style=tema.ESTILO_BOTON_DANGER),
                                                            html.Button("Deshacer", id="btn_deshacer_exclusion", n_clicks=0, disabled=True,
                                                                        style=tema.ESTILO_BOTON_WARN),
                                                            html.Button("Restaurar todo", id="btn_restaurar_descargas", n_clicks=0, disabled=True,
                                                                        style=tema.ESTILO_BOTON_SECONDARY),
                                                            html.Span("|", style={"color": tema.MUTED_LIGHT, "margin": "0 2px"}),
                                                            html.Span("Disparo:", style={"fontSize": "11px", "fontWeight": "bold", "color": tema.INK}),
                                                            dcc.Input(
                                                                id="input_excluir_disparo",
                                                                type="text",
                                                                placeholder="ej. 5 o 2,4",
                                                                style={"width": "75px", "fontSize": "11px", "padding": "3px 5px",
                                                                       "textAlign": "center", "borderRadius": "4px", "border": f"1px solid {tema.BORDER}"}
                                                            ),
                                                            html.Button("Excluir", id="btn_excluir_disparo", n_clicks=0,
                                                                        style=tema.ESTILO_BOTON_DANGER),
                                                            html.Span(id="badge_filtro_descargas",
                                                                      style={"fontSize": "11px", "color": tema.MUTED, "fontWeight": "600", "marginLeft": "auto"}),
                                                        ],
                                                    ),
                                                    dcc.Loading(dcc.Graph(id="grafico_scatter"), type="circle", delay_show=300, color=tema.ACCENT),
                                                ], **_TAB),
                                    ]),
                                ]),
                            ],
                        ),
                    ],
                ),
                html.Div(
                    className="row",
                    children=[
                        html.Div(className="col card", children=[dcc.Loading(dcc.Graph(id="grafico_ventanas"), type="circle", delay_show=300, color=tema.ACCENT)]),
                        html.Div(className="col card", children=[
                            dcc.Tabs(id="tabs_espectro", value="fft", persistence=True, persistence_type="local", children=[
                                dcc.Tab(label="FFT", value="fft",
                                        children=[dcc.Loading(dcc.Graph(id="grafico_fft"), type="circle", delay_show=300, color=tema.ACCENT)], **_TAB),
                                dcc.Tab(label="Transformada S", value="st",
                                        children=[dcc.Loading(dcc.Graph(id="grafico_st_ventana"), type="circle", delay_show=300, color=tema.ACCENT)], **_TAB),
                            ]),
                        ]),
                    ],
                ),
            ],
        ),
        # Panel 2: Estadística (Tabla de densidad amplia)
        html.Div(
            id="panel_estadistica",
            hidden=True,
            children=[
                html.Div(
                    className="card",
                    style={"padding": "14px 16px"},
                    children=[
                        html.Div(
                            style={
                                "display": "flex", "justifyContent": "space-between",
                                "alignItems": "center", "marginBottom": "12px",
                                "flexWrap": "wrap", "gap": "10px",
                                "borderBottom": f"1px solid {tema.BORDER}", "paddingBottom": "10px",
                            },
                            children=[
                                html.Div([
                                    html.H3("Densidad y Estadística de Eventos PD", style={"margin": "0 0 4px 0", "fontSize": "16px", "color": tema.INK}),
                                    html.Span("Resumen estadístico por sensor y medición (distribución de peaks, amplitudes y tiempos de arribo).", style={"fontSize": "13px", "color": tema.MUTED}),
                                ]),
                                html.Div(
                                    style={"display": "flex", "gap": "8px", "alignItems": "center"},
                                    children=[
                                        html.Button("Calcular todos los sensores (CH2..CH4)", id="btn_calc_todos_sensores",
                                                    style=tema.ESTILO_BOTON_PRIMARY),
                                        html.Button("Limpiar tabla", id="btn_limpiar_densidad",
                                                    style=tema.ESTILO_BOTON_SECONDARY),
                                        html.Button("Exportar CSV", id="btn_exportar_densidad",
                                                    style=tema.ESTILO_BOTON_SECONDARY),
                                    ],
                                ),
                            ],
                        ),
                        dcc.Loading(type="circle", delay_show=300, color=tema.ACCENT, children=html.Div(
                            id="tabla_densidad", className="tabla-paper-contenedor",
                            children=construir_tabla_paper([]))),
                        dcc.Download(id="descarga_densidad"),
                    ],
                ),
            ],
        ),
        # Panel 3: Metadata
        html.Div(
            id="panel_metadata",
            hidden=True,
            children=[
                html.Div(
                    className="card",
                    style={"padding": "14px 16px"},
                    children=[
                        html.Div(
                            style={
                                "display": "flex", "justifyContent": "space-between",
                                "alignItems": "center", "marginBottom": "12px", "flexWrap": "wrap",
                                "gap": "8px", "borderBottom": f"1px solid {tema.BORDER}", "paddingBottom": "10px",
                            },
                            children=[
                                html.Div([
                                    html.H3(id="meta_titulo", style={"margin": "0 0 4px 0", "fontSize": "16px", "color": tema.INK}),
                                    html.Span(id="meta_badge_estado", style=tema.BADGE_NEUTRAL),
                                ]),
                                html.Div(style={"display": "flex", "gap": "6px", "alignItems": "center"}, children=[
                                    html.Button("Guardar metadata.yaml", id="btn_guardar_metadata",
                                                style=tema.ESTILO_BOTON_SUCCESS),
                                ]),
                            ],
                        ),
                        html.Div(id="meta_msg_feedback", style={"marginBottom": "8px", "fontSize": "12px"}),
                        html.Div(
                            style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(240px, 1fr))", "gap": "12px", "marginBottom": "14px"},
                            children=[
                                html.Div(className="card", style={"padding": "10px 12px"}, children=[
                                    html.H4("Experimento", style={"margin": "0 0 6px 0", "fontSize": "13px", "color": tema.INK, "borderBottom": f"1px solid {tema.BORDER_SUBTLE}", "paddingBottom": "4px"}),
                                    dcc.Loading(html.Div(id="meta_card_experimento", style={"fontSize": "12px", "lineHeight": "1.5"}), type="circle", delay_show=300, color=tema.ACCENT),
                                ]),
                                html.Div(className="card", style={"padding": "10px 12px"}, children=[
                                    html.H4("Circuito de Impulso (LI)", style={"margin": "0 0 6px 0", "fontSize": "13px", "color": tema.INK, "borderBottom": f"1px solid {tema.BORDER_SUBTLE}", "paddingBottom": "4px"}),
                                    dcc.Loading(html.Div(id="meta_card_circuito", style={"fontSize": "12px", "lineHeight": "1.5"}), type="circle", delay_show=300, color=tema.ACCENT),
                                ]),
                                html.Div(className="card", style={"padding": "10px 12px"}, children=[
                                    html.H4("Probeta / Espécimen", style={"margin": "0 0 6px 0", "fontSize": "13px", "color": tema.INK, "borderBottom": f"1px solid {tema.BORDER_SUBTLE}", "paddingBottom": "4px"}),
                                    dcc.Loading(html.Div(id="meta_card_probeta", style={"fontSize": "12px", "lineHeight": "1.5"}), type="circle", delay_show=300, color=tema.ACCENT),
                                    html.Div(style={"display": "flex", "gap": "6px", "alignItems": "center", "marginTop": "8px", "fontSize": "12px"}, children=[
                                        dcc.Input(id="meta_input_diametros", type="text",
                                                  placeholder="ej. 2mm-2mm-3mm",
                                                  style={"flex": "1", "minWidth": "0", "fontSize": "12px", "padding": "4px 6px", "border": f"1px solid {tema.BORDER}", "borderRadius": "4px"}),
                                        html.Button("Guardar diámetros", id="btn_guardar_diametros",
                                                    title="Guarda probeta.diametros en metadata.yaml",
                                                    style=tema.ESTILO_BOTON_SUCCESS),
                                    ]),
                                ]),
                                html.Div(className="card", style={"padding": "10px 12px"}, children=[
                                    html.H4("Osciloscopio y Adquisición", style={"margin": "0 0 6px 0", "fontSize": "13px", "color": tema.INK, "borderBottom": f"1px solid {tema.BORDER_SUBTLE}", "paddingBottom": "4px"}),
                                    dcc.Loading(html.Div(id="meta_card_osc", style={"fontSize": "12px", "lineHeight": "1.5"}), type="circle", delay_show=300, color=tema.ACCENT),
                                ]),
                            ],
                        ),
                        html.Div(className="card", style={"padding": "10px 12px", "marginBottom": "14px"}, children=[
                            html.H4("Asignación de Sensores y Canales de Adquisición", style={"margin": "0 0 8px 0", "fontSize": "13px", "color": tema.INK}),
                            dcc.Loading(html.Div(id="meta_tabla_canales"), type="circle", delay_show=300, color=tema.ACCENT),
                        ]),
                        html.Details([
                            html.Summary("Ver / Editar YAML crudo", style={"cursor": "pointer", "fontSize": "12px", "fontWeight": "600", "color": tema.MUTED, "padding": "4px 0"}),
                            html.Div(style={"marginTop": "8px"}, children=[
                                dcc.Textarea(
                                    id="meta_yaml_text",
                                    style={"width": "100%", "height": "240px", "fontFamily": "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
                                           "fontSize": "12px", "padding": "8px", "border": f"1px solid {tema.BORDER}",
                                           "borderRadius": "4px", "boxSizing": "border-box"},
                                ),
                                html.Div(style={"marginTop": "6px", "textAlign": "right"}, children=[
                                    html.Button("Guardar cambios del texto YAML", id="btn_guardar_yaml_texto",
                                                style=tema.ESTILO_BOTON_PRIMARY),
                                ]),
                            ]),
                        ]),
                    ],
                ),
            ],
        ),
        # Panel 4: Calibración integrada
        html.Div(
            id="panel_calibracion_embed",
            hidden=True,
            children=[
                html.Div(
                    className="card",
                    style={"padding": "14px 16px"},
                    children=[
                        html.Div(
                            style={
                                "display": "flex", "justifyContent": "space-between",
                                "alignItems": "center", "marginBottom": "12px",
                                "flexWrap": "wrap", "gap": "10px",
                                "borderBottom": f"1px solid {tema.BORDER}", "paddingBottom": "10px",
                            },
                            children=[
                                html.Div([
                                    html.H3("Calibración de Retardo Instrumental y Conformidad IEC 60060-1", style={"margin": "0 0 4px 0", "fontSize": "16px", "color": tema.INK}),
                                    html.Span("calibrar_app integrada (puerto 8052). Si la vista no responde, ejecute run_calibrar.cmd.", style={"fontSize": "13px", "color": tema.MUTED}),
                                ]),
                                html.Div([
                                    html.A("Abrir en ventana aparte", href="http://127.0.0.1:8052", target="_blank",
                                           style={**tema.ESTILO_BOTON_SECONDARY, "textDecoration": "none", "display": "inline-block"}),
                                ]),
                            ],
                        ),
                        html.Iframe(
                            id="iframe_calibracion",
                            src="",
                            style={
                                "width": "100%",
                                "height": "calc(100vh - 220px)",
                                "minHeight": "650px",
                                "border": f"1px solid {tema.BORDER}",
                                "borderRadius": "4px",
                                "backgroundColor": tema.CARD,
                            },
                        ),
                    ],
                ),
            ],
        ),
    ],
)


@app.callback(
    Output("explorador_panel", "hidden"),
    Output("explorador_ruta_actual", "data"),
    Output("carpeta", "value"),
    Output("carpeta", "options"),
    Input("btn_examinar", "n_clicks"),
    Input("explorador_cancelar", "n_clicks"),
    Input("explorador_confirmar", "n_clicks"),
    State("explorador_ruta_actual", "data"),
    State("carpeta", "value"),
    State("carpeta", "options"),
    prevent_initial_call=True,
)
def toggle_explorador(n_abrir, n_cancelar, n_confirmar, ruta_actual, carpeta_val, opciones):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if trig == "btn_examinar":
        inicio = rutas.dir_medicion(carpeta_val) if carpeta_val else None
        if not inicio:
            inicio = ruta_actual if ruta_actual else rutas.ruta_inicial()
        return False, inicio, no_update, no_update
    if trig == "explorador_cancelar":
        return True, no_update, no_update, no_update
    if trig == "explorador_confirmar":
        nuevas = rutas.mediciones_en(ruta_actual)
        if not nuevas:
            return no_update, no_update, no_update, no_update
        # Archivos nuevos o reemplazados en disco: olvidar rutas/handles cacheados
        datos_h5.limpiar_caches()
        opts = list(opciones or [])
        for m in nuevas:
            if not any(o.get("value") == m for o in opts):
                opts.append({"label": rutas.etiqueta(m), "value": m, "title": m})
        return True, no_update, nuevas[0], opts
    return no_update, no_update, no_update, no_update


@app.callback(
    Output("explorador_ruta_actual", "data", allow_duplicate=True),
    Input("explorador_subir", "n_clicks"),
    Input({"type": "explorador_ir", "ruta": ALL}, "n_clicks"),
    State("explorador_ruta_actual", "data"),
    prevent_initial_call=True,
)
def navegar_explorador(n_subir, n_subcarpetas, ruta_actual):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if trig == "explorador_subir":
        return rutas.padre(ruta_actual)
    if isinstance(trig, dict) and trig.get("type") == "explorador_ir":
        return trig["ruta"]
    return no_update


@app.callback(
    Output("explorador_listado", "children"),
    Output("explorador_ruta_label", "children"),
    Output("explorador_confirmar", "disabled"),
    Input("explorador_ruta_actual", "data"),
)
def renderizar_explorador(ruta_actual):
    if ruta_actual != rutas.EQUIPO and (not ruta_actual or not os.path.isdir(ruta_actual)):
        ruta_actual = rutas.EQUIPO
    filas = []
    for nombre, p, tiene_h5 in listar_subcarpetas(ruta_actual):
        filas.append(html.Button(
            f"{'[H5] ' if tiene_h5 else ''}{nombre}",
            id={"type": "explorador_ir", "ruta": p},
            n_clicks=0,
            style={
                "display": "block",
                "width": "100%",
                "textAlign": "left",
                "backgroundColor": "transparent",
                "border": "none",
                "borderBottom": f"1px solid {tema.BORDER_SUBTLE}",
                "padding": "6px 8px",
                "cursor": "pointer",
                "fontSize": "13px",
                "color": tema.INK,
            },
        ))
    if not filas:
        filas = [html.Div("(No hay subcarpetas)", style={"color": tema.MUTED_LIGHT, "fontStyle": "italic", "padding": "6px 8px"})]
    if ruta_actual == rutas.EQUIPO:
        return filas, "Este equipo", True
    return filas, ruta_actual, not rutas.tiene_h5(ruta_actual)


@app.callback(
    Output("ultima_carpeta", "data"),
    Input("carpeta", "value"),
    prevent_initial_call=True,
)
def recordar_carpeta(carpeta):
    """Guarda en el navegador la última medición abierta."""
    return carpeta if carpeta else no_update


@app.callback(
    Output("carpeta", "value", allow_duplicate=True),
    Output("carpeta", "options", allow_duplicate=True),
    Output("explorador_panel", "hidden", allow_duplicate=True),
    Input("ultima_carpeta", "modified_timestamp"),
    State("ultima_carpeta", "data"),
    State("carpeta", "value"),
    State("carpeta", "options"),
    prevent_initial_call="initial_duplicate",
)
def restaurar_carpeta(_ts, ultima, actual, opciones):
    """Al abrir la app, vuelve a la última medición usada si sigue en disco
    (y entonces no hace falta abrir el explorador)."""
    if actual or not ultima or not canales_presentes(ultima):
        return no_update, no_update, no_update
    opts = list(opciones or [])
    if not any(o.get("value") == ultima for o in opts):
        opts.append({"label": rutas.etiqueta(ultima), "value": ultima, "title": ultima})
    return ultima, opts, True


@app.callback(
    Output("segmento", "value"),
    Output("segmento", "max"),
    Output("segmento_total", "children"),
    Input("carpeta", "value"),
)
def actualizar_segmentos(carpeta):
    if not carpeta:
        return 1, 1, "/ 0"
    n = max(1, n_segmentos(carpeta))
    return 1, n, f"/ {n}"


@app.callback(
    Output("segmento", "value", allow_duplicate=True),
    Input("segmento_prev", "n_clicks"),
    Input("segmento_next", "n_clicks"),
    Input("segmento", "value"),
    State("segmento", "max"),
    prevent_initial_call=True,
)
def mover_segmento(n_prev, n_next, valor, seg_max):
    """Flechas anterior/siguiente y saneo del número tecleado, acotado a [1, max]."""
    n_max = int(seg_max) if seg_max else 1
    try:
        actual = int(valor)
    except (TypeError, ValueError):
        actual = 1
    trig = ctx.triggered_id
    if trig == "segmento_prev":
        return max(1, actual - 1)
    if trig == "segmento_next":
        return min(n_max, actual + 1)
    nuevo = max(1, min(n_max, actual))
    return nuevo if nuevo != valor else no_update


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
    Input("switch_filtros", "value"),
    prevent_initial_call=False,
)
def sincronizar_parametros_sensores(carpeta, relayout, sw_filtros=("on",)):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None

    if trig == "grafico":
        # Zoom/pan: solo interesa el arrastre de una línea de umbral (shapes[k].y0)
        if not relayout or not carpeta or not any(k.startswith("shapes[") for k in relayout):
            return (no_update,) * 9
        cambios = umbrales_desde_relayout(relayout, canales_presentes(carpeta))
        if not cambios:
            return (no_update,) * 9
        u2 = round(cambios["ch2"], 4) if "ch2" in cambios else no_update
        u3 = round(cambios["ch3"], 4) if "ch3" in cambios else no_update
        u4 = round(cambios["ch4"], 4) if "ch4" in cambios else no_update
        return u2, no_update, no_update, u3, no_update, no_update, u4, no_update, no_update

    if not carpeta:
        return (no_update,) * 9
    cfg = config_sensores_defecto(carpeta, filtrado=_filtrado(sw_filtros))
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
    # Inputs (no State): editar umbral, Δt o t_mín redibuja la línea de umbral y
    # las cruces de peaks con la misma configuración que usará "Calcular peaks".
    Input("umbral_ch2", "value"),
    Input("dist_ch2", "value"),
    Input("tmin_ch2", "value"),
    Input("umbral_ch3", "value"),
    Input("dist_ch3", "value"),
    Input("tmin_ch3", "value"),
    Input("umbral_ch4", "value"),
    Input("dist_ch4", "value"),
    Input("tmin_ch4", "value"),
    Input("switch_filtros", "value"),
    State("rango_x", "data"),
)
def actualizar(carpeta, seg, canal, p, u2, d2, t2, u3, d3, t3, u4, d4, t4, sw_filtros=("on",),
               rango=None):
    if not carpeta or not seg:
        return _fig_vacia("Seleccione una medición con el botón 📁 para ver sus señales.", altura=850)
    filtrado = _filtrado(sw_filtros)
    cfg_sensores = _cfg_sensores(u2, d2, t2, u3, d3, t3, u4, d4, t4)
    cap = None
    if (p and p["canal"] == canal and p["carpeta"] == carpeta
            and p.get("filtrado", True) == filtrado
            and _captura_vigente(p, cfg_sensores.get(canal, {}))):
        cap = capturar(carpeta, canal, p["umbral"], p["dist"], p["tmin"], filtrado=filtrado)
    try:
        return figura(carpeta, int(seg), canal, cfg_sensores=cfg_sensores, cap=cap,
                      filtrado=filtrado, rango_x=_rango_vigente(rango, carpeta, canal))
    except Exception as e:
        return _fig_error("No se pudo dibujar las señales", e, altura=850)


def _rango_desde_relayout(relayout):
    """(x0, x1) en µs a partir de un relayoutData del gráfico de señales (ejes x
    compartidos: vale cualquier xaxis*), 'completo' si se pidió autorange, o None
    si el evento no cambia el eje x (pan vertical, arrastre de umbral, autosize)."""
    if not relayout:
        return None
    for k, val in relayout.items():
        if k.startswith("xaxis") and k.endswith(".autorange") and val:
            return "completo"
        if k.startswith("xaxis") and k.endswith(".range") and isinstance(val, (list, tuple)) and len(val) == 2:
            return float(val[0]), float(val[1])
    x0 = next((v for k, v in relayout.items() if k.startswith("xaxis") and k.endswith(".range[0]")), None)
    x1 = next((v for k, v in relayout.items() if k.startswith("xaxis") and k.endswith(".range[1]")), None)
    if x0 is not None and x1 is not None:
        return float(x0), float(x1)
    return None


@app.callback(
    Output("grafico", "figure", allow_duplicate=True),
    Output("rango_x", "data"),
    Input("grafico", "relayoutData"),
    State("carpeta", "value"),
    State("segmento", "value"),
    State("canal", "value"),
    State("switch_filtros", "value"),
    prevent_initial_call=True,
)
def redecimar_zoom(relayout, carpeta, seg, canal, sw_filtros=("on",)):
    """Zoom/pan en el gráfico de señales: reenvía solo las trazas de señal con el
    tramo visible (crudo si dura <= SIN_DIEZMADO_US, diezmado si no). Es un Patch:
    no se reconstruye la figura ni se pierden zoom ni umbrales."""
    rango = _rango_desde_relayout(relayout)
    if rango is None or not carpeta or not seg:
        return no_update, no_update
    filtrado = _filtrado(sw_filtros)
    x0, x1 = (None, None) if rango == "completo" else rango
    pat = Patch()
    for i, c in enumerate(_canales_senal(carpeta)):
        t, v = cargar_segmento(carpeta, c, int(seg), filtrado=filtrado)
        td, vd = tramo_visible(t, v, x0, x1)
        pat["data"][i]["x"] = _arreglo_tipado(td)
        pat["data"][i]["y"] = _arreglo_tipado(vd)
    guardado = None if rango == "completo" else {"carpeta": carpeta, "canal": canal, "x0": x0, "x1": x1}
    return pat, guardado


def _cfg_sensores(u2, d2, t2, u3, d3, t3, u4, d4, t4, carpeta=None, filtrado=True):
    """Configuración de detección de los 3 triggers desde los campos de la UI.
    Campo vacío: Δt = DIST_DEFECTO_US, t_mín = TMIN_DEFECTO_US y umbral None (o,
    si se da `carpeta`, el umbral por defecto de esa medición)."""
    def canal(ch, u, d, t):
        if u is not None:
            u = float(u)
        elif carpeta:
            u = umbral_defecto(carpeta, ch, filtrado=filtrado)
        return {"umbral": u,
                "dist": float(d) if d is not None else DIST_DEFECTO_US,
                "tmin": float(t) if t is not None else TMIN_DEFECTO_US}
    return {"ch2": canal("ch2", u2, d2, t2), "ch3": canal("ch3", u3, d3, t3),
            "ch4": canal("ch4", u4, d4, t4)}


def _rango_vigente(rango, carpeta, canal):
    """(x0, x1) del zoom guardado si corresponde a la misma medición y canal."""
    if rango and rango.get("carpeta") == carpeta and rango.get("canal") == canal:
        return rango.get("x0"), rango.get("x1")
    return None


def _filtrado(valor):
    """Estado del interruptor 'Filtros del paper' (dcc.Checklist)."""
    return "on" in (valor or [])


def _captura_vigente(p, cfg_act):
    """True si el snapshot de "Calcular peaks" coincide con la configuración
    actual del canal activo. Si el usuario editó umbral, Δt o t_mín después de
    capturar, las cruces se muestran en vista previa con los valores nuevos."""
    for clave in ("umbral", "dist", "tmin"):
        actual = cfg_act.get(clave)
        if actual is None:
            continue  # umbral vacío: la captura usó el valor por defecto
        if p.get(clave) is None or abs(float(p[clave]) - float(actual)) > 1e-9:
            return False
    return True


@app.callback(
    Output("panel_analisis", "hidden"),
    Output("panel_estadistica", "hidden"),
    Output("panel_metadata", "hidden"),
    Output("panel_calibracion_embed", "hidden"),
    Input("tabs_principal", "value"),
)
def alternar_panel_principal(tab):
    """Alterna los paneles principales (Análisis, Estadística, Metadata, Calibración)
    sin desmontar componentes para preservar estado y zooms."""
    return (
        tab != "senales",
        tab != "estadistica",
        tab != "metadata",
        tab != "calibracion",
    )


@app.callback(
    Output("panel_senales", "hidden"),
    Output("panel_st_segmento", "hidden"),
    Input("tabs_dominio", "value"),
)
def alternar_panel_dominio(tab_dom):
    """Alterna entre la vista temporal de Señales y la Transformada S del segmento."""
    return tab_dom != "senales", tab_dom != "st"


@app.callback(
    Output("grafico_st_segmento", "figure"),
    Input("tabs_principal", "value"),
    Input("tabs_dominio", "value"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
    Input("st_fmax", "value"),
    Input("switch_filtros", "value"),
)
def actualizar_st_segmento(tab_princ, tab_dom, carpeta, seg, fmax, sw_filtros=("on",)):
    """Transformada S del segmento completo (4 filas ch1..ch4). Solo se
    calcula si la pestaña de análisis y la subpestaña ST están activas."""
    if tab_princ != "senales" or tab_dom != "st" or not carpeta or not seg:
        return no_update
    try:
        return figura_st_segmento(carpeta, int(seg), fmax or ST_FMAX_MHZ, filtrado=_filtrado(sw_filtros))
    except Exception as e:
        return _fig_error("No se pudo calcular la Transformada S", e, altura=850)


@app.callback(
    Output("iframe_calibracion", "src"),
    Input("tabs_principal", "value"),
    State("iframe_calibracion", "src"),
    Input("carpeta", "value"),   # también al restaurar la medición con la pestaña ya abierta
)
def diferir_carga_iframe_calibracion(tab, src_actual, carpeta=None):
    """Carga diferida del iframe de calibración: solo al visitar la pestaña, ya
    con la medición actual (?carpeta=...) y en modo embebido. Se recarga solo si
    la medición cambió desde la última visita."""
    if tab != "calibracion":
        return no_update
    url = URL_CALIBRAR
    if carpeta:
        url += "/?" + urllib.parse.urlencode({"embebido": 1, "carpeta": carpeta})
    return url if url != src_actual else no_update


@app.callback(
    Output("tabs_principal", "value"),
    Input("btn_ir_a_calibracion", "n_clicks"),
    prevent_initial_call=True,
)
def ir_a_pestana_calibracion(n_clicks):
    """Navega a la pestaña de Calibración al pulsar el botón en la barra superior."""
    if n_clicks:
        return "calibracion"
    return no_update


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
    Input("switch_filtros", "value"),
    Input("carpeta", "value"),
    Input("canal", "value"),
    running=[(Output("btn", "disabled"), True, False)],
)
def fijar_captura(n_clicks, carpeta, canal, u2, d2, t2, u3, d3, t3, u4, d4, t4, sw_filtros=("on",),
                  _carpeta_in=None, _canal_in=None):
    """Fija el snapshot de parámetros al pulsar el botón. Todos los análisis
    derivan de aquí, garantizando que scatter y ventanas usan el mismo conjunto.
    Al cambiar el interruptor de filtros (con una captura ya hecha) se rehace la
    captura con los parámetros por defecto de la nueva señal, los mismos que
    sincronizar_parametros_sensores escribe en los campos."""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if trig in ("carpeta", "canal"):
        # Otra medición u otro canal: los resultados anteriores ya no corresponden.
        return None
    if not n_clicks or not carpeta:
        return no_update
    filtrado = _filtrado(sw_filtros)
    if trig == "switch_filtros":
        cfg_sensores = config_sensores_defecto(carpeta, filtrado=filtrado)
        cfg_act = cfg_sensores.get(canal, cfg_sensores["ch4"])
        return {"carpeta": carpeta, "canal": canal, "umbral": cfg_act["umbral"],
                "dist": cfg_act["dist"], "tmin": cfg_act["tmin"],
                "cfg_sensores": cfg_sensores, "filtrado": filtrado}
    cfg_sensores = _cfg_sensores(u2, d2, t2, u3, d3, t3, u4, d4, t4, carpeta=carpeta, filtrado=filtrado)
    cfg_act = cfg_sensores.get(canal, cfg_sensores["ch4"])
    return {
        "carpeta": carpeta,
        "canal": canal,
        "umbral": cfg_act["umbral"],
        "dist": cfg_act["dist"],
        "tmin": cfg_act["tmin"],
        "cfg_sensores": cfg_sensores,
        "filtrado": filtrado,
    }


@app.callback(
    Output("grafico_peaks", "figure"),
    Input("captura_params", "data"),
    Input("descargas_excluidas", "data"),
)
def calcular_peaks(p, excl_dict):
    if not p:
        return _fig_vacia("Pulse «Calcular peaks» para analizar las descargas de esta medición.", altura=415)
    key = f"{p['carpeta']}|{p['canal']}"
    excl = _obtener_excluidos(excl_dict, key)
    segs, cuentas = contar_peaks(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], excluidos=excl,
                                 filtrado=p.get("filtrado", True))
    if not segs:
        return _fig_vacia(f"{p['canal'].upper()} no disponible en esta medición", altura=415)
    try:
        return figura_peaks(segs, cuentas, p["umbral"], p["canal"])
    except Exception as e:
        return _fig_error("No se pudo dibujar el conteo de peaks", e, altura=415)


@app.callback(
    Output("panel_calibracion", "hidden"),
    Input("btn_toggle_calibracion", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_panel_calibracion(n):
    return (n % 2 == 0)


@app.callback(
    Output("calibracion_store", "data"),
    Input("carpeta", "value"),
    Input("btn_recargar_calibracion", "n_clicks"),
    Input("tabs_principal", "value"),
    State("calibracion_store", "data"),
)
def cargar_calibracion_store(carpeta, _n, _tab=None, actual=None):
    """Único poblador de `calibracion_store`: lee `calibracion_retardo` de
    metadata.yaml (ns -> µs, normalizado al ancla t10). Al cambiar de pestaña se
    relee (lo guardado en la pestaña Calibración aparece sin pulsar «Recargar»),
    pero solo se propaga si cambió."""
    if not carpeta:
        return no_update
    nuevo = calibracion_desde_metadata(carpeta)
    if actual is not None and nuevo == actual:
        return no_update
    return nuevo


@app.callback(
    Output("cal_detalle", "children"),
    Input("calibracion_store", "data"),
)
def mostrar_detalle_calibracion(cal):
    """Renderiza el resumen de solo lectura de la calibración almacenada en metadata.yaml."""
    if not cal or not cal.get("calibrado"):
        carpeta = (cal or {}).get("carpeta", "")
        aviso = (cal or {}).get("aviso")
        msg_extra = f" ({aviso})" if aviso else ""
        return html.Div(
            f"Sin bloque calibracion_retardo en metadata.yaml para {carpeta}{msg_extra} — retardo 0 ns. "
            f"Calcular en calibrar_app (puerto 8052).",
            style={"color": tema.MUTED, "fontSize": "12px", "padding": "8px 0"}
        )

    fuente = cal.get("fuente") or "N/D"
    fecha = cal.get("fecha") or "N/D"
    ref = cal.get("referencia_impulso") or "t10"
    delta_us = cal.get("delta_t10_O1_us")

    meta_bloque = obtener_metadata(cal.get("carpeta", "")).get("calibracion_retardo", {})
    criterio = meta_bloque.get("criterio", "primer_cruce_umbral")

    cabecera_partes = [
        f"Fuente: {fuente}",
        f"Fecha: {fecha}",
        f"Criterio: {criterio}",
        f"Referencia: {ref}",
    ]
    if delta_us is not None:
        cabecera_partes.append(f"Ancla t10 − O1 = {delta_us * 1e3:.2f} ns (restado a retardos O1)")

    sensores_nombres = {
        "ch2": "HFCT",
        "ch3": "Antena 1",
        "ch4": "Antena 2",
    }

    filas = []
    chs = cal.get("canales", {})
    for ch in TRIGGERS:
        info = chs.get(ch, {})
        b_ch = meta_bloque.get(ch, {}) if isinstance(meta_bloque, dict) else {}
        t_lag_ns = f"{info.get('t_lag_us', 0.0) * 1e3:.2f}" if info.get("calibrado") else "0.00"
        sigma_ns = f"{info.get('sigma_us', 0.0) * 1e3:.2f}" if (info.get("sigma_us") is not None) else "—"
        nv = b_ch.get("n_valid", "—")
        nt = b_ch.get("n_total", "—")
        val_str = f"{nv}/{nt}" if nv != "—" else "—"
        u_str = f"{b_ch.get('umbral_mv', '—')}"
        dt_str = f"{b_ch.get('distancia_us', '—')}"
        tm_str = f"{b_ch.get('tmin_us', '—')}"

        filas.append(html.Tr([
            html.Td(ch.upper(), style={"fontWeight": "600", "padding": "4px 8px"}),
            html.Td(b_ch.get("sensor") or sensores_nombres.get(ch, ch.upper()), style={"padding": "4px 8px"}),
            html.Td(t_lag_ns, style={"fontWeight": "700", "color": tema.ACCENT, "padding": "4px 8px"}),
            html.Td(sigma_ns, style={"padding": "4px 8px"}),
            html.Td(val_str, style={"padding": "4px 8px"}),
            html.Td(u_str, style={"padding": "4px 8px"}),
            html.Td(dt_str, style={"padding": "4px 8px"}),
            html.Td(tm_str, style={"padding": "4px 8px"}),
        ]))

    th_style = {"borderBottom": f"2px solid {tema.BORDER}", "padding": "4px 8px"}
    tabla = html.Table(
        style={"width": "100%", "fontSize": "11px", "borderCollapse": "collapse", "textAlign": "left", "marginTop": "8px"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style=th_style),
                html.Th("Sensor", style=th_style),
                html.Th("t̄_lag [ns]", style=th_style),
                html.Th("σ [ns]", style=th_style),
                html.Th("Válidos", style=th_style),
                html.Th("u_cal [mV]", style=th_style),
                html.Th("Δt [µs]", style=th_style),
                html.Th("t_mín [µs]", style=th_style),
            ])),
            html.Tbody(filas),
        ],
    )

    return html.Div([
        html.Div(" · ".join(cabecera_partes), style={"fontSize": "11px", "color": tema.MUTED, "fontWeight": "600", "marginBottom": "6px"}),
        tabla,
    ])




@app.callback(
    Output("cal_badge_estado", "children"),
    Output("cal_badge_estado", "style"),
    Output("cal_badge_ch2", "children"),
    Output("cal_badge_ch3", "children"),
    Output("cal_badge_ch4", "children"),
    Input("calibracion_store", "data"),
)
def badges_calibracion(cal):
    if not cal or not cal.get("calibrado"):
        st_txt = "Sin calibrar — retardo 0 ns"
        return st_txt, tema.BADGE_WARN, "CH2: 0.00 ns", "CH3: 0.00 ns", "CH4: 0.00 ns"

    fuente = cal.get("fuente") or "actual"
    fecha = cal.get("fecha") or ""
    st_txt = f"Calibrado · {fuente}" + (f" · {fecha}" if fecha else "")

    chs = cal.get("canales", {})
    def fmt_ch(ch):
        info = chs.get(ch, {})
        if info.get("calibrado"):
            ns = info.get("t_lag_us", 0.0) * 1e3
            return f"{ch.upper()}: {ns:.2f} ns"
        return f"{ch.upper()}: 0 ns (sin cal.)"

    return st_txt, tema.BADGE_OK, fmt_ch("ch2"), fmt_ch("ch3"), fmt_ch("ch4")


@app.callback(
    Output("densidad_store", "data"),
    Input("captura_params", "data"),
    Input("btn_calc_todos_sensores", "n_clicks"),
    Input("btn_limpiar_densidad", "n_clicks"),
    Input("descargas_excluidas", "data"),
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
    Input("tabs_principal", "value"),
    prevent_initial_call=True,
    running=[(Output("btn_calc_todos_sensores", "disabled"), True, False)],
)
def actualizar_densidad_store(p, n_todos, n_limpiar, excl_dict, data_actual,
                              u2, d2, t2, u3, d3, t3, u4, d4, t4, cal_store, tab="estadistica"):
    """Filas de la tabla de Estadística. La fila de la captura vigente solo se
    calcula con la pestaña Estadística visible (al entrar en ella se pone al día)."""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if trig == "btn_limpiar_densidad":
        return []
    if tab != "estadistica" and trig in ("captura_params", "descargas_excluidas", "tabs_principal"):
        return no_update

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
    excl_dict = excl_dict or {}

    if trig == "btn_calc_todos_sensores" and p:
        carpeta = p["carpeta"]
        cfg_p = p.get("cfg_sensores", {})
        for ch in ["ch2", "ch3", "ch4"]:
            if ch in canales_presentes(carpeta):
                cfg_ch = cfg_p.get(ch) or cfg_inputs.get(ch, {})
                u_ch = cfg_ch.get("umbral")
                if u_ch is None:
                    u_ch = umbral_defecto(carpeta, ch, filtrado=p.get("filtrado", True))
                dist_ch = cfg_ch.get("dist") or DIST_DEFECTO_US
                tmin_ch = cfg_ch.get("tmin") if cfg_ch.get("tmin") is not None else TMIN_DEFECTO_US
                t_lag = lag_canal(cal_store, carpeta, ch)
                excl_ch = _obtener_excluidos(excl_dict, f"{carpeta}|{ch}")
                f = calcular_fila_densidad(carpeta, ch, float(u_ch), float(dist_ch), float(tmin_ch),
                                           t_lag_us=t_lag, excluidos=excl_ch, filtrado=p.get("filtrado", True))
                _upsert(f)
        return filas

    if trig in ("captura_params", "descargas_excluidas", "tabs_principal") and p:
        t_lag = lag_canal(cal_store, p["carpeta"], p["canal"])
        excl_ch = _obtener_excluidos(excl_dict, f"{p['carpeta']}|{p['canal']}")
        f = calcular_fila_densidad(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"],
                                   t_lag_us=t_lag, excluidos=excl_ch, filtrado=p.get("filtrado", True))
        _upsert(f)
        return filas

    return filas


@app.callback(
    Output("tabla_densidad", "children"),
    Input("densidad_store", "data"),
)
def sincronizar_tabla_densidad(data):
    return construir_tabla_paper(data or [])


@app.callback(
    Output("descarga_densidad", "data"),
    Input("btn_exportar_densidad", "n_clicks"),
    State("densidad_store", "data"),
    prevent_initial_call=True,
)
def exportar_densidad(n, data):
    if not n or not data:
        return no_update
    return dcc.send_string(csv_tabla_densidad(data), "tabla_densidad.csv")


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
    Output("meta_input_diametros", "value"),
    Input("carpeta", "value"),
    Input("btn_guardar_metadata", "n_clicks"),
    Input("btn_guardar_yaml_texto", "n_clicks"),
    Input("btn_guardar_diametros", "n_clicks"),
    Input("calibracion_store", "data"),
    State("meta_yaml_text", "value"),
    State("meta_input_diametros", "value"),
    Input("tabs_principal", "value"),
    running=[(Output("btn_guardar_metadata", "disabled"), True, False),
             (Output("btn_guardar_yaml_texto", "disabled"), True, False),
             (Output("btn_guardar_diametros", "disabled"), True, False)],
)
def actualizar_panel_metadata(carpeta, n_guardar, n_guardar_txt, n_guardar_diam, cal_store,
                              yaml_txt_state, diam_txt, tab="metadata"):
    if not carpeta:
        return "", "", {}, "", "", "", "", "", "", "", ""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    # Solo se construye con la pestaña Metadata visible (al entrar en ella se pone al día)
    if tab != "metadata" and not str(trig or "").startswith("btn_guardar"):
        return (no_update,) * 11
    msg_fb = ""

    if trig == "btn_guardar_diametros":
        ok, msg = guardar_diametros(carpeta, diam_txt)
        color = tema.OK if ok else tema.ERROR
        msg_fb = html.Span(msg, style={"color": color, "fontWeight": "600"})
        if not ok:
            # Se conserva lo escrito para que el usuario lo corrija.
            return (no_update,) * 3 + (msg_fb,) + (no_update,) * 7
    elif trig == "btn_guardar_yaml_texto" and yaml_txt_state:
        ok, msg = guardar_metadata_archivo(carpeta, yaml_txt_state)
        color = tema.OK if ok else tema.ERROR
        msg_fb = html.Span(msg, style={"color": color, "fontWeight": "600"})
    elif trig == "btn_guardar_metadata":
        meta_act = obtener_metadata(carpeta)
        meta_clean = {k: v for k, v in meta_act.items() if not k.startswith("_")}
        meta_str = yaml.safe_dump(meta_clean, sort_keys=False, allow_unicode=True)
        ok, msg = guardar_metadata_archivo(carpeta, meta_str)
        color = tema.OK if ok else tema.ERROR
        msg_fb = html.Span(msg, style={"color": color, "fontWeight": "600"})

    meta = obtener_metadata(carpeta)
    existe = meta.get("_existe_en_disco", False)
    badge_txt = "Archivo en disco: metadata.yaml" if existe else "Autogenerado desde HDF5 (no guardado)"
    badge_style = tema.BADGE_OK if existe else tema.BADGE_WARN

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

    v_sec = circ.get("tension_kv_ac_sec")
    v_sec_str = f"{v_sec} kV" if v_sec is not None else "N/D"
    card_circ = [
        html.Div([html.Strong("Forma de onda: "), str(circ.get("forma_onda_nominal") or "1.2/50 µs")]),
        html.Div([html.Strong("Tensión secundario: "), v_sec_str]),
        html.Div([html.Strong("Disparos programados: "), str(circ.get("nro_disparos_programados") or 50)]),
        html.Div([html.Strong("Intervalo entre disparos: "), f"{circ.get('intervalo_entre_disparos_s')} s" if circ.get('intervalo_entre_disparos_s') is not None else "30 s"]),
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
            html.Td(" · ".join(x for x in (
                filtros.etiqueta(filtros.filtro_canal(meta, c)) if c != "ch1" else None,
                f"-{cfg.get('atenuacion_db')} dB" if cfg.get("atenuacion_db") else None) if x) or "-",
                style={"padding": "4px 8px"}),
            html.Td(t_lag_str, style={"padding": "4px 8px"}),
        ]))

    th_ch_style = {"textAlign": "left", "padding": "4px 8px", "borderBottom": f"1px solid {tema.BORDER}"}
    tabla_ch = html.Table(
        style={"width": "100%", "borderCollapse": "collapse", "fontSize": "11px", "marginTop": "4px"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style=th_ch_style),
                html.Th("Sensor", style=th_ch_style),
                html.Th("Función", style=th_ch_style),
                html.Th("Escala V/div", style=th_ch_style),
                html.Th("Unidad", style=th_ch_style),
                html.Th("Filtro / Atenuación", style=th_ch_style),
                html.Th("t_lag (ns)", style=th_ch_style),
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
        diam if diam != "N/D" else "",
    )


@app.callback(
    Output("seleccion", "data"),
    Input("captura_params", "data"),
    Input("grafico_scatter", "selectedData"),
    Input("grafico_scatter", "clickData"),
    Input("grafico", "clickData"),
    Input("btn_excluir_seleccion", "n_clicks"),
    Input("btn_deshacer_exclusion", "n_clicks"),
    Input("btn_restaurar_descargas", "n_clicks"),
    Input("btn_excluir_disparo", "n_clicks"),
    Input("input_excluir_disparo", "n_submit"),
    State("captura_params", "data"),
    State("descargas_excluidas", "data"),
)
def set_seleccion(_cap_in, sel_pk, click_pk, click_g, n_exc, n_undo, n_res, n_disp, n_sub, p, excl_dict):
    """Fuente única de la selección (índices globales de ventana). La alimentan
    los clics/cajas del scatter TRPD y los clics en las cruces del canal
    trigger. Una nueva captura o acción de exclusión/restauración/deshacer la limpian; los reset a None (por redibujo) se
    ignoran para no romper el ciclo."""
    trg = ctx.triggered[0]["prop_id"] if ctx.triggered else ""
    if (trg.startswith("captura_params") or
            trg.startswith("btn_excluir_seleccion") or
            trg.startswith("btn_deshacer_exclusion") or
            trg.startswith("btn_restaurar_descargas") or
            trg.startswith("btn_excluir_disparo") or
            trg.startswith("input_excluir_disparo")):
        return []  # limpiar selección
    if not p:
        return no_update
    n = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))["W"].shape[0]
    key = f"{p['carpeta']}|{p['canal']}"
    excl = set(_obtener_excluidos(excl_dict, key))
    activos = [i for i in range(n) if i not in excl]

    if trg == "grafico.clickData":            # cruces del trigger (customdata)
        idx = _idx_cruces(click_g, n)
    elif trg == "grafico_scatter.selectedData":
        idx = _idx_scatter(sel_pk, n, activos=activos)
    elif trg == "grafico_scatter.clickData":
        idx = _idx_scatter(click_pk, n, activos=activos)
    else:
        idx = None
    # None = reset por redibujo o clic sin punto válido: no cambiar la selección.
    return no_update if idx is None else idx


@app.callback(
    Output("descargas_excluidas", "data"),
    Output("input_excluir_disparo", "value"),
    Input("btn_excluir_seleccion", "n_clicks"),
    Input("btn_deshacer_exclusion", "n_clicks"),
    Input("btn_restaurar_descargas", "n_clicks"),
    Input("btn_excluir_disparo", "n_clicks"),
    Input("input_excluir_disparo", "n_submit"),
    State("seleccion", "data"),
    State("input_excluir_disparo", "value"),
    State("descargas_excluidas", "data"),
    State("captura_params", "data"),
    prevent_initial_call=True,
)
def gestionar_exclusiones_descargas(n_exc, n_undo, n_res, n_disp, n_sub,
                                    sel, val_disparo, excl_dict, p):
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None
    if not p:
        return no_update, no_update

    excl_dict = dict(excl_dict) if isinstance(excl_dict, dict) else {}
    key = f"{p['carpeta']}|{p['canal']}"

    curr_excl = list(_obtener_excluidos(excl_dict, key))
    curr_hist = [dict(h) for h in _obtener_historial(excl_dict, key)]

    if trig == "btn_excluir_seleccion" and sel:
        ya = set(curr_excl)
        nuevos = [int(i) for i in sel if i not in ya]
        if nuevos:
            curr_hist.append({"tipo": "lazo", "indices": nuevos, "desc": f"{len(nuevos)} descargas"})
            curr_excl = sorted(set(curr_excl).union(nuevos))
            excl_dict[key] = {"excluidos": curr_excl, "historial": curr_hist}
            return excl_dict, no_update
        return no_update, no_update

    if trig in ("btn_excluir_disparo", "input_excluir_disparo"):
        cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))
        n_segs = n_segmentos(p["carpeta"])
        segs = parsear_lista_disparos(val_disparo, n_segs)
        if segs and cap["seg"].size:
            segs_set = set(segs)
            indices_segs = [int(i) for i, s in enumerate(cap["seg"]) if s in segs_set]
            ya = set(curr_excl)
            nuevos = [i for i in indices_segs if i not in ya]
            if nuevos:
                curr_hist.append({
                    "tipo": "disparo",
                    "segs": segs,
                    "indices": nuevos,
                    "desc": f"Disparo(s) {segs} ({len(nuevos)} peaks)"
                })
                curr_excl = sorted(set(curr_excl).union(nuevos))
                excl_dict[key] = {"excluidos": curr_excl, "historial": curr_hist}
                return excl_dict, ""
        return no_update, ""

    if trig == "btn_deshacer_exclusion":
        if curr_hist:
            curr_hist.pop()
            reconstruidos = set()
            for paso in curr_hist:
                reconstruidos.update(paso.get("indices", []))
            curr_excl = sorted(reconstruidos)
            excl_dict[key] = {"excluidos": curr_excl, "historial": curr_hist}
            return excl_dict, no_update
        return no_update, no_update

    if trig == "btn_restaurar_descargas":
        if curr_excl or curr_hist:
            excl_dict[key] = {"excluidos": [], "historial": []}
            return excl_dict, no_update
        return excl_dict, no_update

    return no_update, no_update


@app.callback(
    Output("btn_excluir_seleccion", "disabled"),
    Output("btn_excluir_seleccion", "children"),
    Output("btn_deshacer_exclusion", "disabled"),
    Output("btn_restaurar_descargas", "disabled"),
    Output("badge_filtro_descargas", "children"),
    Input("seleccion", "data"),
    Input("descargas_excluidas", "data"),
    Input("captura_params", "data"),
)
def actualizar_badge_filtro(sel, excl_dict, p):
    if not p:
        return True, "Quitar selección", True, True, ""
    n_sel = len(sel) if sel else 0
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))
    n_total = cap["t_peak"].size
    key = f"{p['carpeta']}|{p['canal']}"
    excl = set(_obtener_excluidos(excl_dict, key))
    hist = _obtener_historial(excl_dict, key)
    n_excl = len(excl.intersection(range(n_total)))
    n_act = max(0, n_total - n_excl)

    btn_txt = f"Quitar {n_sel} seleccionada{'s' if n_sel != 1 else ''}" if n_sel > 0 else "Quitar selección"
    btn_disabled = (n_sel == 0)
    btn_undo_disabled = (len(hist) == 0)
    btn_reset_disabled = (n_excl == 0 and len(hist) == 0)

    if n_excl > 0:
        pasos_txt = f" en {len(hist)} paso{'s' if len(hist) != 1 else ''}" if len(hist) > 1 else ""
        badge = f"{n_act}/{n_total} activas ({n_excl} excluida{'s' if n_excl != 1 else ''}{pasos_txt})"
    else:
        badge = f"{n_total} descargas activas"

    return btn_disabled, btn_txt, btn_undo_disabled, btn_reset_disabled, badge


@app.callback(
    Output("grafico_scatter", "figure"),
    Input("captura_params", "data"),
    Input("seleccion", "data"),
    Input("modo_magnitud_trpd", "value"),
    Input("calibracion_store", "data"),
    Input("descargas_excluidas", "data"),
)
def actualizar_scatter(p, sel, modo_trpd, cal, excl_dict):
    """Scatter de Patrón TRPD, con los puntos seleccionados en
    resaltados (venga la selección del scatter o de las cruces del trigger)."""
    if not p:
        return _fig_vacia("Pulse «Calcular peaks» para analizar las descargas de esta medición.", altura=415)
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))
    t_ref, v_ref = promedio_impulso(p["carpeta"])
    modo = modo_trpd or "vmax"
    t_lag = lag_canal(cal, p["carpeta"], p["canal"])
    t_abs = t_abs_captura(cap, t_lag)
    T = tiempos_impulso(p["carpeta"])
    t10_ref = T["t10"] if T else None
    calibrado = bool(cal and cal.get("carpeta") == p["carpeta"] and cal.get("canales", {}).get(p["canal"], {}).get("calibrado"))
    key = f"{p['carpeta']}|{p['canal']}"
    excl = _obtener_excluidos(excl_dict, key)
    # uirevision estable dentro de una captura: al pintar el amarillo no se
    # pierde zoom ni la caja de selección; cambia al hacer una captura nueva, cambiar modo o exclusiones.
    rev = f"{p['carpeta']}|{p['canal']}|{p['umbral']}|{p['dist']}|{p['tmin']}|{modo}|{len(excl)}"
    try:
        return figura_scatter(cap, t_ref, v_ref, p["canal"], sel, rev, modo=modo,
                              t_abs=t_abs, t10_ref=t10_ref, t_lag_us=t_lag, calibrado=calibrado,
                              excluidos=excl)
    except Exception as e:
        return _fig_error("No se pudo dibujar el patrón TRPD", e, altura=415)


@app.callback(
    Output("grafico_ventanas", "figure"),
    Output("grafico_fft", "figure"),
    Input("seleccion", "data"),
    Input("captura_params", "data"),
)
def actualizar_temporal(sel, p):
    """Ventanas y FFT de SOLO las señales seleccionadas (store `seleccion`)."""
    if not p:
        return _fig_vacia("Pulse «Calcular peaks» para analizar las descargas de esta medición."), _fig_vacia("Pulse «Calcular peaks» para analizar las descargas de esta medición.")
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))
    sel = sel or []
    return figura_ventanas(cap, sel, p["canal"]), figura_fft(cap, sel, p["canal"])


@app.callback(
    Output("grafico_st_ventana", "figure"),
    Input("seleccion", "data"),
    Input("tabs_espectro", "value"),
    Input("st_fmax", "value"),
    Input("captura_params", "data"),
)
def actualizar_st_ventana(sel, tab, fmax, p):
    """Transformada S de la ventana de 70 ns (solo si su pestaña está visible),
    promediando SOLO las señales seleccionadas (store `seleccion`)."""
    if tab != "st":
        return no_update
    if not p:
        return _fig_vacia("Pulse «Calcular peaks» para analizar las descargas de esta medición.")
    cap = capturar(p["carpeta"], p["canal"], p["umbral"], p["dist"], p["tmin"], filtrado=p.get("filtrado", True))
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
    # Sin dev tools por defecto (bundles minificados, sin sondeo de hot-reload).
    # Para depurar: set TRPD_DEBUG=1 antes de arrancar.
    depurar = os.environ.get("TRPD_DEBUG") == "1"
    app.run(debug=depurar, use_reloader=False, dev_tools_props_check=False, host="127.0.0.1", port=8051)
