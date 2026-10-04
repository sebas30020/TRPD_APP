"""Sistema de diseño, tokens de color, estilos reutilizables y plantilla Plotly para TRPD_APP y calibrar_app."""

from __future__ import annotations
import plotly.graph_objects as go
import plotly.io as pio

# -----------------------------------------------------------------------------
# 1. Tokens de Color (Paleta Sobria, Plana y Formal)
# -----------------------------------------------------------------------------
BG = "#f3f4f6"                # Fondo principal de la aplicación
CARD = "#ffffff"              # Fondo de tarjetas y paneles
BORDER = "#d9dee5"            # Borde sutil
BORDER_SUBTLE = "#eef1f5"     # Borde interior tenue
INK = "#1f2933"               # Texto principal de alta legibilidad
MUTED = "#5f6b7a"             # Texto secundario / leyendas
MUTED_LIGHT = "#9aa5b1"       # Líneas guía de ejes
ACCENT = "#2f5d8a"            # Azul pizarra apagado (acento único primario)
ACCENT_HOVER = "#264d73"      # Hover para acento primario
ACCENT_LIGHT = "#e8eef5"      # Fondo suave para acento

NEUTRAL_BTN = "#5f6b7a"       # Gris slate para botones secundarios
NEUTRAL_BTN_HOVER = "#4b5563" # Hover botón secundario

OK = "#3f7d5c"                # Verde salvia apagado (éxito/conforme)
OK_BG = "#eaf3ed"             # Fondo suave para estado conforme
OK_HOVER = "#326449"          # Hover estado conforme

WARN = "#a8741a"              # Ocre apagado (advertencia/atención)
WARN_BG = "#fbf4e8"           # Fondo suave para advertencia
WARN_HOVER = "#8c6115"        # Hover advertencia

ERROR = "#a63d3d"             # Rojo apagado (error/peligro/exclusión)
ERROR_BG = "#fbeeed"          # Fondo suave para error
ERROR_HOVER = "#8b3232"       # Hover error

HEADER_TABLE = "#eef1f5"      # Fondo de cabeceras de tablas
ZEBRA = "#f7f8fa"             # Alternancia cebra en filas de tablas
GRID = "#e5e7eb"              # Cuadrícula sutil de gráficos
AXIS_LINE = "#9aa5b1"         # Líneas de ejes en gráficos

# -----------------------------------------------------------------------------
# 2. Paleta de Canales (Distingibles, Sobrios y Apto Daltónicos)
# -----------------------------------------------------------------------------
COLORES_CANALES = {
    "ch1": "#4c78a8",         # CH1: Impulso (Azul acero)
    "ch2": "#d08a2e",         # CH2: HFCT (Ocre apagado)
    "ch3": "#4f8f6f",         # CH3: Antena 1 (Verde salvia)
    "ch4": "#8a5fa0",         # CH4: Antena 2 (Púrpura apagado)
}

LINEA_ACTIVO = "#1f2933"      # Color de resalte para canal o elemento activo
LINEA_INACTIVO = "#5f6b7a"    # Color para canales no seleccionados
SCATTER_PUNTOS = "#4c78a8"    # Puntos TRPD (opacidad 0.6)
SCATTER_SEL = "#1f2933"       # Selección en scatter (contorno y punto sólido)
LINEA_T10 = "#4f8f6f"         # Referencia temporal t10
LINEA_O1 = "#a63d3d"          # Origen virtual O1 IEC
LINEA_T30_T90 = "#3f7d5c"     # Líneas t30 y t90
LINEA_T50 = "#8a5fa0"         # Línea t50 cola de impulso
COLORMAP_ST = "Cividis"       # Escala de color perceptual sobria para Transformada S

# -----------------------------------------------------------------------------
# 3. Diccionarios de Estilo Reutilizables
# -----------------------------------------------------------------------------
ESTILO_CONTENEDOR = {
    "fontFamily": "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "maxWidth": "1600px",
    "margin": "0 auto",
    "padding": "0 16px 32px",
    "backgroundColor": BG,
    "color": INK,
}

ESTILO_CARD = {
    "backgroundColor": CARD,
    "borderRadius": "6px",
    "border": f"1px solid {BORDER}",
    "padding": "12px 14px",
    "boxShadow": "0 1px 2px rgba(16, 24, 40, 0.04)",
}

ESTILO_BOTON_PRIMARY = {
    "backgroundColor": ACCENT,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "6px 14px",
    "fontWeight": "600",
    "fontSize": "13px",
    "cursor": "pointer",
}

ESTILO_BOTON_SECONDARY = {
    "backgroundColor": NEUTRAL_BTN,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "6px 12px",
    "fontWeight": "600",
    "fontSize": "12px",
    "cursor": "pointer",
}

ESTILO_BOTON_DANGER = {
    "backgroundColor": ERROR,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "6px 12px",
    "fontWeight": "600",
    "fontSize": "12px",
    "cursor": "pointer",
}

ESTILO_BOTON_SUCCESS = {
    "backgroundColor": OK,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "6px 12px",
    "fontWeight": "600",
    "fontSize": "12px",
    "cursor": "pointer",
}

ESTILO_BOTON_WARN = {
    "backgroundColor": WARN,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "6px 12px",
    "fontWeight": "600",
    "fontSize": "12px",
    "cursor": "pointer",
}

ESTILO_BOTON_STEPPER = {
    "backgroundColor": NEUTRAL_BTN,
    "color": "white",
    "border": "none",
    "borderRadius": "4px",
    "padding": "3px 8px",
    "fontWeight": "600",
    "fontSize": "12px",
    "cursor": "pointer",
}

# Badges y etiquetas semánticas
BADGE_OK = {
    "display": "inline-block",
    "fontSize": "11px",
    "padding": "2px 8px",
    "borderRadius": "10px",
    "fontWeight": "600",
    "backgroundColor": OK_BG,
    "color": OK,
    "border": f"1px solid {OK}",
}

BADGE_WARN = {
    "display": "inline-block",
    "fontSize": "11px",
    "padding": "2px 8px",
    "borderRadius": "10px",
    "fontWeight": "600",
    "backgroundColor": WARN_BG,
    "color": WARN,
    "border": f"1px solid {WARN}",
}

BADGE_ERROR = {
    "display": "inline-block",
    "fontSize": "11px",
    "padding": "2px 8px",
    "borderRadius": "10px",
    "fontWeight": "600",
    "backgroundColor": ERROR_BG,
    "color": ERROR,
    "border": f"1px solid {ERROR}",
}

BADGE_INFO = {
    "display": "inline-block",
    "fontSize": "11px",
    "padding": "2px 8px",
    "borderRadius": "10px",
    "fontWeight": "600",
    "backgroundColor": ACCENT_LIGHT,
    "color": ACCENT,
    "border": f"1px solid {ACCENT}",
}

BADGE_NEUTRAL = {
    "display": "inline-block",
    "fontSize": "11px",
    "padding": "2px 8px",
    "borderRadius": "10px",
    "fontWeight": "600",
    "backgroundColor": HEADER_TABLE,
    "color": MUTED,
    "border": f"1px solid {BORDER}",
}


def badge_canal(canal: str) -> dict:
    """Retorna el estilo de badge para un canal con su color distintivo sobrio."""
    c = COLORES_CANALES.get(canal.lower(), ACCENT)
    return {
        "display": "inline-block",
        "fontSize": "11px",
        "padding": "2px 6px",
        "backgroundColor": CARD,
        "border": f"1px solid {BORDER}",
        "borderLeft": f"4px solid {c}",
        "borderRadius": "3px",
        "fontWeight": "600",
        "color": INK,
    }


TAB_PROPS = {"className": "tab", "selected_className": "tab--selected"}

# -----------------------------------------------------------------------------
# 4. Plantilla Plotly Sobria ("trpd")
# -----------------------------------------------------------------------------
def registrar_plantilla_plotly() -> None:
    """Registra y fija la plantilla sobria 'trpd' para todos los gráficos Plotly."""
    t = go.layout.Template(
        layout=go.Layout(
            plot_bgcolor=CARD,
            paper_bgcolor=CARD,
            font=dict(
                family='system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
                size=12,
                color=INK,
            ),
            colorway=[
                COLORES_CANALES["ch1"],
                COLORES_CANALES["ch2"],
                COLORES_CANALES["ch3"],
                COLORES_CANALES["ch4"],
            ],
            xaxis=dict(
                gridcolor=GRID,
                linecolor=AXIS_LINE,
                zerolinecolor=GRID,
                tickfont=dict(size=11, color=MUTED),
                title=dict(font=dict(size=12, color=INK)),
            ),
            yaxis=dict(
                gridcolor=GRID,
                linecolor=AXIS_LINE,
                zerolinecolor=GRID,
                tickfont=dict(size=11, color=MUTED),
                title=dict(font=dict(size=12, color=INK)),
            ),
        )
    )
    pio.templates["trpd"] = t
    pio.templates.default = "trpd"


registrar_plantilla_plotly()
