"""
streamlit_app_cripto.py — Dashboard de Opções Cripto (BTCUSDT / ETHUSDT), 100% ao vivo.

Fontes de dados (nenhuma API key necessária — endpoints públicos):
  - Cotações (spot, histórico, RSI): Binance  -> api.binance.com
  - Cadeia de opções (IV, gregas, OI, GEX):   Deribit -> www.deribit.com

O painel de GEX usa, por padrão, o vencimento de opções disponível na
Deribit mais próximo de "hoje + 2 dias" (opções curtas), como pedido —
ajustável na sidebar.

Rodar localmente:
    pip install -r requirements.txt
    streamlit run streamlit_app_cripto.py
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import coleta_dados as cd
import motor_calculo_cripto as m
import dashboard_cripto as gd

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False

CORES = gd.CORES
st.set_page_config(page_title="Dashboard Cripto — Opções BTC/ETH", page_icon="₿", layout="wide")

TTL_COTACOES = 30  # segundos de cache local das cotações (Binance)
TTL_OPCOES = 30    # segundos de cache local da cadeia de opções (Deribit)


# ----------------------------------------------------------------------------
# TEMA — mesmas classes CSS do padrão original (cards/boxes/tabelas), paleta
# escura ajustada pro tema cripto.
# ----------------------------------------------------------------------------

def _injetar_tema():
    st.html(
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        'family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap">'
        f"<style>"
        f".titulo-painel {{ font-family:'JetBrains Mono',monospace; font-size:13px; color:{CORES['texto']}; margin-bottom:14px; }}"
        f".subtitulo {{ font-family:'JetBrains Mono',monospace; font-size:12px; color:{CORES['fraco']}; margin:18px 0 8px; text-transform:uppercase; letter-spacing:.05em; }}"
        f".cards-row {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:10px; }}"
        f".card {{ background:{CORES['fundo']}; border:1px solid {CORES['borda']}; border-radius:8px; padding:10px 12px; text-align:center; }}"
        f".card-label {{ font-family:'JetBrains Mono',monospace; font-size:10px; color:{CORES['fraco']}; text-transform:uppercase; margin-bottom:6px; }}"
        f".card-value {{ font-family:'JetBrains Mono',monospace; font-size:16px; font-weight:600; color:{CORES['texto']}; }}"
        f".boxes-row {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px; }}"
        f".box {{ border:1px solid {CORES['borda']}; border-radius:8px; padding:8px 14px; flex:1 1 150px; font-family:'JetBrains Mono',monospace; font-size:13px; white-space:nowrap; }}"
        f".box-label {{ color:{CORES['fraco']}; }}"
        f".box-value {{ color:{CORES['texto']}; font-weight:700; }}"
        f".tabela {{ width:100%; border-collapse:collapse; font-family:'JetBrains Mono',monospace; font-size:12px; margin-bottom:6px; color:{CORES['texto']}; }}"
        f".tabela th {{ text-align:left; color:{CORES['fraco']}; font-weight:500; padding:6px 8px; border-bottom:1px solid {CORES['borda']}; text-transform:uppercase; font-size:10px; }}"
        f".tabela td {{ padding:6px 8px; border-bottom:1px solid {CORES['borda']}; }}"
        f".disclaimer {{ margin-top:14px; font-size:11px; color:{CORES['fraco']}; line-height:1.5; }}"
        f"</style>"
    )


# ----------------------------------------------------------------------------
# WRAPPERS CACHEADOS — cache local curto (TTL) pra não martelar as APIs a
# cada interação da sidebar, mas ainda assim manter os dados "ao vivo".
# ----------------------------------------------------------------------------

@st.cache_data(ttl=TTL_COTACOES, show_spinner="Buscando cotações na Binance...")
def _precos_binance(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    return cd.obter_precos_binance(symbol, interval, limit)


@st.cache_data(ttl=TTL_COTACOES, show_spinner=False)
def _preco_atual_binance(symbol: str) -> float:
    return cd.obter_preco_atual_binance(symbol)


@st.cache_data(ttl=TTL_OPCOES, show_spinner="Buscando cadeia de opções na Deribit...")
def _cadeia_deribit(currency: str, dias_alvo: float):
    instrumentos = cd.obter_instrumentos_opcoes(currency)
    vencimento_alvo = cd.escolher_vencimento_curto(instrumentos, dias_alvo)
    cadeia = cd.montar_cadeia(instrumentos, vencimento_alvo)
    return cadeia, vencimento_alvo


# ----------------------------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------------------------

def _sidebar():
    st.sidebar.markdown("### ⚙️ Configuração")
    ativo = st.sidebar.radio("Ativo", ["BTC", "ETH"], horizontal=True)
    dias_alvo = st.sidebar.slider(
        "Vencimento-alvo do GEX (dias a partir de hoje)",
        min_value=0.5, max_value=14.0, value=2.0, step=0.5,
        help="O painel de GEX usa o vencimento de opções disponível na Deribit "
             "mais próximo desse número de dias — por padrão, opções CURTAS (~2 dias).")
    intervalo = st.sidebar.selectbox("Timeframe do gráfico de preço", ["1d", "4h", "1h"], index=0)

    auto = False
    if _AUTOREFRESH_OK:
        auto = st.sidebar.checkbox("Atualizar automaticamente (30s)", value=False)
        if auto:
            st_autorefresh(interval=30_000, key="auto_refresh_tick")
    else:
        st.sidebar.caption(
            "💡 Instale `streamlit-autorefresh` (pip install streamlit-autorefresh) "
            "para atualização automática em tempo real.")

    if st.sidebar.button("🔄 Atualizar agora", width="stretch"):
        st.cache_data.clear()

    st.sidebar.caption(
        "Cotações: Binance (REST, público) · Opções: Deribit (REST, público). "
        f"Cache local: {TTL_COTACOES}s (cotações) / {TTL_OPCOES}s (opções).")
    return ativo, dias_alvo, intervalo


# ----------------------------------------------------------------------------
# PAINÉIS
# ----------------------------------------------------------------------------

def _metricas_contrato(opcao: dict, spot: float):
    st.html('<div class="subtitulo">Contrato em destaque (CALL mais próxima do spot)</div>')
    linha1 = "".join([
        gd._card_box("CÓDIGO", opcao["codigo"]),
        gd._card_box("STRIKE", f"{opcao['strike']:,.0f}"),
        gd._card_box("VENCIMENTO", opcao["vencimento"].strftime("%d/%m %H:%M UTC")),
    ])
    st.html(f'<div class="boxes-row">{linha1}</div>')

    linha2 = "".join([
        gd._card_box("SPOT (BINANCE)", f"{spot:,.2f}"),
        gd._card_box("PREÇO MKT (US$)", f"{opcao['preco_mercado']:,.2f}"),
        gd._card_box("IV IMPLÍCITA", f"{opcao['iv_implicita']:.2f}%"),
        gd._card_box("DELTA", f"{opcao['delta']:.3f}"),
        gd._card_box("GAMMA", f"{opcao['gamma']:.6f}"),
        gd._card_box("OPEN INTEREST", f"{opcao['open_interest']:,.1f}"),
    ])
    st.html(f'<div class="boxes-row">{linha2}</div>')


def _metricas_gex(gex: dict, ticker: str, vencimento_alvo: pd.Timestamp):
    agora = datetime.now(timezone.utc)
    venc_str = vencimento_alvo.strftime("%d %b %Y, %H:%M UTC")
    horas_restantes = (vencimento_alvo.to_pydatetime() - agora).total_seconds() / 3600

    st.html(
        f'<div class="titulo-painel">GEX {ticker}USDT &bull; snapshot ao vivo &bull; '
        f'expiry {venc_str} (faltam {horas_restantes:.1f}h) &bull; {gex["n_contratos"]} contratos</div>')

    linha1 = "".join([
        gd._card("WALLS (C/P)", f"{gex['call_wall']:,.0f} / {gex['put_wall']:,.0f}"),
        gd._card("GAMMA FLIP", f"{gex['gamma_flip']:,.0f}", CORES["neutro"]),
        gd._card("PCR (OI)", f"{gex['pcr']:.2f}"),
        gd._card("SPOT", f"{gex['spot']:,.0f}"),
    ])
    st.html(f'<div class="cards-row">{linha1}</div>')

    st.html('<div class="subtitulo">Pin Candidates (&plusmn;5% do spot)</div>')
    st.html(gd._tabela_pin_candidates(gex["pin_candidates"]))

    cor_sent = (CORES["baixa"] if gex["sentiment"] == "Bearish"
                else CORES["alta"] if gex["sentiment"] == "Bullish" else CORES["fraco"])
    linha2 = "".join([
        gd._card("SENTIMENT", gex["sentiment"], cor_sent),
        gd._card("IV SKEW", f"{gex['iv_skew']:+.2f}pp"),
        gd._card("REGIME", gex["regime"], CORES["neutro"]),
        gd._card("FLIP DIST.", f"{gex['flip_dist']:+.2f}%"),
    ])
    st.html(f'<div class="cards-row">{linha2}</div>')
    st.html(f'<div class="disclaimer">{gex["hedging"]}</div>')

    st.html('<div class="subtitulo">Significant GEX Zones</div>')
    st.html(gd._tabela_zonas(gex["zonas_significativas"]))


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------

def main():
    _injetar_tema()
    ativo, dias_alvo, intervalo = _sidebar()

    symbol = cd.ATIVOS[ativo]["binance_symbol"]
    currency = cd.ATIVOS[ativo]["deribit_currency"]

    try:
        spot = _preco_atual_binance(symbol)
        precos = _precos_binance(symbol, intervalo, 300)
        precos_ind = m.calcular_indicadores_precos(precos)
    except Exception as e:
        st.error(
            f"Falha ao buscar cotações na Binance ({symbol}): {e}\n\n"
            "Se estiver rodando em um servidor/rede que bloqueia api.binance.com, "
            "verifique as configurações de rede/firewall.")
        return

    try:
        cadeia, vencimento_alvo = _cadeia_deribit(currency, dias_alvo)
    except Exception as e:
        st.error(f"Falha ao buscar opções na Deribit ({currency}): {e}")
        return

    try:
        gex = m.calcular_gex(cadeia, spot)
        opcao = m.metricas_contrato_atm(cadeia, spot, tipo="CALL")
    except Exception as e:
        st.error(f"Falha ao calcular GEX/métricas do contrato: {e}")
        return

    st.caption(
        f"**{ativo}USDT** · Spot US$ {spot:,.2f} (Binance) · "
        f"atualizado às {datetime.now().strftime('%H:%M:%S')} · "
        f"opções: {len(cadeia)} contratos no vencimento "
        f"{vencimento_alvo:%d/%m %H:%M UTC} (Deribit)")

    col_esq, col_dir = st.columns([2, 3], gap="large")

    with col_esq:
        with st.container(border=True):
            _metricas_contrato(opcao, spot)
            st.divider()
            _metricas_gex(gex, ativo, vencimento_alvo)

    with col_dir:
        with st.container(border=True):
            st.plotly_chart(gd.fig_preco_rsi(precos_ind, f"{ativo}USDT"),
                             use_container_width=True, config={"displayModeBar": False},
                             key="fig_preco_rsi")
            st.plotly_chart(gd.fig_gex_profile(gex, f"{ativo}USDT"),
                             use_container_width=True, config={"displayModeBar": False},
                             key="fig_gex")
            st.html(
                '<div class="disclaimer">Convenção assumida: dealers líquidos COMPRADOS em '
                'calls e VENDIDOS em puts (padrão usado por trackers públicos de GEX). O GEX é '
                'calculado a partir das gregas (gamma) e do open interest reportados pela '
                'própria Deribit para cada contrato, combinados com o preço à vista (spot) da '
                'Binance. Ajuste o sinal no código se sua leitura de mercado indicar o '
                'oposto para este ativo.</div>')


if __name__ == "__main__":
    main()
