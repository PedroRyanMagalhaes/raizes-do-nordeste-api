from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Pedido, Perfil, StatusPedido, Usuario
from app.schemas import CancelamentoIn, DescontoIn, PaginaPedidos, PedidoIn, PedidoOut, StatusPedidoIn
from app.security import exigir_perfil, garantir_acesso_unidade, usuario_atual
from app.services import pedidos as servico

router = APIRouter(prefix="/pedidos", tags=["Pedidos"])

FUNCIONARIOS = (Perfil.ATENDENTE, Perfil.COZINHA, Perfil.GERENTE, Perfil.ADMIN)
# Status que a operação da loja pode definir manualmente (PAGO vem só do webhook).
STATUS_OPERACIONAIS = {StatusPedido.EM_PREPARO, StatusPedido.PRONTO, StatusPedido.ENTREGUE}


@router.post("", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def criar_pedido(
    dados: PedidoIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=80),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_atual),
):
    pedido, criado = servico.criar_pedido(db, dados, usuario, idempotency_key)
    if not criado:
        response.status_code = status.HTTP_200_OK
    return pedido


@router.get("", response_model=PaginaPedidos)
def listar_pedidos(
    unidade_id: int,
    status_pedido: StatusPedido | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_perfil(*FUNCIONARIOS)),
):
    """Fila da loja (paginada). Índices em unidade_id/status/criado_em sustentam a consulta."""
    garantir_acesso_unidade(usuario, unidade_id)
    filtro = [Pedido.unidade_id == unidade_id]
    if status_pedido:
        filtro.append(Pedido.status == status_pedido)
    total = db.scalar(select(func.count()).select_from(Pedido).where(*filtro))
    itens = db.scalars(
        select(Pedido).options(selectinload(Pedido.itens)).where(*filtro)
        .order_by(Pedido.criado_em).limit(limit).offset(offset)
    ).all()
    return PaginaPedidos(total=total, limit=limit, offset=offset, itens=itens)


@router.get("/{pedido_id}", response_model=PedidoOut)
def obter_pedido(pedido_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    """Acompanhamento de status (cliente vê só os próprios pedidos)."""
    return servico.obter_pedido(db, pedido_id, usuario)


@router.patch("/{pedido_id}/status", response_model=PedidoOut)
def atualizar_status(
    pedido_id: int,
    dados: StatusPedidoIn,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_perfil(*FUNCIONARIOS)),
):
    pedido = servico.obter_pedido(db, pedido_id, usuario)
    if dados.status not in STATUS_OPERACIONAIS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Use os endpoints de pagamento/cancelamento para este status")
    servico.transicionar(db, pedido, dados.status)
    db.commit()
    db.refresh(pedido)
    return pedido


@router.post("/{pedido_id}/cancelar", response_model=PedidoOut)
def cancelar(pedido_id: int, dados: CancelamentoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(usuario_atual)):
    pedido = servico.obter_pedido(db, pedido_id, usuario)
    return servico.cancelar(db, pedido, usuario, dados.motivo)


@router.post("/{pedido_id}/desconto", response_model=PedidoOut)
def desconto(
    pedido_id: int,
    dados: DescontoIn,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_perfil(Perfil.GERENTE, Perfil.ADMIN)),
):
    pedido = servico.obter_pedido(db, pedido_id, usuario)
    garantir_acesso_unidade(usuario, pedido.unidade_id)
    return servico.aplicar_desconto(db, pedido, usuario, dados.valor, dados.motivo)
