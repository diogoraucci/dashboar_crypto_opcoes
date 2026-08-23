"""
leitura_repo.py — Lê os dados JÁ COLETADOS (cotações + cadeia de opções)
diretamente de um repositório público no GitHub, em vez de chamar
Binance/Deribit a partir do próprio Streamlit.

Por quê: hospedar o Streamlit em nuvem costuma cair em IPs bloqueados pela
Binance (erro 451, geobloqueio) ou esbarrar em instabilidades pontuais da
API pública da Deribit. Rodando a coleta à parte, via GitHub Actions
(coletar_dados.py, agendado em .github/workflows/coleta.yml) e publicando
os arquivos em data/ no repositório, o Streamlit passa a só buscar
arquivos estáticos via HTTPS do raw.githubusercontent.com — que não tem
esse tipo de bloqueio.
"""
from __future__ import annotations

import io
import json
import time

import pandas as pd
import requests

# Repositório público padrão. Se você fizer um fork ou mudar o nome do
# repo/branch, ajuste aqui (ou passe outra base pelo campo da sidebar).
GITHUB_RAW_BASE_PADRAO = "https://raw.githubusercontent.com/diogoraucci/dashboar_crypto_opcoes/main/data"

_session = requests.Session()
_session.headers.update({"User-Agent": "dashboard-opcoes-cripto/1.0"})


def _url(base: str, nome_arquivo: str) -> str:
    # Cache-busting: raw.githubusercontent.com fica atrás de uma CDN
    # (Fastly) com cache de alguns minutos. O parâmetro "?t=" muda a URL a
    # cada leitura, evitando servir uma versão desatualizada por muito tempo.
    return f"{base.rstrip('/')}/{nome_arquivo}?t={int(time.time())}"


def _get_texto(url: str) -> str:
    resp = _session.get(url, timeout=15)
    if resp.status_code == 404:
        raise FileNotFoundError(
            f"Arquivo não encontrado em {url.split('?')[0]}. Verifique se o "
            "workflow de coleta (.github/workflows/coleta.yml) já rodou pelo "
            "menos uma vez com sucesso e publicou os dados em data/ no repositório "
            "(aba 'Actions' do GitHub)."
        )
    resp.raise_for_status()
    return resp.text


def ler_precos(base: str, ativo: str) -> pd.DataFrame:
    """Histórico de candles publicado em data/precos_{ativo}.csv."""
    texto = _get_texto(_url(base, f"precos_{ativo}.csv"))
    df = pd.read_csv(io.StringIO(texto))
    df["data"] = pd.to_datetime(df["data"], utc=True)
    return df.sort_values("data").reset_index(drop=True)


def ler_opcoes(base: str, ativo: str) -> pd.DataFrame:
    """Cadeia de opções (1 ou mais vencimentos) publicada em
    data/opcoes_{ativo}.csv."""
    texto = _get_texto(_url(base, f"opcoes_{ativo}.csv"))
    df = pd.read_csv(io.StringIO(texto))
    df["vencimento"] = pd.to_datetime(df["vencimento"], utc=True)
    return df


def ler_meta(base: str, ativo: str) -> dict:
    """Metadados da última coleta (timestamp, spot no momento da coleta,
    vencimentos disponíveis etc.) publicados em data/meta_{ativo}.json."""
    texto = _get_texto(_url(base, f"meta_{ativo}.json"))
    return json.loads(texto)
