import hashlib
import hmac
import uuid
from typing import Protocol

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EventoGateway, Pagamento, Pedido, StatusPagamento, StatusPedido
from app.services import auditoria, fidelidade
from app.services.pedidos import transicionar


class GatewayIndisponivel(Exception):
    pass


class GatewayPagamento(Protocol):
    def solicitar_cobranca(self, valor: str, metodo: str, idempotency_key: str) -> str:
        ...

    def solicitar_estorno(self, gateway_ref: str) -> None: ...


class GatewayFake:
    def __init__(self) -> None:
        self.falhar = False
        self.cobrancas: dict[str, str] = {}  # idempotency_key -> gateway_ref
        self.estornos: list[str] = []

    def solicitar_cobranca(self, valor: str, metodo: str, idempotency_key: str) -> str:
        if self.falhar:
            raise GatewayIndisponivel("timeout")
        return self.cobrancas.setdefault(idempotency_key, f"gw_{uuid.uuid4().hex[:16]}")

    def solicitar_estorno(self, gateway_ref: str) -> None:
        if self.falhar:
            raise GatewayIndisponivel("timeout")
        self.estornos.append(gateway_ref)


gateway: GatewayPagamento = GatewayFake()


def assinar(corpo: bytes) -> str:
    return hmac.new(settings.gateway_webhook_secret.encode(), corpo, hashlib.sha256).hexdigest()


def assinatura_valida(corpo: bytes, assinatura: str | None) -> bool:
    return bool(assinatura) and hmac.compare_digest(assinar(corpo), assinatura)


def iniciar_pagamento(db: Session, pedido: Pedido, metodo: str) -> Pagamento:
    if pedido.status == StatusPedido.PAGAMENTO_RECUSADO:
        transicionar(db, pedido, StatusPedido.AGUARDANDO_PAGAMENTO)
    elif pedido.status != StatusPedido.AGUARDANDO_PAGAMENTO:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Pedido em status {pedido.status.value} não aceita pagamento")

    # reaproveita tentativa pendente
    pagamento = db.scalar(
        select(Pagamento).where(Pagamento.pedido_id == pedido.id, Pagamento.status == StatusPagamento.PENDENTE)
    )
    if pagamento is None:
        tentativa = len(pedido.pagamentos) + 1
        pagamento = Pagamento(
            pedido_id=pedido.id,
            valor=pedido.total,
            metodo=metodo,
            status=StatusPagamento.PENDENTE,
            idempotency_key=f"pedido-{pedido.id}-tentativa-{tentativa}",
        )
        db.add(pagamento)
        db.flush()
    if pagamento.gateway_ref:
        db.commit()
        return pagamento

    try:
        pagamento.gateway_ref = gateway.solicitar_cobranca(str(pagamento.valor), metodo, pagamento.idempotency_key)
    except GatewayIndisponivel:
        db.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Gateway de pagamento indisponível. Tente novamente em instantes.",
            headers={"Retry-After": "5"},
        )
    db.commit()
    db.refresh(pagamento)
    return pagamento


def processar_webhook(db: Session, evento_id: str, gateway_ref: str, resultado: str) -> str:
    try:
        db.add(EventoGateway(evento_id=evento_id))
        db.flush()
    except IntegrityError:
        db.rollback()
        return "DUPLICADO"

    pagamento = db.scalar(select(Pagamento).where(Pagamento.gateway_ref == gateway_ref))
    if pagamento is None:
        db.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transação desconhecida")
    if pagamento.status != StatusPagamento.PENDENTE:
        db.commit()
        return "IGNORADO"

    pedido = pagamento.pedido
    if resultado == "APROVADO":
        pagamento.status = StatusPagamento.APROVADO
        transicionar(db, pedido, StatusPedido.PAGO)
        fidelidade.creditar_pontos_do_pedido(db, pedido)
    else:
        pagamento.status = StatusPagamento.RECUSADO
        transicionar(db, pedido, StatusPedido.PAGAMENTO_RECUSADO)
    auditoria.registrar(
        db, f"PAGAMENTO_{resultado}", "Pagamento", pagamento.id, None,
        pedido_id=pedido.id, gateway_ref=gateway_ref, evento_id=evento_id,
    )
    db.commit()
    return "PROCESSADO"


def solicitar_estorno(db: Session, pedido: Pedido) -> None:
    pagamento = next((p for p in pedido.pagamentos if p.status == StatusPagamento.APROVADO), None)
    if pagamento is None:
        return
    pagamento.status = StatusPagamento.ESTORNO_SOLICITADO
    try:
        gateway.solicitar_estorno(pagamento.gateway_ref)
    except GatewayIndisponivel:
        # TODO: job de reconciliação
        auditoria.registrar(db, "ESTORNO_PENDENTE_REENVIO", "Pagamento", pagamento.id, None)
