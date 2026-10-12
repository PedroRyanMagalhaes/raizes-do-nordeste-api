# API Raízes do Nordeste — Trilha Back-end

Back-end da rede de lanchonetes **Raízes do Nordeste** (Projeto Multidisciplinar – ADS).
Atende os canais **App, Totem, Balcão e Pick-up** com cardápio por unidade, controle de estoque,
pagamento via gateway externo (webhook assinado + idempotência), programa de fidelidade com
consentimento LGPD, auditoria de operações sensíveis e relatórios para a matriz.

## Stack
| Camada | Tecnologia | Motivo |
|---|---|---|
| API | Python 3.13 + FastAPI | Validação automática (Pydantic), OpenAPI/Swagger gerado, alta performance (ASGI) |
| ORM | SQLAlchemy 2.0 | Independência de banco: SQLite em dev/teste, PostgreSQL em produção |
| Auth | JWT (PyJWT) + PBKDF2-SHA256 | Stateless (escala horizontal), hash de senha recomendado pela OWASP |
| Testes | pytest + TestClient | 30 testes de integração (positivos e negativos) |

## Como executar
```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed              # cria o banco com dados de demonstração
uvicorn app.main:app --reload   # http://localhost:8000/docs
```
Usuários de demonstração (senha `Senha@123`): `admin@raizes.com`, `gerente.recife@raizes.com`,
`atendente.recife@raizes.com`, `cozinha.recife@raizes.com`, `totem01.recife@raizes.com`, `gerente.sp@raizes.com`.

## Testes
```bash
pytest -v
```
Evidências em `docs/evidencias/` (saída do pytest, relatório JUnit, fluxo HTTP real e print do Swagger).

Jornada completa contra o servidor rodando: `python scripts/demo_fluxo.py http://localhost:8000`

## Estrutura
```
app/
  main.py            # app FastAPI, middleware de log/correlação, /health
  config.py          # configurações via variáveis de ambiente
  models.py          # entidades (ORM)
  schemas.py         # DTOs de entrada/saída (Pydantic)
  security.py        # JWT, hash de senha, RBAC
  routers/           # camada HTTP (auth, unidades, pedidos, pagamentos, fidelidade, relatórios)
  services/          # regras de negócio (pedidos, pagamentos, fidelidade, auditoria)
tests/               # testes de integração CT-01..CT-30
scripts/demo_fluxo.py
docs/                # diagramas e evidências
```

## Variáveis de ambiente
| Nome | Padrão (somente dev) |
|---|---|
| `DATABASE_URL` | `sqlite:///./raizes.db` (prod: `postgresql+psycopg://...`) |
| `JWT_SECRET` | `dev-only-secret-change-me` |
| `GATEWAY_WEBHOOK_SECRET` | `dev-webhook-secret` |
