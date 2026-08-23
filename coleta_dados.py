"""
coleta_dados.py — Coleta de dados EM TEMPO REAL para o dashboard cripto.

  - Cotações (spot, histórico de candles): Binance, REST público
    (https://api.binance.com), sem necessidade de API key.
  - Cadeia de opções (instrumentos, IV, gregas, open interest): Deribit,
    REST público (https://www.deribit.com/api/v2/public/...), sem
    necessidade de API key.

Nenhuma credencial é necessária — todos os endpoints usados aqui são
públicos (market data).
"""
from __future__ import annotations

import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# A Binance retorna 451 (bloqueio geográfico) em api.binance.com pra várias
# regiões/IPs (não é firewall local, é o próprio Binance recusando o
# endereço de origem). Por isso tentamos, em ordem, vários espelhos que
# servem os MESMOS dados públicos de mercado — o primeiro que responder
# 200 é usado, e o resultado fica em cache (ver _BASE_BINANCE_OK) pra não
# testar tudo de novo a cada chamada.
BINANCE_BASES = [
    "https://data-api.binance.vision",  # espelho oficial só de market data, sem geobloqueio
    "https://api1.binance.com",
    "https://api2.binance.com",
    "https://api3.binance.com",
    "https://api4.binance.com",
    "https://api.binance.com",
]
DERIBIT_BASE = "https://www.deribit.com/api/v2/public"

# Ativos suportados pelo dashboard (só BTC e ETH, conforme pedido)
ATIVOS = {
    "BTC": {"binance_symbol": "BTCUSDT", "deribit_currency": "BTC"},
    "ETH": {"binance_symbol": "ETHUSDT", "deribit_currency": "ETH"},
}

_session = requests.Session()
_session.headers.update({"User-Agent": "dashboard-opcoes-cripto/1.0"})

_base_binance_ok: str | None = None  # memoriza qual espelho funcionou


# ---------------------------------------------------------------------------
# BINANCE — cotações do ativo-objeto
# ---------------------------------------------------------------------------

def _get_binance(path: str, params: dict):
    """Faz um GET num endpoint público da Binance, tentando vários espelhos
    em sequência até um responder com sucesso (contorna o 451 de
    geobloqueio de api.binance.com em certas regiões)."""
    global _base_binance_ok
    bases = [_base_binance_ok] + [b for b in BINANCE_BASES if b != _base_binance_ok] \
        if _base_binance_ok else BINANCE_BASES

    ultimo_erro = None
    for base in bases:
        try:
            resp = _session.get(f"{base}{path}", params=params, timeout=15)
            if resp.status_code == 200:
                _base_binance_ok = base
                return resp.json()
            ultimo_erro = requests.HTTPError(
                f"{resp.status_code} {resp.reason} em {base}{path}", response=resp)
        except requests.RequestException as e:
            ultimo_erro = e
            continue
    raise ConnectionError(
        "Não foi possível acessar nenhum dos espelhos públicos da Binance "
        f"({', '.join(BINANCE_BASES)}). Último erro: {ultimo_erro}"
    )


def obter_precos_binance(symbol: str, interval: str = "1d", limit: int = 300) -> pd.DataFrame:
    """Histórico de candles (klines) da Binance — GET /api/v3/klines.

    Retorna DataFrame ordenado do mais antigo pro mais recente, com colunas
    data / abertura / maxima / minima / fechamento / volume.
    """
    dados = _get_binance("/api/v3/klines",
                          {"symbol": symbol, "interval": interval, "limit": limit})
    df = pd.DataFrame(dados, columns=[
        "open_time", "abertura", "maxima", "minima", "fechamento", "volume",
        "close_time", "quote_volume", "n_trades", "taker_base", "taker_quote", "ignore",
    ])
    df["data"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    for c in ("abertura", "maxima", "minima", "fechamento", "volume"):
        df[c] = df[c].astype(float)
    return df[["data", "abertura", "maxima", "minima", "fechamento", "volume"]].reset_index(drop=True)


def obter_preco_atual_binance(symbol: str) -> float:
    """Último preço negociado — GET /api/v3/ticker/price."""
    dados = _get_binance("/api/v3/ticker/price", {"symbol": symbol})
    return float(dados["price"])


# ---------------------------------------------------------------------------
# DERIBIT — cadeia de opções
# ---------------------------------------------------------------------------

def _get_deribit(method: str, params: dict) -> dict:
    resp = _session.get(f"{DERIBIT_BASE}/{method}", params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if "error" in payload:
        raise RuntimeError(f"Deribit {method}: {payload['error']}")
    return payload["result"]


def obter_index_price_deribit(currency: str) -> float:
    """Índice à vista usado pela própria Deribit (referência auxiliar; o
    'spot' oficial do dashboard continua sendo o preço da Binance)."""
    resultado = _get_deribit("get_index_price", {"index_name": f"{currency.lower()}_usd"})
    return float(resultado["index_price"])


def obter_instrumentos_opcoes(currency: str) -> pd.DataFrame:
    """Todos os instrumentos de opções ABERTOS (não expirados) — GET
    /public/get_instruments?currency=BTC&kind=option&expired=false."""
    resultado = _get_deribit("get_instruments", {
        # IMPORTANTE: a Deribit espera "false"/"true" em minúsculas na
        # query string. Um bool do Python (False) vira "False" (maiúsculo)
        # quando o requests monta a URL, e a Deribit responde 400 Bad
        # Request pra esse valor — por isso a string minúscula explícita.
        "currency": currency, "kind": "option", "expired": "false",
    })
    df = pd.DataFrame(resultado)
    if df.empty:
        return df
    df["vencimento"] = pd.to_datetime(df["expiration_timestamp"], unit="ms", utc=True)
    return df


def escolher_vencimento_curto(df_instrumentos: pd.DataFrame, dias_alvo: float = 2.0) -> pd.Timestamp:
    """Escolhe, entre os vencimentos futuros disponíveis na Deribit, o mais
    próximo de 'agora + dias_alvo dias' — usado para restringir o cálculo do
    GEX a OPÇÕES CURTAS (por padrão, vencimento em ~2 dias), como pedido."""
    if df_instrumentos.empty:
        raise ValueError("Nenhum instrumento de opção retornado pela Deribit.")
    agora = pd.Timestamp.now(tz="UTC")
    alvo = agora + pd.Timedelta(days=dias_alvo)
    vencimentos = df_instrumentos["vencimento"].drop_duplicates()
    vencimentos = vencimentos[vencimentos > agora]
    if vencimentos.empty:
        raise ValueError("Nenhum vencimento futuro encontrado na Deribit.")
    diffs = (vencimentos - alvo).abs()
    return vencimentos.loc[diffs.idxmin()]


def _ticker_um_instrumento(instrument_name: str) -> dict:
    return _get_deribit("ticker", {"instrument_name": instrument_name})


def montar_cadeia(instrumentos: pd.DataFrame, vencimento_alvo: pd.Timestamp,
                   max_workers: int = 12) -> pd.DataFrame:
    """Cadeia completa (todas as calls/puts) do vencimento escolhido, já
    cruzada com o ticker individual de cada contrato — GET /public/ticker
    (traz mark_iv, gregas, open_interest, book). As chamadas são feitas em
    paralelo (threads) via REST simples, evitando a complexidade de manter
    uma conexão WebSocket viva dentro do Streamlit."""
    cadeia_venc = instrumentos.loc[instrumentos["vencimento"] == vencimento_alvo].copy()
    if cadeia_venc.empty:
        raise ValueError("Vencimento escolhido não encontrado entre os instrumentos.")
    nomes = cadeia_venc["instrument_name"].tolist()

    tickers = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futuros = {pool.submit(_ticker_um_instrumento, nome): nome for nome in nomes}
        for futuro in as_completed(futuros):
            nome = futuros[futuro]
            try:
                tickers[nome] = futuro.result()
            except Exception:
                tickers[nome] = {}

    linhas = []
    for _, row in cadeia_venc.iterrows():
        nome = row["instrument_name"]
        t = tickers.get(nome) or {}
        gregas = t.get("greeks") or {}
        stats = t.get("stats") or {}
        linhas.append({
            "instrument_name": nome,
            "strike": float(row["strike"]),
            "tipo": "CALL" if str(row["option_type"]).lower() == "call" else "PUT",
            "vencimento": row["vencimento"],
            "mark_iv": t.get("mark_iv"),
            "mark_price_btc": t.get("mark_price"),
            "underlying_price": t.get("underlying_price"),
            "best_bid": t.get("best_bid_price"),
            "best_ask": t.get("best_ask_price"),
            "open_interest": t.get("open_interest"),
            "volume_24h": stats.get("volume"),
            "delta": gregas.get("delta"),
            "gamma": gregas.get("gamma"),
            "vega": gregas.get("vega"),
            "theta": gregas.get("theta"),
        })
    df = pd.DataFrame(linhas)
    colunas_numericas = ["mark_iv", "mark_price_btc", "underlying_price", "best_bid", "best_ask",
                          "open_interest", "volume_24h", "delta", "gamma", "vega", "theta"]
    for c in colunas_numericas:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_interest"] = df["open_interest"].fillna(0.0)
    return df.sort_values(["strike", "tipo"]).reset_index(drop=True)


def obter_cadeia_curta(currency: str, dias_alvo: float = 2.0):
    """Atalho: busca instrumentos, escolhe o vencimento curto e monta a
    cadeia completa com tickers — usado fora do Streamlit (ex.: testes)."""
    instrumentos = obter_instrumentos_opcoes(currency)
    vencimento_alvo = escolher_vencimento_curto(instrumentos, dias_alvo)
    cadeia = montar_cadeia(instrumentos, vencimento_alvo)
    return cadeia, vencimento_alvo
