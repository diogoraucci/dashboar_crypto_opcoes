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
}
FONTE = "JetBrains Mono, monospace"


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


def fig_preco_rsi(precos_ind: pd.DataFrame, ticker: str) -> go.Figure:
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
                         vertical_spacing=0.05)

    fig.add_scatter(x=precos_ind["data"], y=precos_ind["fechamento"], name="Fechamento",
                     line=dict(color=CORES["neutro"], width=1.6), row=1, col=1)

    fig.add_scatter(x=precos_ind["data"], y=precos_ind["rsi"], name="RSI(14)",
                     line=dict(color="#c98bf0", width=1.4), row=2, col=1)
    fig.add_hline(y=70, line_dash="dot", line_color=CORES["baixa"], row=2, col=1)
    fig.add_hline(y=30, line_dash="dot", line_color=CORES["alta"], row=2, col=1)

    fig.update_layout(title=f"Preço & RSI — {ticker}")
    fig.update_yaxes(title="Preço (US$)", row=1, col=1)
    fig.update_yaxes(title="RSI", range=[0, 100], row=2, col=1)
    return _layout_base(fig, altura=460)
