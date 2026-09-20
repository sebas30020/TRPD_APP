"""Punto de entrada y servidor Dash de calibrar_app (puerto 8051).

Aplicación autónoma para calibración instrumental de retardos y diagnóstico IEC 60060-1.
"""

from __future__ import annotations
import os
import sys
import numpy as np
from dash import Dash, html, dcc, Input, Output, State, ctx, no_update

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
    _muestras,
    VENTANA_T10,
)
from arribo import t_arribo, calibrar_retardo
from referencia import (
    ancla_por_segmento,
    evaluar_segmento_iec,
    resumen_iec,
    delta_t10_menos_O1,
)
from figuras import (
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
    Output("label_segmento", "children"),
    Input("segmento", "value"),
)
def actualizar_label_segmento(seg: int) -> str:
    return f"Disparo {seg}"


@app.callback(
    Output("ucal", "value"),
    Input("grafico_canal", "relayoutData"),
    Input("carpeta", "value"),
    Input("canal", "value"),
    State("ucal", "value"),
    prevent_initial_call=False,
)
def sincronizar_umbral(relayout: dict | None, carpeta: str, canal: str, u_actual: float | None):
    """Sincroniza el arrastre visual de la línea de umbral con el input numérico sin resetear zoom."""
    try:
        trig = ctx.triggered_id
    except Exception:
        trig = None

    if trig == "grafico_canal" or (trig is None and relayout is not None):
        if not relayout:
            return no_update
        # Solo actualizar si el relayout proviene explícitamente de arrastrar una forma (shape)
        hay_shape = any("shapes" in str(k) and (".y0" in str(k) or ".y1" in str(k)) for k in relayout.keys())
        if not hay_shape:
            return no_update
        val = umbral_desde_relayout(relayout, fallback=u_actual or 10.0)
        if u_actual is not None and abs(val - float(u_actual)) < 0.02:
            return no_update
        return round(float(val), 2)

    # Cambio de carpeta o canal -> valor por defecto inteligente
    canal_target = "ch4" if canal == "todos" else canal
    if not carpeta or not canal_target:
        return no_update
    return round(float(umbral_defecto(carpeta, canal_target, seg=1)), 2)


@app.callback(
    Output("grafico_canal", "figure"),
    Input("carpeta", "value"),
    Input("canal", "value"),
    Input("segmento", "value"),
    Input("ucal", "value"),
    Input("dtcal", "value"),
    Input("tmincal", "value"),
    Input("referencia", "value"),
)
def actualizar_grafico_canal(carpeta: str, canal: str, seg: int, ucal: float | None,
                             dtcal: float | None, tmincal: float | None, ref: str):
    """Actualiza el gráfico multicanal sincronizado con umbrales y marcas de arribo."""
    if not carpeta:
        return no_update

    canal_foco = "ch4" if canal == "todos" else canal
    u = float(ucal or umbral_defecto(carpeta, canal_foco, seg=seg))
    dt_us = float(dtcal or 0.035)
    tmin = float(tmincal or 0.15)

    # Ancla temporal para el segmento seleccionado
    anclas = ancla_por_segmento(carpeta, referencia=ref)["ancla_us"]
    ancla_us = float(anclas[seg - 1]) if (anclas.size >= seg) else None

    # Cálculo del arribo para el canal foco
    t, v = cargar_segmento(carpeta, canal_foco, seg, ventana=VENTANA_T10)
    dist_m = _muestras(carpeta, canal_foco, dt_us) or 1
    t_arr = t_arribo(t, v, u, dist_m, tmin) if v.size > 0 else None

    ref_nombre = "t10" if ref == "t10" else "O1"
    return figura_canal(
        carpeta=carpeta,
        canal=canal_foco,
        seg=seg,
        umbral=u,
        dist_us=dt_us,
        tmin=tmin,
        ancla_us=ancla_us,
        t_arr_us=t_arr,
        referencia_nombre=ref_nombre,
    )


@app.callback(
    Output("grafico_impulso", "figure"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
)
def actualizar_grafico_impulso(carpeta: str, seg: int):
    """Actualiza la visualización del impulso CH1 con el ajuste IEC 60060-1."""
    if not carpeta:
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
    prevent_initial_call=True,
)
def calcular_retardo_canal(n_clicks: int, carpeta: str, canal: str, ucal: float | None,
                           dtcal: float | None, tmincal: float | None, ref: str,
                           store_actual: dict | None):
    """Calcula el retardo para el canal seleccionado (o todos) sobre todos los segmentos y acumula en el store."""
    if not n_clicks or not carpeta or not canal:
        return no_update

    store = dict(store_actual or {})
    # Si cambió de carpeta, resetear store
    if store.get("_carpeta") != carpeta:
        store = {"_carpeta": carpeta}

    dt_us = float(dtcal or 0.035)
    tmin = float(tmincal or 0.15)

    if canal == "todos":
        canales_calc = [c for c in ("ch2", "ch3", "ch4") if c in canales_presentes(carpeta)]
    else:
        canales_calc = [canal] if canal in canales_presentes(carpeta) else []

    for c in canales_calc:
        if c == canal and ucal is not None:
            u = float(ucal)
        else:
            u = float(umbral_defecto(carpeta, c, seg=1))
        res = calibrar_retardo(
            carpeta=carpeta,
            canal=c,
            umbral=u,
            dist_us=dt_us,
            tmin=tmin,
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
    Input("canal", "value"),
)
def actualizar_grafico_dispersion(store: dict | None, canal: str):
    """Muestra la dispersión e histograma del retardo del canal activo o seleccionado."""
    if not store:
        return figura_dispersion_lag({})
    if canal == "todos":
        calibrados = [c for c in ("ch4", "ch2", "ch3") if c in store and isinstance(store[c], dict)]
        ch_target = calibrados[0] if calibrados else "ch4"
    else:
        ch_target = canal
    if ch_target not in store or not isinstance(store[ch_target], dict):
        return figura_dispersion_lag({})
    return figura_dispersion_lag(store[ch_target])


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
