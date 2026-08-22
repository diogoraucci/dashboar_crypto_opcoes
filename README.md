# Dashboard de Opções Cripto — BTCUSDT / ETHUSDT (ao vivo)

Versão do seu dashboard de opções focada **só em BTC e ETH**, com dados
coletados **em tempo real**, sem CSVs nem planilhas:

- **Cotações** (preço à vista, histórico, RSI): direto da **Binance**
  (`api.binance.com`, endpoints públicos, sem chave de API).
- **Cadeia de opções** (IV, gregas, open interest): direto da **Deribit**
  (`www.deribit.com`, endpoints públicos, sem chave de API).
- **GEX**: calculado usando **opções curtas**, com vencimento mais próximo
  de **hoje + 2 dias** (ajustável na sidebar, de 0.5 a 14 dias).

## Arquivos

| Arquivo | Função |
|---|---|
| `coleta_dados.py` | Busca cotações na Binance e cadeia de opções na Deribit |
| `motor_calculo_cripto.py` | Calcula GEX por strike, gamma flip, walls, PCR, IV skew, RSI, volatilidade histórica |
| `dashboard_cripto.py` | Gera os gráficos (Plotly) e os cards/tabelas HTML |
| `streamlit_app_cripto.py` | App principal — rodar este |
| `requirements.txt` | Dependências |

## Como rodar

```bash
pip install -r requirements.txt
streamlit run streamlit_app_cripto.py
```

Abra o link que o Streamlit imprime no terminal (normalmente
`http://localhost:8501`). Na sidebar você escolhe **BTC** ou **ETH**, o
**vencimento-alvo** do GEX (padrão: 2 dias) e o timeframe do gráfico de
preço.

## Atualização automática (opcional)

Por padrão, os dados ficam em cache local por 30 segundos e você atualiza
clicando em **"🔄 Atualizar agora"** na sidebar. Se quiser atualização
automática a cada 30s sem precisar clicar, instale:

```bash
pip install streamlit-autorefresh
```

e marque a caixa "Atualizar automaticamente" que aparece na sidebar.

## Notas sobre o cálculo do GEX

- Convenção padrão de trackers públicos de GEX: dealers líquidos
  **COMPRADOS em calls** (+gamma) e **VENDIDOS em puts** (-gamma).
- Gamma e demais gregas usados vêm **direto do modelo de precificação da
  própria Deribit** (campo `greeks` do endpoint `public/ticker`) — não
  recalculamos Black-Scholes por fora, para não misturar duas fontes de
  volatilidade implícita diferentes.
- `GEX_strike = Σ (±1 × gamma × open_interest × spot² × 0.01)` — ou seja,
  a variação em US$ da exposição a gamma dos dealers para uma variação de
  1% no spot.
- **Gamma Flip**: strike onde o GEX acumulado (somado do menor pro maior
  strike) cruza zero (interpolado linearmente).
- **Call Wall / Put Wall**: strike com o maior GEX positivo (calls) / mais
  negativo (puts).
- **PCR**: razão entre open interest de puts e de calls no vencimento
  escolhido.
- **IV Skew**: IV média das puts OTM menos IV média das calls OTM, dentro
  de uma banda de ±5% do spot.

## Se algo não funcionar

- **Rede bloqueando `api.binance.com` ou `www.deribit.com`**: o app roda
  local no seu computador, então depende da sua conexão ter acesso a esses
  domínios (nem toda VPN/firewall corporativo libera). Teste abrindo essas
  URLs num navegador comum.
- **"Nenhum vencimento futuro encontrado"**: a Deribit às vezes fica sem
  opções BTC/ETH com vencimento tão próximo quanto 2 dias (depende do
  calendário de listagem deles). Aumente o slider "Vencimento-alvo do GEX"
  na sidebar para pegar o próximo vencimento disponível.
- **"Cadeia de opções sem gregas/open interest suficientes"**: pode
  acontecer em vencimentos com pouquíssima liquidez (poucos strikes
  negociados). Tente outro vencimento-alvo.
