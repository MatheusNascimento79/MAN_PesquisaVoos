# PesquisaVoos - Monitor de Passagens Aéreas

Sistema automatizado de monitoramento de preços de passagens aéreas para viagens à Europa.

## Cenário Padrão

- **Ida:** São Paulo (GRU/CGH/VCP) → Paris (CDG/ORY)
- **Volta:** Roma (FCO/CIA) → São Paulo (GRU/CGH/VCP)
- **Datas:** ~09/09/2026 a ~23/09/2026 (flexível ±3 dias)
- **Passageiros:** 4 adultos, classe econômica
- **Restrições:** Máx. 1 parada, sem conexão nos EUA

## Arquitetura

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Frontend   │────▶│  Flask API   │────▶│   SQLite DB  │
│  HTML/CSS/JS │◀────│   + Agente   │◀────│  flights.db  │
└──────────────┘     └──────┬───────┘     └──────────────┘
                            │
                     ┌──────┴───────┐
                     │  APScheduler │
                     │  (diário 6h) │
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   SerpAPI    │
                     │ Google Flights│
                     └──────────────┘
```

## Setup Local

```bash
# 1. Clonar e entrar no diretório
git clone <repo-url> && cd MAN_PesquisaVoos

# 2. Criar ambiente virtual
python3 -m venv venv && source venv/bin/activate

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis de ambiente
cp .env.example .env
# Edite .env com sua chave do SerpAPI

# 5. Rodar
python app.py
```

Acesse: http://localhost:5000

## Fontes de Dados

### 1. SerpAPI - Google Flights (recomendada)
1. Acesse https://serpapi.com e crie uma conta
2. Plano gratuito: **100 buscas/mês**
3. Copie sua API Key do dashboard
4. Configure `SERPAPI_KEY`

### 2. Skyscanner via RapidAPI (complementar)
1. Acesse https://rapidapi.com/apiheya/api/sky-scrapper
2. Clique em **"Subscribe to Test"** (plano gratuito: 50 req/mês)
3. Copie sua RapidAPI Key
4. Configure `RAPIDAPI_KEY`

> Configure pelo menos uma. Com as duas, o sistema cruza resultados de fontes diferentes.

## Deploy no Render (Gratuito)

1. Faça push do código para o GitHub
2. Acesse https://render.com e conecte seu repositório
3. Crie um novo **Web Service** apontando para o repo
4. Configure as variáveis `SERPAPI_KEY` e/ou `RAPIDAPI_KEY`
5. O Render detectará o `render.yaml` automaticamente
6. Deploy automático a cada push

## Funcionalidades

- **Busca automática diária** às 06:00 (Brasília)
- **Botão de atualização manual** na interface
- **Filtros:** preço, companhia, aeroporto, paradas, confiabilidade
- **Ordenação:** preço, duração, paradas, confiança
- **Histórico de preços** com gráfico de evolução
- **Badges:** Mais Barata, Melhor Custo-Benefício, Menor Tempo, Mais Confiável
- **Indicador de tendência:** preço caindo/subindo/estável
- **Detalhes expandíveis** por oferta
- **Configuração de viagem** editável pela interface
- **Responsivo** para desktop e mobile

## API Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/offers` | Lista ofertas (aceita filtros via query params) |
| GET | `/api/config` | Retorna configuração ativa |
| POST | `/api/config` | Atualiza configuração |
| POST | `/api/search` | Dispara busca manual |
| GET | `/api/history` | Histórico de preços |
| GET | `/api/status` | Status do sistema |
| GET | `/api/logs` | Logs de execução |

## Variáveis de Ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `SERPAPI_KEY` | Sim* | API key do SerpAPI (Google Flights) |
| `RAPIDAPI_KEY` | Não | API key do RapidAPI (Skyscanner) |
| `SECRET_KEY` | Não | Chave secreta Flask |
| `SEARCH_HOUR` | Não | Hora da busca diária (padrão: 6) |
| `ENABLE_SCHEDULER` | Não | Ativar agendamento (padrão: true) |
| `DB_PATH` | Não | Caminho do banco SQLite |
| `PORT` | Não | Porta do servidor (padrão: 5000) |
