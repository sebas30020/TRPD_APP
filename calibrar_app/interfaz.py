"""Definición del layout y componentes visuales para calibrar_app."""

from __future__ import annotations
from dash import dcc, html


ESTILO_CONTENEDOR = {
    "fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "maxWidth": "1560px",
    "margin": "0 auto",
    "padding": "20px 24px",
    "backgroundColor": "#f8fafc",
    "color": "#1e293b",
}

ESTILO_CARD = {
    "backgroundColor": "#ffffff",
    "borderRadius": "8px",
    "border": "1px solid #e2e8f0",
    "padding": "16px",
    "marginBottom": "16px",
    "boxShadow": "0 1px 3px rgba(0,0,0,0.05)",
}

ESTILO_BOTON_PRIMARY = {
    "backgroundColor": "#2563eb",
    "color": "white",
    "border": "none",
    "borderRadius": "6px",
    "padding": "8px 16px",
    "fontWeight": "600",
    "fontSize": "14px",
    "cursor": "pointer",
    "marginRight": "8px",
}

ESTILO_BOTON_SECONDARY = {
    "backgroundColor": "#475569",
    "color": "white",
    "border": "none",
    "borderRadius": "6px",
    "padding": "8px 16px",
    "fontWeight": "600",
    "fontSize": "14px",
    "cursor": "pointer",
    "marginRight": "8px",
}

ESTILO_BOTON_SUCCESS = {
    "backgroundColor": "#16a34a",
    "color": "white",
    "border": "none",
    "borderRadius": "6px",
    "padding": "8px 16px",
    "fontWeight": "600",
    "fontSize": "14px",
    "cursor": "pointer",
}


def layout(mediciones: list[str], carpeta_inicial: str = "") -> html.Div:
    """Construye el árbol de componentes del layout de calibrar_app."""
    med_options = [{"label": m, "value": m} for m in mediciones]

    return html.Div(
        style=ESTILO_CONTENEDOR,
        children=[
            # Stores
            dcc.Store(id="resultado_store", data={}),
            dcc.Store(id="iec_store", data={}),

            # Cabecera
            html.Div(
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "center",
                    "marginBottom": "16px",
                    "borderBottom": "2px solid #e2e8f0",
                    "paddingBottom": "12px",
                },
                children=[
                    html.Div([
                        html.H1(
                            "⚡ Calibración de Retardo Instrumental y Conformidad IEC 60060-1",
                            style={"fontSize": "22px", "margin": "0 0 4px 0", "color": "#0f172a"},
                        ),
                        html.P(
                            "Estimación robusta de retardos instrumentales (t_lag) con referencia t10 / origen virtual O1 (Anexo B).",
                            style={"margin": "0", "fontSize": "13px", "color": "#64748b"},
                        ),
                    ]),
                    html.Div([
                        html.Span(
                            "Puerto 8051 · Modo Autónomo",
                            style={
                                "backgroundColor": "#eff6ff",
                                "color": "#1d4ed8",
                                "padding": "4px 10px",
                                "borderRadius": "20px",
                                "fontSize": "12px",
                                "fontWeight": "600",
                                "marginRight": "12px",
                                "border": "1px solid #bfdbfe",
                            },
                        ),
                        html.A(
                            "🔗 Ir a TRPD_APP (8050)",
                            href="http://127.0.0.1:8050",
                            target="_blank",
                            style={
                                "fontSize": "13px",
                                "color": "#2563eb",
                                "textDecoration": "none",
                                "fontWeight": "600",
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
                                html.Label("Medición:", style={"fontWeight": "600", "fontSize": "13px"}),
                                dcc.Dropdown(
                                    id="carpeta",
                                    options=med_options,
                                    value=carpeta_inicial or (mediciones[0] if mediciones else ""),
                                    clearable=False,
                                    style={"marginTop": "4px", "fontSize": "13px"},
                                ),
                            ]),
                            html.Div([
                                html.Label("Referencia de Impulso:", style={"fontWeight": "600", "fontSize": "13px"}),
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
                                html.Label("Fuente en Metadata:", style={"fontWeight": "600", "fontSize": "13px"}),
                                dcc.Input(
                                    id="fuente_calibracion",
                                    type="text",
                                    value="calibrar_app",
                                    style={"width": "100%", "padding": "6px", "marginTop": "4px", "borderRadius": "4px", "border": "1px solid #cbd5e1"},
                                ),
                            ]),
                        ],
                    ),

                    # Fila Multi-Trigger: Controles independientes por canal (CH2, CH3, CH4)
                    html.Div(
                        style={
                            "display": "flex", "gap": "10px", "alignItems": "center",
                            "padding": "8px 12px", "backgroundColor": "#f8fafc",
                            "border": "1px solid #e2e8f0", "borderRadius": "6px",
                            "marginBottom": "12px", "flexWrap": "wrap",
                        },
                        children=[
                            html.Span("🎯 Triggers por Canal:",
                                      style={"fontSize": "12px", "fontWeight": "bold", "color": "#1e293b", "marginRight": "4px"}),
                            # CH2: HFCT
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": "white",
                                    "border": "1px solid #bfdbfe", "borderLeft": "4px solid #2563eb",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH2 (HFCT):", style={"fontWeight": "bold", "color": "#1d4ed8"}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch2", type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch2", type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # CH3: Vivaldi
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": "white",
                                    "border": "1px solid #a7f3d0", "borderLeft": "4px solid #059669",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH3 (Vivaldi):", style={"fontWeight": "bold", "color": "#047857"}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch3", type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch3", type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # CH4: Bioinspirada
                            html.Div(
                                style={
                                    "display": "flex", "alignItems": "center", "gap": "6px",
                                    "padding": "4px 10px", "backgroundColor": "white",
                                    "border": "1px solid #fde68a", "borderLeft": "4px solid #d97706",
                                    "borderRadius": "4px", "fontSize": "12px",
                                },
                                children=[
                                    html.Span("CH4 (Bioinspirada):", style={"fontWeight": "bold", "color": "#d97706"}),
                                    html.Span("u [mV]:"),
                                    dcc.Input(id="umbral_ch4", type="number", step=0.1, style={"width": "75px", "fontSize": "12px", "padding": "2px 4px"}),
                                    html.Span("t_mín [µs]:"),
                                    dcc.Input(id="tmin_ch4", type="number", step=0.005, value=0.15, style={"width": "65px", "fontSize": "12px", "padding": "2px 4px"}),
                                ],
                            ),
                            # Inputs ocultos para retrocompatibilidad con tests existentes
                            html.Div(style={"display": "none"}, children=[
                                dcc.Input(id="canal", value="todos"),
                                dcc.Input(id="ucal", type="number"),
                                dcc.Input(id="dtcal", type="number", value=0.035),
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
                            "backgroundColor": "#f1f5f9",
                            "padding": "10px 14px",
                            "borderRadius": "6px",
                        },
                        children=[
                            html.Div([
                                html.Div(
                                    style={"display": "flex", "justifyContent": "space-between"},
                                    children=[
                                        html.Label("Inspeccionar Disparo / Segmento:", style={"fontWeight": "600", "fontSize": "12px"}),
                                        html.Span(id="label_segmento", style={"fontWeight": "700", "fontSize": "12px", "color": "#2563eb"}),
                                    ]
                                ),
                                dcc.Slider(
                                    id="segmento",
                                    min=1,
                                    max=50,
                                    step=1,
                                    value=1,
                                    marks={1: "1", 10: "10", 25: "25", 50: "50"},
                                ),
                            ]),
                            html.Div(
                                style={"display": "flex", "alignItems": "center", "justifyContent": "flex-end"},
                                children=[
                                    html.Button("▶ Calcular Retardo", id="btn_calcular", style=ESTILO_BOTON_PRIMARY, n_clicks=0),
                                    html.Button("📐 Evaluar IEC", id="btn_evaluar_iec", style=ESTILO_BOTON_SECONDARY, n_clicks=0),
                                    html.Button("💾 Guardar YAML", id="btn_guardar", style=ESTILO_BOTON_SUCCESS, n_clicks=0),
                                ],
                            ),
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
                            html.H3("📊 Inspección Multicanal Sincronizada (CH1 Impulso vs CH2–CH4 Sensores)",
                                    style={"fontSize": "15px", "margin": "0", "color": "#0f172a"}),
                            html.Span("💡 Tip: Arrastra la línea horizontal de umbral con el ratón en cualquier canal (CH2–CH4) para ajustar su trigger en tiempo real.",
                                      style={"fontSize": "12px", "color": "#2563eb", "fontWeight": "500"}),
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
                            html.H3("📐 Evaluación Normativa IEC 60060-1 (CH1 Impulso)", style={"fontSize": "15px", "margin": "0 0 10px 0"}),
                            dcc.Loading(dcc.Graph(id="grafico_impulso", config={"displayModeBar": True})),
                        ],
                    ),
                    html.Div(
                        style=ESTILO_CARD,
                        children=[
                            html.Div(
                                style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"},
                                children=[
                                    html.H3("⏱️ Dispersión del Retardo (t_lag)", style={"fontSize": "15px", "margin": "0", "color": "#0f172a"}),
                                    dcc.RadioItems(
                                        id="canal_dispersion",
                                        options=[
                                            {"label": " CH2 (HFCT)", "value": "ch2"},
                                            {"label": " CH3 (Vivaldi)", "value": "ch3"},
                                            {"label": " CH4 (Bioinspirada)", "value": "ch4"},
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
                        html.H3("📋 Resumen de Calibración por Canal", style={"fontSize": "15px", "margin": "0 0 10px 0"}),
                        html.Div(id="tabla_resumen"),
                    ]),
                    html.Div(style=ESTILO_CARD, children=[
                        html.H3("📊 Diagnóstico y Conformidad IEC 60060-1", style={"fontSize": "15px", "margin": "0 0 10px 0"}),
                        html.Div(id="panel_iec_resumen"),
                    ]),
                ],
            ),
        ],
    )
