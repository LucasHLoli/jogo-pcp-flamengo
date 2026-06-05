import pytest
import pandas as pd


@pytest.fixture(scope="session")
def op_rodada_dummy(tmp_path_factory):
    path = tmp_path_factory.mktemp("rodadas") / "OP_Rodada_2.xlsx"
    pd.DataFrame([
        {"Rodada": 2, "Cidade": "São Paulo", "PA": "PA1", "Qtd": 50000, "Dia_Entrega": 3},
        {"Rodada": 2, "Cidade": "Rio de Janeiro", "PA": "PA2", "Qtd": 30000, "Dia_Entrega": 5},
    ]).to_excel(path, index=False)
    return path
