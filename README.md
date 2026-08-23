# Dashboard de Opções Cripto — BTCUSDT / ETHUSDT

Dashboard focado só em **BTC e ETH**, com GEX calculado usando **opções
curtas** (vencimento mais próximo de hoje + 2 dias).

## Arquitetura (plano B — coleta desacoplada do Streamlit)

O Streamlit **não chama mais a Binance/Deribit diretamente**. Em vez
disso:

```
GitHub Actions (a cada 15 min)     data/*.csv, data/*.json      Streamlit app
coletar_dados.py                -> publicados no próprio     -> lê via
-> Binance + Deribit               repositório (git push)       raw.githubusercontent.com
                                                                  (leitura_repo.py)
```

Isso resolve dois problemas que você bateu rodando tudo dentro do
Streamlit:

- **Erro 451 da Binance**: bloqueio geográfico de `api.binance.com` em
  certos IPs/regiões de hospedagem do Streamlit.
- **Erro 400 da Deribit**: bug do parâmetro `expired=False` sendo
  serializado errado (já corrigido também no `coleta_dados.py`).

Como o GitHub Actions roda em servidores próprios do GitHub (normalmente
sem esses bloqueios) e o Streamlit passa a só baixar arquivos estáticos do
`raw.githubusercontent.com`, o dashboard fica muito mais resiliente.

## Arquivos

| Arquivo | Onde roda | Função |
|---|---|---|
| `coleta_dados.py` | GitHub Actions | Funções de baixo nível: fala com Binance e Deribit |
| `coletar_dados.py` | GitHub Actions | Script principal da coleta — escreve em `data/` |
| `.github/workflows/coleta.yml` | GitHub Actions | Agenda a coleta (cron a cada 15 min) e publica (`git push`) |
| `data/precos_{BTC,ETH}.csv` | — | Histórico de candles (Binance) |
| `data/opcoes_{BTC,ETH}.csv` | — | Cadeia de opções curtas, 1-3 vencimentos (Deribit) |
| `data/meta_{BTC,ETH}.json` | — | Timestamp da coleta, spot no momento, vencimentos disponíveis |
| `leitura_repo.py` | Streamlit | Lê `data/*.csv` e `data/*.json` via `raw.githubusercontent.com` |
| `motor_calculo_cripto.py` | Streamlit | Calcula GEX, gamma flip, walls, PCR, IV skew, RSI, volatilidade |
| `dashboard_cripto.py` | Streamlit | Gráficos (Plotly) e cards HTML |
| `streamlit_app_cripto.py` | Streamlit | App principal — rodar/hospedar este |
| `requirements-coleta.txt` | GitHub Actions | Dependências mínimas do job de coleta |
| `requirements.txt` | Streamlit | Dependências do app |

## Como configurar no seu repositório

Seu repositório já é `diogoraucci/dashboar_crypto_opcoes` — os arquivos
já apontam pra ele por padrão (`leitura_repo.GITHUB_RAW_BASE_PADRAO`).
Passos:

1. **Suba estes arquivos** para a raiz do repositório (substituindo os
   antigos `coleta_dados.py`, `streamlit_app_cripto.py`, etc.), mantendo a
   estrutura de pastas — incluindo `.github/workflows/coleta.yml` e a
   pasta `data/` (pode ficar só com o `.gitkeep` por enquanto).

2. **Habilite permissão de escrita pro workflow**: em
   `Settings → Actions → General → Workflow permissions`, marque
   **"Read and write permissions"** e salve. Sem isso o `git push` do
   workflow falha com permissão negada.

3. **Rode a coleta pela primeira vez manualmente**: aba **Actions** do
   repositório → workflow **"Coleta de dados (Binance + Deribit)"** →
   botão **"Run workflow"**. Acompanhe o log — ele deve terminar
   publicando `data/precos_BTC.csv`, `data/opcoes_BTC.csv`,
   `data/meta_BTC.json` (e os equivalentes de ETH) com um commit
   automático.

4. Depois do primeiro sucesso, o cron (`*/15 * * * *`, a cada 15 minutos)
   assume sozinho.

5. **Rode o Streamlit** (local ou no Streamlit Community Cloud):

   ```bash
   pip install -r requirements.txt
   streamlit run streamlit_app_cripto.py
   ```

   Ele vai buscar os dados direto de
   `https://raw.githubusercontent.com/diogoraucci/dashboar_crypto_opcoes/main/data/...`
   — não precisa rodar no mesmo lugar que o GitHub Actions.

## Rodando a coleta localmente (sem esperar o Actions)

```bash
pip install -r requirements-coleta.txt
python coletar_dados.py
```

Isso já popula a pasta `data/` localmente — útil pra testar antes de
mexer no workflow, ou se você preferir rodar a coleta em outro lugar (um
cron no seu próprio servidor, por exemplo) em vez do GitHub Actions.

## Sidebar do Streamlit

- **Ativo**: BTC ou ETH.
- **Vencimento (GEX)**: dropdown com os vencimentos que o Actions coletou
  (por padrão, o mais próximo de "hoje + 2 dias" e até 2 vizinhos
  cronológicos).
- **Repositório de dados** (expansível): URL base caso você tenha feito um
  fork do repositório com outro nome/branch.
- **Atualizar agora**: limpa o cache local (60s) e força reler os arquivos
  do GitHub.
- **Atualizar automaticamente**: precisa de
  `pip install streamlit-autorefresh` (opcional).

## Notas sobre o cálculo do GEX

- Convenção padrão de trackers públicos de GEX: dealers líquidos
  **COMPRADOS em calls** (+gamma) e **VENDIDOS em puts** (-gamma).
- Gamma e demais gregas vêm **direto do modelo de precificação da própria
  Deribit** (campo `greeks` do endpoint `public/ticker`).
- `GEX_strike = Σ (±1 × gamma × open_interest × spot² × 0.01)`.
- **Gamma Flip**: strike onde o GEX acumulado cruza zero (interpolado).
- **Call Wall / Put Wall**: strike com maior GEX positivo / mais negativo.
- **PCR**: open interest de puts ÷ open interest de calls.
- **IV Skew**: IV média das puts OTM menos IV média das calls OTM, dentro
  de ±5% do spot.
- Os dados **não são tick-a-tick em tempo real** — refletem o horário da
  última coleta do GitHub Actions (mostrado no topo do dashboard).

## Notas sobre o painel de Preço, Volatilidade e RSI

Réplica do painel do dashboard original (script OMSF/NoTrend), adaptada
pra cripto — usando **365** como janela rolante em vez dos **252** dias
úteis de bolsa tradicional (cripto negocia todo santo dia, sem fim de
semana):

- **Média móvel com seletor**: a sidebar tem um slider "Período (Média
  Móvel)" (20 a 300, padrão 50) — define a janela da média móvel simples
  usada como linha de base (baseline) das bandas do gráfico de preço.
- **Bandas de desvio-padrão**: baseline ± 1/2/3 desvios-padrão, calculados
  em **janela rolante de 365 períodos** sobre o log-preço normalizado
  (log-preço − baseline), projetadas de volta pra escala de US$.
- **Volatilidade histórica com quartis rolantes**: a linha de volatilidade
  anualizada (rolling 30 dias, anualizada por √365) vem acompanhada de uma
  banda sombreada com os **quantis 0.2 e 0.8**, também calculados em
  **janela rolante de 365 períodos** — mostra se a vol de hoje está
  historicamente alta ou baixa frente ao regime recente (não à série toda).
- **RSI em janela rolante de 365 períodos**: além do RSI(14) padrão de
  mercado, o gráfico traz o **RSI(365)** — o mesmo oscilador, calculado com
  lookback de ~1 ano, pra medir momentum de prazo mais longo.
- Card **"REGIME DE VOL."** no painel esquerdo: classifica a vol. atual
  como ALTA (acima do quantil 0.8 rolante), BAIXA (abaixo do quantil 0.2)
  ou NEUTRA.
- Essas métricas rolantes de 365 períodos só aparecem depois que o
  histórico acumulado em `data/precos_{ativo}.csv` tiver pelo menos ~180
  candles diários (`MIN_PERIODOS_ROLANTE`) — por isso o coletor
  (`coletar_dados.py`) já busca **1000 candles diários** da Binance (o
  máximo por chamada) em vez de 300, pra ter histórico suficiente desde a
  primeira coleta.

## Se algo não funcionar

- **"Arquivo não encontrado" no Streamlit**: o workflow ainda não rodou
  com sucesso. Veja a aba Actions do repositório e rode manualmente
  ("Run workflow").
- **Workflow falha no `git push`**: falta a permissão de escrita — revise
  o passo 2 acima (Settings → Actions → General → Workflow permissions).
- **Erro 451/400 mesmo assim**: só pode acontecer dentro do job do GitHub
  Actions agora (não mais no Streamlit). Olhe o log do job em Actions —
  se for 451 da Binance, o `coleta_dados.py` já tenta vários espelhos
  (`data-api.binance.vision`, `api1-4.binance.com`, `api.binance.com`) em
  sequência antes de desistir.
- **Um dos dois ativos não atualiza**: o script só falha o job inteiro se
  **ambos** (BTC e ETH) derem erro na mesma rodada — um problema pontual
  num só ativo não trava o outro. Veja o log do job pra identificar qual.
