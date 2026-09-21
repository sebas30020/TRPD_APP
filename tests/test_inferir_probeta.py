import pytest
from generate_metadata import inferir_parametros, inferir_diametros


def test_inferir_parametros_nuevo_paradigma():
    # 2 vacuolas monodiametro misma capa
    res = inferir_parametros("Mediciones/2Vmo/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "2Vmo"
    assert res["nro_vacuolas"] == 2
    assert res["tipo_geometria"] == "monodiametro"
    assert res["tension_dc"] == 30.0

    # 2 vacuolas mixtas misma capa
    res = inferir_parametros("Mediciones/2Vmi/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "2Vmi"
    assert res["nro_vacuolas"] == 2
    assert res["tipo_geometria"] == "mixta"
    assert res["tension_dc"] == 30.0

    # 2 vacuolas monodiametro asimétrica (distinta capa / altura)
    res = inferir_parametros("Mediciones/2VmoH/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "2VmoH"
    assert res["nro_vacuolas"] == 2
    assert res["tipo_geometria"] == "asimetrica"
    assert res["tension_dc"] == 30.0

    # 2 vacuolas mixtas asimétrica
    res = inferir_parametros("Mediciones/2VmiH/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "2VmiH"
    assert res["nro_vacuolas"] == 2
    assert res["tipo_geometria"] == "asimetrica"
    assert res["tension_dc"] == 30.0

    # 3 vacuolas mixtas
    res = inferir_parametros("Mediciones/3Vmi/20260920_40kV_rep05")
    assert res["codigo_probeta"] == "3Vmi"
    assert res["nro_vacuolas"] == 3
    assert res["tipo_geometria"] == "mixta"
    assert res["tension_dc"] == 40.0

    # 3 vacuolas monodiametro asimétrica
    res = inferir_parametros("Mediciones/3VmoH/20260920_40kV_rep05")
    assert res["codigo_probeta"] == "3VmoH"
    assert res["nro_vacuolas"] == 3
    assert res["tipo_geometria"] == "asimetrica"
    assert res["tension_dc"] == 40.0


def test_inferir_parametros_retrocompatibilidad_legada():
    # 3V224
    res = inferir_parametros("Mediciones/3V224/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "3V224"
    assert res["nro_vacuolas"] == 3
    assert res["tipo_geometria"] == "mixta"
    assert res["diametros"] == "2mm-2mm-4mm"
    assert res["tension_dc"] == 30.0

    # 3V444H
    res = inferir_parametros("Mediciones/3V444H/20260915_30kV_rep01")
    assert res["codigo_probeta"] == "3V444H"
    assert res["nro_vacuolas"] == 3
    assert res["tipo_geometria"] == "asimetrica"
    assert res["diametros"] == "4mm-4mm-4mm"


def test_inferir_diametros():
    # Desde campo explícito 'diametros'
    assert inferir_diametros({"diametros": "2mm-2mm-3mm"}) == "2mm-2mm-3mm"
    assert inferir_diametros({"diametros": "3mm-3mm"}) == "3mm-3mm"

    # Desde lista 'vacuolas'
    prob_vacs = {
        "vacuolas": [
            {"diametro_mm": 2},
            {"diametro_mm": 2},
            {"diametro_mm": 3},
        ]
    }
    assert inferir_diametros(prob_vacs) == "2mm-2mm-3mm"

    # Fallback con código legado
    assert inferir_diametros(codigo_probeta="3V224") == "2mm-2mm-4mm"
    assert inferir_diametros({"codigo": "2V22"}) == "2mm-2mm"

    # Código nuevo sin campo diametros ni vacuolas -> N/D
    assert inferir_diametros(codigo_probeta="2Vmi") == "N/D"
    assert inferir_diametros({"codigo": "2Vmo"}) == "N/D"
