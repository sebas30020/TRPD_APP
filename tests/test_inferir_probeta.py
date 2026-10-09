import pytest
from generate_metadata import inferir_parametros, inferir_diametros


def test_inferir_parametros_nueva_jerarquia():
    # 3 vacuolas mixtas en misma capa, set 0, 10kV
    res = inferir_parametros("Mediciones/3v_2mm3mm3.5mm_0/10kV")
    assert res["codigo_probeta"] == "3v_2mm3mm3.5mm_0"
    assert res["nro_vacuolas"] == 3
    assert res["asimetrica"] is False
    assert res["tipo_geometria"] == "mixta"
    assert res["diametros"] == [2, 3, 3.5]
    assert res["set_impulsos"] == 0
    assert res["tension_sec_kv"] == 10.0
    assert "tension_dc" not in res

    # 3 vacuolas asimétrica (distintas capas / altura), set 0, 11kV
    res = inferir_parametros("Mediciones/3VH_2mm3mm3.5mm_0/11kV")
    assert res["codigo_probeta"] == "3VH_2mm3mm3.5mm_0"
    assert res["nro_vacuolas"] == 3
    assert res["asimetrica"] is True
    assert res["tipo_geometria"] == "asimetrica"
    assert res["diametros"] == [2, 3, 3.5]
    assert res["set_impulsos"] == 0
    assert res["tension_sec_kv"] == 11.0

    # 1 vacuola, set 1, 17.5kV
    res = inferir_parametros("Mediciones/1v_2mm_1/17.5kV")
    assert res["codigo_probeta"] == "1v_2mm_1"
    assert res["nro_vacuolas"] == 1
    assert res["asimetrica"] is False
    assert res["tipo_geometria"] == "monodiametro"
    assert res["diametros"] == [2]
    assert res["set_impulsos"] == 1
    assert res["tension_sec_kv"] == 17.5

    # Set de 2 dígitos y monodiámetro
    res = inferir_parametros("Mediciones/2v_3mm3mm_12/15kV")
    assert res["codigo_probeta"] == "2v_3mm3mm_12"
    assert res["nro_vacuolas"] == 2
    assert res["asimetrica"] is False
    assert res["tipo_geometria"] == "monodiametro"
    assert res["diametros"] == [3, 3]
    assert res["set_impulsos"] == 12
    assert res["tension_sec_kv"] == 15.0

    # Separadores Windows backslash y trailing slash
    res = inferir_parametros(r"Mediciones\3v_2mm3mm3.5mm_0\10kV\\")
    assert res["codigo_probeta"] == "3v_2mm3mm3.5mm_0"
    assert res["tension_sec_kv"] == 10.0
    assert res["diametros"] == [2, 3, 3.5]


def test_tension_desde_carpeta_kv():
    # Archivos agrupados: '<probeta>/<XkV>/<stem>'
    res = inferir_parametros("M/1v_2mm_0/17.5kV/medA")
    assert res["tension_sec_kv"] == 17.5
    assert res["codigo_probeta"] == "1v_2mm_0"
    # Variantes del nombre de la carpeta
    assert inferir_parametros("M/1v_2mm_0/17,5kV")["tension_sec_kv"] == 17.5
    assert inferir_parametros("M/1v_2mm_0/17.5 kV")["tension_sec_kv"] == 17.5
    assert inferir_parametros("M/1v_2mm_0/22.57kV")["tension_sec_kv"] == 22.57
    assert inferir_parametros("M/1v_2mm_0/10KV")["tension_sec_kv"] == 10.0
    # La tensión no depende de que el código de probeta sea válido
    res = inferir_parametros("M/carpeta_rara/30kV")
    assert res["tension_sec_kv"] == 30.0 and res["codigo_probeta"] == "carpeta_rara"
    assert inferir_parametros("Mediciones/3V224/30kV")["tension_sec_kv"] == 30.0
    assert inferir_parametros("3v_2mm3mm_0/10kV")["tension_sec_kv"] == 10.0


def test_inferir_parametros_nombres_invalidos():
    rutas_invalidas = [
        "Mediciones/invalido",
        "Mediciones/2Vmo/20260915_30kV_rep01",
        "Mediciones/3V224/30kV",
        "Mediciones/30s_3v_2mm",
        "3v_2mm3mm_0/10kV",     # n=3 pero solo 2 diámetros
        "carpeta_aleatoria",
        "",
    ]
    con_kv = {"Mediciones/3V224/30kV", "3v_2mm3mm_0/10kV"}
    for ruta in rutas_invalidas:
        res = inferir_parametros(ruta)
        assert res["nro_vacuolas"] is None, ruta
        assert res["asimetrica"] is None, ruta
        assert res["tipo_geometria"] is None, ruta
        assert res["diametros"] is None, ruta
        assert res["set_impulsos"] is None, ruta
        if ruta not in con_kv:
            assert res["tension_sec_kv"] is None, ruta
            assert res["codigo_probeta"] is None, ruta
        else:  # bajo una carpeta XkV el código es el nombre de la carpeta de la probeta
            assert res["codigo_probeta"] == ruta.split("/")[-2], ruta


def test_un_diametro_para_varias_vacuolas():
    # '3v_4mm_1' = 3 vacuolas de 4 mm; el código es el nombre de la carpeta
    res = inferir_parametros("med_proced/3v_4mm_1/11kV")
    assert res["codigo_probeta"] == "3v_4mm_1"
    assert res["nro_vacuolas"] == 3
    assert res["diametros"] == [4, 4, 4]
    assert res["tipo_geometria"] == "monodiametro"
    assert res["set_impulsos"] == 1
    assert res["tension_sec_kv"] == 11.0
    assert inferir_diametros(codigo_probeta="3v_4mm_1") == "4mm-4mm-4mm"


def test_inferir_diametros():
    # Desde lista 'diametros'
    assert inferir_diametros({"diametros": [2, 3, 3.5]}) == "2mm-3mm-3.5mm"
    assert inferir_diametros({"diametros": [3, 3]}) == "3mm-3mm"

    # Desde string 'diametros'
    assert inferir_diametros({"diametros": "2mm-2mm-3mm"}) == "2mm-2mm-3mm"

    # Desde lista 'vacuolas'
    prob_vacs = {
        "vacuolas": [
            {"diametro_mm": 2},
            {"diametro_mm": 2},
            {"diametro_mm": 3},
        ]
    }
    assert inferir_diametros(prob_vacs) == "2mm-2mm-3mm"

    # Desde codigo_probeta con nueva jerarquía
    assert inferir_diametros(codigo_probeta="3v_2mm3mm3.5mm_0") == "2mm-3mm-3.5mm"
    assert inferir_diametros({"codigo": "2v_2mm2mm_1"}) == "2mm-2mm"

    # Sin fallback legado: códigos antiguos o inválidos -> N/D
    assert inferir_diametros(codigo_probeta="3V224") == "N/D"
    assert inferir_diametros({"codigo": "2Vmo"}) == "N/D"
    assert inferir_diametros(codigo_probeta="invalido") == "N/D"
