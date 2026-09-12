"""
Genera una plantilla YAML de metadatos para una medición.

Crea `Mediciones/<experimento>/metadata.yaml` con el esquema descrito en
archivos_md/DOCUMENTACION.md (sección 12): condiciones ambientales, tensiones aplicadas y
descripción de la probeta (vacuolas, distancias entre ellas, fotos). No
sobrescribe un metadata.yaml existente salvo que se pase --forzar.

Ejecutar:  python3 generate_metadata.py <experimento> [--forzar]
           (<experimento> relativo a Mediciones/, p. ej. cada_30s/7)
"""
import os
import sys

import yaml

AQUI = os.path.dirname(os.path.abspath(__file__))
# Misma carpeta de datos que usa app.py: ../mediciones/Mediciones (ruta directa,
# sin depender de un symlink dentro del repo).
MEDICIONES = os.path.abspath(os.path.join(AQUI, os.pardir, "mediciones", "Mediciones"))


def plantilla_metadata():
    """Esquema por defecto (valores en blanco/null, a completar a mano)."""
    return {
        "medicion": {
            "fecha_hora": None,
            "humedad_relativa_pct": None,
            "temperatura_c": None,
            "tension_kv_ac_sec": None,
            "tension_v_ac_prim": None,
            "voltaje_dc_kv": None,
            "probeta": {
                "descripcion": "",
                "nro_vacuolas": None,
                "nro_capas_total": None,
                "vacuolas": [],
                "distancias_entre_vacuolas_mm": [],
                "fotos": [],
            },
        }
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
    with open(destino, "w", encoding="utf-8") as f:
        yaml.safe_dump(plantilla_metadata(), f, allow_unicode=True, sort_keys=False)
    print("Plantilla generada:", destino)
    return destino


def main():
    if len(sys.argv) < 2:
        print("Uso: python3 generate_metadata.py <experimento> [--forzar]")
        sys.exit(1)
    generar(sys.argv[1], forzar="--forzar" in sys.argv[2:])


if __name__ == "__main__":
    main()
