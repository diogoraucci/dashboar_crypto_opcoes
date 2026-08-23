"""
motor_calculo_cripto.py — Métricas de GEX, RSI, volatilidade histórica e
métricas de contrato para o dashboard BTCUSDT/ETHUSDT.

Convenção de GEX (padrão de trackers públicos, ex. SpotGamma-like): dealers
líquidos assumidos COMPRADOS em calls (+gamma) e VENDIDOS em puts (-gamma).
As gregas (gamma, delta) e o open interest usados aqui vêm direto do modelo
de precificação da própria Deribit (campo 'greeks' do ticker) — não
recalculamos Black-Scholes, pra não introduzir uma segunda fonte de IV.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DIAS_ANO_CRIPTO = 365   # cripto negocia 24/7 -> anualização com 365 dias
JANELA_ROLANTE = 365    # janela rolante padrão (RSI longo, quartis de vol) — equivalente
                         # cripto do rolling(252) usado em ações (252 = dias úteis de bolsa;
                         # 365 = dias corridos, já que cripto não tem fim de semana)
MIN_PERIODOS_ROLANTE = 180  # começa a exibir métricas rolantes de 365 já com ~6 meses de histórico


# ---------------------------------------------------------------------------
# RSI (genérico, usado tanto pro RSI curto quanto pro RSI de janela longa)
# ---------------------------------------------------------------------------

def _rsi(fechamento: pd.Series, janela: int) -> pd.Series:
    delta = fechamento.diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / janela, min_periods=janela, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / janela, min_periods=janela, adjust=False).mean()
    rs = media_ganho / media_perda.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


# ---------------------------------------------------------------------------
# INDICADORES DE PREÇO (RSI curto + RSI de janela rolante longa + volatilidade
# histórica com bandas de quartil rolantes)
# ---------------------------------------------------------------------------

def calcular_indicadores_precos(precos: pd.DataFrame, janela_rsi: int = 14,
                                 janela_hv: int = 30, janela_rolante: int = JANELA_ROLANTE,
                                 min_periodos_rolante: int = MIN_PERIODOS_ROLANTE) -> pd.DataFrame:
    df = precos.copy().sort_values("data").reset_index(drop=True)

    # RSI "curto" (14, padrão de mercado) e RSI de JANELA ROLANTE LONGA (365
    # períodos) — mesmo oscilador, só que calculado com lookback de ~1 ano,
    # pra captar momentum de prazo mais longo (a versão cripto do que
    # normalmente seria feito com 252 dias úteis em ações).
    df["rsi"] = _rsi(df["fechamento"], janela_rsi)
    df["rsi_365"] = _rsi(df["fechamento"], janela_rolante)

    # Volatilidade histórica anualizada (rolling 30 dias de log-retorno, anualizada por sqrt(365))
    log_ret = np.log(df["fechamento"] / df["fechamento"].shift(1))
    df["hv_anualizada"] = log_ret.rolling(janela_hv).std() * np.sqrt(DIAS_ANO_CRIPTO) * 100

    # Bandas de quartil da volatilidade, em JANELA ROLANTE (365 períodos):
    # a cada dia, olha só pros últimos 365 valores de HV e calcula onde ficam
    # o quantil 0.2 e o quantil 0.8 dessa janela — mostra se a vol de hoje
    # está "alta" ou "baixa" frente ao próprio histórico recente (não frente
    # à série toda, que ficaria estática e não se adaptaria a novos regimes).
    hv_rolante = df["hv_anualizada"].rolling(janela_rolante, min_periods=min_periodos_rolante)
    df["hv_q20_365"] = hv_rolante.quantile(0.2)
    df["hv_q80_365"] = hv_rolante.quantile(0.8)

    return df


# ---------------------------------------------------------------------------
# BANDAS DE MÉDIA MÓVEL + DESVIO-PADRÃO (préço) — réplica do script
# OMSF/NoTrend original, com o período da média móvel ajustável (seletor na
# sidebar) e o desvio-padrão calculado em JANELA ROLANTE.
# ---------------------------------------------------------------------------

def calcular_bandas_desvio_padrao(precos_ind: pd.DataFrame, period: int,
                                   janela_std: int = JANELA_ROLANTE) -> pd.DataFrame:
    """
    1) Normaliza o fechamento em log: log(close / close[0]).
    2) Média móvel SIMPLES (rolling) do log-preço, janela = `period` — é o
       valor escolhido no seletor "Período (Média Móvel)" da sidebar.
    3) close_no_trend = log-preço - média móvel.
    4) Desvio-padrão ROLANTE (janela = `janela_std`, padrão 365 períodos —
       equivalente cripto do rolling(252) usado no script original de ações)
       de close_no_trend.
    5) Bandas = média móvel ± N × desvio-padrão (N = 1, 2, 3), calculadas em
       escala log e projetadas de volta pra escala de preço via exp(), pra
       sobrepor corretamente o gráfico de preço em US$.
    """
    close = precos_ind["fechamento"]
    preco_base = float(close.iloc[0])

    log_close = np.log(close / preco_base)
    media_movel = log_close.rolling(period).mean()
    close_no_trend = log_close - media_movel
    std = close_no_trend.rolling(janela_std, min_periods=max(30, janela_std // 4)).std()

    bandas_log = pd.DataFrame(index=precos_ind.index)
    bandas_log["banda_0"] = media_movel
    for n in (1, 2, 3):
        bandas_log[f"banda+{n}"] = media_movel + std * n
        bandas_log[f"banda-{n}"] = media_movel - std * n

    bandas = np.exp(bandas_log) * preco_base
    bandas["data"] = precos_ind["data"].values
    return bandas


# ---------------------------------------------------------------------------
# GEX — Gamma Exposure por strike
# ---------------------------------------------------------------------------

def calcular_gex(cadeia: pd.DataFrame, spot: float, banda_pin_pct: float = 5.0,
                  n_zonas: int = 8) -> dict:
    """GEX por strike a partir da cadeia (já filtrada para o vencimento curto
    escolhido). GEX de cada contrato = gamma * open_interest * spot^2 * 0.01
    (variação de 1% no spot), com sinal +1 para calls e -1 para puts."""
    df = cadeia.dropna(subset=["gamma"]).copy()
    df = df[df["open_interest"] > 0]
    if df.empty:
        raise ValueError(
            "Cadeia de opções sem gregas/open interest suficientes para "
            "calcular o GEX neste vencimento. Tente outro vencimento-alvo na sidebar."
        )

    sinal = np.where(df["tipo"] == "CALL", 1.0, -1.0)
    df["gex_usd"] = sinal * df["gamma"] * df["open_interest"] * (spot ** 2) * 0.01

    por_strike = (df.groupby("strike", as_index=False)["gex_usd"].sum()
                  .sort_values("strike").reset_index(drop=True))
    por_strike["gex_acumulado"] = por_strike["gex_usd"].cumsum()

    gamma_flip = _interpolar_zero(por_strike["strike"].to_numpy(),
                                   por_strike["gex_acumulado"].to_numpy())
    if gamma_flip is None:
        gamma_flip = float(por_strike.loc[por_strike["gex_acumulado"].abs().idxmin(), "strike"])

    calls = df.loc[df["tipo"] == "CALL"].groupby("strike")["gex_usd"].sum()
    puts = df.loc[df["tipo"] == "PUT"].groupby("strike")["gex_usd"].sum()
    call_wall = float(calls.idxmax()) if not calls.empty else float("nan")
    put_wall = float(puts.idxmin()) if not puts.empty else float("nan")

    oi_call = float(df.loc[df["tipo"] == "CALL", "open_interest"].sum())
    oi_put = float(df.loc[df["tipo"] == "PUT", "open_interest"].sum())
    pcr = (oi_put / oi_call) if oi_call else float("nan")
    sentiment = "Bearish" if pcr > 1.2 else ("Bullish" if pcr < 0.8 else "Neutral")

    banda = spot * banda_pin_pct / 100
    prox = df[(df["strike"] >= spot - banda) & (df["strike"] <= spot + banda)]
    iv_call_otm = prox.loc[(prox["tipo"] == "CALL") & (prox["strike"] >= spot), "mark_iv"].mean()
    iv_put_otm = prox.loc[(prox["tipo"] == "PUT") & (prox["strike"] <= spot), "mark_iv"].mean()
    iv_skew = float(iv_put_otm - iv_call_otm) if pd.notna(iv_put_otm) and pd.notna(iv_call_otm) else 0.0

    flip_dist = float((spot - gamma_flip) / gamma_flip * 100) if gamma_flip else float("nan")
    if spot > gamma_flip:
        regime, hedging = "Long Gamma", "Dealers tendem a estabilizar o preço (compram na queda / vendem na alta)."
    else:
        regime, hedging = "Short Gamma", "Dealers tendem a amplificar o movimento (vendem na queda / compram na alta)."

    zonas = por_strike.reindex(por_strike["gex_usd"].abs().sort_values(ascending=False).index)
    zonas = zonas.head(n_zonas).sort_values("strike")
    zonas_significativas = [
        {"strike": float(r["strike"]), "gex_musd": float(r["gex_usd"] / 1e6),
         "lado": "CALL" if r["gex_usd"] >= 0 else "PUT"}
        for _, r in zonas.iterrows()
    ]

    pin_pool = por_strike[(por_strike["strike"] >= spot - banda) & (por_strike["strike"] <= spot + banda)]
    pin_pool = pin_pool.reindex(pin_pool["gex_usd"].abs().sort_values(ascending=False).index).head(5)
    pin_candidates = [
        {"strike": float(r["strike"]), "gex_musd": float(r["gex_usd"] / 1e6),
         "dist_pct": float((r["strike"] - spot) / spot * 100)}
        for _, r in pin_pool.sort_values("strike").iterrows()
    ]

    return {
        "spot": float(spot), "call_wall": call_wall, "put_wall": put_wall,
        "gamma_flip": float(gamma_flip), "flip_dist": flip_dist,
        "pcr": pcr, "sentiment": sentiment, "iv_skew": iv_skew,
        "regime": regime, "hedging": hedging,
        "por_strike": por_strike, "zonas_significativas": zonas_significativas,
        "pin_candidates": pin_candidates, "oi_call": oi_call, "oi_put": oi_put,
        "n_contratos": int(len(df)),
    }


def _interpolar_zero(x: np.ndarray, y: np.ndarray):
    """Interpola linearmente o strike onde o GEX acumulado cruza zero."""
    for i in range(1, len(x)):
        if (y[i - 1] < 0 <= y[i]) or (y[i - 1] > 0 >= y[i]):
            if y[i] == y[i - 1]:
                return float(x[i])
            frac = -y[i - 1] / (y[i] - y[i - 1])
            return float(x[i - 1] + frac * (x[i] - x[i - 1]))
    return None


# ---------------------------------------------------------------------------
# MÉTRICAS DO CONTRATO EM DESTAQUE (CALL mais próxima do spot, ATM)
# ---------------------------------------------------------------------------

def metricas_contrato_atm(cadeia: pd.DataFrame, spot: float, tipo: str = "CALL") -> dict:
    subset = cadeia[cadeia["tipo"] == tipo].dropna(subset=["strike"]).copy()
    if subset.empty:
        raise ValueError(f"Sem contratos do tipo {tipo} na cadeia deste vencimento.")
    subset["dist"] = (subset["strike"] - spot).abs()
    linha = subset.sort_values("dist").iloc[0]

    bid, ask = linha.get("best_bid"), linha.get("best_ask")
    if pd.notna(bid) and pd.notna(ask):
        preco_mercado = (float(bid) + float(ask)) / 2 * spot
    elif pd.notna(linha.get("mark_price_btc")):
        preco_mercado = float(linha["mark_price_btc"]) * spot
    else:
        preco_mercado = float("nan")

    def _f(v):
        return float(v) if pd.notna(v) else float("nan")

    return {
        "codigo": linha["instrument_name"], "tipo": tipo, "strike": float(linha["strike"]),
        "vencimento": linha["vencimento"], "preco_mercado": float(preco_mercado),
        "iv_implicita": _f(linha["mark_iv"]), "delta": _f(linha["delta"]),
        "gamma": _f(linha["gamma"]), "open_interest": _f(linha["open_interest"]) or 0.0,
    }
