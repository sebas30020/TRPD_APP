"""Punto de entrada y servidor Dash de calibrar_app (puerto 8052).

Aplicación autónoma para calibración instrumental de retardos y diagnóstico IEC 60060-1.
"""

from __future__ import annotations
import os
import sys
import urllib.parse
from dash import Dash, html, dcc, Input, Output, State, ctx, no_update, ALL

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, os.pardir))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
if AQUI not in sys.path:
    sys.path.insert(0, AQUI)

import filtros
import rutas
import tema
from datos import (
    spec_filtro,
    obtener_metadata,
    canales_presentes,
    umbral_defecto,
    n_segmentos,
    listar_subcarpetas,
)
from arribo import calibrar_retardo
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
from ediciones import (
    ediciones_medicion,
    guardar_ediciones_canal,
    estado_ediciones,
    resultados_editados,
)
from interfaz import layout


app = Dash(
    __name__,
    title="Calibración Instrumental IEC 60060-1 / t10",
    assets_folder=os.path.join(RAIZ, "assets"),
)

# Sin carpeta de datos fija: la medición se elige con el explorador de carpetas.
app.layout = layout([], "")


@app.callback(
    Output("carpeta", "value", allow_duplicate=True),
    Output("carpeta", "options", allow_duplicate=True),
    Output("explorador_panel", "hidden", allow_duplicate=True),
    Output("badge_modo", "children"),
    Output("enlace_volver", "style"),
    Input("url", "search"),
    State("carpeta", "options"),
    State("enlace_volver", "style"),
    prevent_initial_call="initial_duplicate",
)
def abrir_desde_url(search, opciones, estilo_enlace):
    """?carpeta=<medición> (lo pone TRPD_APP al abrir la pestaña Calibración)
    selecciona esa medición; ?embebido=1 oculta el enlace para volver a 8051."""
    q = urllib.parse.parse_qs((search or "").lstrip("?"))
    embebido = q.get("embebido", ["0"])[0] == "1"
    estilo = dict(estilo_enlace or {})
    estilo["display"] = "none" if embebido else "inline"
    badge = "Embebido en TRPD_APP" if embebido else "Puerto 8052 · Modo Autónomo"
    carpeta = q.get("carpeta", [None])[0]
    if not carpeta or not canales_presentes(carpeta):
        return no_update, no_update, no_update, badge, estilo
    opts = list(opciones or [])
    if not any(o.get("value") == carpeta for o in opts):
        opts.append({"label": rutas.etiqueta(carpeta), "value": carpeta, "title": carpeta})
    return carpeta, opts, True, badge, estilo


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
            f"{'📁✅ ' if tiene_h5 else '📁 '}{nombre}",
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
        filas = [html.Div("(No hay subcarpetas)", style={"color": tema.MUTED, "fontStyle": "italic", "padding": "6px 8px"})]
    if ruta_actual == rutas.EQUIPO:
        return filas, "Este equipo", True
    return filas, ruta_actual, not rutas.tiene_h5(ruta_actual)


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
    Input("ediciones_arribo", "data"),
    Input("marca_arribo", "data"),
    Input("tmax_ch2", "value"),
    Input("tmax_ch3", "value"),
    Input("tmax_ch4", "value"),
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
    store_ed: dict | None = None,
    marca: dict | None = None,
    tmax2: float | None = None,
    tmax3: float | None = None,
    tmax4: float | None = None,
):
    """Actualiza el gráfico multicanal sincronizado con umbrales independientes y marcas de arribo."""
    if not carpeta or not seg:
        return no_update

    canal_foco = "ch4" if canal == "todos" else canal
    dt_us = float(dtcal or 0.05)

    # Configuración por canal independiente
    cfg_sensores = {
        "ch2": {
            "umbral": u2 if u2 is not None else (ucal if canal == "ch2" and ucal is not None else float(umbral_defecto(carpeta, "ch2", seg=seg))),
            "tmin": tmin2 if tmin2 is not None else (tmincal if tmincal is not None else 0.15),
            "tmax": tmax2,
        },
        "ch3": {
            "umbral": u3 if u3 is not None else (ucal if canal == "ch3" and ucal is not None else float(umbral_defecto(carpeta, "ch3", seg=seg))),
            "tmin": tmin3 if tmin3 is not None else (tmincal if tmincal is not None else 0.15),
            "tmax": tmax3,
        },
        "ch4": {
            "umbral": u4 if u4 is not None else (ucal if canal in ("ch4", "todos") and ucal is not None else float(umbral_defecto(carpeta, "ch4", seg=seg))),
            "tmin": tmin4 if tmin4 is not None else (tmincal if tmincal is not None else 0.15),
            "tmax": tmax4,
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
        ediciones=_ed_canales(store_ed, carpeta),
        marca=marca if (marca or {}).get("carpeta") == carpeta else None,
    )


# ---------------- Edición manual de arribos ----------------

def _ed_canales(store_ed: dict | None, carpeta: str) -> dict:
    """{canal: ediciones} del store si corresponde a la medición, si no {}."""
    if not store_ed or store_ed.get("carpeta") != carpeta:
        return {}
    return dict(store_ed.get("canales") or {})


@app.callback(
    Output("ediciones_arribo", "data"),
    Input("carpeta", "value"),
)
def cargar_ediciones_arribo(carpeta: str):
    """Ediciones manuales de arribos de la medición (metadata.yaml: ediciones_arribo)."""
    if not carpeta:
        return None
    return {"carpeta": carpeta, "canales": ediciones_medicion(carpeta)}


@app.callback(
    Output("marca_arribo", "data"),
    Output("marca_t", "value"),
    Output("marca_canal", "value"),
    Output("aviso_arribo", "children", allow_duplicate=True),
    Input("grafico_canal", "clickData"),
    Input("marca_t", "value"),
    Input("marca_canal", "value"),
    Input("carpeta", "value"),
    Input("segmento", "value"),
    Input("ediciones_arribo", "data"),
    State("marca_arribo", "data"),
    prevent_initial_call="initial_duplicate",
)
def fijar_marca_arribo(click, t_txt, canal_sel, carpeta, seg, _ed=None, marca=None):
    """Marca temporal para editar un arribo: clic sobre la señal de CH2–CH4 (el canal
    sale del curveNumber de la traza; la ✕/rombo del arribo lo trae en customdata),
    o valor escrito en el campo t para el canal elegido. Se borra al cambiar de
    medición o segmento y tras cada edición."""
    trig = ctx.triggered_id if ctx.triggered else None
    if trig == "ediciones_arribo":
        return None, None, no_update, no_update   # conservar el aviso de la edición
    if trig in ("carpeta", "segmento") or not carpeta or not seg:
        return None, None, no_update, ""
    if trig in ("marca_t", "marca_canal"):
        if t_txt is None:
            return None, no_update, no_update, no_update
        nueva = {"carpeta": carpeta, "canal": canal_sel, "seg": int(seg), "t_us": float(t_txt)}
        if marca == nueva:
            return no_update, no_update, no_update, no_update
        return nueva, no_update, no_update, ""
    if trig != "grafico_canal" or not click or not click.get("points"):
        return no_update, no_update, no_update, no_update
    pt = click["points"][0]
    if pt.get("x") is None:
        return no_update, no_update, no_update, no_update
    cd = pt.get("customdata")
    if isinstance(cd, list):
        cd = cd[0] if cd else None
    if isinstance(cd, str) and cd in ("ch2", "ch3", "ch4"):
        canal = cd
    else:
        canales = [c for c in ("ch1", "ch2", "ch3", "ch4") if c in canales_presentes(carpeta)]
        n = pt.get("curveNumber")
        canal = canales[n] if isinstance(n, int) and 0 <= n < len(canales) else None
    if canal not in ("ch2", "ch3", "ch4"):
        return no_update, no_update, no_update, "La marca se pone sobre la señal de un sensor (CH2–CH4)."
    t = round(float(pt["x"]), 6)
    return {"carpeta": carpeta, "canal": canal, "seg": int(seg), "t_us": t}, t, canal, ""


@app.callback(
    Output("ediciones_arribo", "data", allow_duplicate=True),
    Output("aviso_arribo", "children"),
    Input("btn_fijar_arribo", "n_clicks"),
    Input("btn_quitar_arribo", "n_clicks"),
    Input("btn_deshacer_arribo", "n_clicks"),
    Input("btn_restaurar_arribo", "n_clicks"),
    State("carpeta", "value"),
    State("segmento", "value"),
    State("marca_canal", "value"),
    State("marca_arribo", "data"),
    State("ediciones_arribo", "data"),
    prevent_initial_call=True,
)
def gestionar_ediciones_arribo(n_fijar, n_quitar, n_undo, n_rest, carpeta, seg, canal_sel,
                               marca=None, store=None):
    """Fijar el arribo en la marca, quitar el disparo del promedio, deshacer y
    restaurar. Cada acción es un paso del historial del canal guardado en metadata.yaml."""
    trig = ctx.triggered_id if ctx.triggered else None
    if not carpeta or not seg:
        return no_update, "Elija una medición."
    hay_marca = bool(marca and marca.get("carpeta") == carpeta and marca.get("seg") == int(seg)
                     and marca.get("t_us") is not None)
    canal = marca["canal"] if hay_marca else canal_sel
    if canal not in ("ch2", "ch3", "ch4"):
        return no_update, "Elija el canal de la marca."
    canales = _ed_canales(store, carpeta) or ediciones_medicion(carpeta)
    hist = [dict(h) for h in (canales.get(canal) or {}).get("historial") or []]

    if trig == "btn_fijar_arribo":
        if not hay_marca:
            return no_update, "Ponga primero la marca sobre la señal del canal (clic o t)."
        t = round(float(marca["t_us"]), 6)
        hist.append({"accion": "fijar", "seg": int(seg), "t_us": t,
                     "desc": f"Arribo manual {canal.upper()} disparo {int(seg)}"})
        ok_msg = f"✓ Arribo {canal.upper()} fijado: disparo {int(seg)}, t_ant = {t:.4f} µs"
    elif trig == "btn_quitar_arribo":
        hist.append({"accion": "quitar", "seg": int(seg),
                     "desc": f"Disparo {int(seg)} quitado de {canal.upper()}"})
        ok_msg = f"✓ Disparo {int(seg)} quitado del promedio de {canal.upper()}"
    elif trig == "btn_deshacer_arribo":
        if not hist:
            return no_update, ""
        ok_msg = f"✓ Deshecho: {hist.pop().get('desc') or 'último paso'}"
    elif trig == "btn_restaurar_arribo":
        if not hist:
            return no_update, ""
        hist = []
        ok_msg = f"✓ Ediciones de {canal.upper()} restauradas"
    else:
        return no_update, no_update

    ok, msg = guardar_ediciones_canal(carpeta, canal, {"historial": hist})
    if not ok:
        return no_update, f"No se guardaron las ediciones: {msg}"
    canales = dict(canales)
    canales[canal] = {"historial": hist}
    return {"carpeta": carpeta, "canales": canales}, ok_msg


@app.callback(
    Output("aviso_arribo", "style"),
    Input("aviso_arribo", "children"),
)
def estilo_aviso_arribo(texto):
    """Avisos de éxito (empiezan por ✓) en verde; el resto en rojo."""
    ok = isinstance(texto, str) and texto.startswith("✓")
    return {"fontSize": "11px", "fontWeight": "600" if ok else "normal",
            "color": tema.OK if ok else tema.ERROR}


@app.callback(
    Output("btn_fijar_arribo", "disabled"),
    Output("btn_quitar_arribo", "disabled"),
    Output("btn_deshacer_arribo", "disabled"),
    Output("btn_restaurar_arribo", "disabled"),
    Output("badge_arribo", "children"),
    Input("ediciones_arribo", "data"),
    Input("marca_arribo", "data"),
    Input("marca_canal", "value"),
    State("carpeta", "value"),
)
def estado_botones_arribo(store, marca, canal_sel, carpeta):
    """Botones habilitados según la marca y el historial del canal de la marca."""
    if not carpeta:
        return True, True, True, True, ""
    hay_marca = bool(marca and marca.get("carpeta") == carpeta and marca.get("t_us") is not None)
    canal = marca["canal"] if hay_marca else canal_sel
    ed = _ed_canales(store, carpeta).get(canal) or {}
    sin_hist = not ed.get("historial")
    est = estado_ediciones(ed)
    n_man, n_quit = len(est["manuales"]), len(est["quitados"])
    badge = (f"{(canal or '').upper()}: {n_man} manual{'es' if n_man != 1 else ''} · "
             f"{n_quit} quitado{'s' if n_quit != 1 else ''}") if not sin_hist else \
        f"{(canal or '').upper()}: sin ediciones manuales"
    return not hay_marca, not canal, sin_hist, sin_hist, badge


@app.callback(
    Output("segmento", "value", allow_duplicate=True),
    Output("marca_canal", "value", allow_duplicate=True),
    Input("grafico_dispersion", "clickData"),
    State("canal_dispersion", "value"),
    State("segmento", "value"),
    prevent_initial_call=True,
)
def ir_a_disparo_dispersion(click, canal_disp, seg_actual):
    """Clic en un punto de la dispersión → ese disparo en el gráfico multicanal,
    con el canal de la marca en el canal de la dispersión."""
    if not click or not click.get("points"):
        return no_update, no_update
    x = click["points"][0].get("x")
    try:
        s = int(round(float(x)))
    except (TypeError, ValueError):
        return no_update, no_update
    return (s if s != seg_actual else no_update), (canal_disp or no_update)


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
    State("tmax_ch2", "value"),
    State("tmax_ch3", "value"),
    State("tmax_ch4", "value"),
    prevent_initial_call=True,
    running=[(Output("btn_calcular", "disabled"), True, False)],
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
    tmax2: float | None = None,
    tmax3: float | None = None,
    tmax4: float | None = None,
):
    """Calcula el retardo para el canal seleccionado (o todos) con triggers independientes por canal."""
    if not n_clicks or not carpeta or not canal:
        return no_update

    store = dict(store_actual or {})
    if store.get("_carpeta") != carpeta:
        store = {"_carpeta": carpeta}

    dt_us = float(dtcal or 0.05)

    cfg_map = {
        "ch2": (u2 if u2 is not None else (ucal if canal == "ch2" and ucal is not None else None), tmin2 if tmin2 is not None else tmincal),
        "ch3": (u3 if u3 is not None else (ucal if canal == "ch3" and ucal is not None else None), tmin3 if tmin3 is not None else tmincal),
        "ch4": (u4 if u4 is not None else (ucal if canal in ("ch4", "todos") and ucal is not None else None), tmin4 if tmin4 is not None else tmincal),
    }

    tmax_map = {"ch2": tmax2, "ch3": tmax3, "ch4": tmax4}

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
            tmax=tmax_map.get(c),
        )
        store[c] = res

    store["_referencia"] = ref
    return store


@app.callback(
    Output("iec_store", "data"),
    Input("btn_evaluar_iec", "n_clicks"),
    Input("carpeta", "value"),
    running=[(Output("btn_evaluar_iec", "disabled"), True, False)],
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
    Input("ediciones_arribo", "data"),
)
def actualizar_grafico_dispersion(store: dict | None, canal: str = "ch4", store_ed: dict | None = None):
    """Muestra la dispersión e histograma del retardo del canal seleccionado en el gráfico
    (con los arribos editados a mano aplicados)."""
    ch_target = canal or "ch4"
    store = resultados_editados(store, store_ed)
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
    Input("ediciones_arribo", "data"),
)
def actualizar_tabla_resumen(store: dict | None, carpeta: str, store_ed: dict | None = None):
    """Genera la tabla resumen de canales calibrados (con las ediciones manuales aplicadas)."""
    store = resultados_editados(store, store_ed)
    if not store:
        return html.P("Sin canales calibrados en la sesión actual. Pulsa Calcular Retardo.", style={"color": tema.MUTED, "fontSize": "13px"})

    sensores_map = {
        "ch2": "HFCT",
        "ch3": "Antena 1",
        "ch4": "Antena 2",
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
                html.Td(t_lag_ns, style={"fontWeight": "700", "color": tema.ACCENT, "padding": "6px 10px"}),
                html.Td(sig_ns, style={"padding": "6px 10px"}),
                html.Td(f"{r.get('n_valid')}/{r.get('n_total')}" + _detalle_ediciones(r),
                        style={"padding": "6px 10px"}),
                html.Td(f"{p.get('umbral_mv', 0):.2f}", style={"padding": "6px 10px"}),
                html.Td(f"{p.get('distancia_us', 0):.3f}", style={"padding": "6px 10px"}),
                html.Td(f"{p.get('tmin_us', 0):.3f}", style={"padding": "6px 10px"}),
                html.Td(f"{p['tmax_us']:.3f}" if p.get("tmax_us") is not None else "—",
                        style={"padding": "6px 10px"}),
                html.Td(filtros.etiqueta(spec_filtro(carpeta, ch)) if carpeta else "—",
                        style={"padding": "6px 10px"}),
            ]))

    if not filas:
        return html.P("Sin canales calibrados en la sesión actual. Pulsa Calcular Retardo.", style={"color": tema.MUTED, "fontSize": "13px"})

    tabla = html.Table(
        style={"width": "100%", "fontSize": "12px", "borderCollapse": "collapse", "textAlign": "left"},
        children=[
            html.Thead(html.Tr([
                html.Th("Canal", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("Sensor", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("t̄_lag [ns]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("σ [ns]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("Válidos", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("u_cal [mV]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("Δt [µs]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("t_mín [µs]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("t_máx [µs]", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
                html.Th("Filtro", style={"borderBottom": f"2px solid {tema.BORDER}", "padding": "6px 10px"}),
            ])),
            html.Tbody(filas),
        ],
    )
    aviso = aviso_calibracion_cruda(carpeta)
    return html.Div([tabla, aviso]) if aviso else tabla


def _detalle_ediciones(r: dict) -> str:
    """' (2 man., 1 quit.)' si el canal tiene arribos editados a mano."""
    partes = []
    if r.get("n_manual"):
        partes.append(f"{r['n_manual']} man.")
    if r.get("n_quitados"):
        partes.append(f"{r['n_quitados']} quit.")
    return f" ({', '.join(partes)})" if partes else ""


def aviso_calibracion_cruda(carpeta: str):
    """Aviso si metadata.yaml guarda una calibración sin campo 'filtro' por canal:
    se midió sobre señal cruda y no es coherente con la señal filtrada actual."""
    bloque = (obtener_metadata(carpeta) or {}).get("calibracion_retardo") if carpeta else None
    if not isinstance(bloque, dict):
        return None
    crudos = [ch.upper() for ch in ["ch2", "ch3", "ch4"]
              if isinstance(bloque.get(ch), dict) and "filtro" not in bloque[ch]]
    if not crudos:
        return None
    return html.Div(
        f"La calibración guardada en metadata.yaml para {', '.join(crudos)} se hizo sobre señal "
        "cruda: recalibrar con los filtros actuales.",
        style={"color": tema.WARN, "backgroundColor": tema.WARN_BG, "padding": "6px 10px",
               "borderRadius": "4px", "border": f"1px solid {tema.WARN}", "marginTop": "8px",
               "fontSize": "12px"})


@app.callback(
    Output("panel_iec_resumen", "children"),
    Input("iec_store", "data"),
)
def actualizar_panel_iec(store: dict | None):
    """Muestra el estado de conformidad normativa IEC 60060-1."""
    if not store:
        return html.P("Cargando diagnóstico IEC...", style={"color": tema.MUTED, "fontSize": "13px"})

    iec = store.get("resumen_iec", {})
    delta = store.get("delta", {})

    t1 = f"{iec.get('T1_medio_us', 0):.3f} µs" if iec.get("T1_medio_us") is not None else "—"
    t2 = f"{iec.get('T2_medio_us', 0):.2f} µs" if iec.get("T2_medio_us") is not None else "—"
    beta = f"{iec.get('beta_medio_pct', 0):.2f} %" if iec.get("beta_medio_pct") is not None else "—"
    delta_ns = f"{delta.get('media_us', 0) * 1e3:.1f} ± {delta.get('sigma_us', 0) * 1e3:.1f} ns" if delta.get("media_us") is not None else "—"
    conforme = iec.get("conforme", False)
    fuera = iec.get("fuera_tolerancia", 0)

    color_conf = tema.OK if conforme else tema.ERROR
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
    State("ediciones_arribo", "data"),
    prevent_initial_call=True,
    running=[(Output("btn_guardar", "disabled"), True, False)],
)
def guardar_en_metadata(n_clicks: int, carpeta: str, store: dict | None, fuente: str, ref: str,
                        store_ed: dict | None = None):
    """Persiste los retardos calculados (con los arribos editados a mano) en metadata.yaml."""
    if not n_clicks or not carpeta or not store:
        return no_update
    store = resultados_editados(store, store_ed)

    canales_validos = {ch: store[ch] for ch in ["ch2", "ch3", "ch4"] if ch in store}
    if not canales_validos:
        return html.Div("No hay canales calculados para guardar. Pulsa primero Calcular Retardo.",
                        style={"color": tema.WARN, "backgroundColor": tema.WARN_BG, "padding": "8px 12px", "borderRadius": "4px", "border": f"1px solid {tema.WARN}"})

    info_ancla = None
    if ref == "origen_virtual_IEC60060":
        info_ancla = construir_info_ancla(carpeta)

    bloque = bloque_calibracion_retardo(
        resultados=canales_validos,
        fuente=fuente or "calibrar_app",
        referencia_impulso=ref,
        info_ancla=info_ancla,
        filtros={ch: filtros.texto(spec_filtro(carpeta, ch)) for ch in canales_validos},
    )
    # Trazabilidad: cuántos arribos del promedio se fijaron o quitaron a mano
    for ch, r in canales_validos.items():
        if isinstance(bloque.get(ch), dict) and (r.get("n_manual") or r.get("n_quitados")):
            bloque[ch]["n_arribos_manuales"] = int(r.get("n_manual") or 0)
            bloque[ch]["n_disparos_quitados"] = int(r.get("n_quitados") or 0)
    ok, msg = guardar_calibracion_metadata(carpeta, bloque)
    if ok:
        return html.Div(
            f"{msg} · Bloque calibracion_retardo actualizado exitosamente con referencia '{ref}'.",
            style={"color": tema.OK, "backgroundColor": tema.OK_BG, "padding": "8px 12px", "borderRadius": "4px", "fontWeight": "600", "border": f"1px solid {tema.OK}"}
        )
    return html.Div(
        f"{msg}",
        style={"color": tema.ERROR, "backgroundColor": tema.ERROR_BG, "padding": "8px 12px", "borderRadius": "4px", "border": f"1px solid {tema.ERROR}"}
    )


if __name__ == "__main__":
    print("Iniciando servidor calibrar_app en http://127.0.0.1:8052 ...")
    app.run(host="127.0.0.1", port=8052, debug=False)
