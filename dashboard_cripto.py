"""
dashboard_cripto.py — Gráficos (Plotly) e cards HTML do dashboard BTCUSDT/ETHUSDT.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

CORES = {
    "fundo": "#12151c", "papel": "#181c25", "borda": "#2a2f3a",
    "texto": "#e8eaf0", "fraco": "#8b93a7",
    "alta": "#2ecc71", "baixa": "#e74c3c", "neutro": "#4d9dff",
    "call": "#2ecc71", "put": "#e74c3c",
    "roxo": "#c25bef", "rosa": "#e0568c",
}
FONTE = "JetBrains Mono, monospace"

JANELA_PERCENTIL_PADRAO = 365  # janela rolante (P20/P80) — mesma janela usada nas
                                # bandas de desvio-padrão, equivalente cripto do
                                # rolling(252) usado no dashboard de ações (streamlitB3)


# ---------------------------------------------------------------------------
# CARDS / TABELAS (HTML puro, injetado via st.html)
# ---------------------------------------------------------------------------

def _card(label: str, valor: str, cor: str | None = None) -> str:
    cor = cor or CORES["texto"]
    return (f'<div class="card"><div class="card-label">{label}</div>'
            f'<div class="card-value" style="color:{cor};">{valor}</div></div>')


def _card_box(label: str, valor: str, cor: str | None = None) -> str:
    cor = cor or CORES["texto"]
    return (f'<div class="box"><span class="box-label">{label}: </span>'
            f'<span class="box-value" style="color:{cor};">{valor}</span></div>')


def _tabela_pin_candidates(pin_candidates: list) -> str:
    if not pin_candidates:
        return '<div class="disclaimer">Sem candidatos de pin próximos ao spot.</div>'
    linhas = "".join(
        f'<tr><td>{p["strike"]:,.0f}</td><td>{p["dist_pct"]:+.2f}%</td>'
        f'<td style="color:{CORES["alta"] if p["gex_musd"] >= 0 else CORES["baixa"]};">'
        f'{p["gex_musd"]:+.2f}M</td></tr>'
        for p in pin_candidates
    )
    return (f'<table class="tabela"><thead><tr><th>Strike</th><th>Dist. Spot</th>'
            f'<th>GEX</th></tr></thead><tbody>{linhas}</tbody></table>')


def _tabela_zonas(zonas: list) -> str:
    if not zonas:
        return '<div class="disclaimer">Sem zonas significativas de GEX.</div>'
    linhas = "".join(
        f'<tr><td>{z["strike"]:,.0f}</td><td>{z["lado"]}</td>'
        f'<td style="color:{CORES["alta"] if z["gex_musd"] >= 0 else CORES["baixa"]};">'
        f'{z["gex_musd"]:+.2f}M</td></tr>'
        for z in zonas
    )
    return (f'<table class="tabela"><thead><tr><th>Strike</th><th>Lado</th>'
            f'<th>GEX</th></tr></thead><tbody>{linhas}</tbody></table>')


# ---------------------------------------------------------------------------
# GRÁFICOS
# ---------------------------------------------------------------------------

def _layout_base(fig: go.Figure, altura: int = 380) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=40, r=20, t=40, b=30),
        paper_bgcolor=CORES["papel"], plot_bgcolor=CORES["papel"],
        font=dict(family=FONTE, color=CORES["texto"], size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(bgcolor=CORES["fundo"], font_family=FONTE),
    )
    fig.update_xaxes(gridcolor=CORES["borda"], zeroline=False)
    fig.update_yaxes(gridcolor=CORES["borda"], zeroline=False)
    return fig


def fig_gex_profile(gex: dict, ticker: str) -> go.Figure:
    df = gex["por_strike"]
    cores_barras = [CORES["call"] if v >= 0 else CORES["put"] for v in df["gex_usd"]]

    fig = go.Figure()
    fig.add_bar(x=df["strike"], y=df["gex_usd"] / 1e6, marker_color=cores_barras,
                name="GEX por strike",
                hovertemplate="Strike %{x:,.0f}<br>GEX %{y:+.2f}M<extra></extra>")

    fig.add_vline(x=gex["spot"], line_dash="dot", line_color=CORES["neutro"],
                  annotation_text="Spot", annotation_font_color=CORES["neutro"])
    fig.add_vline(x=gex["gamma_flip"], line_dash="dash", line_color=CORES["fraco"],
                  annotation_text="Gamma Flip", annotation_font_color=CORES["fraco"])
    if pd.notna(gex["call_wall"]):
        fig.add_vline(x=gex["call_wall"], line_color=CORES["call"], opacity=0.45,
                       annotation_text="Call Wall", annotation_font_color=CORES["call"],
                       annotation_position="top left")
    if pd.notna(gex["put_wall"]):
        fig.add_vline(x=gex["put_wall"], line_color=CORES["put"], opacity=0.45,
                       annotation_text="Put Wall", annotation_font_color=CORES["put"],
                       annotation_position="bottom left")

    fig.update_layout(title=f"Gamma Exposure Profile — {ticker}")
    fig.update_yaxes(title="GEX (US$ milhões / 1% de variação)")
    fig.update_xaxes(title="Strike (US$)")
    return _layout_base(fig, altura=400)


def _rolling_percentis(serie: pd.Series, janela: int = JANELA_PERCENTIL_PADRAO,
                        p_baixo: float = 0.2, p_alto: float = 0.8):
    """Percentis móveis (rolling) de uma série (ex.: HV ou RSI), calculados sobre uma
    janela de `janela` períodos (padrão: 365 — janela rolante-padrão cripto, equivalente
    ao rolling(252) usado no dashboard de ações de referência).

    `min_periods` menor que a janela cheia permite que as faixas P20/P80 já apareçam
    no início da série, mesmo antes de existirem 365 observações — evita um trecho
    inicial todo em branco (NaN) no gráfico.
    """
    min_periodos = max(20, janela // 5)
    p20 = serie.rolling(janela, min_periods=min_periodos).quantile(p_baixo)
    p80 = serie.rolling(janela, min_periods=min_periodos).quantile(p_alto)
    return p20, p80


def fig_preco_vol_rsi(precos_ind: pd.DataFrame, bandas: pd.DataFrame, ticker: str,
                       period: int, janela_percentil: int = JANELA_PERCENTIL_PADRAO) -> go.Figure:
    """3 painéis empilhados, réplica fiel do gráfico de referência (streamlitB3 /
    gerar_dashboard._fig_direita):

    (1) Preço + baseline (média móvel simples de `period` períodos sobre o log-preço
        normalizado) + bandas de desvio-padrão ROLANTE (±1/2/3σ, sem preenchimento,
        com opacidade em degradê) + marcadores coloridos nos pontos onde o fechamento
        se afasta da baseline: roxo (≥3σ/≤-3σ), azul (≥1σ/≤-2σ) e rosa (≥1σ/≤-1σ) —
        prioridade roxo > azul > rosa quando as faixas se sobrepõem.
    (2) Volatilidade histórica anualizada + faixas de percentil MÓVEL (P20/P80,
        janela rolante de `janela_percentil` períodos) calculadas em cima da própria
        série de volatilidade — mostra se a vol de hoje está "cara" ou "barata" frente
        ao regime recente do próprio ativo.
    (3) RSI curto (14) + RSI de janela rolante longa (365) + as mesmas faixas de
        percentil móvel (P20/P80), agora calculadas em cima do RSI(14) — complementa
        as linhas fixas de sobrecompra/sobrevenda (70/30).
    """
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05,
        row_heights=[0.42, 0.28, 0.30],
        subplot_titles=(
            f"{ticker} — Preço",
            f"Volatilidade Histórica (30 dias, anualizada) — Baseada em Retornos "
            f"(com P20/P80 móveis, janela {janela_percentil})",
            f"RSI (14) (com P20/P80 móveis, janela {janela_percentil})",
        ),
    )

    # ---- Painel 1: preço + baseline (média móvel) + bandas de desvio-padrão ----
    for n in (3, 2, 1):
        fig.add_scatter(x=bandas["data"], y=bandas[f"banda-{n}"], name=f"Banda -{n}",
                         line=dict(color=CORES["baixa"], width=1, dash="dot"),
                         opacity=0.35 + 0.15 * (3 - n), showlegend=False, row=1, col=1)
    for n in (1, 2, 3):
        fig.add_scatter(x=bandas["data"], y=bandas[f"banda+{n}"], name=f"Banda +{n}",
                         line=dict(color=CORES["alta"], width=1, dash="dot"),
                         opacity=0.35 + 0.15 * (3 - n), showlegend=False, row=1, col=1)
    fig.add_scatter(x=bandas["data"], y=bandas["banda_0"], name=f"Baseline (MM {period})",
                     line=dict(color=CORES["neutro"], width=1.4, dash="dash"),
                     showlegend=False, row=1, col=1)
    fig.add_scatter(x=precos_ind["data"], y=precos_ind["fechamento"], name="Fechamento",
                     line=dict(color=CORES["texto"], width=1.6), row=1, col=1)

    # marcadores de desvio: fechamento vs baseline, em unidades de desvio-padrão
    fechamento = precos_ind["fechamento"].reset_index(drop=True)
    banda0 = bandas["banda_0"].reset_index(drop=True)
    std = (bandas["banda+1"] - bandas["banda_0"]).reset_index(drop=True)
    desvio = (fechamento - banda0) / std
    datas = precos_ind["data"].reset_index(drop=True)

    mask_roxo = (desvio >= 3) | (desvio <= -3)
    mask_azul = ~mask_roxo & ((desvio >= 1) | (desvio <= -2))
    mask_rosa = ~mask_roxo & ~mask_azul & ((desvio >= 1) | (desvio <= -1))

    for mask, cor, nome in (
        (mask_roxo, CORES["roxo"], "≥3σ / ≤-3σ"),
        (mask_azul, CORES["neutro"], "≥1σ / ≤-2σ"),
        (mask_rosa, CORES["rosa"], "≥1σ / ≤-1σ"),
    ):
        if mask.any():
            fig.add_scatter(
                x=datas[mask], y=fechamento[mask], mode="markers", name=nome,
                marker=dict(color=cor, size=6, line=dict(color=CORES["fundo"], width=0.5)),
                showlegend=False, row=1, col=1,
            )

    # ---- Painel 2: volatilidade histórica + faixas de percentil móvel (P20/P80) ----
    fig.add_scatter(x=precos_ind["data"], y=precos_ind["hv_anualizada"], name="Vol. hist. anualizada",
                     line=dict(color=CORES["neutro"], width=1.6), row=2, col=1)

    hv_p20, hv_p80 = _rolling_percentis(precos_ind["hv_anualizada"], janela_percentil)
    fig.add_scatter(x=precos_ind["data"], y=hv_p80, name=f"HV P80 (rolante {janela_percentil})",
                     line=dict(color=CORES["roxo"], width=1, dash="dot"), showlegend=False, row=2, col=1)
    fig.add_scatter(x=precos_ind["data"], y=hv_p20, name=f"HV P20 (rolante {janela_percentil})",
                     line=dict(color=CORES["rosa"], width=1, dash="dot"), showlegend=False, row=2, col=1)
    if pd.notna(hv_p80.iloc[-1]):
        fig.add_annotation(x=precos_ind["data"].iloc[-1], y=hv_p80.iloc[-1], xref="x2", yref="y2",
                            text="P80", showarrow=False, font=dict(size=9, color=CORES["roxo"]),
                            xanchor="left", xshift=8)
    if pd.notna(hv_p20.iloc[-1]):
        fig.add_annotation(x=precos_ind["data"].iloc[-1], y=hv_p20.iloc[-1], xref="x2", yref="y2",
                            text="P20", showarrow=False, font=dict(size=9, color=CORES["rosa"]),
                            xanchor="left", xshift=8)

    # ---- Painel 3: RSI curto (14) + RSI de janela rolante longa (365) + percentis móveis do RSI(14) ----
    fig.add_scatter(x=precos_ind["data"], y=precos_ind["rsi"], name="RSI(14)",
                     line=dict(color=CORES["rosa"], width=1.6), row=3, col=1)
    fig.add_scatter(x=precos_ind["data"], y=precos_ind["rsi_365"], name="RSI(365, rolante)",
                     line=dict(color=CORES["neutro"], width=1.2, dash="dash"), row=3, col=1)
    fig.add_hline(y=70, line=dict(color=CORES["neutro"], width=1, dash="dot"), row=3, col=1)
    fig.add_hline(y=30, line=dict(color=CORES["roxo"], width=1, dash="dot"), row=3, col=1)

    rsi_p20, rsi_p80 = _rolling_percentis(precos_ind["rsi"], janela_percentil)
    fig.add_scatter(x=precos_ind["data"], y=rsi_p80, name=f"RSI P80 (rolante {janela_percentil})",
                     line=dict(color=CORES["roxo"], width=1, dash="dot"), showlegend=False, row=3, col=1)
    fig.add_scatter(x=precos_ind["data"], y=rsi_p20, name=f"RSI P20 (rolante {janela_percentil})",
                     line=dict(color=CORES["rosa"], width=1, dash="dot"), showlegend=False, row=3, col=1)
    if pd.notna(rsi_p80.iloc[-1]):
        fig.add_annotation(x=precos_ind["data"].iloc[-1], y=rsi_p80.iloc[-1], xref="x3", yref="y3",
                            text="P80", showarrow=False, font=dict(size=9, color=CORES["roxo"]),
                            xanchor="left", xshift=8)
    if pd.notna(rsi_p20.iloc[-1]):
        fig.add_annotation(x=precos_ind["data"].iloc[-1], y=rsi_p20.iloc[-1], xref="x3", yref="y3",
                            text="P20", showarrow=False, font=dict(size=9, color=CORES["rosa"]),
                            xanchor="left", xshift=8)

    fig.update_layout(title=f"Preço, Volatilidade & RSI — {ticker}", showlegend=False)
    fig.update_yaxes(title="Preço (US$)", row=1, col=1)
    fig.update_yaxes(title="Vol. anual. (%)", row=2, col=1)
    fig.update_yaxes(title="RSI", range=[0, 100], row=3, col=1)
    return _layout_base(fig, altura=780)
