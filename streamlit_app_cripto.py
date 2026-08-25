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

import leitura_repo as lr
import motor_calculo_cripto as m
import dashboard_cripto as gd

try:
    from streamlit_autorefresh import st_autorefresh
    _AUTOREFRESH_OK = True
except ImportError:
    _AUTOREFRESH_OK = False

CORES = gd.CORES
st.set_page_config(page_title="Dashboard Cripto — Opções BTC/ETH", page_icon="₿", layout="wide")

ATIVOS = ["BTC", "ETH"]
TTL_LEITURA = 60  # segundos de cache local da leitura do GitHub


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
# WRAPPERS CACHEADOS — leem os arquivos já coletados e publicados no
# GitHub (data/*.csv, data/*.json), nunca chamam Binance/Deribit direto.
# ----------------------------------------------------------------------------

@st.cache_data(ttl=TTL_LEITURA, show_spinner="Lendo cotações publicadas no repositório...")
def _precos_repo(base: str, ativo: str) -> pd.DataFrame:
    return lr.ler_precos(base, ativo)


@st.cache_data(ttl=TTL_LEITURA, show_spinner="Lendo cadeia de opções publicada no repositório...")
def _opcoes_repo(base: str, ativo: str) -> pd.DataFrame:
    return lr.ler_opcoes(base, ativo)


@st.cache_data(ttl=TTL_LEITURA, show_spinner=False)
def _meta_repo(base: str, ativo: str) -> dict:
    return lr.ler_meta(base, ativo)


# ----------------------------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------------------------

def _sidebar():
    st.sidebar.markdown("### ⚙️ Configuração")
    ativo = st.sidebar.radio("Ativo", ATIVOS, horizontal=True)

    period = st.sidebar.slider(
        "Período (Média Móvel)", min_value=20, max_value=300, value=50, step=5,
        help="Janela da média móvel usada como baseline das bandas de "
             "desvio-padrão no gráfico de preço.")

    with st.sidebar.expander("Repositório de dados", expanded=False):
        base = st.text_input(
            "URL base (raw.githubusercontent.com/.../data)",
            value=lr.GITHUB_RAW_BASE_PADRAO,
            help="Aponta pra pasta data/ do repositório público onde o "
                 "GitHub Actions publica os dados coletados. Só mude se "
                 "você tiver feito um fork do repositório.")

    auto = False
    if _AUTOREFRESH_OK:
        auto = st.sidebar.checkbox("Atualizar automaticamente (60s)", value=False)
        if auto:
            st_autorefresh(interval=60_000, key="auto_refresh_tick")
    else:
        st.sidebar.caption(
            "💡 Instale `streamlit-autorefresh` (pip install streamlit-autorefresh) "
            "para atualização automática em tempo real.")

    if st.sidebar.button("🔄 Atualizar agora", width="stretch"):
        st.cache_data.clear()

    st.sidebar.caption(
        "Dados publicados via GitHub Actions (coletar_dados.py) a partir da "
        f"Binance e Deribit. Cache local de leitura: {TTL_LEITURA}s.")
    return ativo, base, period


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


def _metricas_precos(precos_ind: pd.DataFrame):
    """Cards de RSI curto/longo e volatilidade histórica + posição frente às
    bandas de quartil rolantes (365 períodos)."""
    ultima = precos_ind.iloc[-1]

    def _pos_quartil(valor, q20, q80):
        if pd.isna(valor) or pd.isna(q20) or pd.isna(q80):
            return "—", CORES["fraco"]
        if valor >= q80:
            return "ALTA (>p80)", CORES["baixa"]
        if valor <= q20:
            return "BAIXA (<p20)", CORES["alta"]
        return "NEUTRA", CORES["fraco"]

    regime_vol, cor_vol = _pos_quartil(ultima["hv_anualizada"], ultima["hv_q20_365"], ultima["hv_q80_365"])

    st.html('<div class="subtitulo">Preço &bull; RSI &bull; Volatilidade</div>')
    linha = "".join([
        gd._card_box("RSI (14)", f"{ultima['rsi']:.1f}"),
        gd._card_box("RSI (365, rolante)", f"{ultima['rsi_365']:.1f}"),
        gd._card_box("VOL. ANUALIZADA", f"{ultima['hv_anualizada']:.1f}%" if pd.notna(ultima["hv_anualizada"]) else "—"),
        gd._card_box("REGIME DE VOL.", regime_vol, cor_vol),
    ])
    st.html(f'<div class="boxes-row">{linha}</div>')


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
    ativo, base, period = _sidebar()

    try:
        meta = _meta_repo(base, ativo)
        precos = _precos_repo(base, ativo)
        cadeia_completa = _opcoes_repo(base, ativo)
        precos_ind = m.calcular_indicadores_precos(precos)
        bandas = m.calcular_bandas_desvio_padrao(precos_ind, period)
    except Exception as e:
        st.error(
            f"Falha ao ler os dados publicados no repositório para {ativo}: {e}\n\n"
            "Confirme na aba **Actions** do repositório que o workflow de coleta "
            "já rodou com sucesso pelo menos uma vez (ele publica os arquivos em "
            "`data/`). Se você acabou de configurar o repositório, rode o "
            "workflow manualmente (\"Run workflow\") e aguarde ele terminar.")
        return

    if precos_ind["hv_q20_365"].isna().all():
        st.warning(
            "Histórico de preços curto demais pra calcular as bandas de quartil "
            "(janela rolante de 365 períodos) — elas vão aparecer conforme o "
            "GitHub Actions acumular mais candles diários publicados em `data/`.",
            icon="⚠️")

    spot = float(meta.get("spot", precos["fechamento"].iloc[-1]))

    vencimentos_disponiveis = sorted(cadeia_completa["vencimento"].drop_duplicates())
    if not vencimentos_disponiveis:
        st.error(f"Nenhum vencimento de opções encontrado nos dados publicados para {ativo}.")
        return

    with st.sidebar:
        vencimento_alvo = st.selectbox(
            "Vencimento (GEX)", vencimentos_disponiveis,
            format_func=lambda v: v.strftime("%d/%m/%Y %H:%M UTC"),
            help="Vencimentos que o GitHub Actions coletou — por padrão, o mais "
                 "próximo de 'hoje + 2 dias' (opções curtas) e seus vizinhos.")

    cadeia = cadeia_completa[cadeia_completa["vencimento"] == vencimento_alvo].copy()

    try:
        gex = m.calcular_gex(cadeia, spot)
        opcao = m.metricas_contrato_atm(cadeia, spot, tipo="CALL")
    except Exception as e:
        st.error(f"Falha ao calcular GEX/métricas do contrato: {e}")
        return

    atualizado_em = meta.get("atualizado_em", "?")
    st.caption(
        f"**{ativo}USDT** · Spot US$ {spot:,.2f} (Binance, no momento da coleta) · "
        f"dados coletados em {atualizado_em} · "
        f"opções: {len(cadeia)} contratos no vencimento "
        f"{vencimento_alvo:%d/%m %H:%M UTC} (Deribit) · lido às "
        f"{datetime.now().strftime('%H:%M:%S')}")

    col_esq, col_dir = st.columns([2, 3], gap="large")

    with col_esq:
        with st.container(border=True):
            _metricas_contrato(opcao, spot)
            _metricas_precos(precos_ind)
            st.divider()
            _metricas_gex(gex, ativo, vencimento_alvo)

    with col_dir:
        with st.container(border=True):
            st.plotly_chart(gd.fig_preco_vol_rsi(precos_ind, bandas, f"{ativo}USDT", period),
                             use_container_width=True, config={"displayModeBar": False},
                             key="fig_preco_vol_rsi")
            st.html(
                '<div class="disclaimer">Painel de preço: baseline (linha azul tracejada) = '
                f'média móvel simples de {period} períodos sobre o log-preço normalizado '
                '(seletor "Período (Média Móvel)" na sidebar); bandas verde/amarela/vermelha = '
                'baseline &plusmn; 1/2/3 desvios-padrão em JANELA ROLANTE de 365 períodos de '
                '(log-preço &minus; baseline), convertidas de volta pra escala de preço (US$). '
                'Painel de volatilidade: linha = volatilidade histórica anualizada (rolling 30 '
                'dias, anualizada por &radic;365); banda sombreada = quantis 0.2 e 0.8 da própria '
                'volatilidade, calculados em JANELA ROLANTE de 365 períodos — mostra se a vol de '
                'hoje está alta/baixa frente ao regime recente. Painel de RSI: RSI(14) padrão de '
                'mercado + RSI(365) calculado com janela rolante longa, pra momentum de prazo '
                'mais largo.</div>')
            st.plotly_chart(gd.fig_gex_profile(gex, f"{ativo}USDT"),
                             use_container_width=True, config={"displayModeBar": False},
                             key="fig_gex")
            st.html(
                '<div class="disclaimer">Convenção assumida: dealers líquidos COMPRADOS em '
                'calls e VENDIDOS em puts (padrão usado por trackers públicos de GEX). O GEX é '
                'calculado a partir das gregas (gamma) e do open interest.</div>')


if __name__ == "__main__":
    main()
