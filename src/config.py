"""Carrega constantes do jogo e matrizes de distância."""
from __future__ import annotations
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

import pandas as pd


@dataclass
class Config:
    BoM: Dict[str, Dict[str, int]]
    velocidades: Dict[str, int]
    peso_un_ton: Dict[str, float]
    densidades_mp: Dict[str, float]
    densidades_pa: Dict[str, float]
    cap_modal_ton: Dict[str, float]
    cap_modal_por_item: Dict[str, Dict[str, float]]
    frete_viagem: Dict[str, float]
    frete_peso: Dict[str, float]
    doc_modal: Dict[str, float]
    fornecedores: Dict[str, List[Tuple[str, float]]]
    ne_por_cidade: Dict[str, int]
    distancias: Dict[str, pd.DataFrame]
    rotas_navio_validas: Set[Tuple[str, str]]
    capacidades: Dict[str, Any]
    precos_referencia: Dict[str, float]

    @classmethod
    def load(cls, base_dir: Path) -> "Config":
        params = json.loads((base_dir / "data" / "parametros.json").read_text(encoding="utf-8"))

        bom = params["bom_pa"]
        BoM = {}
        for pa, d in bom.items():
            BoM[pa] = {"MP1": d["MP1"], "MP2": d["MP2"], "MP3": d["MP3"],
                       "peso_total_g": d["peso_total_g"], "prod_un_min": d["prod_un_min"]}
        velocidades = {pa: d["prod_un_min"] for pa, d in bom.items()}
        peso_un_ton = {pa: d["peso_total_g"] / 1_000_000 for pa, d in bom.items()}

        cap_modal_ton = {m: d["cap_ton"] for m, d in params["modais"].items()}
        cap_modal_por_item = {}
        for m, d in params["modais"].items():
            cap_modal_por_item[m] = {}
            for pa in ("PA1", "PA2", "PA3"):
                cap_modal_por_item[m][pa] = math.floor(d["cap_ton"] / peso_un_ton[pa])
            for mp in ("MP1", "MP2", "MP3"):
                cap_modal_por_item[m][mp] = d["cap_ton"]

        frete_viagem = {m: d["frete_viagem"] for m, d in params["modais"].items()}
        frete_peso = {m: d["frete_peso"] for m, d in params["modais"].items()}
        doc_modal = {m: d["doc"] for m, d in params["modais"].items()}

        fornecedores: Dict[str, List[Tuple[str, float]]] = {}
        for f in params["fornecedores_mp"]:
            fornecedores.setdefault(f["mp"], []).append((f["cidade"], float(f["custo_ton"])))

        distancias = {}
        modal_files = {
            "Caminhão": "distancias_caminhao.parquet",
            "Avião": "distancias_aviao.parquet",
            "Navio": "distancias_navio.parquet",
        }
        rotas_navio: Set[Tuple[str, str]] = set()
        for modal, fname in modal_files.items():
            df = pd.read_parquet(base_dir / "data" / fname)
            distancias[modal] = df
            if modal == "Navio":
                for orig in df.index:
                    for dest in df.columns:
                        v = df.at[orig, dest]
                        if pd.notna(v) and float(v) > 0:
                            rotas_navio.add((orig, dest))

        return cls(
            BoM=BoM,
            velocidades=velocidades,
            peso_un_ton=peso_un_ton,
            densidades_mp=params["densidade_mp_ton_m3"],
            densidades_pa=params["densidade_pa_ton_m3"],
            cap_modal_ton=cap_modal_ton,
            cap_modal_por_item=cap_modal_por_item,
            frete_viagem=frete_viagem,
            frete_peso=frete_peso,
            doc_modal=doc_modal,
            fornecedores=fornecedores,
            ne_por_cidade=params["ne_por_cidade"],
            distancias=distancias,
            rotas_navio_validas=rotas_navio,
            capacidades=params["custos_estruturais"],
            precos_referencia=params["preco_referencia"],
        )
