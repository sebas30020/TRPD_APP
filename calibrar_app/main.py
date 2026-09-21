"""Punto de entrada y servidor Dash de calibrar_app (puerto 8051).

Aplicación autónoma para calibración instrumental de retardos y diagnóstico IEC 60060-1.
"""

from __future__ import annotations
import os
import sys
import numpy as np
from dash import Dash, html, dcc, Input, Output, State, ctx, no_update, ALL

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, os.pardir))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

from datos import (
    listar_mediciones,
    canales_presentes,
    cargar_segmento,
    umbral_defecto,
    n_segmentos,
    _muestras,
    VENTANA_T10,
    listar_subcarpetas,
    _CHAN_RE,
    _orden_natural,
    _dir_medicion,
    MEDICIONES,
)
from arribo import t_arribo, calibrar_retardo
from referencia import (
    ancla_por_segmento,
    evaluar_segmento_iec,
    resumen_iec,
    delta_t10_menos_O1,
)
from figuras import (
    umbrales_desde_relayout,
    umbral_desde_relayout,
    figura_canal,
    figura_impulso_iec,
    figura_dispersion_lag,
    figura_ancla_por_segmento,
)
from persistencia import (
    bloque_calibracion_retardo,
    construir_info_ancla,
    guardar_calibracion_metadata,
)
from interfaz import layout


app = Dash(
    __name__,
    title="Calibración Instrumental IEC 60060-1 / t10",
    assets_folder=os.path.join(RAIZ, "assets"),
)

mediciones_disponibles = listar_mediciones()
carpeta_defecto = "mediciones_filtros/cada_30s/7" if "mediciones_filtros/cada_30s/7" in mediciones_disponibles else (
    mediciones_disponibles[0] if mediciones_disponibles else ""
)

app.layout = layout(mediciones_disponibles, carpeta_defecto)


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
        inicio = _dir_medicion(carpeta_val) if carpeta_val else None
        if not inicio or not os.path.isdir(inicio):
            inicio = os.path.dirname(MEDICIONES)
        return False, inicio, no_update, no_update
    if trig == "explorador_cancelar":
        return True, no_update, no_update, no_update
    if trig == "explorador_confirmar":
        if not ruta_actual:
            return no_update, no_update, no_update, no_update
        opts = list(opciones or [])
        if not any(o.get("value") == ruta_actual for o in opts):
            opts = opts + [{"label": ruta_actual, "value": ruta_actual}]
        return True, no_update, ruta_actual, opts
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
        if ruta_actual:
            padre = os.path.dirname(os.path.normpath(ruta_actual))
            return padre if os.path.isdir(padre) else no_update
        return no_update
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
    if not ruta_actual or not os.path.isdir(ruta_actual):
        return [], "", True
    filas = []
    for nombre, p, tiene_h5 in listar_subcarpetas(ruta_actual):
        filas.append(html.Button(
            f"{'📁✅ ' if tiene_h5 else '📁 '}{nombre}",
            id={"type": "explorador_ir", "ruta": p},
            n_clicks=0,
            style={
                "display": "block",
                "width": "100%",
                "textAlign": "left",
                "backgroundColor": "transparent",
                "border": "none",
                "borderBottom": "1px solid #f1f5f9",
                "padding": "6px 8px",
                "cursor": "pointer",
                "fontSize": "13px",
                "color": "#1e293b",
            },
        ))
    if not filas:
        filas = [html.Div("(No hay subcarpetas)", style={"color": "#94a3b8", "fontStyle": "italic", "padding": "6px 8px"})]
    try:
        tiene_h5_aqui = any(
            _CHAN_RE.match(f) for f in os.listdir(ruta_actual)
            if os.path.isfile(os.path.join(ruta_actual, f))
        )
    except Exception:
        tiene_h5_aqui = False
    return filas, ruta_actual, not tiene_h5_aqui


@app.callback(
    Output("label_segmento", "children"),
    Input("segmento", "value"),
)
def actualizar_label_segmento(seg: int) -> str:
    return f"Disparo {seg}" if seg else "—"


@app.callback(
    Output("segmento", "value"),
    Output("segmento", "max"),
    Output("segmento_total", "children"),
    Input("carpeta", "value"),
)
def actualizar_rango_segmento(carpeta: str):
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


def sincronizar_umbral(relayout: dict | None, carpeta: str, canal: str, u_actual: float | None):
    """Sincroniza el arrastre visual de la línea de umbral con el input numérico (helper retrocompatible)."""
    if relayout:
        hay_shape = any("shapes" in str(k) and (".y0" in str(k) or ".y1" in str(k)) for k in relayout.keys())
        if not hay_shape:
            return no_update
        val = umbral_desde_relayout(relayout, fallback=u_actual or 10.0)
        if u_actual is not None and abs(val - float(u_actual)) < 0.02:
            return no_update
        return round(float(val), 2)

    canal_target = "ch4" if canal == "todos" else canal
    if not carpeta or not canal_target:
        return no_update
    return round(float(umbral_defecto(carpeta, canal_target, seg=1)), 2)


@app.callback(
    Output("umbral_ch2", "value"),
    Output("tmin_ch2", "value"),
    Output("umbral_ch3", "value"),
    Output("tmin_ch3", "value"),
    Output("umbral_ch4", "value"),
    Output("tmin_ch4", "value"),
    Output("ucal", "value"),
    Input("grafico_canal", "relayoutData"),
    Input("carpeta", "value"),
    State("canal", "value"),
    State("umbral_ch2", "value"),
    State("tmin_ch2", "value"),
    State("umbral_ch3", "value"),
    State("tmin_ch3", "value"),
    State("umbral_ch4", "value"),
    State("tmin_ch4", "value"),
    State("ucal", "value"),
    prevent_initial_call=False,
)
def sincronizar_triggers(
    relayout: dict | None = None,
    carpeta: str = "",
    canal: str = "todos",
    u2: float | None = None,
    tmin2: float | None = None,
    u3: float | None = None,
    tmin3: float | None = None,
    u4: float | None = None,
    tmin4: float | None = None,
    ucal_act: float | None = None,
):
    """Mantiene la persistencia e independencia de los triggers por canal y captura arrastre visual."""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None

    # Caso 1: Arrastre visual en el gráfico
    if trig == "grafico_canal" or (trig is None and relayout is not None):
        if not relayout:
            return (no_update,) * 7
        hay_shape = any("shapes" in str(k) and (".y0" in str(k) or ".y1" in str(k)) for k in relayout.keys())
        if not hay_shape:
            return (no_update,) * 7

        disponibles = canales_presentes(carpeta) if carpeta else ["ch1", "ch2", "ch3", "ch4"]
        cambios = umbrales_desde_relayout(relayout, disponibles)
        if not cambios:
            return (no_update,) * 7

        nuevo_u2 = no_update
        if "ch2" in cambios:
            v2 = cambios["ch2"]
            if u2 is None or abs(v2 - float(u2)) >= 0.05:
                nuevo_u2 = v2

        nuevo_u3 = no_update
        if "ch3" in cambios:
            v3 = cambios["ch3"]
            if u3 is None or abs(v3 - float(u3)) >= 0.05:
                nuevo_u3 = v3

        nuevo_u4 = no_update
        if "ch4" in cambios:
            v4 = cambios["ch4"]
            if u4 is None or abs(v4 - float(u4)) >= 0.05:
                nuevo_u4 = v4

        ch_activo = "ch4" if canal == "todos" else canal
        nuevo_ucal = cambios.get(ch_activo, no_update)

        return (nuevo_u2, no_update, nuevo_u3, no_update, nuevo_u4, no_update, nuevo_ucal)

    # Caso 2: Cambio de carpeta (o carga inicial cuando faltan triggers)
    if trig == "carpeta" or (u2 is None and u3 is None and u4 is None):
        if not carpeta:
            return (no_update,) * 7
        disp = canales_presentes(carpeta)
        val_u2 = round(float(umbral_defecto(carpeta, "ch2", seg=1)), 2) if "ch2" in disp else 50.0
        val_u3 = round(float(umbral_defecto(carpeta, "ch3", seg=1)), 2) if "ch3" in disp else 50.0
        val_u4 = round(float(umbral_defecto(carpeta, "ch4", seg=1)), 2) if "ch4" in disp else 50.0
        ch_act = "ch4" if canal == "todos" else canal
        val_ucal = val_u4 if ch_act == "ch4" else (val_u2 if ch_act == "ch2" else val_u3)
        return (val_u2, 0.15, val_u3, 0.15, val_u4, 0.15, val_ucal)

    return (no_update,) * 7


@app.callback(
    Output("grafico_canal", "figure"),
    Input("carpeta", "value"),
    Input("canal", "value"),
    Input("segmento", "value"),
    Input("ucal", "value"),
    Input("dtcal", "value"),
    Input("tmincal", "value"),
    Input("referencia", "value"),
    Input("umbral_ch2", "value"),
    Input("tmin_ch2", "value"),
    Input("umbral_ch3", "value"),
    Input("tmin_ch3", "value"),
    Input("umbral_ch4", "value"),
    Input("tmin_ch4", "value"),
)
def actualizar_grafico_canal(
    carpeta: str,
    canal: str,
    seg: int,
    ucal: float | None = None,
    dtcal: float | None = None,
    tmincal: float | None = None,
    ref: str = "t10",
    u2: float | None = None,
    tmin2: float | None = None,
    u3: float | None = None,
    tmin3: float | None = None,
    u4: float | None = None,
    tmin4: float | None = None,
):
    """Actualiza el gráfico multicanal sincronizado con umbrales independientes y marcas de arribo."""
    if not carpeta or not seg:
        return no_update

    canal_foco = "ch4" if canal == "todos" else canal
    dt_us = float(dtcal or 0.035)

    # Configuración por canal independiente
    cfg_sensores = {
        "ch2": {
            "umbral": u2 if u2 is not None else (ucal if canal == "ch2" and ucal is not None else float(umbral_defecto(carpeta, "ch2", seg=seg))),
            "tmin": tmin2 if tmin2 is not None else (tmincal if tmincal is not None else 0.15),
        },
        "ch3": {
            "umbral": u3 if u3 is not None else (ucal if canal == "ch3" and ucal is not None else float(umbral_defecto(carpeta, "ch3", seg=seg))),
            "tmin": tmin3 if tmin3 is not None else (tmincal if tmincal is not None else 0.15),
        },
        "ch4": {
            "umbral": u4 if u4 is not None else (ucal if canal in ("ch4", "todos") and ucal is not None else float(umbral_defecto(carpeta, "ch4", seg=seg))),
            "tmin": tmin4 if tmin4 is not None else (tmincal if tmincal is not None else 0.15),
        },
    }

    # Ancla temporal para el segmento seleccionado
    anclas = ancla_por_segmento(carpeta, referencia=ref)["ancla_us"]
    ancla_us = float(anclas[seg - 1]) if (anclas.size >= seg) else None

    # Parámetros para canal foco
    u_foco = cfg_sensores.get(canal_foco, {}).get("umbral", ucal or 50.0)
    tmin_foco = cfg_sensores.get(canal_foco, {}).get("tmin", tmincal or 0.15)

    ref_nombre = "t10" if ref == "t10" else "O1"
    return figura_canal(
        carpeta=carpeta,
        canal=canal_foco,
        seg=seg,
        umbral=u_foco,
        dist_us=dt_us,
        tmin=tmin_foco,
        ancla_us=ancla_us,
        referencia_nombre=ref_nombre,
        cfg_sensores=cfg_sensores,
    )


@app.callback(
    Output("grafico_impulso", "figure"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
)
def actualizar_grafico_impulso(carpeta: str, seg: int):
    """Actualiza la visualización del impulso CH1 con el ajuste IEC 60060-1."""
    if not carpeta or not seg:
        return no_update
    res_iec = evaluar_segmento_iec(carpeta, seg, con_curva=True, diezmado_ajuste=10)
    return figura_impulso_iec(carpeta, seg, res_iec)


@app.callback(
    Output("resultado_store", "data"),
    Input("btn_calcular", "n_clicks"),
    State("carpeta", "value"),
    State("canal", "value"),
    State("ucal", "value"),
    State("dtcal", "value"),
    State("tmincal", "value"),
    State("referencia", "value"),
    State("resultado_store", "data"),
    State("umbral_ch2", "value"),
    State("tmin_ch2", "value"),
    State("umbral_ch3", "value"),
    State("tmin_ch3", "value"),
    State("umbral_ch4", "value"),
    State("tmin_ch4", "value"),
    prevent_initial_call=True,
)
def calcular_retardo_canal(
    n_clicks: int,
    carpeta: str,
    canal: str,
    ucal: float | None = None,
    dtcal: float | None = None,
    tmincal: float | None = None,
    ref: str = "t10",
    store_actual: dict | None = None,
    u2: float | None = None,
    tmin2: float | None = None,
    u3: float | None = None,
    tmin3: float | None = None,
    u4: float | None = None,
    tmin4: float | None = None,
):
    """Calcula el retardo para el canal seleccionado (o todos) con triggers independientes por canal."""
    if not n_clicks or not carpeta or not canal:
        return no_update

    store = dict(store_actual or {})
    if store.get("_carpeta") != carpeta:
        store = {"_carpeta": carpeta}

    dt_us = float(dtcal or 0.035)

    cfg_map = {
        "ch2": (u2 if u2 is not None else (ucal if canal == "ch2" and ucal is not None else None), tmin2 if tmin2 is not None else tmincal),
        "ch3": (u3 if u3 is not None else (ucal if canal == "ch3" and ucal is not None else None), tmin3 if tmin3 is not None else tmincal),
        "ch4": (u4 if u4 is not None else (ucal if canal in ("ch4", "todos") and ucal is not None else None), tmin4 if tmin4 is not None else tmincal),
    }

    if canal == "todos":
        canales_calc = [c for c in ("ch2", "ch3", "ch4") if c in canales_presentes(carpeta)]
    else:
        canales_calc = [canal] if canal in canales_presentes(carpeta) else []

    for c in canales_calc:
        u_cfg, tm_cfg = cfg_map.get(c, (None, None))
        u = float(u_cfg if u_cfg is not None else umbral_defecto(carpeta, c, seg=1))
        tm = float(tm_cfg if tm_cfg is not None else (tmincal or 0.15))
        res = calibrar_retardo(
            carpeta=carpeta,
            canal=c,
            umbral=u,
            dist_us=dt_us,
            tmin=tm,
            referencia=ref,
        )
        store[c] = res

    store["_referencia"] = ref
    return store


@app.callback(
    Output("iec_store", "data"),
    Input("btn_evaluar_iec", "n_clicks"),
    Input("carpeta", "value"),
)
def evaluar_conformidad_iec(n_clicks: int | None, carpeta: str):
    """Evalúa la conformidad normativa IEC 60060-1 y estadísticas de ancla."""
    if not carpeta:
        return {}
    res = resumen_iec(carpeta)
    delta = delta_t10_menos_O1(carpeta)
    return {
        "resumen_iec": res,
        "delta": delta,
    }


@app.callback(
    Output("grafico_dispersion", "figure"),
    Input("resultado_store", "data"),
    Input("canal_dispersion", "value"),
)
def actualizar_grafico_dispersion(store: dict | None, canal: str = "ch4"):
    """Muestra la dispersión e histograma del retardo del canal seleccionado en el gráfico."""
    ch_target = canal or "ch4"
    if not store:
        return figura_dispersion_lag({}, canal=ch_target)
    if ch_target not in store or not isinstance(store[ch_target], dict):
        return figura_dispersion_lag({}, canal=ch_target)
    return figura_dispersion_lag(store[ch_target], canal=ch_target)


@app.callback(
    Output("grafico_ancla", "figure"),
    Input("carpeta", "value"),
    Input("referencia", "value"),
)
def actualizar_grafico_ancla(carpeta: str, ref: str):
    """Muestra las marcas de ancla por segmento."""
    if not carpeta:
        return no_update
    anclas = ancla_por_segmento(carpeta, referencia=ref)["ancla_us"]
    return figura_ancla_por_segmento(carpeta, ref, anclas)


@app.callback(
    Output("tabla_resumen", "children"),
    Input("resultado_store", "data"),
    Input("carpeta", "value"),
)
def actualizar_tabla_resumen(store: dict | None, carpeta: str):
    """Genera la tabla resumen de canales calibrados."""
    if not store:
        return html.P("Sin canales calibrados en la sesión actual. Pulsa ▶ Calcular Retardo.", style={"color": "#64748b", "fontSize": "13px"})

    sensores_map = {
        "ch2": "HFCT",
        "ch3": "Antena Vivaldi",
        "ch4": "Antena Bioinspirada",
    }
    filas = []
    for ch in ["ch2", "ch3", "ch4"]:
        if ch in store and isinstance(store[ch], dict):
            r = store[ch]
            t_lag_ns = f"{r['t_lag_us'] * 1e3:.2f}" if r.get("t_lag_us") is not None else "—"
            sig_ns = f"{r['sigma_us'] * 1e3:.2f}" if r.get("sigma_us") is not None else "—"
            p = r.get("params", {})
            filas.append(html.Tr([
                html.Td(ch.upper(), style={"fontWeight": "600", "padding": "6px 10px"}),
                html.Td(sensores_map.get(ch, ch.upper()), style={"padding": "6px 10px"}),
                html.Td(t_lag_ns, style={"fontWeight": "700", "color": "#1d4ed8", "padding": "6px 10px"}),
                html.Td(sig_ns, style={"padding": "6px 10px"}),
                html.Td(f"{r.get('n_valid')}/{r.get('n_total')}", style={"padding": "6px 10px"}),
                html.Td(f"{p.get('umbral_mv', 0):.2f}", style={"padding": "6px 10px"}),
                html.Td(f"{p.get('distancia_us', 0):.3f}", style={"padding": "6px 10px"}),
                html.Td(f"{p.get('tmin_us', 0):.3f}", style={"padding": "6px 10px"}),
            ]))

    if not filas:
        return html.P("Sin canales calibrados en la sesión actual. Pulsa ▶ Calcular Retardo.", style={"color": "#64748b", "fontSize": "13px"})

    return html.Table(
        style={"width": "100%", "fontSize": "12px", "borderCollapse": "collapse", "textAlign": "left"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("Sensor", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("t̄_lag [ns]", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("σ [ns]", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("Válidos", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("u_cal [mV]", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("Δt [µs]", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
                html.Th("t_mín [µs]", style={"borderBottom": "2px solid #cbd5e1", "padding": "6px 10px"}),
            ])),
            html.Tbody(filas),
        ],
    )


@app.callback(
    Output("panel_iec_resumen", "children"),
    Input("iec_store", "data"),
)
def actualizar_panel_iec(store: dict | None):
    """Muestra el estado de conformidad normativa IEC 60060-1."""
    if not store:
        return html.P("Cargando diagnóstico IEC...", style={"color": "#64748b", "fontSize": "13px"})

    iec = store.get("resumen_iec", {})
    delta = store.get("delta", {})

    t1 = f"{iec.get('T1_medio_us', 0):.3f} µs" if iec.get("T1_medio_us") is not None else "—"
    t2 = f"{iec.get('T2_medio_us', 0):.2f} µs" if iec.get("T2_medio_us") is not None else "—"
    beta = f"{iec.get('beta_medio_pct', 0):.2f} %" if iec.get("beta_medio_pct") is not None else "—"
    delta_ns = f"{delta.get('media_us', 0) * 1e3:.1f} ± {delta.get('sigma_us', 0) * 1e3:.1f} ns" if delta.get("media_us") is not None else "—"
    conforme = iec.get("conforme", False)
    fuera = iec.get("fuera_tolerancia", 0)

    color_conf = "#16a34a" if conforme else "#e11d48"
    texto_conf = "Lote Conforme con IEC 60060-1 (1.2/50 µs)" if conforme else f"Atención: {fuera} disparos fuera de tolerancia"

    return html.Div([
        html.Div(
            texto_conf,
            style={"fontWeight": "700", "color": color_conf, "marginBottom": "8px", "fontSize": "13px"}
        ),
        html.Div(
            style={"display": "grid", "gridTemplateColumns": "1fr 1fr", "gap": "6px", "fontSize": "12px"},
            children=[
                html.Div(f"• T1 medio: {t1}"),
                html.Div(f"• T2 medio: {t2}"),
                html.Div(f"• β' oscilaciones: {beta}"),
                html.Div(f"• Ancla t10 - O1: {delta_ns}"),
            ]
        ),
    ])


@app.callback(
    Output("msg_feedback", "children"),
    Input("btn_guardar", "n_clicks"),
    State("carpeta", "value"),
    State("resultado_store", "data"),
    State("fuente_calibracion", "value"),
    State("referencia", "value"),
    prevent_initial_call=True,
)
def guardar_en_metadata(n_clicks: int, carpeta: str, store: dict | None, fuente: str, ref: str):
    """Persiste los retardos calculados en metadata.yaml de la carpeta seleccionada."""
    if not n_clicks or not carpeta or not store:
        return no_update

    canales_validos = {ch: store[ch] for ch in ["ch2", "ch3", "ch4"] if ch in store}
    if not canales_validos:
        return html.Div("⚠️ No hay canales calculados para guardar. Pulsa primero ▶ Calcular Retardo.",
                        style={"color": "#b45309", "backgroundColor": "#fef3c7", "padding": "8px 12px", "borderRadius": "4px"})

    info_ancla = None
    if ref == "origen_virtual_IEC60060":
        info_ancla = construir_info_ancla(carpeta)

    bloque = bloque_calibracion_retardo(
        resultados=canales_validos,
        fuente=fuente or "calibrar_app",
        referencia_impulso=ref,
        info_ancla=info_ancla,
    )
    ok, msg = guardar_calibracion_metadata(carpeta, bloque)
    if ok:
        return html.Div(
            f"✅ {msg} · Bloque calibracion_retardo actualizado exitosamente con referencia '{ref}'.",
            style={"color": "#15803d", "backgroundColor": "#dcfce7", "padding": "8px 12px", "borderRadius": "4px", "fontWeight": "600"}
        )
    return html.Div(
        f"❌ {msg}",
        style={"color": "#b91c1c", "backgroundColor": "#fee2e2", "padding": "8px 12px", "borderRadius": "4px"}
    )


if __name__ == "__main__":
    print("Iniciando servidor calibrar_app en http://127.0.0.1:8051 ...")
    app.run(host="127.0.0.1", port=8051, debug=False)
