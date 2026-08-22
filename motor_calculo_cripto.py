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

DIAS_ANO_CRIPTO = 365  # cripto negocia 24/7 -> anualização com 365 dias


# ---------------------------------------------------------------------------
# INDICADORES DE PREÇO (RSI + volatilidade histórica)
# ---------------------------------------------------------------------------

def calcular_indicadores_precos(precos: pd.DataFrame, janela_rsi: int = 14,
                                 janela_hv: int = 30) -> pd.DataFrame:
    df = precos.copy().sort_values("data").reset_index(drop=True)

    delta = df["fechamento"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / janela_rsi, min_periods=janela_rsi, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / janela_rsi, min_periods=janela_rsi, adjust=False).mean()
    rs = media_ganho / media_perda.replace(0, np.nan)
    df["rsi"] = (100 - (100 / (1 + rs))).fillna(50)

    log_ret = np.log(df["fechamento"] / df["fechamento"].shift(1))
    df["hv_anualizada"] = log_ret.rolling(janela_hv).std() * np.sqrt(DIAS_ANO_CRIPTO) * 100

    hv_valida = df["hv_anualizada"].dropna()
    if len(hv_valida) >= 30:
        df["hv_rank"] = hv_valida.rank(pct=True).reindex(df.index) * 100
        base = hv_valida.tail(min(len(hv_valida), 365))
        df["hv_percentil"] = df["hv_anualizada"].apply(
            lambda v: (base < v).mean() * 100 if pd.notna(v) else np.nan)
    else:
        df["hv_rank"] = np.nan
        df["hv_percentil"] = np.nan

    return df


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
