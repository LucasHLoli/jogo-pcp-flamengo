import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def test_notebook_existe_e_eh_valido():
    nb_path = BASE / "jogo" / "rodada.ipynb"
    assert nb_path.exists()
    data = json.loads(nb_path.read_text(encoding="utf-8"))
    assert data.get("nbformat") == 4
    assert len(data["cells"]) >= 10
    code_cells = [c for c in data["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) >= 7
    # primeira célula de código tem setup
    primeiro_code = "".join(code_cells[0]["source"])
    assert "from src.pipeline import run_rodada" in primeiro_code
    assert "from src.cockpit_view import" in primeiro_code
    # alguma célula define OPS e PRECOS
    all_code = "\n".join("".join(c["source"]) for c in code_cells)
    assert "OPS = [" in all_code
    assert "PRECOS = {" in all_code
    assert "imprimir_cockpit" in all_code
    assert "preview_rodada_xlsm" in all_code
