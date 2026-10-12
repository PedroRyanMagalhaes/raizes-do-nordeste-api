from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Consentimento, ContaFidelidade, Finalidade, Pedido, TransacaoPontos


def tem_consentimento(db: Session, usuario_id: int, finalidade: Finalidade) -> bool:
    """Vale o registro mais recente: o consentimento pode ser revogado a qualquer momento."""
    ultimo = db.scalar(
        select(Consentimento)
        .where(Consentimento.usuario_id == usuario_id, Consentimento.finalidade == finalidade)
        .order_by(Consentimento.registrado_em.desc(), Consentimento.id.desc())
        .limit(1)
    )
    return bool(ultimo and ultimo.concedido)


def obter_conta(db: Session, usuario_id: int) -> ContaFidelidade:
    conta = db.scalar(select(ContaFidelidade).where(ContaFidelidade.usuario_id == usuario_id))
    if conta is None:
        conta = ContaFidelidade(usuario_id=usuario_id, saldo_pontos=0)
        db.add(conta)
        db.flush()
    return conta


def calcular_desconto_por_pontos(pontos: int, subtotal: Decimal) -> tuple[int, Decimal]:
    """Converte pontos em desconto respeitando o teto percentual. Retorna (pontos_usados, desconto)."""
    teto = (subtotal * Decimal(str(settings.desconto_maximo_percentual))).quantize(Decimal("0.01"), ROUND_DOWN)
    desconto = (Decimal(pontos) / settings.pontos_por_real_desconto).quantize(Decimal("0.01"), ROUND_DOWN)
    if desconto > teto:
        desconto = teto
    pontos_usados = int(desconto * settings.pontos_por_real_desconto)
    return pontos_usados, desconto


def creditar_pontos_do_pedido(db: Session, pedido: Pedido) -> None:
    """Acúmulo só ocorre com consentimento ativo para FIDELIDADE (LGPD)."""
    if pedido.cliente_id is None or not tem_consentimento(db, pedido.cliente_id, Finalidade.FIDELIDADE):
        return
    pontos = int(pedido.total) * settings.pontos_por_real
    if pontos <= 0:
        return
    conta = obter_conta(db, pedido.cliente_id)
    conta.saldo_pontos += pontos
    db.add(TransacaoPontos(conta_id=conta.id, pedido_id=pedido.id, pontos=pontos, tipo="ACUMULO"))
