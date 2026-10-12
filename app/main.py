"""Ponto de entrada da API Raízes do Nordeste."""
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.database import Base, engine
from app.routers import auth, fidelidade, pagamentos, pedidos, relatorios, unidades

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("raizes")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Em produção as tabelas seriam versionadas com Alembic (migrations).
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="API Raízes do Nordeste",
    version="1.0.0",
    description="Back-end multicanal (app, totem, balcão, pick-up) da rede Raízes do Nordeste.",
    lifespan=lifespan,
)

for r in (auth.router, unidades.router, pedidos.router, pagamentos.router, fidelidade.router, relatorios.router):
    app.include_router(r)


@app.middleware("http")
async def correlacao_e_tempo(request: Request, call_next):
    """Log estruturado com ID de correlação e latência: base para observabilidade."""
    request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex)
    inicio = time.perf_counter()
    resposta = await call_next(request)
    ms = (time.perf_counter() - inicio) * 1000
    resposta.headers["X-Request-ID"] = request_id
    log.info("request_id=%s %s %s status=%s %.1fms", request_id, request.method, request.url.path, resposta.status_code, ms)
    return resposta


@app.get("/health", tags=["Infra"])
def health():
    """Usado pelo load balancer / orquestrador para checar a instância."""
    return {"status": "ok"}
