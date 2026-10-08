"""
Rellena automáticamente el metadata.yaml de mediciones de impulsos tipo rayo (LI).

Único punto de entrada para generar la metadata (incluye la lógica de cadencia
que antes vivía solo en cadencia.py). Extrae al máximo desde los .h5:

1. Atributos del osciloscopio (sin leer señales):
   - Modelo, serie y fecha de guardado del archivo (Keysight Infiniium).
   - Por canal: escala vertical (V/div), offset, rango total, ancho de banda.
   - Base de tiempo: Fs, ventana, puntos, segmentos, posición del trigger en
     pantalla, pre-trigger y jitter del trigger entre segmentos.
2. Cadencia (SegmentedTimeTag de cada segmento): intervalo entre disparos
   (mediana, mín, máx), clase cada_1min / cada_30s / otros, duración total,
   saltos anómalos y coincidencia de marcas entre canales.
3. Señales (lee solo el inicio de cada segmento, ventana -5..20 µs; --sin-senales lo omite):
   - Por canal: línea base, ruido, pico medio/σ/máx, Vpp medio y segmentos que
     se salen de la pantalla vertical (escala mal elegida).
   - CH1 (impulso): si CH1 está en su flanco en t = 0, canal,
     pendiente y nivel del trigger estimados.
4. Desde la ruta: código de probeta, geometría, nº de vacuolas, diámetros, set de impulsos, tensión del secundario (kV).

Lo que no se puede deducir queda en None y se lista en
'generado_automaticamente.campos_pendientes'. plantilla_metadata() no incluye
'calibracion_retardo' (su ausencia indica medición sin calibrar).

Ejecutar (ruta absoluta o relativa al directorio actual):
    python generate_metadata.py <carpeta_medicion | carpeta_raiz> [--completar | --forzar] [--sin-senales]
  - Si la ruta contiene chN.h5 se procesa esa medición; si no, se recorren sus
    subcarpetas y se procesan todas las mediciones encontradas.
  - Sin opciones no se modifica un metadata.yaml existente.
  - --completar: rellena solo los campos ausentes o vacíos, conservando lo escrito a mano.
  - --forzar: reemplaza el metadata.yaml completo.
"""
import copy
import datetime
import os
import re
import sys

import h5py
import numpy as np
import yaml

import rutas
from filtros import FILTROS_DEFECTO

AQUI = os.path.dirname(os.path.abspath(__file__))


# Cadencia de adquisición: clase -> dt nominal [s] y tolerancia
CLASES_CADENCIA = {"cada_1min": 60.0, "cada_30s": 30.0}
CADENCIA_OTROS = "otros"
TOL_CADENCIA_S = 2.0

# Ventana analizada de cada segmento para amplitudes (s, respecto al trigger).
# Igual a la ventana de app.py (T_MIN = -5 us): las descargas pueden ocurrir antes
# de t = 0. La línea base se toma del pre-trigger anterior a T_INI_ANALISIS_S.
T_INI_ANALISIS_S = -5e-6
T_FIN_ANALISIS_S = 20e-6

_CACHE_SENALES = {}


def _decodificar(b):
    return b.decode("utf-8", errors="ignore").strip() if isinstance(b, bytes) else str(b).strip()


# Formatos de 'Frame/TheFrame.Date' vistos en los .h5: Infiniium ('9-Sep-2026 14:16:57')
# y archivos convertidos desde CSV ('14 AUG 2025 19:09:37'). strptime ignora mayúsculas.
_FORMATOS_FECHA_OSC = ("%d-%b-%Y %H:%M:%S", "%d %b %Y %H:%M:%S")


def parsear_fecha_osc(texto):
    """Fecha 'Date' del .h5 -> datetime, o None si no se reconoce el formato."""
    for fmt in _FORMATOS_FECHA_OSC:
        try:
            return datetime.datetime.strptime(str(texto).strip(), fmt)
        except ValueError:
            pass
    return None


def normalizar_fecha_osc(texto):
    """Fecha 'Date' del .h5 -> 'YYYY-MM-DD HH:MM:SS'. Un texto no reconocido se
    conserva tal cual; None si no hay fecha."""
    if texto is None:
        return None
    dt = parsear_fecha_osc(texto)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else texto


def _segmentos(grupo):
    """[(n_segmento, dataset)] ordenados por número de segmento."""
    segs = []
    for nombre, ds in grupo.items():
        m = re.search(r"Seg(\d+)Data$", nombre)
        if m:
            segs.append((int(m.group(1)), ds))
    return sorted(segs, key=lambda x: x[0])


def _r(x, n=4):
    return None if x is None or not np.isfinite(x) else round(float(x), n)


_CACHE_INFO = {}


def extraer_info_h5(carpeta_medicion):
    """extraer_info_h5 cacheado por (ruta, fecha de modificación) de cada .h5:
    la app pide la plantilla varias veces por medición y antes reabría los 4
    archivos en Google Drive cada vez. Devuelve una copia modificable."""
    clave = []
    for ch in rutas.CANALES:
        p = rutas.ruta_canal(carpeta_medicion, ch)
        if p:
            try:
                clave.append((p, os.path.getmtime(p)))
            except OSError:
                clave.append((p, None))
    clave = tuple(clave)
    if clave not in _CACHE_INFO:
        _CACHE_INFO[clave] = _extraer_info_h5(carpeta_medicion)
    return copy.deepcopy(_CACHE_INFO[clave])


def _extraer_info_h5(carpeta_medicion):
    """Extrae metadatos de hardware, escalas, base de tiempo y marcas temporales
    (atributos de los .h5, sin leer las señales).

    `carpeta_medicion`: cualquier valor de medición aceptado por rutas.ruta_canal
    (directorio, '<dir>/<stem>' de archivos agrupados o ruta a un chN.h5)."""
    info = {"osciloscopio": {}, "canales": {}, "base_tiempo": {}, "marcas": {}}
    for ch in rutas.CANALES:
        p = rutas.ruta_canal(carpeta_medicion, ch)
        if not p:
            continue
        try:
            with h5py.File(p, "r") as f:
                # Metadatos del equipo (Frame) del primer canal presente (CH1, referencia
                # del experimento, igual que el trigger). 'Date' es la hora de GUARDADO
                # del archivo (o de exportación del CSV), no la de inicio de adquisición.
                if "Frame/TheFrame" in f and not info["osciloscopio"]:
                    tf = f["Frame/TheFrame"][()]
                    info["osciloscopio"] = {
                        "modelo": _decodificar(tf["Model"]),
                        "serial": _decodificar(tf["Serial"]),
                        "fecha_guardado": normalizar_fecha_osc(_decodificar(tf["Date"])),
                    }
                if "Waveforms" not in f:
                    continue
                k = list(f["Waveforms"].keys())[0]
                g = f["Waveforms"][k]
                attrs = g.attrs
                ydisp_range = float(attrs.get("YDispRange", 0.0))
                ydisp_origin = float(attrs.get("YDispOrigin", 0.0))
                xdisp_range = float(attrs.get("XDispRange", 0.0))
                xdisp_origin = float(attrs.get("XDispOrigin", 0.0))
                xinc = float(attrs.get("XInc", 0.0))
                max_bw = float(attrs.get("MaxBandwidth", 0.0))

                # Osciloscopios Infiniium: 8 divisiones verticales, 10 horizontales
                info["canales"][ch] = {
                    "canal_osc": k,
                    "archivo": os.path.basename(p),
                    "escala_v_div": round(ydisp_range / 8.0, 4) if ydisp_range > 0 else 0.0,
                    "offset_v": round(ydisp_origin, 4),
                    "rango_total_v": round(ydisp_range, 4),
                    "ancho_banda_ghz": round(max_bw / 1e9, 3) if max_bw > 0 else None,
                    "yinc": float(attrs.get("YInc", 0.0)),
                }
                segs = _segmentos(g)
                info["marcas"][ch] = [float(ds.attrs["SegmentedTimeTag"]) for _, ds in segs
                                      if "SegmentedTimeTag" in ds.attrs]
                xorgs = [float(ds.attrs["SegmentedXOrg"]) for _, ds in segs if "SegmentedXOrg" in ds.attrs]

                if not info["base_tiempo"]:
                    fs = (1.0 / xinc) if xinc > 0 else None
                    info["base_tiempo"] = {
                        "frecuencia_muestreo_gsas": round(fs / 1e9, 2) if fs else None,
                        "tiempo_total_us": round(xdisp_range * 1e6, 2),
                        "escala_tiempo_us_div": round(xdisp_range / 10.0 * 1e6, 2) if xdisp_range > 0 else 0.0,
                        "num_segmentos": int(attrs.get("NumSegments", 0)),
                        "puntos_por_segmento": int(attrs.get("NumPoints", 0)),
                        # Posición del trigger (t = 0) medida desde el borde izquierdo de pantalla
                        "posicion_trigger_pct": round(-xdisp_origin / xdisp_range * 100.0, 2)
                        if xdisp_range > 0 else None,
                        "pretrigger_us": round(-xdisp_origin * 1e6, 3),
                        # Dispersión del origen de cada segmento respecto al trigger
                        "jitter_trigger_ns": round((max(xorgs) - min(xorgs)) * 1e9, 4) if xorgs else None,
                    }
        except Exception as e:
            print(f"Advertencia: no se pudo leer {p} para metadatos ({e})")
    return info


def clasificar_cadencia(mediana_s):
    """(clase, dt_nominal) según la mediana del intervalo entre disparos."""
    for clase, nominal in CLASES_CADENCIA.items():
        if abs(mediana_s - nominal) <= TOL_CADENCIA_S:
            return clase, nominal
    return CADENCIA_OTROS, None


def analizar_cadencia(marcas_por_canal):
    """Cadencia a partir de SegmentedTimeTag [s] (relativo al segmento 1) de cada canal.

    Devuelve None si no hay marcas. 'anomalias' lista los saltos cuyo Δt se aparta
    más de TOL_CADENCIA_S del nominal de su clase."""
    canales = [c for c in rutas.CANALES if marcas_por_canal.get(c)]
    if not canales:
        return None
    ref = np.asarray(marcas_por_canal[canales[0]], dtype=float)
    coinciden = all(
        len(marcas_por_canal[c]) == ref.size and np.allclose(marcas_por_canal[c], ref)
        for c in canales
    )
    dt = np.diff(ref)
    if not dt.size:
        return {"clase": None, "n_segmentos": int(ref.size), "marcas_coinciden_entre_canales": coinciden}
    mediana = float(np.median(dt))
    clase, nominal = clasificar_cadencia(mediana)
    anomalias = [] if nominal is None else [
        {"desde_seg": i + 1, "hasta_seg": i + 2, "dt_s": round(float(d), 2)}
        for i, d in enumerate(dt) if abs(d - nominal) > TOL_CADENCIA_S
    ]
    return {
        "clase": clase,
        "dt_nominal_s": nominal,
        "dt_mediana_s": round(mediana, 2),
        "dt_min_s": round(float(dt.min()), 2),
        "dt_max_s": round(float(dt.max()), 2),
        "duracion_total_s": round(float(ref[-1] - ref[0]), 2),
        "n_segmentos": int(ref.size),
        "tolerancia_s": TOL_CADENCIA_S,
        "anomalias": anomalias,
        "marcas_coinciden_entre_canales": bool(coinciden),
        "fuente": "SegmentedTimeTag de cada segmento (.h5)",
    }


def _analizar_canal(ruta_h5, es_impulso):
    """Amplitudes por segmento de un canal en la ventana [T_INI_ANALISIS_S,
    T_FIN_ANALISIS_S] (lee solo el inicio de cada segmento). Para el canal de
    impulso (CH1, que siempre es el canal de trigger) mide además el
    nivel del trigger (señal en t = 0)."""
    with h5py.File(ruta_h5, "r") as f:
        k = list(f["Waveforms"].keys())[0]
        g = f["Waveforms"][k]
        a = g.attrs
        yinc, yorg = float(a["YInc"]), float(a["YOrg"])
        xinc, xorg = float(a["XInc"]), float(a["XOrg"])
        n = int(a["NumPoints"])
        # Pantalla vertical: se supone YDispOrigin = centro de pantalla (Infiniium)
        ycentro, yrango = float(a.get("YDispOrigin", 0.0)), float(a.get("YDispRange", 0.0))

        def idx(t):
            return min(max(int(round((t - xorg) / xinc)), 0), n)

        i_ini, i0, i_fin = idx(T_INI_ANALISIS_S), idx(0.0), idx(T_FIN_ANALISIS_S)
        picos, pp, niveles, bases, ruidos = [], [], [], [], []
        segs_fuera = []
        for nseg, ds in _segmentos(g):
            v = ds[0:i_fin].astype(np.float64) * yinc + yorg
            if v.size <= i0:
                continue
            pre = v[:i_ini] if i_ini >= 10 else v[:1]
            base = float(np.median(pre))
            w = v[i_ini:]
            dev = w - base
            j = int(np.argmax(np.abs(dev)))
            picos.append(float(dev[j]))
            pp.append(float(w.max() - w.min()))
            bases.append(base)
            ruidos.append(float(np.std(pre)))
            niveles.append(float(v[max(i0 - 2, 0):i0 + 3].mean()))
            # Fuera de pantalla = el ADC satura (la señal queda recortada)
            if yrango > 0 and (w.max() >= ycentro + yrango / 2 or w.min() <= ycentro - yrango / 2):
                segs_fuera.append(nseg)
    if not picos:
        return {}
    picos = np.asarray(picos)
    res = {
        "n_segmentos_analizados": int(picos.size),
        "linea_base_v": _r(np.median(bases)),
        "ruido_rms_v": _r(np.median(ruidos), 5),
        "v_pico_media_v": _r(np.mean(np.abs(picos))),
        "v_pico_sigma_v": _r(np.std(np.abs(picos))),
        "v_pico_max_v": _r(np.max(np.abs(picos))),
        "v_pp_media_v": _r(np.mean(pp)),
        "n_segmentos_fuera_de_pantalla": len(segs_fuera),
        "segmentos_fuera_de_pantalla": segs_fuera,
    }
    if es_impulso:
        # El trigger siempre está en CH1: en t = 0 la señal está en el nivel de disparo.
        # Verificación: ese valor debe quedar claramente fuera del ruido y bajo el pico.
        nivel = float(np.median(niveles))
        salto = abs(nivel - float(np.median(bases)))
        ruido = float(np.median(ruidos))
        en_flanco = 5 * ruido < salto < 0.95 * float(np.median(np.abs(picos)))
        res["trigger_en_este_canal"] = bool(en_flanco)
        res["nivel_trigger_estimado_v"] = _r(nivel)
    return res


def analizar_senales(carpeta_medicion):
    """{canal: resultado de _analizar_canal} para los canales presentes.
    CH1 se analiza como canal de impulso. Cacheado por (ruta, fecha de modificación)."""
    res = {}
    for ch in rutas.CANALES:
        p = rutas.ruta_canal(carpeta_medicion, ch)
        if not p:
            continue
        try:
            clave = (p, os.path.getmtime(p))
            if clave not in _CACHE_SENALES:
                _CACHE_SENALES[clave] = _analizar_canal(p, es_impulso=(ch == "ch1"))
            res[ch] = _CACHE_SENALES[clave]
        except Exception as e:
            print(f"Advertencia: no se pudieron analizar las señales de {p} ({e})")
    return res


RE_KV = re.compile(r"^(\d+(?:[.,]\d+)?)\s*kV$", re.IGNORECASE)
RE_PRINCIPAL = re.compile(
    r"^(?P<n>[1-9])[vV](?P<h>[hH])?_(?P<diams>(?:\d+(?:\.\d+)?mm)+)_(?P<set>\d+)$"
)
RE_DIAM_TOKEN = re.compile(r"(\d+(?:\.\d+)?)mm", re.IGNORECASE)


def inferir_parametros(experimento):
    """Infiere código de probeta, geometría, vacuolas, diámetros, set y tensión
    del secundario a partir de la jerarquía: <principal>/<XkV>."""
    partes = [p for p in str(experimento or "").replace("\\", "/").split("/") if p]
    if partes and partes[-1].lower().endswith((".h5", ".yaml", ".yml")):
        partes = partes[:-1]

    codigo_probeta = None
    tension_sec_kv = None
    nro_vacuolas = None
    asimetrica = None
    tipo_geometria = None
    diametros = None
    set_impulsos = None

    if not partes:
        return {
            "codigo_probeta": None,
            "tipo_geometria": None,
            "nro_vacuolas": None,
            "asimetrica": None,
            "diametros": None,
            "set_impulsos": None,
            "tension_sec_kv": None,
        }

    # Nivel de tensión: el componente 'XkV' más profundo de la ruta (admite
    # '<probeta>/<XkV>/<stem>' de archivos agrupados). Independiente del código.
    cand_principal = None
    i_kv = next((i for i in range(len(partes) - 1, -1, -1) if RE_KV.match(partes[i])), None)
    if i_kv is not None:
        tension_sec_kv = float(RE_KV.match(partes[i_kv]).group(1).replace(",", "."))
        if i_kv >= 1:
            cand_principal = partes[i_kv - 1]
    else:
        m_direct = RE_PRINCIPAL.match(partes[-1])
        if m_direct:
            cand_principal = partes[-1]

    if cand_principal:
        m_p = RE_PRINCIPAL.match(cand_principal)
        if m_p:
            n_val = int(m_p.group("n"))
            h_val = bool(m_p.group("h"))
            diams_str = m_p.group("diams")
            set_val = int(m_p.group("set"))

            raw_tokens = RE_DIAM_TOKEN.findall(diams_str)
            parsed_diams = [
                int(float(x)) if float(x).is_integer() else float(x)
                for x in raw_tokens
            ]

            tokens_rebuilt = "".join(f"{x}mm" for x in raw_tokens)
            if tokens_rebuilt.lower() == diams_str.lower() and len(parsed_diams) == n_val:
                codigo_probeta = cand_principal
                nro_vacuolas = n_val
                asimetrica = h_val
                diametros = parsed_diams
                set_impulsos = set_val
                if asimetrica:
                    tipo_geometria = "asimetrica"
                elif len(set(diametros)) == 1:
                    tipo_geometria = "monodiametro"
                else:
                    tipo_geometria = "mixta"

    return {
        "codigo_probeta": codigo_probeta,
        "tipo_geometria": tipo_geometria,
        "nro_vacuolas": nro_vacuolas,
        "asimetrica": asimetrica,
        "diametros": diametros,
        "set_impulsos": set_impulsos,
        "tension_sec_kv": tension_sec_kv,
    }


def inferir_diametros(probeta_data=None, codigo_probeta=None):
    """Extrae o formatea los diámetros de las cavidades en formato estándar (ej. '2mm-2mm-3mm')."""
    if isinstance(probeta_data, dict):
        # 1. Campo explícito 'diametros'
        d_val = probeta_data.get("diametros")
        if isinstance(d_val, list) and d_val:
            return "-".join(f"{float(d):g}mm" for d in d_val)
        if d_val and str(d_val).strip():
            return str(d_val).strip()

        # 2. Lista de diccionarios 'vacuolas'
        vacs = probeta_data.get("vacuolas") or []
        if vacs:
            partes = []
            for v in vacs:
                if isinstance(v, dict):
                    d = v.get("diametro_mm") or v.get("d_mm") or v.get("diametro")
                    if d is not None:
                        partes.append(f"{float(d):g}mm")
                elif isinstance(v, (int, float, str)):
                    s = str(v).strip()
                    if not s.lower().endswith("mm"):
                        s = f"{float(s):g}mm"
                    partes.append(s)
            if partes:
                return "-".join(partes)

        if not codigo_probeta:
            codigo_probeta = probeta_data.get("codigo")

    # 3. Formato nuevo en codigo_probeta (ej. 3v_2mm3mm3.5mm_0 -> 2mm-3mm-3.5mm)
    if codigo_probeta:
        m = RE_PRINCIPAL.match(str(codigo_probeta).strip())
        if m:
            raw_tokens = RE_DIAM_TOKEN.findall(m.group("diams"))
            if raw_tokens:
                return "-".join(f"{float(x):g}mm" for x in raw_tokens)

    return "N/D"


SENSORES_DEFECTO = {"ch2": "HFCT", "ch3": "Antena 1", "ch4": "Antena 2"}
# Nombres antiguos que pueden quedar en metadata.yaml ya escritos
_SENSORES_LEGADO = {"antena vivaldi": "Antena 1", "vivaldi": "Antena 1",
                    "antena bioinspirada": "Antena 2", "bioinspirada": "Antena 2"}


def nombre_corto_sensor(nombre, canal):
    """Nombre corto del sensor para tablas: traduce los nombres antiguos
    (Vivaldi / Bioinspirada) y, sin nombre, usa el de defecto del canal."""
    n = str(nombre or "").strip()
    if not n:
        return SENSORES_DEFECTO.get(str(canal).lower(), str(canal).upper())
    return _SENSORES_LEGADO.get(n.lower(), n)


def normalizar_diametros(texto, nro_vacuolas=None, tipo_geometria=None):
    """Texto libre de diámetros -> (formato estándar '2mm-2mm-3mm', None) o (None, error).

    Acepta separadores '-', ',', ';', '/' o espacios, con o sin 'mm' (decimales con
    punto: '2.5'). Si se conocen, valida contra el número de vacuolas y la geometría
    del código de probeta (monodiametro: todos iguales; mixta: al menos dos distintos).
    """
    partes = [p for p in re.split(r"[-,;/\s]+", str(texto or "").lower()) if p]
    if not partes:
        return None, "Escriba al menos un diámetro (ej. 2mm-2mm-3mm)."
    valores = []
    for p in partes:
        num = p[:-2] if p.endswith("mm") else p
        try:
            d = float(num)
        except ValueError:
            return None, f"'{p}' no es un diámetro válido."
        if d <= 0:
            return None, f"'{p}' debe ser mayor que 0."
        valores.append(d)
    if nro_vacuolas and len(valores) != int(nro_vacuolas):
        return None, (f"Se indicaron {len(valores)} diámetros, pero la probeta tiene "
                      f"{nro_vacuolas} vacuolas.")
    tipo = str(tipo_geometria or "").lower()
    if tipo == "monodiametro" and len(set(valores)) > 1:
        return None, "Probeta monodiámetro: todos los diámetros deben ser iguales."
    if tipo == "mixta" and len(valores) > 1 and len(set(valores)) == 1:
        return None, "Probeta mixta: debe haber al menos dos diámetros distintos."
    return "-".join(f"{d:g}mm" for d in valores), None



def _campos_pendientes(d, prefijo=""):
    """Rutas 'a.b.c' de los campos sin valor (None o "") que quedan por completar a mano."""
    pend = []
    for k, v in d.items():
        ruta = f"{prefijo}{k}"
        if isinstance(v, dict):
            pend += _campos_pendientes(v, ruta + ".")
        elif v is None or v == "" or (k == "diametros" and v == []):
            pend.append(ruta)
    return pend


def plantilla_metadata(experimento, carpeta_medicion, analizar=True):
    """Esquema enriquecido, rellenado automáticamente al máximo desde los .h5:
    atributos del osciloscopio, cadencia (SegmentedTimeTag) y, si `analizar`,
    amplitudes de las señales y nivel de trigger estimados."""
    # Se lee la medición concreta (soporta '<dir>/<stem>' de archivos agrupados)
    fuente = experimento if rutas.canales_presentes(experimento) else carpeta_medicion
    h5_info = extraer_info_h5(fuente)
    sen = analizar_senales(fuente) if analizar else {}
    cad = analizar_cadencia(h5_info.get("marcas", {}))
    inf = inferir_parametros(experimento)

    osc = h5_info.get("osciloscopio", {})
    bt = h5_info.get("base_tiempo", {})
    chs = h5_info.get("canales", {})
    imp = sen.get("ch1", {})

    def _canal(ch, **fijos):
        c = chs.get(ch, {})
        d = {
            **fijos,
            "presente": ch in chs,
            "archivo": c.get("archivo"),
            "escala_v_div": c.get("escala_v_div"),
            "offset_v": c.get("offset_v", 0.0),
            "rango_total_v": c.get("rango_total_v"),
            "ancho_banda_ghz": c.get("ancho_banda_ghz"),
        }
        s = {k: v for k, v in sen.get(ch, {}).items()
             if k not in ("polaridad", "trigger_en_este_canal", "nivel_trigger_estimado_v")}
        if s:
            d["senal"] = s
        return d

    # Asignaciones por defecto de sensores (totalmente editables por el usuario)
    # CH1 siempre es el divisor capacitivo de impulso; CH2..CH4 configurables según sensor conectado
    ch_config = {
        "ch1": _canal("ch1", sensor="Divisor capacitivo", funcion="Tension LI / Sincronismo",
                      unidad="kV", atenuacion_db=0),
        "ch2": _canal("ch2", sensor="HFCT", funcion="Corriente PD", unidad="V", atenuacion_db=30,
                      filtro=FILTROS_DEFECTO["ch2"]),
        "ch3": _canal("ch3", sensor="Antena 1", funcion="UHF Banda ancha", unidad="V",
                      filtro=FILTROS_DEFECTO["ch3"]),
        "ch4": _canal("ch4", sensor="Antena 2", funcion="UHF / Resolucion picos frente",
                      unidad="V", filtro=FILTROS_DEFECTO["ch4"]),
    }

    partes_exp = [p for p in str(experimento or "").replace("\\", "/").split("/") if p]
    if partes_exp and partes_exp[-1].lower().endswith((".h5", ".yaml", ".yml")):
        partes_exp = partes_exp[:-1]
    if len(partes_exp) >= 2:
        exp_id = f"{partes_exp[-2]}/{partes_exp[-1]}"
    else:
        exp_id = partes_exp[-1] if partes_exp else str(experimento)

    pendiente = h5_info.get("trigger", {}).get("pendiente") or ("positiva" if analizar else None)

    datos = {
        "experimento": {
            "id": exp_id,
            # Única fecha del experimento: 'Frame/TheFrame.Date' del .h5 de CH1
            # (hora de guardado del archivo ≈ fin de la adquisición)
            "fecha_hora": osc.get("fecha_guardado"),
            "temperatura_c": None,
            "humedad_relativa_pct": None,
        },
        "circuito_impulso": {
            "forma_onda_nominal": "1.2/50us",
            "tension_kv_ac_sec": inf["tension_sec_kv"],
            "nro_disparos_programados": bt.get("num_segmentos", 50),
            "intervalo_entre_disparos_s": (cad or {}).get("dt_mediana_s", 30.0),
            # Salida del divisor en CH1 (V en el osciloscopio, no kV)
            "v_pico_divisor_media_v": imp.get("v_pico_media_v"),
            "v_pico_divisor_sigma_v": imp.get("v_pico_sigma_v"),
        },
        "probeta": {
            "codigo": inf["codigo_probeta"] or "",
            "tipo_geometria": inf["tipo_geometria"] or "",
            "descripcion": "Pressboard sumergido en aceite mineral",
            "nro_capas_total": 4,
            "espesor_capa_mm": 0.48,
            "nro_vacuolas": inf["nro_vacuolas"],
            "diametros": inf.get("diametros") if inf.get("diametros") is not None else [],
            "set_impulsos": inf.get("set_impulsos"),
            "vacuolas": [],
            "distancias_entre_vacuolas_mm": [],
            "fotos": [],
        },
        "osciloscopio": {
            "modelo": osc.get("modelo", "DSOS804A"),
            "serial": osc.get("serial"),
            "frecuencia_muestreo_gsas": bt.get("frecuencia_muestreo_gsas"),
            "tiempo_total_ventana_us": bt.get("tiempo_total_us"),
            "escala_tiempo_us_div": bt.get("escala_tiempo_us_div"),
            "num_segmentos_capturados": bt.get("num_segmentos"),
            "puntos_por_segmento": bt.get("puntos_por_segmento"),
        },
        "trigger": {
            # El trigger siempre es CH1 (montaje fijo). El .h5 no guarda la configuración
            # del trigger: pendiente y nivel se miden en la señal de CH1 en t = 0.
            "canal_origen": "ch1",
            "tipo": "flanco",
            "pendiente": pendiente,
            "nivel_v": imp.get("nivel_trigger_estimado_v"),
            "nivel_v_fuente": "medido: mediana de CH1 en t = 0 (.h5)"
            if imp.get("nivel_trigger_estimado_v") is not None else None,
            # True si CH1 está en su flanco en t = 0 (confirma que disparó CH1)
            "flanco_ch1_en_t0": imp.get("trigger_en_este_canal"),
            "posicion_horizontal_pct": bt.get("posicion_trigger_pct"),
            "pretrigger_us": bt.get("pretrigger_us"),
            "jitter_trigger_ns": bt.get("jitter_trigger_ns"),
        },
        "cadencia": cad,
        "canales": ch_config,
    }
    datos["generado_automaticamente"] = {
        "fecha": datetime.date.today().isoformat(),
        "analisis_senales": bool(sen),
        "campos_pendientes": _campos_pendientes(datos),
    }
    return datos


def completar_metadata(existente, nuevo):
    """Rellena en `existente` solo lo que falta (claves ausentes o valores None/""/[])
    con lo de `nuevo`, sin tocar los valores ya escritos. Devuelve `existente`."""
    for k, v in nuevo.items():
        actual = existente.get(k)
        if isinstance(actual, dict) and isinstance(v, dict):
            completar_metadata(actual, v)
        elif k not in existente or actual is None or actual == "" or actual == []:
            existente[k] = v
    return existente


def bloque_calibracion_retardo(resultados, fuente, sensores=None, fecha=None,
                               referencia_impulso="t10", info_ancla=None, filtros=None):
    """Bloque 'calibracion_retardo' para metadata.yaml.

    resultados: dict {ch: dict de calibrar_retardo o {'t_lag_us','sigma_us','n_valid','n_total','params'}}.
    Unidades de tiempo en ns (3 decimales). fecha por defecto: hoy ISO.
    referencia_impulso: 't10' o 'origen_virtual_IEC60060'.
    info_ancla: dict con métricas del ancla (requerido si referencia_impulso == 'origen_virtual_IEC60060').
    """
    if fecha is None:
        fecha = datetime.date.today().isoformat()

    default_sensores = {
        "ch2": "HFCT",
        "ch3": "Antena 1",
        "ch4": "Antena 2",
    }
    sensores = sensores or {}

    mapa_legado = {
        "t10": "t10_CH1_por_segmento",
        "origen_virtual_IEC60060": "origen_virtual_IEC60060_por_segmento",
    }
    ref_legado = mapa_legado.get(referencia_impulso, str(referencia_impulso))

    bloque = {
        "fecha": str(fecha),
        "fuente_calibracion": fuente,
        "criterio": "primer_cruce_umbral",
        "referencia": ref_legado,
        "referencia_impulso": referencia_impulso,
    }

    if info_ancla is not None:
        bloque["ancla"] = dict(info_ancla)

    for ch in ["ch2", "ch3", "ch4"]:
        if ch in resultados and resultados[ch] and resultados[ch].get("t_lag_us") is not None:
            r = resultados[ch]
            t_lag_us = r["t_lag_us"]
            sigma_us = r.get("sigma_us")
            params = r.get("params") or {}
            sensor_name = sensores.get(ch) or default_sensores.get(ch, ch.upper())

            bloque[ch] = {
                "sensor": sensor_name,
                "t_lag_ns": round(float(t_lag_us) * 1e3, 3),
                "sigma_ns": round(float(sigma_us) * 1e3, 3) if sigma_us is not None else None,
                "n_valid": r.get("n_valid"),
                "n_total": r.get("n_total"),
                "umbral_mv": round(float(params["umbral_mv"]), 4) if params.get("umbral_mv") is not None else None,
                "distancia_us": round(float(params["distancia_us"]), 4) if params.get("distancia_us") is not None else None,
                "tmin_us": round(float(params["tmin_us"]), 4) if params.get("tmin_us") is not None else None,
            }
            if params.get("tmax_us") is not None:
                # Fin de la ventana de búsqueda del arribo (solo calibración)
                bloque[ch]["tmax_us"] = round(float(params["tmax_us"]), 4)
            if filtros and ch in filtros:
                # Filtro digital con que se midió el arribo (ver filtros.py)
                bloque[ch]["filtro"] = filtros[ch]

    return bloque


def _actualizar_desde_h5(datos, nuevo):
    """Fecha y trigger se leen del .h5 de CH1 (no se editan a mano): siempre se
    reescriben desde `nuevo`. En el trigger solo se reescriben los valores obtenidos
    (con --sin-senales el nivel y la pendiente quedan None y se conserva lo que había).
    La fecha vive solo en 'experimento.fecha_hora': se eliminan las claves de fecha
    del bloque 'osciloscopio'."""
    datos.setdefault("experimento", {})["fecha_hora"] = nuevo["experimento"]["fecha_hora"]
    osc = datos.setdefault("osciloscopio", {})
    for k in ("fecha_adquisicion", "fecha_guardado", "fecha_guardado_por_canal"):
        osc.pop(k, None)
    trig = datos.setdefault("trigger", {})
    for k, v in nuevo["trigger"].items():
        if v is not None:
            trig[k] = v


def _actualizar_desde_ruta(datos, experimento):
    """La tensión del secundario se lee de la carpeta '<X>kV' de la ruta: si existe,
    siempre manda sobre lo escrito en el YAML."""
    kv = inferir_parametros(experimento)["tension_sec_kv"]
    if kv is not None:
        datos.setdefault("circuito_impulso", {})["tension_kv_ac_sec"] = kv


def _guardar_yaml(datos, destino):
    with open(destino, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def generar(experimento, forzar=False, completar=False, analizar=True):
    """Crea (o completa) el metadata.yaml de UNA medición.

    `experimento`: ruta a la carpeta de la medición (o '<dir>/<stem>' si el
    directorio agrupa archivos '<pref>chN<suf>.h5').
    - Si metadata.yaml no existe: lo crea con todo lo que se puede extraer.
    - Si existe: con `forzar` lo reemplaza; con `completar` solo rellena los campos
      ausentes o vacíos (conserva lo escrito a mano); si no, no lo toca.
    Devuelve la ruta del metadata.yaml."""
    carpeta = os.path.abspath(experimento)
    d = rutas.dir_medicion(carpeta)
    if not d or not rutas.canales_presentes(carpeta):
        raise FileNotFoundError(f"No hay archivos chN.h5 de medición en: {carpeta}")
    destino = os.path.join(d, "metadata.yaml")
    existe = os.path.exists(destino)
    if existe and not (forzar or completar):
        print(f"Ya existe, no se modifica (use --completar o --forzar): {destino}")
        return destino

    nuevo = plantilla_metadata(carpeta, d, analizar=analizar)
    if existe and completar:
        with open(destino, "r", encoding="utf-8") as f:
            datos = yaml.safe_load(f) or {}
        datos = completar_metadata(datos, nuevo)
        _actualizar_desde_h5(datos, nuevo)
        _actualizar_desde_ruta(datos, carpeta)
        datos.setdefault("generado_automaticamente", {})
        datos["generado_automaticamente"]["fecha"] = datetime.date.today().isoformat()
        datos["generado_automaticamente"]["campos_pendientes"] = _campos_pendientes(
            {k: v for k, v in datos.items() if k != "generado_automaticamente"})
        _guardar_yaml(datos, destino)
        print("Metadata completada:", destino)
    else:
        _guardar_yaml(nuevo, destino)
        print("Metadata generada:", destino)
    return destino


def buscar_mediciones(raiz):
    """Mediciones bajo `raiz` (recursivo), una por directorio. Los directorios que
    agrupan varias mediciones con archivos '<pref>chN<suf>.h5' comparten un solo
    metadata.yaml, así que se omiten con aviso."""
    encontradas = []
    for root, dirs, _ in os.walk(raiz):
        dirs.sort(key=rutas.orden_natural)
        meds = rutas.mediciones_en(root)
        if len(meds) == 1:
            encontradas.append(meds[0])
        elif len(meds) > 1:
            print(f"Aviso: {root} agrupa {len(meds)} mediciones en un mismo directorio; "
                  "se omite (un metadata.yaml por carpeta).")
    return encontradas


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        sys.exit(1)
    ruta = os.path.abspath(args[0])
    mediciones = [ruta] if rutas.canales_presentes(ruta) else buscar_mediciones(ruta)
    if not mediciones:
        print(f"No se encontraron mediciones (chN.h5) en {ruta}")
        sys.exit(1)
    errores = 0
    for m in mediciones:
        try:
            generar(m, forzar="--forzar" in flags, completar="--completar" in flags,
                    analizar="--sin-senales" not in flags)
        except Exception as e:
            errores += 1
            print(f"Error en {m}: {e}")
    print(f"\n{len(mediciones) - errores}/{len(mediciones)} mediciones procesadas.")


if __name__ == "__main__":
    main()
