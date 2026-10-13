import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario
from app.schemas import PagamentoIn, PagamentoOut, WebhookIn
from app.security import usuario_atual
from app.services import pagamentos as servico
from app.services.pedidos import obter_pedido

router = APIRouter(prefix="/pagamentos", tags=["Pagamentos"])


@router.post("/pedidos/{pedido_id}", response_model=PagamentoOut, status_code=status.HTTP_202_ACCEPTED)
def solicitar_pagamento(
    pedido_id: int, dados: PagamentoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)
):
    pedido = obter_pedido(db, pedido_id, usuario)
    return servico.iniciar_pagamento(db, pedido, dados.metodo)


@router.post("/webhook")
async def webhook_gateway(
    request: Request,
    x_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    corpo = await request.body()
    if not servico.assinatura_valida(corpo, x_signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Assinatura inválida")
    try:
        evento = WebhookIn.model_validate(json.loads(corpo))
    except (ValueError, ValidationError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Payload inválido")
    resultado = servico.processar_webhook(db, evento.evento_id, evento.gateway_ref, evento.resultado)
    return {"status": resultado}
