"""Regras de negócio de cardápio, estoque e pedidos (camada de serviço).

Os routers só tratam HTTP; toda regra fica aqui, o que facilita testar e
reaproveitar a lógica em outros canais (ex.: fila, job).
"""
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Canal,
    Estoque,
    ItemCardapio,
    ItemPedido,
    Pedido,
    Perfil,
    Produto,
    StatusPedido,
    TipoCozinha,
    TransacaoPontos,
    Unidade,
    Usuario,
)
from app.schemas import ItemCardapioOut, PedidoIn
from app.security import garantir_acesso_unidade
from app.services import auditoria, fidelidade

# Máquina de estados do pedido: só as transições abaixo são válidas.
TRANSICOES: dict[StatusPedido, set[StatusPedido]] = {
    StatusPedido.AGUARDANDO_PAGAMENTO: {StatusPedido.PAGO, StatusPedido.PAGAMENTO_RECUSADO, StatusPedido.CANCELADO},
    StatusPedido.PAGAMENTO_RECUSADO: {StatusPedido.AGUARDANDO_PAGAMENTO, StatusPedido.CANCELADO},
    StatusPedido.PAGO: {StatusPedido.EM_PREPARO, StatusPedido.CANCELADO},
    StatusPedido.EM_PREPARO: {StatusPedido.PRONTO},
    StatusPedido.PRONTO: {StatusPedido.ENTREGUE},
    StatusPedido.ENTREGUE: set(),
    StatusPedido.CANCELADO: set(),
}

# Quais perfis podem abrir pedido em cada canal.
PERFIS_POR_CANAL: dict[Canal, set[Perfil]] = {
    Canal.APP: {Perfil.CLIENTE},
    Canal.PICKUP: {Perfil.CLIENTE},
    Canal.TOTEM: {Perfil.TOTEM},
    Canal.BALCAO: {Perfil.ATENDENTE, Perfil.GERENTE},
}


def _produto_disponivel(produto: Produto, unidade: Unidade, hoje: date) -> bool:
    if produto.requer_cozinha_completa and unidade.tipo_cozinha == TipoCozinha.REDUZIDA:
        return False
    if produto.disponivel_de and produto.disponivel_ate:
        return produto.disponivel_de <= hoje <= produto.disponivel_ate
    return True


def obter_unidade_ativa(db: Session, unidade_id: int) -> Unidade:
    unidade = db.get(Unidade, unidade_id)
    if unidade is None or not unidade.ativa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unidade não encontrada")
    return unidade


def listar_cardapio(db: Session, unidade_id: int, hoje: date | None = None) -> list[ItemCardapioOut]:
    hoje = hoje or date.today()
    unidade = obter_unidade_ativa(db, unidade_id)
    linhas = db.execute(
        select(ItemCardapio, Produto, Estoque.quantidade)
        .join(Produto, Produto.id == ItemCardapio.produto_id)
        .outerjoin(
            Estoque,
            (Estoque.unidade_id == ItemCardapio.unidade_id) & (Estoque.produto_id == ItemCardapio.produto_id),
        )
        .where(ItemCardapio.unidade_id == unidade_id, ItemCardapio.ativo.is_(True))
        .order_by(Produto.categoria, Produto.nome)
    ).all()
    return [
        ItemCardapioOut(
            produto_id=produto.id,
            nome=produto.nome,
            categoria=produto.categoria,
            preco=item.preco,
            variacao_regional=item.variacao_regional,
            sazonal=produto.disponivel_de is not None,
            estoque_disponivel=qtd or 0,
        )
        for item, produto, qtd in linhas
        if _produto_disponivel(produto, unidade, hoje) and (qtd or 0) > 0
    ]


def _baixar_estoque(db: Session, unidade_id: int, produto_id: int, quantidade: int) -> bool:
    """UPDATE condicional e atômico: evita vender o mesmo item duas vezes em
    acessos concorrentes (horário de pico) sem precisar de lock explícito."""
    resultado = db.execute(
        update(Estoque)
        .where(
            Estoque.unidade_id == unidade_id,
            Estoque.produto_id == produto_id,
            Estoque.quantidade >= quantidade,
        )
        .values(quantidade=Estoque.quantidade - quantidade)
    )
    return resultado.rowcount == 1


def _devolver_estoque(db: Session, pedido: Pedido) -> None:
    for item in pedido.itens:
        db.execute(
            update(Estoque)
            .where(Estoque.unidade_id == pedido.unidade_id, Estoque.produto_id == item.produto_id)
            .values(quantidade=Estoque.quantidade + item.quantidade)
        )


def criar_pedido(db: Session, dados: PedidoIn, usuario: Usuario, idempotency_key: str | None) -> tuple[Pedido, bool]:
    """Retorna (pedido, criado_agora). Se a chave de idempotência já existe, devolve o pedido original."""
    if idempotency_key:
        existente = db.scalar(select(Pedido).where(Pedido.idempotency_key == idempotency_key))
        if existente:
            return existente, False

    if usuario.perfil not in PERFIS_POR_CANAL[dados.canal]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Perfil {usuario.perfil.value} não pode usar o canal {dados.canal.value}")
    if usuario.perfil != Perfil.CLIENTE and usuario.unidade_id != dados.unidade_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Funcionário/totem só registra pedidos da própria unidade")

    unidade = obter_unidade_ativa(db, dados.unidade_id)
    hoje = date.today()

    # Agrupa itens repetidos (ex.: 2 linhas do mesmo produto) antes de validar.
    quantidades: dict[int, int] = {}
    for item in dados.itens:
        quantidades[item.produto_id] = quantidades.get(item.produto_id, 0) + item.quantidade

    cardapio = {
        ic.produto_id: ic
        for ic in db.scalars(
            select(ItemCardapio).where(
                ItemCardapio.unidade_id == unidade.id,
                ItemCardapio.produto_id.in_(quantidades),
                ItemCardapio.ativo.is_(True),
            )
        )
    }

    pedido = Pedido(
        unidade_id=unidade.id,
        cliente_id=usuario.id if usuario.perfil == Perfil.CLIENTE else None,
        criado_por_id=usuario.id,
        canal=dados.canal,
        status=StatusPedido.AGUARDANDO_PAGAMENTO,
        subtotal=Decimal("0"),
        desconto=Decimal("0"),
        total=Decimal("0"),
        pontos_utilizados=0,
        idempotency_key=idempotency_key,
    )
    subtotal = Decimal("0")
    for produto_id, qtd in quantidades.items():
        item_cardapio = cardapio.get(produto_id)
        if item_cardapio is None or not _produto_disponivel(item_cardapio.produto, unidade, hoje):
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Produto {produto_id} indisponível nesta unidade")
        if not _baixar_estoque(db, unidade.id, produto_id, qtd):
            db.rollback()  # desfaz baixas já feitas para os itens anteriores
            raise HTTPException(status.HTTP_409_CONFLICT, f"Estoque insuficiente para o produto {produto_id}")
        pedido.itens.append(ItemPedido(produto_id=produto_id, quantidade=qtd, preco_unitario=item_cardapio.preco))
        subtotal += item_cardapio.preco * qtd

    pedido.subtotal = subtotal
    if dados.usar_pontos:
        if pedido.cliente_id is None:
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Resgate de pontos exige cliente identificado")
        conta = fidelidade.obter_conta(db, usuario.id)
        if dados.usar_pontos > conta.saldo_pontos:
            db.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Saldo de pontos insuficiente")
        pontos_usados, desconto = fidelidade.calcular_desconto_por_pontos(dados.usar_pontos, subtotal)
        conta.saldo_pontos -= pontos_usados
        pedido.desconto = desconto
        pedido.pontos_utilizados = pontos_usados
    pedido.total = subtotal - pedido.desconto

    db.add(pedido)
    db.flush()
    if pedido.pontos_utilizados:
        db.add(TransacaoPontos(conta_id=conta.id, pedido_id=pedido.id, pontos=-pedido.pontos_utilizados, tipo="RESGATE"))
    db.commit()
    db.refresh(pedido)
    return pedido, True


def obter_pedido(db: Session, pedido_id: int, usuario: Usuario) -> Pedido:
    pedido = db.get(Pedido, pedido_id)
    if pedido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido não encontrado")
    if usuario.perfil == Perfil.CLIENTE:
        if pedido.cliente_id != usuario.id:
            # 404 em vez de 403: não revela a existência de pedidos de terceiros (IDOR).
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Pedido não encontrado")
    else:
        garantir_acesso_unidade(usuario, pedido.unidade_id)
    return pedido


def transicionar(db: Session, pedido: Pedido, novo: StatusPedido) -> None:
    if novo not in TRANSICOES[pedido.status]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Transição inválida: {pedido.status.value} -> {novo.value}",
        )
    pedido.status = novo


def cancelar(db: Session, pedido: Pedido, usuario: Usuario, motivo: str) -> Pedido:
    if pedido.status == StatusPedido.PAGO and usuario.perfil not in (Perfil.GERENTE, Perfil.ADMIN):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cancelar pedido já pago exige gerente")
    if usuario.perfil == Perfil.CLIENTE and pedido.status != StatusPedido.AGUARDANDO_PAGAMENTO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cliente só cancela pedido ainda não pago")
    status_anterior = pedido.status
    transicionar(db, pedido, StatusPedido.CANCELADO)
    _devolver_estoque(db, pedido)
    if pedido.pontos_utilizados and pedido.cliente_id:
        conta = fidelidade.obter_conta(db, pedido.cliente_id)
        conta.saldo_pontos += pedido.pontos_utilizados
        db.add(TransacaoPontos(conta_id=conta.id, pedido_id=pedido.id, pontos=pedido.pontos_utilizados, tipo="ESTORNO"))
    if status_anterior == StatusPedido.PAGO:
        from app.services.pagamentos import solicitar_estorno

        solicitar_estorno(db, pedido)
    auditoria.registrar(
        db, "PEDIDO_CANCELADO", "Pedido", pedido.id, usuario.id,
        motivo=motivo, status_anterior=status_anterior.value, valor=pedido.total,
    )
    db.commit()
    db.refresh(pedido)
    return pedido


def aplicar_desconto(db: Session, pedido: Pedido, usuario: Usuario, valor: Decimal, motivo: str) -> Pedido:
    if pedido.status != StatusPedido.AGUARDANDO_PAGAMENTO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Desconto só é permitido antes do pagamento")
    if pedido.desconto + valor > pedido.subtotal:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Desconto maior que o valor do pedido")
    total_anterior = pedido.total
    pedido.desconto += valor
    pedido.total = pedido.subtotal - pedido.desconto
    auditoria.registrar(
        db, "DESCONTO_MANUAL", "Pedido", pedido.id, usuario.id,
        motivo=motivo, valor=valor, total_anterior=total_anterior, total_novo=pedido.total,
    )
    db.commit()
    db.refresh(pedido)
    return pedido
