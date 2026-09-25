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
   - CH1 (impulso): polaridad y, si CH1 está en su flanco en t = 0, canal,
     pendiente y nivel del trigger estimados.
4. Desde la ruta: código de probeta, geometría, nº de vacuolas, diámetros, tensión DC.

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
import datetime
import os
import re
import sys

import h5py
import numpy as np
import yaml

import rutas

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


def extraer_info_h5(carpeta_medicion):
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
                # Metadatos del equipo (Frame). 'Date' es la hora de GUARDADO del
                # archivo (o de exportación del CSV), no la de inicio de adquisición.
                if "Frame/TheFrame" in f and not info["osciloscopio"]:
                    tf = f["Frame/TheFrame"][()]
                    info["osciloscopio"] = {
                        "modelo": _decodificar(tf["Model"]),
                        "serial": _decodificar(tf["Serial"]),
                        "fecha_adquisicion": _decodificar(tf["Date"]),
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
    impulso estima además polaridad y nivel del trigger (señal en t = 0)."""
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
        res["polaridad"] = "positiva" if np.median(picos) >= 0 else "negativa"
        # Si el trigger está en este canal, en t = 0 la señal cruza el nivel de
        # disparo: claramente fuera del ruido y por debajo del pico.
        nivel = float(np.median(niveles))
        salto = abs(nivel - float(np.median(bases)))
        ruido = float(np.median(ruidos))
        en_flanco = 5 * ruido < salto < 0.95 * float(np.median(np.abs(picos)))
        res["trigger_en_este_canal"] = bool(en_flanco)
        res["nivel_trigger_estimado_v"] = _r(nivel) if en_flanco else None
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


def inferir_parametros(experimento):
    """Infiere código de probeta, tensión DC y tipo de geometría a partir de la ruta."""
    partes = experimento.replace("\\", "/").split("/")
    codigo_probeta = None
    tension_dc = None
    tipo_geometria = None
    nro_vacuolas = None
    diametros = None

    # Patrón nuevo: 1-4 vacuolas, 'mo' (monodiametro) o 'mi' (mixto), sufijo opcional 'H' (asimetrica)
    patron_nuevo = re.compile(r"([1-4]V(?:mo|mi)[H]?)(?:[_\-\s/]|\b|$)", re.IGNORECASE)
    # Patrón legado de respaldo: dígitos de diámetros en el código (ej. 3V224, 3V444H)
    patron_legado = re.compile(r"([1-4]V[2-4]+[H]?)(?:[_\-\s/]|\b|$)", re.IGNORECASE)

    for p in partes:
        m = patron_nuevo.search(p)
        if m:
            raw = m.group(1)
            # Normalizar convención: ej. 2Vmo, 2Vmi, 2VmoH, 2VmiH
            n = raw[0]
            v = "V"
            tipo_tag = raw[2:4].lower()
            h_tag = "H" if len(raw) > 4 and raw[4].upper() == "H" else ""
            codigo_probeta = f"{n}{v}{tipo_tag}{h_tag}"
            break

    if not codigo_probeta:
        for p in partes:
            m = patron_legado.search(p)
            if m:
                codigo_probeta = m.group(1).upper()
                break

    if codigo_probeta:
        if codigo_probeta[0].isdigit():
            nro_vacuolas = int(codigo_probeta[0])

        # Caso 1: Nuevo formato (mo / mi / H)
        match_nuevo = re.search(r"^[1-4]V(mo|mi)(H)?$", codigo_probeta, re.IGNORECASE)
        if match_nuevo:
            distrib = match_nuevo.group(1).lower()
            tiene_h = bool(match_nuevo.group(2))
            if tiene_h:
                tipo_geometria = "asimetrica"
            elif distrib == "mo":
                tipo_geometria = "monodiametro"
            else:
                tipo_geometria = "mixta"
        else:
            # Caso 2: Formato legado con dígitos (ej. 3V224, 3V444H)
            if "H" in codigo_probeta.upper():
                tipo_geometria = "asimetrica"
            else:
                match_v = re.search(r"^[1-4]V([2-4]+)", codigo_probeta, re.IGNORECASE)
                if match_v:
                    digitos = match_v.group(1)
                    tipo_geometria = "monodiametro" if len(set(digitos)) == 1 else "mixta"
            match_v = re.search(r"^[1-4]V([2-4]+)", codigo_probeta, re.IGNORECASE)
            if match_v:
                digitos = match_v.group(1)
                diametros = "-".join([f"{d}mm" for d in digitos])

    if nro_vacuolas is None:
        # Respaldo: número de vacuolas suelto en el nombre de carpeta (ej. '30s_3v_2mm',
        # '2vac', '4 vacuolas'). Se busca desde la carpeta más profunda hacia arriba.
        patron_nro = re.compile(r"(?<![A-Za-z0-9])([1-4])\s*(?:vacuolas?|vac|v)(?![A-Za-z])", re.IGNORECASE)
        for p in reversed(partes):
            m = patron_nro.search(p)
            if m:
                nro_vacuolas = int(m.group(1))
                break

    for p in partes:
        m = re.search(r"(\d+(?:\.\d+)?)kV", p, re.IGNORECASE)
        if m:
            tension_dc = float(m.group(1))
            break

    return {
        "codigo_probeta": codigo_probeta,
        "tipo_geometria": tipo_geometria,
        "nro_vacuolas": nro_vacuolas,
        "tension_dc": tension_dc,
        "diametros": diametros,
    }


def inferir_diametros(probeta_data=None, codigo_probeta=None):
    """Extrae o formatea los diámetros de las cavidades en formato estándar (ej. '2mm-2mm-3mm')."""
    if isinstance(probeta_data, dict):
        # 1. Campo explícito 'diametros'
        d_val = probeta_data.get("diametros")
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
                        partes.append(f"{d}mm")
                elif isinstance(v, (int, float, str)):
                    s = str(v).strip()
                    if not s.lower().endswith("mm"):
                        s = f"{s}mm"
                    partes.append(s)
            if partes:
                return "-".join(partes)

        if not codigo_probeta:
            codigo_probeta = probeta_data.get("codigo")

    # 3. Formato numérico legado en codigo_probeta (ej. 3V224 -> 2mm-2mm-4mm)
    if codigo_probeta:
        m = re.search(r"^[1-4]V([2-4]+)", str(codigo_probeta), re.IGNORECASE)
        if m:
            digitos = m.group(1)
            return "-".join([f"{d}mm" for d in digitos])

    return "N/D"



def _campos_pendientes(d, prefijo=""):
    """Rutas 'a.b.c' de los campos sin valor (None o "") que quedan por completar a mano."""
    pend = []
    for k, v in d.items():
        ruta = f"{prefijo}{k}"
        if isinstance(v, dict):
            pend += _campos_pendientes(v, ruta + ".")
        elif v is None or v == "":
            pend.append(ruta)
    return pend


def plantilla_metadata(experimento, carpeta_medicion, analizar=True):
    """Esquema enriquecido, rellenado automáticamente al máximo desde los .h5:
    atributos del osciloscopio, cadencia (SegmentedTimeTag) y, si `analizar`,
    amplitudes de las señales, polaridad y nivel de trigger estimados."""
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
        "ch2": _canal("ch2", sensor="HFCT", funcion="Corriente PD", unidad="V", atenuacion_db=30),
        "ch3": _canal("ch3", sensor="Antena Vivaldi", funcion="UHF Banda ancha", unidad="V",
                      filtro="ninguno"),
        "ch4": _canal("ch4", sensor="Antena Bioinspirada", funcion="UHF / Resolucion picos frente",
                      unidad="V", filtro="HP_200MHz"),
    }

    polaridad = imp.get("polaridad", "positiva")
    trigger_ch1 = imp.get("trigger_en_este_canal")
    datos = {
        "experimento": {
            "id": experimento,
            "fecha_hora": osc.get("fecha_adquisicion"),
            "temperatura_c": None,
            "humedad_relativa_pct": None,
        },
        "circuito_impulso": {
            "forma_onda_nominal": "1.2/50us",
            "tension_v_ac_prim": None,
            "tension_kv_ac_sec": None,
            "tension_dc_condensador_kv": inf["tension_dc"],
            "polaridad": polaridad,
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
            "diametros": inf.get("diametros") or "",
            "vacuolas": [],
            "distancias_entre_vacuolas_mm": [],
            "fotos": [],
        },
        "osciloscopio": {
            "modelo": osc.get("modelo", "DSOS804A"),
            "serial": osc.get("serial"),
            # 'Date' del .h5: hora de guardado del archivo, no de inicio de adquisición
            "fecha_adquisicion": osc.get("fecha_adquisicion"),
            "frecuencia_muestreo_gsas": bt.get("frecuencia_muestreo_gsas"),
            "tiempo_total_ventana_us": bt.get("tiempo_total_us"),
            "escala_tiempo_us_div": bt.get("escala_tiempo_us_div"),
            "num_segmentos_capturados": bt.get("num_segmentos"),
            "puntos_por_segmento": bt.get("puntos_por_segmento"),
        },
        "trigger": {
            # El .h5 no guarda la configuración del trigger: canal, pendiente y nivel se
            # deducen de CH1 en t = 0 (si CH1 está en su flanco, el trigger es CH1).
            "canal_origen": "ch1" if trigger_ch1 else None,
            "tipo": "flanco",
            "pendiente": polaridad if trigger_ch1 else None,
            "nivel_v": imp.get("nivel_trigger_estimado_v"),
            "nivel_v_fuente": "estimado: mediana de CH1 en t = 0" if trigger_ch1 else None,
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
                               referencia_impulso="t10", info_ancla=None):
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
        "ch3": "Antena Vivaldi",
        "ch4": "Antena Bioinspirada",
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

    return bloque


def _guardar_yaml(datos, destino):
    with open(destino, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, allow_unicode=True, sort_keys=False, default_flow_style=None)


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
