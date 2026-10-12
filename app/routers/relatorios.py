from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ItemPedido, LogAuditoria, Pedido, Perfil, Produto, StatusPedido, Unidade
from app.schemas import LinhaProduto, LinhaVendas, LogAuditoriaOut
from app.security import exigir_perfil

router = APIRouter(tags=["Relatórios da Matriz"], dependencies=[Depends(exigir_perfil(Perfil.ADMIN))])

# Pedido conta como venda a partir do pagamento confirmado.
STATUS_VENDA = (StatusPedido.PAGO, StatusPedido.EM_PREPARO, StatusPedido.PRONTO, StatusPedido.ENTREGUE)


def _periodo(inicio: date, fim: date):
    """Intervalo semiaberto [inicio, fim+1): usa o índice em criado_em (sargable)."""
    return (
        Pedido.criado_em >= datetime.combine(inicio, time.min, timezone.utc),
        Pedido.criado_em < datetime.combine(fim + timedelta(days=1), time.min, timezone.utc),
    )


@router.get("/relatorios/vendas", response_model=list[LinhaVendas])
def vendas(
    inicio: date,
    fim: date,
    agrupar_por: str = Query(default="unidade", pattern="^(unidade|regiao)$"),
    db: Session = Depends(get_db),
):
    chave = Unidade.nome if agrupar_por == "unidade" else Unidade.regiao
    linhas = db.execute(
        select(chave, func.count(Pedido.id), func.coalesce(func.sum(Pedido.total), 0))
        .join(Unidade, Unidade.id == Pedido.unidade_id)
        .where(Pedido.status.in_(STATUS_VENDA), *_periodo(inicio, fim))
        .group_by(chave)
        .order_by(func.sum(Pedido.total).desc())
    ).all()
    return [LinhaVendas(chave=c, quantidade_pedidos=q, faturamento=f) for c, q, f in linhas]


@router.get("/relatorios/produtos-mais-vendidos", response_model=list[LinhaProduto])
def produtos_mais_vendidos(
    inicio: date, fim: date, unidade_id: int | None = None,
    limite: int = Query(default=10, ge=1, le=50), db: Session = Depends(get_db),
):
    consulta = (
        select(Produto.id, Produto.nome, func.sum(ItemPedido.quantidade).label("qtd"))
        .join(ItemPedido, ItemPedido.produto_id == Produto.id)
        .join(Pedido, Pedido.id == ItemPedido.pedido_id)
        .where(Pedido.status.in_(STATUS_VENDA), *_periodo(inicio, fim))
        .group_by(Produto.id, Produto.nome)
        .order_by(func.sum(ItemPedido.quantidade).desc())
        .limit(limite)
    )
    if unidade_id:
        consulta = consulta.where(Pedido.unidade_id == unidade_id)
    return [LinhaProduto(produto_id=i, nome=n, quantidade_vendida=q) for i, n, q in db.execute(consulta).all()]


@router.get("/auditoria", response_model=list[LogAuditoriaOut])
def auditoria(
    acao: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    consulta = select(LogAuditoria).order_by(LogAuditoria.criado_em.desc(), LogAuditoria.id.desc())
    if acao:
        consulta = consulta.where(LogAuditoria.acao == acao)
    return db.scalars(consulta.limit(limit).offset(offset)).all()
