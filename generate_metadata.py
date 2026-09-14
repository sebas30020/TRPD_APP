"""
Genera una plantilla YAML de metadatos para una medición de impulsos tipo rayo (Lightning Impulse - LI).

Crea `Mediciones/<experimento>/metadata.yaml` combinando:
1. Extracción automática desde los archivos HDF5 del osciloscopio (ch1..ch4.h5):
   - Modelo, número de serie y fecha/hora de adquisición del osciloscopio (Keysight Infiniium DSOS804A).
   - Escalas verticales por canal (V/div, rango total, offset).
   - Base de tiempo y muestreo (frecuencia de muestreo en GSa/s, ventana horizontal, puntos y segmentos).
2. Circuito de generación de impulso:
   - Tensión del Variac (V AC primario) y transformador elevador (kV AC secundario).
   - Tensión DC en el condensador de carga previo al disparo (kV DC).
   - Polaridad, número de disparos e intervalo entre descargas.
3. Especificación física de la probeta:
   - Código de probeta (mono-diámetro, mixta o asimétrica), número de capas y espesor.
   - Detalle de cavidades/vacuolas (diámetro, capa/altura, posición) y distancias entre ellas.
4. Configuración del trigger y asignación de sensores por canal:
   - CH1: Canal reservado para el divisor capacitivo de tensión de impulso / sincronismo.
   - CH2, CH3, CH4: Canales configurables según el sensor conectado (HFCT, antena Vivaldi, bioinspirada, etc.).

No sobrescribe un metadata.yaml existente salvo que se pase --forzar.

Ejecutar:
    python generate_metadata.py <experimento> [--forzar]
    (p. ej.: python generate_metadata.py 3V224/20260915_30kV_rep01)
"""
import os
import re
import sys

import h5py
import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
# Misma carpeta de datos que usa app.py: ../mediciones/Mediciones (ruta directa,
# sin depender de un symlink dentro del repo).
MEDICIONES = os.path.abspath(os.path.join(AQUI, os.pardir, "mediciones", "Mediciones"))


def extraer_info_h5(carpeta_medicion):
    """Extrae metadatos de hardware, escalas y base de tiempo desde los archivos .h5."""
    info = {"osciloscopio": {}, "canales": {}, "base_tiempo": {}}
    for ch in ["ch1", "ch2", "ch3", "ch4"]:
        p = os.path.join(carpeta_medicion, f"{ch}.h5")
        if not os.path.exists(p):
            continue
        try:
            with h5py.File(p, "r") as f:
                # Metadatos del equipo (Frame)
                if "Frame/TheFrame" in f and not info["osciloscopio"]:
                    tf = f["Frame/TheFrame"][()]
                    info["osciloscopio"] = {
                        "modelo": tf["Model"].decode("utf-8", errors="ignore").strip(),
                        "serial": tf["Serial"].decode("utf-8", errors="ignore").strip(),
                        "fecha_adquisicion": tf["Date"].decode("utf-8", errors="ignore").strip(),
                    }
                # Atributos de forma de onda y escala
                if "Waveforms" in f:
                    for k in f["Waveforms"].keys():
                        attrs = f["Waveforms"][k].attrs
                        ydisp_range = float(attrs.get("YDispRange", 0.0))
                        ydisp_origin = float(attrs.get("YDispOrigin", 0.0))
                        xdisp_range = float(attrs.get("XDispRange", 0.0))
                        xinc = float(attrs.get("XInc", 0.0))
                        num_segments = int(attrs.get("NumSegments", 0))
                        num_points = int(attrs.get("NumPoints", 0))

                        # Osciloscopios Infiniium: 8 divisiones verticales, 10 horizontales
                        v_per_div = ydisp_range / 8.0 if ydisp_range > 0 else 0.0
                        t_per_div = xdisp_range / 10.0 if xdisp_range > 0 else 0.0
                        fs_gsas = (1.0 / xinc) / 1e9 if xinc > 0 else None

                        info["canales"][ch] = {
                            "canal_osc": k,
                            "escala_v_div": round(v_per_div, 4),
                            "offset_v": round(ydisp_origin, 4),
                            "rango_total_v": round(ydisp_range, 4),
                            "yinc": float(attrs.get("YInc", 0.0)),
                        }

                        if not info["base_tiempo"]:
                            info["base_tiempo"] = {
                                "frecuencia_muestreo_gsas": round(fs_gsas, 2) if fs_gsas else None,
                                "tiempo_total_us": round(xdisp_range * 1e6, 2),
                                "escala_tiempo_us_div": round(t_per_div * 1e6, 2),
                                "num_segmentos": num_segments,
                                "puntos_por_segmento": num_points,
                            }
        except Exception as e:
            print(f"Advertencia: no se pudo leer {ch}.h5 para metadatos ({e})")
    return info


def inferir_parametros(experimento):
    """Infiere código de probeta, tensión DC y tipo de geometría a partir de la ruta."""
    partes = experimento.replace("\\", "/").split("/")
    codigo_probeta = None
    tension_dc = None
    tipo_geometria = None
    nro_vacuolas = None

    patron_probeta = re.compile(r"^[1-4]V[2-4]+[H]?(_\d+)?$", re.IGNORECASE)
    for p in partes:
        m = patron_probeta.match(p)
        if m:
            codigo_probeta = p.upper()
            break

    if codigo_probeta:
        if "H" in codigo_probeta:
            tipo_geometria = "asimetrica"
        else:
            match_v = re.search(r"^[1-4]V([2-4]+)", codigo_probeta)
            if match_v:
                digitos = match_v.group(1)
                tipo_geometria = "monodiametro" if len(set(digitos)) == 1 else "mixta"
        if codigo_probeta[0].isdigit():
            nro_vacuolas = int(codigo_probeta[0])

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
    }


def plantilla_metadata(experimento, carpeta_medicion):
    """Esquema enriquecido con extracción automática de osciloscopio y configuración de ensayo."""
    h5_info = extraer_info_h5(carpeta_medicion)
    inf = inferir_parametros(experimento)

    osc = h5_info.get("osciloscopio", {})
    bt = h5_info.get("base_tiempo", {})
    chs = h5_info.get("canales", {})

    # Asignaciones por defecto de sensores (totalmente editables por el usuario)
    # CH1 siempre es el divisor capacitivo de impulso; CH2..CH4 configurables según sensor conectado
    ch_config = {
        "ch1": {
            "sensor": "Divisor capacitivo",
            "funcion": "Tension LI / Sincronismo",
            "unidad": "kV",
            "atenuacion_db": 0,
            "escala_v_div": chs.get("ch1", {}).get("escala_v_div"),
            "offset_v": chs.get("ch1", {}).get("offset_v", 0.0),
            "rango_total_v": chs.get("ch1", {}).get("rango_total_v"),
        },
        "ch2": {
            "sensor": "HFCT",
            "funcion": "Corriente PD",
            "unidad": "V",
            "atenuacion_db": 30,
            "escala_v_div": chs.get("ch2", {}).get("escala_v_div"),
            "offset_v": chs.get("ch2", {}).get("offset_v", 0.0),
            "rango_total_v": chs.get("ch2", {}).get("rango_total_v"),
        },
        "ch3": {
            "sensor": "Antena Vivaldi",
            "funcion": "UHF Banda ancha",
            "unidad": "V",
            "filtro": "ninguno",
            "escala_v_div": chs.get("ch3", {}).get("escala_v_div"),
            "offset_v": chs.get("ch3", {}).get("offset_v", 0.0),
            "rango_total_v": chs.get("ch3", {}).get("rango_total_v"),
        },
        "ch4": {
            "sensor": "Antena Bioinspirada",
            "funcion": "UHF / Resolucion picos frente",
            "unidad": "V",
            "filtro": "HP_200MHz",
            "escala_v_div": chs.get("ch4", {}).get("escala_v_div"),
            "offset_v": chs.get("ch4", {}).get("offset_v", 0.0),
            "rango_total_v": chs.get("ch4", {}).get("rango_total_v"),
        },
    }

    return {
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
            "polaridad": "positiva",
            "nro_disparos_programados": bt.get("num_segmentos", 50),
            "intervalo_entre_disparos_s": 30.0,
        },
        "probeta": {
            "codigo": inf["codigo_probeta"] or "",
            "tipo_geometria": inf["tipo_geometria"] or "",
            "descripcion": "Pressboard sumergido en aceite mineral",
            "nro_capas_total": 4,
            "espesor_capa_mm": 0.48,
            "nro_vacuolas": inf["nro_vacuolas"],
            "vacuolas": [],
            "distancias_entre_vacuolas_mm": [],
            "fotos": [],
        },
        "osciloscopio": {
            "modelo": osc.get("modelo", "DSOS804A"),
            "serial": osc.get("serial"),
            "fecha_adquisicion": osc.get("fecha_adquisicion"),
            "frecuencia_muestreo_gsas": bt.get("frecuencia_muestreo_gsas"),
            "tiempo_total_ventana_us": bt.get("tiempo_total_us"),
            "escala_tiempo_us_div": bt.get("escala_tiempo_us_div"),
            "num_segmentos_capturados": bt.get("num_segmentos"),
            "puntos_por_segmento": bt.get("puntos_por_segmento"),
        },
        "trigger": {
            "canal_origen": "ch1",
            "tipo": "flanco",
            "pendiente": "positiva",
            "nivel_v": None,
            "posicion_horizontal_pct": 10.0,
        },
        "canales": ch_config,
    }


def generar(experimento, forzar=False):
    """Crea Mediciones/<experimento>/metadata.yaml si no existe (o si forzar=True)."""
    carpeta = os.path.join(MEDICIONES, experimento)
    if not os.path.isdir(carpeta):
        raise FileNotFoundError(f"No existe la carpeta de medición: {carpeta}")
    destino = os.path.join(carpeta, "metadata.yaml")
    if os.path.exists(destino) and not forzar:
        print(f"Ya existe, no se sobrescribe: {destino}")
        return destino
    plantilla = plantilla_metadata(experimento, carpeta)
    with open(destino, "w", encoding="utf-8") as f:
        yaml.safe_dump(plantilla, f, allow_unicode=True, sort_keys=False)
    print("Plantilla generada exitosamente:", destino)
    return destino


def main():
    if len(sys.argv) < 2:
        print("Uso: python generate_metadata.py <experimento> [--forzar]")
        sys.exit(1)
    generar(sys.argv[1], forzar="--forzar" in sys.argv[2:])


if __name__ == "__main__":
    main()
