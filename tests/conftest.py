import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.seed import SENHA_PADRAO, popular
from app.services import pagamentos


@pytest.fixture()
def ctx():
    """Banco SQLite em memória isolado por teste + dados de demonstração."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Sessao = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _get_db():
        db = Sessao()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    pagamentos.gateway = pagamentos.GatewayFake()
    with Sessao() as db:
        dados = popular(db)
    with TestClient(app) as client:
        yield {"client": client, "dados": dados, "gateway": pagamentos.gateway, "Sessao": Sessao}
    app.dependency_overrides.clear()


def token(client, email, senha=SENHA_PADRAO) -> dict:
    r = client.post("/auth/login", json={"email": email, "senha": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def registrar_cliente(client, email="maria@email.com", aceita_fidelidade=True) -> dict:
    r = client.post("/auth/registrar", json={"nome": "Maria", "email": email, "senha": "Cliente@123",
                                             "aceita_fidelidade": aceita_fidelidade})
    assert r.status_code == 201, r.text
    return token(client, email, "Cliente@123")


def enviar_webhook(client, gateway_ref, resultado="APROVADO", evento_id="evt-1", assinatura=None):
    corpo = json.dumps({"evento_id": evento_id, "gateway_ref": gateway_ref, "resultado": resultado}).encode()
    return client.post("/pagamentos/webhook", content=corpo,
                       headers={"X-Signature": assinatura or pagamentos.assinar(corpo), "Content-Type": "application/json"})
