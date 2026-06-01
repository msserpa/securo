# CLAUDE.md — Securo

Gerenciador de finanças pessoais self-hosted e privacy-first (AGPL-3.0). Multi-usuário, multi-workspace, multi-moeda. Roda inteiramente na infra do usuário (Docker/Podman), sem telemetria. Recursos: transações, contas, orçamentos, metas, conversões de câmbio, ciclos de cartão de crédito, splits/grupos, categorização por regras, sync bancário (Pluggy/Enable Banking/SimpleFIN) e um assistente de IA opcional (agents).

> Idioma: prosa/docs/commits/PR em PT-BR. Código (variáveis, funções, classes) e logs técnicos em inglês.

---

## Stack

- **Backend**: Python 3.11+ (imagem 3.13-slim), FastAPI, SQLAlchemy 2.0 async (asyncpg), Pydantic v2, fastapi-users (UUID + JWT), Alembic, Celery + Redis, PostgreSQL 16 com pgvector.
- **Frontend**: React 19 + TypeScript + Vite, shadcn/ui sobre Radix UI, Tailwind CSS v4, TanStack React Query, React Router v7, React Hook Form + Zod, i18next (EN + PT-BR), nginx em produção.
- **IA (opt-in)**: runtime de agents com providers de LLM (Ollama, OpenAI, Anthropic, openai_compatible), MCP server (JSON-RPC 2.0), RAG via fastembed + pgvector.
- **Infra**: Docker Compose (dev e prod), imagens em `ghcr.io/securo-finance/*`, deploy via `install.sh`.

---

## Arquitetura em camadas

```
Routes (app/api/*)  →  Services (app/services/*)  →  Repositories (queries SQLAlchemy)  →  Models (app/models/*)
```

- **Routes**: dependem de `workspace_context` para auth e resolução de workspace/role; validam entrada com schemas `*Create`/`*Update`; retornam schemas `*Read`. Mutações dependem de `current_writable_workspace`.
- **Services**: funções async puras, sem contexto de request. Recebem `AsyncSession`, `user_id`, `workspace_id` como parâmetros. Concentram as queries SQLAlchemy.
- **Models**: ORM com `mapped_column`, PK UUID, `Decimal` para dinheiro. Toda entidade financeira tem `workspace_id` FK.
- **Schemas**: Pydantic v2; `Create` tem menos campos que `Read`; relacionamentos com `selectinload()`/`joinedload()`.

### Multi-tenancy
Workspace é a fronteira de isolamento. O listener `workspace_autostamp` preenche `workspace_id` automaticamente no insert (resolve do FK pai ou do primeiro workspace do usuário) — services não devem stampar à mão. Roles: `owner`/`editor`/`viewer`, mais `manager` (virtual, admin externo via `managed_by_user_id`, fora da tabela de membros). Permissão de escrita via `ctx.require_write()` (403 ao negar).

---

## Estrutura de diretórios

```
backend/
  app/
    main.py                  # entrypoint FastAPI; monta 30+ routers; lifespan de tasks Celery
    cli.py                   # CLI (ex.: criar usuário) via asyncio.run()  [omitido da coverage]
    worker.py                # config Celery + beat schedule (sync/recurring/assets/FX)  [omitido da coverage]
    core/
      config.py              # Pydantic Settings (DATABASE_URL, SECRET_KEY, flags)
      auth.py                # fastapi-users; UserManager (seed de wallet/categorias), JWT
      database.py            # AsyncEngine, async_session_maker, DeclarativeBase
      workspace_context.py   # DI de workspace + membership + role
      workspace_autostamp.py # listener before_insert que preenche workspace_id
      rate_limit.py          # token bucket no Redis (5/min login, 3/h register/reset)
    models/                  # ORM (User, Account, Transaction, Category, Budget, Goal, Asset, Workspace...)
    schemas/                 # Pydantic request/response
    api/                     # routers (transactions, accounts, categories, budgets, goals, imports, rules, two_factor...)
    services/                # lógica de negócio (transaction_service, rule_engine, fx_rate_service, connection_service...)
    providers/               # camada de dados externos (ver "Provider financeiro")  [externos omitidos da coverage]
    agents/                  # subsistema de IA (opt-in via AGENTS_ENABLED)
      config.py              # AgentSettings (env_prefix AGENTS_*)
      runtime/executor.py    # loop do agente (turnos, dispatch de tools, persistência, usage log)
      providers/             # base.py + registry.py + ollama/openai/anthropic
      mcp/                   # client.py (MCPRegistry) + auth.py (JWT escopado)
      services/              # embedding.py, knowledge_service.py (RAG), connection_service.py, crypto.py
      api/                   # chat.py (SSE), agents.py (CRUD + tools)
      models/                # agent.py, conversation.py (Message multipart)
      tasks/ingest.py        # Celery: parse → chunk → embed docs
  mcp_server/                # MCP server standalone (uvicorn mcp_server.main:app :8765)
    main.py                  # endpoint /mcp JSON-RPC 2.0 com JWT (tools/list, tools/call)
    registry.py              # @tool decorator + ToolSpec (is_proposal)
    tools/                   # tools built-in (read-only e propose_*; NÃO mutam direto)
  alembic/                   # migrations async (env.py importa todos os models p/ autodetect)
  tests/                     # pytest; SQLite in-memory; Vector shimmado p/ JSON
  pyproject.toml             # deps, config pytest/ruff/coverage
  Dockerfile

frontend/
  src/
    main.tsx, App.tsx        # entry + Router (lazy pages, QueryClient, guards)
    contexts/                # auth-context, workspace-context
    lib/                     # api.ts (axios + interceptors), i18n.ts, utils.ts (cn())
    components/ui/           # shadcn (button, card, dialog, form, table...)
    components/              # domínio (app-layout, protected-route, transaction-dialog, agents/*)
    pages/                   # rotas lazy (dashboard, transactions, accounts, budgets, agents, admin...)
    locales/                 # en.json, pt-BR.json
    types/index.ts           # interfaces espelhadas do contrato do backend
    hooks/                   # use-privacy-mode, use-feature-flags...
  Dockerfile / Dockerfile.dev / nginx.conf

docker-compose.yml           # DEV: build from source, hot-reload, mcp-server em profile
docker-compose.prod.yml      # PROD: imagens ghcr.io; volumes pgdata, attachments, agent_knowledge, agent_embedding_models
install.sh                   # instalador (detecta OS/Docker/Podman, gera .env, health check)
.env.example                 # template de configuração
```

> Tudo de agents é gated em import time por `AGENTS_ENABLED` — custo zero quando desligado.

---

## Comandos

### Dev (stack completo)
```bash
docker compose up --build                # backend:8000, frontend:3000, postgres:5432, redis:6379
docker compose logs -f backend           # tail de logs (alembic roda no startup)
docker compose down                      # para a stack
```
Alembic (`alembic upgrade head`) roda automaticamente no startup do backend.

### Agents (opt-in)
```bash
AGENTS_ENABLED=true docker compose --profile agents up -d   # sobe mcp-server :8765
```

### Testes (backend)
```bash
docker compose exec backend pytest
docker compose exec backend pytest --cov=app --cov-report=term-missing   # coverage
docker compose exec backend pytest backend/tests/test_agents_executor.py -v
docker compose exec backend pytest tests/test_providers_pluggy.py -xvs
docker compose exec backend python scripts/seed_perf.py                  # 10k transações
docker compose exec backend python scripts/seed_perf.py --scale 0.1      # smoke test
```
Local sem Docker: `cd backend && pip install -e '.[dev]' && alembic upgrade head && uvicorn app.main:app --reload`. Testes usam SQLite in-memory (`asyncio_mode=auto`, `concurrency=greenlet`).

### Lint (backend)
```bash
ruff check app/ tests/
ruff format app/ tests/
```

### Frontend
```bash
cd frontend
npm install
npm run dev        # Vite :5173, proxy /api → BACKEND_URL (default http://localhost:8000)
npm run build      # gera dist/
npm run preview    # serve dist/ localmente
npm run lint       # ESLint flat config (sem erros TS)
```

### Migrations
```bash
docker compose exec backend alembic revision --autogenerate -m "descrição"
docker compose exec backend alembic upgrade head
```

### Deploy em produção (host remoto via ssh)
Use o `deploy.sh` (na raiz `Seguro/`, fora deste repo) — idempotente, faz clone-ou-pull no host,
envia o `secrets.env` local como `.env` (scp + chmod 600) e sobe a stack prod com health check:
```bash
../deploy.sh                 # deploy padrão (pull do GHCR + up -d + health check em /api/health)
../deploy.sh --build         # builda no host em vez de puxar do GHCR
../deploy.sh --logs          # tail dos logs do backend no host
../deploy.sh --down          # para a stack
```
> Agents: como o `secrets.env` já define `COMPOSE_PROFILES=agents`, o `deploy.sh` padrão **já sobe** o
> `mcp-server`. A flag `--agents` é redundante nesse caso (só necessária se `COMPOSE_PROFILES` não estiver no `.env`).
> O `docker-compose.prod.yml` foi estendido localmente (serviço `mcp-server` + volumes + vars `AGENTS_*`);
> isso é divergência do upstream — isolar em branch própria se for abrir PR.

Deploy manual (sem o script), caso precise:
```bash
git clone https://github.com/securo-finance/securo.git && cd securo
cp .env.example .env && echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env   # ou copie o secrets.env
docker compose -f docker-compose.prod.yml pull && docker compose -f docker-compose.prod.yml up -d
curl http://localhost:8000/api/health     # aguardar 200
```

---

## Env vars críticas (.env.example)

| Var | Obrigatória | Notas |
|---|---|---|
| `SECRET_KEY` | Sim (prod) | >30 chars. Default `dev-secret-change-in-production` é inseguro. Gerar com `openssl rand -hex 32` |
| `DATABASE_URL` | Sim | **driver asyncpg**: `postgresql+asyncpg://...` (nunca psycopg2) |
| `REDIS_URL` | — | default `redis://redis:6379/0` (sem auth); broker + result backend + rate limiter |
| `REGISTRATION_ENABLED` | — | default `true`; controla cadastro de novos usuários |
| `FRONTEND_PORT` / `BACKEND_PORT` | — | default 3000 / 8000; ajustar p/ evitar colisão no host |
| `PLUGGY_CLIENT_ID` / `PLUGGY_CLIENT_SECRET` | — | sync bancos BR (Open Finance) |
| `ENABLE_BANKING_APP_ID` / `ENABLE_BANKING_PRIVATE_KEY_FILE` | — | PSD2 Europa; PEM em `./secrets/enable_banking_private.pem` (gitignored) |
| `SIMPLEFIN_ENABLED` | — | sync US (paste-a-token) |
| `OPENEXCHANGERATES_APP_ID` + `FX_SYNC_MODE` | — | câmbio (`on_demand`/`scheduled`); sem key → fallback 1:1 com warning |
| `STORAGE_LOCAL_PATH` | — | default `/app/data/attachments`; max 10 MB/arquivo, 10/transação |
| `AGENTS_ENABLED` | — | default `false`; liga todo o subsistema de IA |
| `AGENTS_BUILTIN_MCP_URL` | — | precisa ser alcançável do container backend (default `http://mcp-server:8765/mcp`) |
| `AGENTS_MCP_JWT_SECRET` | — | per-instance; múltiplos backends precisam **compartilhar** o mesmo |
| `AGENTS_EMBEDDING_NATIVE_CACHE_DIR` | — | default `/app/data/embedding_models` (volume `agent_embedding_models`); cache do embedder ONNX |
| `AGENTS_EMBEDDING_DIM` | — | default 1536; **travado na migration** |
| `COMPOSE_PROFILES` | — | `agents` para subir o mcp-server |

`.env` e `secrets/` são gitignored — nunca commitar.

---

## Gotchas

- **PostgreSQL precisa ser pgvector** (drop-in do postgres:16), não vanilla — v0.11.0+ exige a extensão para o knowledge base dos agents (inofensiva se `AGENTS_ENABLED=false`). A extensão já vem na imagem; não migrar.
- **Redis é obrigatório** (hardcoded nos dois compose), usado pelo Celery para sync bancário, FX, assets etc.
- **Celery beat + workers** rodam tasks async (sync, recorrências, preços). Beat schedule em **segundos** (não crontab). Tasks são registradas via `conf.include` em `worker.py` (não auto-discovery) e são idempotentes (checam timestamp/estado antes de inserir; `sync_all_connections` pula se sincronizou < 4h).
- **Embedder ONNX (~120 MB MiniLM multilingual)** é baixado on-demand no primeiro embed para `/app/data/embedding_models` — no compose isso é o volume `agent_embedding_models` (precisa estar montado e gravável). O default não é exposto no `.env.example`; sobrescrever via `AGENTS_EMBEDDING_NATIVE_CACHE_DIR` só se mudar o path.
- **`AGENTS_EMBEDDING_DIM` é travado na migration** — mudar exige migrar e re-embeddar todos os docs.
- **Tool whitelisting dos agents** é allow-all enquanto não houver nenhuma `AgentTool` row; ao habilitar/desabilitar a primeira tool, todas passam a desabilitadas por default.
- **Anthropic não suporta embeddings** — agents com Anthropic caem para native/Ollama/OpenAI no embedding.
- **MCP tools são read-only ou `propose_*`** (previews, não mutam). Tools têm timeout de 60s (connect 10s).
- **Celery `ingest_doc`** cria engine fresco por task (NullPool) porque `asyncio.run()` fecha o event loop.
- **workspace_autostamp** roda em contexto sync mesmo dentro de handlers async (greenlet bridge); `Session.get()` dentro do listener deve ser síncrono.
- **Frontend Vite** roda em :5173 interno, exposto em :3000 pelo compose. Precisa ser acessível externamente para os callbacks OAuth de bancos (Pluggy/Enable Banking/SimpleFIN). nginx em prod usa `cache-control no-store` no index.html.
- **Token/workspace no frontend** persistem em `localStorage`; 401 limpa o token e redireciona p/ login (interceptor global em `api.ts`).
- **Coverage** omite `cli.py`, `worker.py`, `tasks/*` e providers externos (Pluggy/Enable Banking/SimpleFIN/market_price) — dependem de HTTP mockado e contratos externos.

---

## Provider financeiro (padrão)

Camada que abstrai bancos, preços de mercado, câmbio e storage. Contratos em `app/providers/base.py`: `BankProvider`, `MarketPriceProvider`, `FxRateProvider`, `StorageProvider`. Providers são auto-registrados no boot **só se as credenciais existirem** (`_auto_register_providers()` em `__init__.py`) — sem credencial, o sync simplesmente pula o provider.

Para adicionar um banco novo:
1. Criar `app/providers/meu_provider.py` herdando `BankProvider` (PascalCase + `Provider`).
2. Implementar os abstract methods: `name`, `get_oauth_url`, `handle_oauth_callback`, `get_accounts`, `get_transactions`, `refresh_credentials` (opcionais: `create_connect_token`, `list_institutions`, `reauth_url`, `trigger_refresh`, `get_holdings`, `get_bills`).
3. **Normalizar** as respostas para as data classes padrão (`AccountData`, `TransactionData`, `HoldingData`, `BillData`); preservar campos específicos do provider no dict `metadata`.
4. Tudo **async** (`httpx.AsyncClient`; para libs sync como yfinance, `asyncio.to_thread()`).
5. Parsing defensivo (capturar `ValueError`/`InvalidOperation` em datas/decimais — não derrubar o sync).
6. Erros: `SessionExpiredError` (auth/consentimento expirado), `ProviderUserActionRequired` (MFA/reauth do usuário), transientes logados e expostos como `failed`.
7. Credenciais **encriptadas** via `app.agents.services.crypto` antes de gravar em `BankConnection.credentials`.
8. Bloco de auto-register em `__init__.py` checando env vars + atualizar `KNOWN_PROVIDERS`.
9. Teste em `tests/test_providers_meu_provider.py` com `httpx` mockado (pytest-asyncio).

---

## Convenções de contribuição

- **Licença AGPL-3.0**: qualquer fork/modificação é copyleft — código modificado precisa ser liberado. Abrir PR implica concordância.
- **Git**: nunca commitar direto na `main`. Branch a partir de `main` no padrão `feature/<slug>` ou `bugfix/<slug>`. Commits convencionais em inglês (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- **PRs focadas**: 1 feature ou 1 fix por PR; descrição What/Why/How; checklist com testes. Usar o `.github/PULL_REQUEST_TEMPLATE.md`.
- **Traduções**: strings user-facing exigem atualizar `en.json` **e** `pt-BR.json` (PT-BR é o fallback).
- **Migrations**: mudanças de schema exigem migration Alembic (`alembic revision --autogenerate`) no PR.
- **TDD**: escrever testes antes da implementação.
  - Backend: conftest provê `async_session` (SQLite in-memory); mockar APIs externas (Pluggy, yfinance, openexchangerates) com monkeypatch/AsyncMock; integração via `TestClient` (httpx `ASGITransport`). Agents: `_ScriptedProvider` + `_FakeMCP` para testes offline.
  - Frontend: sem framework de teste configurado (considerar Vitest + RTL se necessário).
- **CI (`.github/workflows/ci.yml`)** roda em todo PR e **bloqueia merge** se falhar:
  - Backend: `pytest` + coverage (`--cov-fail-under=60`, **mínimo 60%**) + `ruff check`.
  - Frontend: `npm run lint` + `npm run build`.
  - PR que derruba coverage abaixo de 60%, quebra lint/build, ou falta tradução é rejeitada.
- **Release (`.github/workflows/release.yml`)**: build e push de imagens para GHCR (`ghcr.io/securo-finance/*`, semver tags + `latest`) em release.
- **Segurança**: vulnerabilidades **não** vão em issue pública — email `contact@usesecuro.com` (ver `SECURITY.md`). Nunca expor secrets em código/docs; referenciar `.env`.
- **PR checklist resumido**: migration se mexeu em models · testes atualizados · `ruff check app/ tests/` · `npm run lint` + `npm run build` · traduções EN+PT-BR · testar caminhos com feature flag on/off (agents, providers).

---

## Contribuições em andamento (fork/uso próprio + PRs upstream)

> Trabalho do usuário neste fork. Roda local no ai.berg via `deploy.sh` (rsync, independe do GitHub deles). Cada feature em branch própria; oferecida como PR upstream — se rejeitada, a branch já é o fork.

- **#241** — Stepper de mês em `/transactions`: navegação `‹ Mês Ano ›` que reusa o filtro de date-range existente (mesmo `from`/`to`, URL-sync, React Query, resumo). Default = mês atual. Extrai lógica de mês do `dashboard.tsx` → `lib/month-utils.ts`. Branch `feature/transactions-month-stepper`.
- **#242** — Total de "Investimentos" no rodapé de `/transactions` (categoria é `treat_as_transfer`, fica fora de income/expense; vira linha própria).
- **#3 (futuro)** — resumo no topo + meta de investimento mensal (mais invasivo; provável só-fork).

**Regras ao contribuir** (ver memórias `securo-contributions-roadmap`, `securo-upstream-convention-override`):
- NUNCA citar produto concorrente em issue/PR/commit/código.
- Branch `feature/<slug>` de `main`; commits conventional em inglês; PR focado; template What/Why/How to Test/Checklist; traduções EN+PT-BR sempre.
- Abrir issue antes de codar. Labels: só o maintainer (@tassionoronha) aplica.
- Sem framework de teste FE no repo — não introduzir num PR de feature.
