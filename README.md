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
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐ ┌──────────┐  (extensível)
        │ Amadeus  │ │ SerpAPI  │
        │   API    │ │ G.Flights│
        └──────────┘ └──────────┘
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
# Edite .env com suas chaves de API

# 5. Rodar
python app.py
```

Acesse: http://localhost:5000

## Fontes de Dados (APIs)

### Kiwi.com Tequila API (Recomendada)
1. Acesse https://tequila.kiwi.com e crie uma conta gratuita
2. Crie uma **Solution** e copie sua **API Key**
3. Configure `KIWI_API_KEY` nas variáveis de ambiente
4. Gratuita, sem limite rígido de chamadas para uso pessoal

### SerpAPI - Google Flights (Opcional)
1. Crie conta em https://serpapi.com (100 buscas/mês grátis)
2. Copie sua API key
3. Configure `SERPAPI_KEY`

## Deploy no Render (Gratuito)

1. Faça push do código para o GitHub
2. Acesse https://render.com e conecte seu repositório
3. Crie um novo **Web Service** apontando para o repo
4. Configure as variáveis de ambiente (KIWI_API_KEY e/ou SERPAPI_KEY)
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
| `KIWI_API_KEY` | Sim* | API key do Kiwi.com Tequila |
| `SERPAPI_KEY` | Não | API key do SerpAPI |
| `SECRET_KEY` | Não | Chave secreta Flask |
| `SEARCH_HOUR` | Não | Hora da busca diária (padrão: 6) |
| `ENABLE_SCHEDULER` | Não | Ativar agendamento (padrão: true) |
| `DB_PATH` | Não | Caminho do banco SQLite |
| `PORT` | Não | Porta do servidor (padrão: 5000) |

*Pelo menos uma fonte (Kiwi.com ou SerpAPI) deve estar configurada.
