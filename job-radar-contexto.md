# Contexto do Projeto — Agente de Busca de Vagas (nome provisório: JobRadar)

> Documento de contexto para brainstorm e desenvolvimento no Claude Code.
> Objetivo geral: projeto open source em Python para portfólio de AI Engineer júnior.

## 1. Objetivo do projeto

Construir um **agente de IA que busca vagas de emprego continuamente**, configurável por usuário, com foco em vagas de tecnologia. O projeto deve:

- Ser **open source**, publicado no GitHub, servindo como peça central de portfólio para vagas de junior AI Engineer.
- Resolver uma dor real (buscar vagas com parâmetros específicos) para que outras pessoas também possam usar/contribuir, não só ser uma demo pessoal.
- Demonstrar competências de **AI Engineering**: agentes com LangGraph, RAG-lite/matching semântico com embeddings, integração com múltiplas APIs de LLM, arquitetura plugável, boas práticas de engenharia de software (testes, CI, contribuição).

## 2. Funcionalidade principal

Fluxo do sistema:

1. **Formulário de configuração (multi-step/wizard)** — usuário define:
   - Cargo(s) desejado(s) e senioridade
   - Modalidade: remoto / híbrido / presencial
   - Região: Brasil, Europa, ou país/cidade específico
   - Faixa salarial mínima
   - Stack/skills obrigatórias ou desejadas
   - Frequência de notificação
2. **Coleta de vagas** — busca periódica em múltiplas fontes via APIs públicas (não scraping):
   - Adzuna API
   - RemoteOK API
   - Arbeitnow API (foco Europa)
   - Jooble API
   - The Muse API
3. **Agente de matching (IA)** — para cada vaga nova:
   - Gera embedding da descrição da vaga
   - Compara com embedding do perfil/preferências do usuário
   - LLM avalia o fit e gera score + justificativa textual (não é só filtro por palavra-chave)
4. **Execução contínua ("24 horas por dia")** — agente roda em background, verificando vagas novas periodicamente e evitando duplicatas.
5. **Dashboard + notificação** — usuário visualiza vagas encontradas e recebe alerta (dashboard + possivelmente Telegram) quando surge um bom match.

## 3. Decisões de stack

- **Backend / agente**: Python (o máximo possível do projeto deve ser Python)
  - **FastAPI** — API REST
  - **LangGraph** — orquestração do agente (planner → researcher/matching → writer/notifier)
  - **SQLModel + PostgreSQL** — persistência (usuários, preferências, vagas, matches)
  - **Celery + Redis** ou **APScheduler** — execução periódica/contínua
  - **Pydantic** — schemas estruturados (UserPreferences, Job, Match)
- **Frontend**:
  - Preferência por manter em Python: **Reflex** (compila para React, mantém stack Python) ou **Streamlit** (mais simples/rápido)
  - Alternativa aceitável: **Next.js/React**, caso opte por mostrar competência fullstack — mas não é prioridade
- **Notificação**: Telegram Bot API (opção rápida de implementar) e/ou WebSocket no dashboard
- **Infra**: Docker Compose para rodar tudo localmente/deploy

## 4. Internacionalização (i18n)

- **Idioma principal do projeto**: inglês (README principal, código, comentários)
- **README traduzido**: também em português (pt-BR) e espanhol
  - `README.md` (inglês)
  - `README.pt-BR.md`
  - `README.es.md`
  - Seletor de idiomas no topo do README principal
- **Site/dashboard**: seletor de idioma (inglês, português, espanhol)
  - Backend: dicionário de strings por idioma (`locales/en.json`, `locales/pt.json`, `locales/es.json`) ou Babel/gettext
  - Frontend: se Reflex/Streamlit, state simples trocando dicionário ativo; se Next.js, `next-intl`

## 5. Estrutura de repositório (proposta)

```
job-radar/
├── README.md
├── README.pt-BR.md
├── README.es.md
├── LICENSE                    # MIT (preferencial para atrair contribuidores)
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── .github/
│   ├── ISSUE_TEMPLATE/
│   ├── workflows/              # CI: testes, lint
│   └── PULL_REQUEST_TEMPLATE.md
├── backend/
│   ├── src/
│   │   ├── agents/              # nodes do LangGraph (planner, matching, writer/notifier)
│   │   ├── sources/             # integrações plugáveis (adzuna.py, remoteok.py, arbeitnow.py...)
│   │   ├── matching/             # embeddings + scoring
│   │   ├── api/                  # rotas FastAPI
│   │   ├── models/               # SQLModel (User, UserPreferences, Job, Match)
│   │   └── locales/              # i18n backend
│   ├── tests/
│   └── pyproject.toml
├── frontend/                    # Reflex ou Next.js
│   └── locales/                 # i18n frontend
├── docker-compose.yml
└── docs/
    └── architecture.md
```

## 6. Princípios de engenharia para credibilidade open source

- **Arquitetura de "sources" plugável**: cada job board implementa uma interface comum (`fetch_jobs()`), facilitando contribuições externas (ex: "add support for X job board").
- **Testes desde o início** (pytest).
- **CI no GitHub Actions**: lint (ruff) + testes a cada PR.
- **CONTRIBUTING.md** claro com setup local.
- **Licença MIT**.

## 7. Roadmap sugerido (fatiado em etapas)

1. **MVP sem IA**: formulário → salva preferências → busca em 1 API → lista simples no dashboard
2. **Agente de matching**: embeddings + LLM explicando o score de fit
3. **Execução contínua**: scheduler rodando em background
4. **Notificações**: Telegram bot (mais rápido) e/ou alerta no dashboard
5. **Multi-fonte + multi-usuário + Docker Compose** para deploy completo
6. **i18n completo** (README + site) e polimento para lançamento público (contribuição externa)

## 8. Pontos ainda em aberto (para o brainstorm)

- Nome final do projeto (opções cogitadas: JobRadar, HireScout, JobPulse, OpenJobHunter) — verificar disponibilidade no GitHub/PyPI
- Escolha definitiva entre Reflex vs. Streamlit vs. Next.js para o frontend
- Escolha entre Celery+Redis vs. APScheduler para o scheduler (trade-off robustez vs. simplicidade)
- Detalhamento dos schemas Pydantic/SQLModel (User, UserPreferences, Job, Match)
- Definição do provider de LLM padrão (OpenAI, Anthropic, ou multi-provider via algo como LiteLLM) para não travar o projeto a um único fornecedor

## 9. Contexto adicional sobre o autor (para adequar tom/decisões)

- Autor está construindo carreira como AI Engineer júnior; o projeto é peça central de portfólio.
- Prioridade: mostrar competências de agentes de IA (LangGraph), RAG/matching semântico, integração com APIs de LLM, e boas práticas de engenharia de software — não apenas um script funcional.
