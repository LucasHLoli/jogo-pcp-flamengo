# Solver v2 — Multi-rodada com cenários + buffer de MP

> Nova tentativa do solver do Jogo PCP (Flamengo). Mantém o `solver/` v1 intacto.
> Decide **tudo numa otimização só** (compra de MP → produção → transporte →
> entrega no dia exato → buffer de MP), guiado por previsão Holt-Winters que se
> auto-atualiza a cada rodada, maximizando **lucro esperado** com **NS alto**.

## Filosofia

```
HW (auto-tuna) → prevê 3 rodadas à frente (cenários 1/3 PA1/PA2/PA3)
   → SOLVER decide MP, produção, entrega, buffer → joga
   → realizado realimenta e afina o HW → repete (horizonte rolante)
```

## Descobertas que fundamentam o desenho (validadas)

1. **Frete calibrado**: <80% ocup = frete-peso puro (sem meia-viagem nem CT-e).
   Lucro previsto bate o real (erro 0,015%). Ver `memory/project_regra_frete_calibrada`.
2. **Share = 100%**: a previsão nacional ≈ a carteira real. Validado em R2 (PA1,
   razão 0,99), R3 e R4 (PA3, razão 1,06). O `0,40` antigo era erro.
3. **Gargalo = MP1**: todo PA precisa de MP1 (PA3 usa 75g/un), e MP1 só vem de
   Manaus/Belém (**lead 3 dias**). MP3 é local (lead 0), MP2 lead 2.
4. **R4 quebrou** porque R3 terminou com MP1=0 → NS máx ~37% (Dia 17-18 impossíveis).
5. **Buffer certo = MP cru, não PA pronto**: ~5× mais barato de carregar, serve
   qualquer produto, ataca o lead de 3 dias.

## Gargalos / restrições a SEMPRE vigiar

| # | Restrição | Por quê importa |
|---|---|---|
| 1 | MP1 lead 3d (Manaus/Belém) | tem que estar em estoque no início da rodada |
| 2 | Cap armazém MP2 = 50,4t | teto estrutural pra rodada PA1/PA2 (PA2 grande ~70% máx) |
| 3 | Entrega no DIA EXATO | produção+rota+lead têm que casar; fora do dia = descarte |
| 4 | ≤ 220 viagens/rodada | avião gasta muitas viagens |
| 5 | PA sai da F1 no mesmo dia que produz | não estoca PA na fábrica, só nos CDs |
| 6 | OP tudo-ou-nada (binário) | não atende OP pela metade |
| 7 | Cap fábrica 10.080 min/dia | PA1=15, PA2=30, PA3=60 un/min (PA1 é 4× mais lento) |
| 8 | Caps de estoque MP/PA | MP1≤127t, MP2≤50,4t, MP3≤75,6t |

## Parâmetros físicos (do jogo)

```
BoM (g/un):   PA1{MP1:60, MP2:90,  MP3:150}
              PA2{MP1:75, MP2:125, MP3:50}
              PA3{MP1:75, MP2:30,  MP3:45}
Velocidade:   PA1=15, PA2=30, PA3=60 un/min
Cap fábrica:  10.080 min/dia (5 dias/rodada)
Cap MP (F1):  MP1=127t, MP2=50,4t, MP3=75,6t
Fornec. MP1:  Manaus(R$48k/t,lt3), Belém(R$56k/t,lt3)
Fornec. MP2:  Cuiabá(R$16k/t,lt2), V.Conquista(R$22k/t,lt2)
Fornec. MP3:  Joinville(R$41k/t,lt0), Porto Alegre(R$32k/t,lt1)
Frete viagem: Cam=8, Navio=5, Avião=12 (R$/km)
Frete peso:   Cam=0,5, Navio=0,075, Avião=18 (R$/km·t)
Cap modal:    Cam=24t, Navio=100t, Avião=1t
```

## Objetivo do solver

```
max   lucro_R_atual
    + (1/3)  Σ_s lucro_R+1(s)        s ∈ {PA1,PA2,PA3} cenários (rodada cheia)
    + (1/3²) Σ   lucro_R+2(...)      (mais leve)

  lucro_r = Σ(entregue × preço) − compra_MP − frete − carregamento
          − α · (demanda − entregue)        ← NS como receita, α ALTO (~3× preço)
```
Estoque ligado entre rodadas: `stk_mp[fim r] = stk_mp[início r+1]` = **buffer endógeno**.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `forecast.py` | HW série densa por (cidade, produto), auto-tuna, share 100%, ×1,05 de-viés, backtest |
| `milp_multi.py` | modelo MILP multi-rodada + cenários 1/3 + buffer de MP |
| `solve_v2.py` | entry point: estado → forecast → solver → Excel + DRE |

## Plano de build (incremental)

1. **forecast.py** — previsão por produto/cidade das próximas 3 rodadas. ✅ validável isolado.
2. **milp_multi base** — R_atual sozinha, NS soft (α), buffer de MP endógeno.
3. **+ cenários R+1** (3 cenários, buffer compartilhado).
4. **+ R+2** (se rodar rápido).
5. Validação 12 regras + Excel + DRE.
