from pathlib import Path

from src.config import Config
from src.factibilidade import gerar_cockpit
from src.estado import estado_inicial
from src.domain import OP, OPDescartada, PlanoTransporte
from src.io_xlsm import ler_instalacoes

BASE = Path(__file__).resolve().parents[1]


def test_cockpit_smoke():
    cfg = Config.load(BASE)
    instalacoes = ler_instalacoes(BASE / "rodadas" / "FLAMENGO.xlsm")
    estado = estado_inicial()
    estado.estoque_pa_cd["CD2"]["PA1"] = 100000

    ops = [OP(rodada=2, cidade="São Paulo", pa="PA1", qtd=50000, dia_entrega=5)]
    planos_t = [
        PlanoTransporte(rodada=2, origem_tipo="CD", origem_cidade="Santos",
                        dia_coleta=2, modal="Caminhão", item="PA1", qtd=50000,
                        destino_tipo="Varejista", destino_cidade="São Paulo"),
    ]
    planos_p = []
    precos = {"PA1": 78.50, "PA2": 51.20, "PA3": 24.80}
    cockpit = gerar_cockpit(
        planos_t, planos_p, estado, ops, [], precos,
        cfg, instalacoes, rodada_n=2,
    )

    assert cockpit["rodada"] == 2
    assert cockpit["atendimento"]["total_ops"] == 1
    assert cockpit["atendimento"]["atendidas"] == 1
    assert cockpit["financeiro"]["receita"] == 50000 * 78.50
    assert cockpit["financeiro"]["margem_R$"] < cockpit["financeiro"]["receita"]
    assert "alertas" in cockpit
    assert "producao" in cockpit
    assert cockpit["transporte"]["total_viagens"] == 1


def test_cockpit_op_descartada():
    cfg = Config.load(BASE)
    instalacoes = ler_instalacoes(BASE / "rodadas" / "FLAMENGO.xlsm")
    estado = estado_inicial()
    op = OP(rodada=2, cidade="Manaus", pa="PA1", qtd=10000, dia_entrega=1)
    desc = OPDescartada(op=op, motivo="lead_time_inviavel", rodada_descarte=2)
    precos = {"PA1": 78.50, "PA2": 51.20, "PA3": 24.80}
    cockpit = gerar_cockpit(
        [], [], estado, [op], [desc], precos, cfg, instalacoes, rodada_n=2,
    )
    assert cockpit["atendimento"]["descartadas"] == 1
    assert cockpit["ops"][0]["status"] == "descartada"
    assert cockpit["financeiro"]["receita"] == 0
