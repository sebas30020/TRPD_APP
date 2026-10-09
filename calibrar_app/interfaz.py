"""Definición del layout y componentes visuales para calibrar_app."""

from __future__ import annotations
import os
import sys
from dash import dcc, html

_RAIZ = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)
import rutas  # noqa: E402
import tema   # noqa: E402

ESTILO_CONTENEDOR = tema.ESTILO_CONTENEDOR
ESTILO_CARD = tema.ESTILO_CARD
ESTILO_BOTON_PRIMARY = tema.ESTILO_BOTON_PRIMARY
ESTILO_BOTON_SECONDARY = tema.ESTILO_BOTON_SECONDARY
ESTILO_BOTON_SUCCESS = tema.ESTILO_BOTON_SUCCESS
ESTILO_BOTON_STEPPER = tema.ESTILO_BOTON_STEPPER


def layout(mediciones: list[str], carpeta_inicial: str = "") -> html.Div:
    """Construye el árbol de componentes del layout de calibrar_app."""
    med_options = [{"label": rutas.etiqueta(m), "value": m, "title": m} for m in mediciones]

    return html.Div(
        style=ESTILO_CONTENEDOR,
        children=[
            # Stores
            dcc.Store(id="resultado_store", data={}),
            dcc.Store(id="iec_store", data={}),
            # Ediciones manuales de arribos ({"carpeta", "canales": {ch: {"historial"}}})
            # y marca temporal de edición ({carpeta, canal, seg, t_us})
            dcc.Store(id="ediciones_arribo"),
            dcc.Store(id="marca_arribo"),
            dcc.Store(id="metadata_asegurada"),  # resultado de generate_metadata al abrir la medición
            dcc.Store(id="explorador_ruta_actual", data=rutas.ruta_inicial()),
            # TRPD_APP la abre embebida con ?embebido=1&carpeta=<medición>
            dcc.Location(id="url", refresh=False),

            # Cabecera
            html.Div(
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "marginBottom": "16px",
                    "borderBottom": f"1px solid {tema.BORDER}",
                    "paddingBottom": "12px",
                },
                children=[
                    html.Div([
                        html.H1(
                            "Calibración de Retardo Instrumental y Conformidad IEC 60060-1",
                            style={"fontSize": "20px", "margin": "0 0 4px 0", "color": tema.INK},
                        ),
                        html.P(
                            "Estimación robusta de retardos instrumentales (t_lag) con referencia t10 / origen virtual O1 (Anexo B).",
                            style={"margin": "0", "fontSize": "13px", "color": tema.MUTED},
                        ),
                    ]),
                    html.Div([
                        html.Span(
                            "Puerto 8052 · Modo Autónomo",
                            id="badge_modo",
                            style=tema.BADGE_INFO,
                        ),
                        html.A(
                            "Volver a TRPD_APP (8051)",
                            id="enlace_volver",
                            href="http://127.0.0.1:8051",
                            target="_blank",
                            style={
                                "fontSize": "13px",
                                "color": tema.ACCENT,
                                "textDecoration": "none",
                                "fontWeight": "600",
                                "marginLeft": "12px",
                            },
                        ),
                    ]),
                ],
            ),

            # Fila de Controles Principales
            html.Div(
                style=ESTILO_CARD,
                children=[
                    html.Div(
                        style={
                            "display": "grid",
                            "gridTemplateColumns": "2.2fr 1.8fr 1fr",
                            "gap": "16px",
                            "alignItems": "center",
                            "marginBottom": "12px",
                        },
                        children=[
                            html.Div([
                                html.Div(
                                    style={"display": "flex", "justifyContent": "space-between", "alignItems": "center"},
                                    children=[
                                        html.Label("Medición:", style={"fontWeight": "600", "fontSize": "13px", "color": tema.INK}),
                                        html.Button("Examinar…", id="btn_examinar", n_clicks=0,
                                                    style={"backgroundColor": tema.NEUTRAL_BTN, "color": "white", "border": "none",
                                                           "borderRadius": "4px", "padding": "2px 8px", "cursor": "pointer",
                                                           "fontSize": "12px"}),
                                    ],
                                ),
                                dcc.Dropdown(
                                    id="carpeta",
                                    options=med_options,
                                    value=carpeta_inicial or (mediciones[0] if mediciones else None),
                                    clearable=False,
                                    placeholder="Elija una carpeta con Examinar…",
                                    style={"marginTop": "4px", "fontSize": "13px"},
                                ),
                            ]),
                            html.Div([
                                html.Label("Referencia de Impulso:", style={"fontWeight": "600", "fontSize": "13px", "color": tema.INK}),
                                dcc.RadioItems(
                                    id="referencia",
                                    options=[
                                        {"label": " t10 (10% CH1)", "value": "t10"},
                                        {"label": " Origen virtual O1 (IEC 60060-1)", "value": "origen_virtual_IEC60060"},
                                    ],
                                    value="t10",
                                    inline=True,
                                    inputStyle={"marginRight": "4px", "marginLeft": "8px"},
                                    style={"marginTop": "8px", "fontSize": "13px"},
                                ),
                            ]),
                            html.Div([
                                html.Label("Fuente en Metadata:", style={"fontWeight": "600", "fontSize": "13px", "color": tema.INK}),
                                dcc.Input(
                                    id="fuente_calibracion",
                                    type="text",
                                    value="calibrar_app",
                                    style={"width": "100%", "padding": "6px", "marginTop": "4px", "borderRadius": "4px", "border": f"1px solid {tema.BORDER}"},
                                ),
                            ]),
                        ],
                    ),

                    # Fila Multi-Trigger: Controles independientes por canal (CH2, CH3, CH4)
                    html.Div(
                        style={
                            "display": "flex", "gap": "10px", "alignItems": "center",
                            "padding": "8px 12px", "backgroundColor": tema.BG,
                            "border": f"1px solid {tema.BORDER}", "borderRadius": "6px",
                            "marginBottom": "12px", "flexWrap": "wrap",
                        },
                        children=[
                            html.Span("Triggers por canal:",
                                      style={"fontSize": "12px", "fontWeight": "bold", "color": tema.INK, "marginRight": "4px"}),
                            # CH2: HFCT
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": tema.CARD,
                                    "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch2']}",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH2 (HFCT):", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch2"]}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch2", debounce=True, type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch2", debounce=True, type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_máx [µs]:"),
                                    dcc.Input(id="tmax_ch2", debounce=True, type="number", step=0.005,
                                              placeholder="sin límite",
                                              style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # CH3: Antena 1
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": tema.CARD,
                                    "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch3']}",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH3 (Antena 1):", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch3"]}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch3", debounce=True, type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch3", debounce=True, type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_máx [µs]:"),
                                    dcc.Input(id="tmax_ch3", debounce=True, type="number", step=0.005,
                                              placeholder="sin límite",
                                              style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # CH4: Antena 2
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": tema.CARD,
                                    "border": f"1px solid {tema.BORDER}", "borderLeft": f"4px solid {tema.COLORES_CANALES['ch4']}",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH4 (Antena 2):", style={"fontWeight": "bold", "color": tema.COLORES_CANALES["ch4"]}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch4", debounce=True, type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch4", debounce=True, type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_máx [µs]:"),
                                    dcc.Input(id="tmax_ch4", debounce=True, type="number", step=0.005,
                                              placeholder="sin límite",
                                              style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # Inputs ocultos para retrocompatibilidad con tests existentes
                            html.Div(style={"display": "none"}, children=[
                                dcc.Input(id="canal", value="todos"),
                                dcc.Input(id="ucal", type="number"),
                                dcc.Input(id="dtcal", type="number", value=0.05),
                                dcc.Input(id="tmincal", type="number", value=0.15),
                            ]),
                        ],
                    ),

                    # Subfila de Segmento y Botones de Acción
                    html.Div(
                        style={
                            "display": "grid",
                            "gridTemplateColumns": "2fr 3fr",
                            "gap": "16px",
                            "alignItems": "center",
                            "backgroundColor": tema.HEADER_TABLE,
                            "padding": "10px 14px",
                            "borderRadius": "6px",
                        },
                        children=[
                            html.Div([
                                html.Div(
                                    style={"display": "flex", "justifyContent": "space-between", "marginBottom": "4px"},
                                    children=[
                                        html.Label("Inspeccionar Disparo / Segmento:", style={"fontWeight": "600", "fontSize": "12px"}),
                                        html.Span(id="label_segmento", style={"fontWeight": "700", "fontSize": "12px", "color": tema.ACCENT}),
                                    ]
                                ),
                                html.Div(
                                    style={"display": "flex", "alignItems": "center", "gap": "6px"},
                                    children=[
                                        html.Button("◀", id="segmento_prev", n_clicks=0, style=ESTILO_BOTON_STEPPER),
                                        dcc.Input(id="segmento", type="number", min=1, max=50, step=1, value=1,
                                                  debounce=True, style={"width": "64px", "textAlign": "center"}),
                                        html.Span(id="segmento_total", children="/ 50",
                                                  style={"fontSize": "12px", "color": tema.MUTED}),
                                        html.Button("▶", id="segmento_next", n_clicks=0, style=ESTILO_BOTON_STEPPER),
                                    ],
                                ),
                            ]),
                            html.Div(
                                style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
                                children=[
                                    html.Button("Calcular Retardo", id="btn_calcular", style=ESTILO_BOTON_PRIMARY, n_clicks=0),
                                    html.Button("Evaluar IEC", id="btn_evaluar_iec", style=ESTILO_BOTON_SECONDARY, n_clicks=0),
                                    html.Button("Guardar en metadata.yaml", id="btn_guardar", style=ESTILO_BOTON_SUCCESS, n_clicks=0),
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Panel Explorador de Carpetas
            html.Div(
                id="explorador_panel",
                hidden=False,
                style={
                    **ESTILO_CARD,
                    "backgroundColor": tema.BG,
                    "border": f"1px solid {tema.BORDER}",
                    "marginBottom": "16px",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "10px", "marginBottom": "10px"},
                        children=[
                            html.Button("Subir nivel", id="explorador_subir", n_clicks=0,
                                        style={"backgroundColor": tema.NEUTRAL_BTN, "color": "white", "border": "none",
                                               "borderRadius": "4px", "padding": "4px 10px", "cursor": "pointer"}),
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
                                        style={"backgroundColor": tema.ACCENT, "color": "white", "fontWeight": "600",
                                               "border": "none", "borderRadius": "4px", "padding": "6px 14px", "cursor": "pointer"}),
                            html.Button("Cancelar", id="explorador_cancelar", n_clicks=0,
                                        style={"backgroundColor": tema.MUTED_LIGHT, "color": "white",
                                               "border": "none", "borderRadius": "4px", "padding": "6px 14px", "cursor": "pointer"}),
                        ],
                    ),
                ],
            ),

            # Mensajes de feedback
            html.Div(id="msg_feedback", style={"marginBottom": "12px"}),

            # Sección 1: Inspección Multicanal Sincronizada (CH1..CH4)
            html.Div(
                style=ESTILO_CARD,
                children=[
                    html.Div(
                        style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "6px"},
                        children=[
                            html.H3("Inspección Multicanal Sincronizada (CH1 Impulso vs CH2–CH4 Sensores)",
                                    style={"fontSize": "15px", "margin": "0", "color": tema.INK}),
                            html.Span("Nota: Arrastra la línea horizontal de umbral con el ratón en cualquier canal (CH2–CH4) para ajustar su trigger en tiempo real.",
                                      style={"fontSize": "12px", "color": tema.ACCENT, "fontWeight": "500"}),
                        ],
                    ),
                    # Barra de edición manual de arribos (como «Añadir peak» de TRPD_APP)
                    html.Div(
                        style={
                            "display": "flex", "alignItems": "center", "gap": "6px",
                            "padding": "6px 8px", "backgroundColor": tema.BG,
                            "border": f"1px solid {tema.BORDER}", "borderRadius": "6px",
                            "marginBottom": "6px", "flexWrap": "wrap", "fontSize": "11px",
                        },
                        title="Fijar: clic sobre la señal de CH2–CH4 en el instante del arribo (o escriba t) → "
                              "«Fijar arribo en la marca». Quitar: clic en la ✕/rombo del arribo (o ponga la "
                              "marca en ese canal) → «Quitar disparo»: el disparo no entra al promedio del canal.",
                        children=[
                            html.Span("Marca:", style={"fontWeight": "bold", "color": tema.INK}),
                            dcc.Dropdown(id="marca_canal", options=[{"label": c.upper(), "value": c}
                                                                    for c in ("ch2", "ch3", "ch4")],
                                         value="ch2", clearable=False, searchable=False,
                                         style={"width": "80px", "fontSize": "11px"}),
                            html.Span("t [µs]:", style={"fontWeight": "bold", "color": tema.INK}),
                            dcc.Input(id="marca_t", type="number", step="any", debounce=True,
                                      placeholder="clic en la señal",
                                      style={"width": "110px", "fontSize": "11px", "padding": "3px 5px",
                                             "borderRadius": "4px", "border": f"1px solid {tema.BORDER}"}),
                            html.Button("Fijar arribo en la marca", id="btn_fijar_arribo", n_clicks=0, disabled=True,
                                        style=tema.ESTILO_BOTON_SUCCESS),
                            html.Button("Quitar disparo", id="btn_quitar_arribo", n_clicks=0, disabled=True,
                                        style=tema.ESTILO_BOTON_DANGER),
                            html.Button("Deshacer", id="btn_deshacer_arribo", n_clicks=0, disabled=True,
                                        style=tema.ESTILO_BOTON_WARN),
                            html.Button("Restaurar canal", id="btn_restaurar_arribo", n_clicks=0, disabled=True,
                                        style=tema.ESTILO_BOTON_SECONDARY),
                            html.Span(id="aviso_arribo", style={"fontSize": "11px", "color": tema.ERROR}),
                            html.Span(id="badge_arribo", style={"fontSize": "11px", "color": tema.MUTED,
                                                                "fontWeight": "600", "marginLeft": "auto"}),
                        ],
                    ),
                    dcc.Loading(dcc.Graph(id="grafico_canal", config={"displayModeBar": True, "edits": {"shapePosition": True}})),
                ],
            ),

            # Sección 2: Fila de Evaluación Normativa y Dispersión
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1.1fr 0.9fr", "gap": "16px", "marginBottom": "16px"},
                children=[
                    html.Div(
                        style=ESTILO_CARD,
                        children=[
                            html.H3("Evaluación Normativa IEC 60060-1 (CH1 Impulso)", style={"fontSize": "15px", "margin": "0 0 10px 0", "color": tema.INK}),
                            dcc.Loading(dcc.Graph(id="grafico_impulso", config={"displayModeBar": True})),
                        ],
                    ),
                    html.Div(
                        style=ESTILO_CARD,
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"},
                                children=[
                                    html.H3("Dispersión del Retardo (t_lag)", style={"fontSize": "15px", "margin": "0", "color": tema.INK}),
                                    dcc.RadioItems(
                                        id="canal_dispersion",
                                        options=[
                                            {"label": " CH2 (HFCT)", "value": "ch2"},
                                            {"label": " CH3 (Antena 1)", "value": "ch3"},
                                            {"label": " CH4 (Antena 2)", "value": "ch4"},
                                        ],
                                        value="ch4",
                                        inline=True,
                                        inputStyle={"marginRight": "3px", "marginLeft": "8px"},
                                        style={"fontSize": "12px", "fontWeight": "600"},
                                    ),
                                ],
                            ),
                            dcc.Loading(dcc.Graph(id="grafico_dispersion", config={"displayModeBar": True})),
                        ],
                    ),
                ],
            ),

            # Sección 3: Estabilidad de Ancla por Disparo
            html.Div(
                style={"marginBottom": "16px"},
                children=[
                    html.Div(
                        style=ESTILO_CARD,
                        children=[
                            dcc.Loading(dcc.Graph(id="grafico_ancla", config={"displayModeBar": True})),
                        ],
                    ),
                ],
            ),

            # Resumen y Estadísticas
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "1.4fr 1fr", "gap": "16px"},
                children=[
                    html.Div(style=ESTILO_CARD, children=[
                        html.H3("Resumen de Calibración por Canal", style={"fontSize": "15px", "margin": "0 0 10px 0", "color": tema.INK}),
                        dcc.Loading(html.Div(id="tabla_resumen"), type="circle", delay_show=300, color=tema.ACCENT),
                    ]),
                    html.Div(style=ESTILO_CARD, children=[
                        html.H3("Diagnóstico y Conformidad IEC 60060-1", style={"fontSize": "15px", "margin": "0 0 10px 0", "color": tema.INK}),
                        dcc.Loading(html.Div(id="panel_iec_resumen"), type="circle", delay_show=300, color=tema.ACCENT),
                    ]),
                ],
            ),
        ],
    )
