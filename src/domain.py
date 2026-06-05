"""Dataclasses do domínio do Jogo PCP 2 (FLAMENGO)."""
from dataclasses import dataclass, field
from typing import Dict, List, Literal

Item = Literal["MP1", "MP2", "MP3", "PA1", "PA2", "PA3"]
Modal = Literal["Avião", "Caminhão", "Navio"]
TipoOrigem = Literal["Fornecedor", "Fábrica", "CD"]
TipoDestino = Literal["Fábrica", "CD", "Varejista"]


@dataclass
class TransitItem:
    rod_part: int
    dia_part: int
    rod_cheg: int
    dia_cheg: int
    origem_tipo: TipoOrigem
    origem_cidade: str
    destino_tipo: TipoDestino
    destino_cidade: str
    modal: Modal
    item: Item
    qtd: float


@dataclass
class OP:
    rodada: int
    cidade: str
    pa: Item
    qtd: int
    dia_entrega: int


@dataclass
class OPDescartada:
    op: OP
    motivo: str
    rodada_descarte: int


@dataclass
class Estado:
    rodada_atual: int
    estoque_mp_fabrica: Dict[str, Dict[str, float]]
    estoque_pa_cd: Dict[str, Dict[str, int]]
    transit: List[TransitItem]
    ops_pendentes: List[OP]
    ops_atendidas: List[OP]
    ops_descartadas: List[OPDescartada]


@dataclass
class PlanoTransporte:
    rodada: int
    origem_tipo: TipoOrigem
    origem_cidade: str
    dia_coleta: int
    modal: Modal
    item: Item
    qtd: float
    destino_tipo: TipoDestino
    destino_cidade: str


@dataclass
class PlanoProducao:
    rodada: int
    fabrica: str
    dia: int
    pa: Item
    qtd: int


@dataclass
class TarefaTransporte:
    origem_cidade: str
    destino_cidade: str
    item: Item
    qtd: float
    janela_dias: List[int]
    rodada: int
    motivo: str
    origem_tipo: TipoOrigem = "Fábrica"
    destino_tipo: TipoDestino = "CD"
