"""
coletar_dados.py — Script de coleta OFFLINE (rodado pelo GitHub Actions, não
pelo Streamlit).

Busca cotações na Binance e a cadeia de opções curtas na Deribit, para BTC
e ETH, e grava tudo em CSV/JSON dentro de data/. O app Streamlit
(streamlit_app_cripto.py) NUNCA chama Binance/Deribit diretamente — ele só
lê esses arquivos publicados aqui, via raw.githubusercontent.com (ver
leitura_repo.py). Isso evita os bloqueios de rede (erro 451 da Binance por
geobloqueio, etc.) que costumam acontecer quando o Streamlit roda em nuvem.

Rodar manualmente:
    python coletar_dados.py

Rodado automaticamente pelo workflow .github/workflows/coleta.yml (cron).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import coleta_dados as cd

DIRETORIO_DADOS = Path(__file__).resolve().parent / "data"
DIAS_ALVO_PADRAO = 2.0   # opções CURTAS: vencimento-alvo ~2 dias, conforme pedido
N_VENCIMENTOS = 3        # quantos vencimentos próximos salvar (dá uma escolha no app)


def _escolher_vencimentos(instrumentos: pd.DataFrame, dias_alvo: float, n: int) -> list[pd.Timestamp]:
    """Pega o vencimento mais próximo de 'agora + dias_alvo' e mais até
    (n-1) vizinhos cronológicos, pra dar uma pequena faixa de escolha no
    dashboard sem precisar coletar TODOS os vencimentos (que seriam
    centenas de contratos e chamadas de API desnecessárias)."""
    agora = pd.Timestamp.now(tz="UTC")
    vencimentos = sorted(v for v in instrumentos["vencimento"].drop_duplicates() if v > agora)
    if not vencimentos:
        raise ValueError("Nenhum vencimento futuro encontrado na Deribit.")
    alvo = agora + pd.Timedelta(days=dias_alvo)
    idx = min(range(len(vencimentos)), key=lambda i: abs(vencimentos[i] - alvo))
    inicio = max(0, idx - 1)
    selecionados = vencimentos[inicio:inicio + n]
    return selecionados or [vencimentos[idx]]


def coletar_ativo(ativo: str) -> None:
    symbol = cd.ATIVOS[ativo]["binance_symbol"]
    currency = cd.ATIVOS[ativo]["deribit_currency"]

    print(f"[{ativo}] Buscando cotações na Binance ({symbol})...")
    # 1000 candles diários (máximo permitido por chamada da Binance) — precisa
    # de bastante histórico pra alimentar as janelas ROLANTES de 365 períodos
    # (RSI longo, quartis de volatilidade, desvio-padrão das bandas de preço).
    # Com 300 candles essas métricas ficariam quase todas em branco (NaN).
    precos = cd.obter_precos_binance(symbol, "1d", 1000)
    spot = cd.obter_preco_atual_binance(symbol)
    print(f"[{ativo}] Spot: {spot:,.2f}")

    print(f"[{ativo}] Buscando instrumentos de opções na Deribit ({currency})...")
    instrumentos = cd.obter_instrumentos_opcoes(currency)
    vencimentos_alvo = _escolher_vencimentos(instrumentos, DIAS_ALVO_PADRAO, N_VENCIMENTOS)
    print(f"[{ativo}] Vencimentos coletados: {[v.isoformat() for v in vencimentos_alvo]}")

    cadeias = []
    for venc in vencimentos_alvo:
        print(f"[{ativo}]   -> montando cadeia do vencimento {venc:%Y-%m-%d %H:%M UTC}...")
        cadeias.append(cd.montar_cadeia(instrumentos, venc))
    cadeia = pd.concat(cadeias, ignore_index=True)

    DIRETORIO_DADOS.mkdir(parents=True, exist_ok=True)
    precos.to_csv(DIRETORIO_DADOS / f"precos_{ativo}.csv", index=False)
    cadeia.to_csv(DIRETORIO_DADOS / f"opcoes_{ativo}.csv", index=False)

    meta = {
        "ativo": ativo,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "spot": spot,
        "fonte_spot": "binance",
        "fonte_opcoes": "deribit",
        "dias_alvo_vencimento_curto": DIAS_ALVO_PADRAO,
        "vencimentos_disponiveis": [v.isoformat() for v in vencimentos_alvo],
        "n_contratos": int(len(cadeia)),
    }
    with open(DIRETORIO_DADOS / f"meta_{ativo}.json", "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"[{ativo}] OK — {len(precos)} candles, {len(cadeia)} contratos salvos em {DIRETORIO_DADOS}")


def main():
    erros = []
    for ativo in cd.ATIVOS:
        try:
            coletar_ativo(ativo)
        except Exception as e:
            print(f"[{ativo}] ERRO: {e}", file=sys.stderr)
            erros.append((ativo, str(e)))

    # Só falha o job (código de saída != 0) se TODOS os ativos falharem —
    # assim um problema pontual num ativo não impede o outro de ser
    # publicado, e o workflow ainda comita o que deu certo.
    if erros and len(erros) == len(cd.ATIVOS):
        sys.exit(1)


if __name__ == "__main__":
    main()
