from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Estoque, ItemCardapio, Perfil, Unidade, Usuario
from app.schemas import EstoqueIn, EstoqueOut, ItemCardapioOut, UnidadeOut
from app.security import exigir_perfil, garantir_acesso_unidade
from app.services import auditoria
from app.services.pedidos import listar_cardapio

router = APIRouter(prefix="/unidades", tags=["Unidades e Cardápio"])


@router.get("", response_model=list[UnidadeOut])
def listar_unidades(regiao: str | None = None, db: Session = Depends(get_db)):
    consulta = select(Unidade).where(Unidade.ativa.is_(True)).order_by(Unidade.nome)
    if regiao:
        consulta = consulta.where(Unidade.regiao == regiao)
    return db.scalars(consulta).all()


@router.get("/{unidade_id}/cardapio", response_model=list[ItemCardapioOut])
def cardapio(unidade_id: int, db: Session = Depends(get_db)):
    """Cardápio público da unidade: só itens ativos, com estoque, compatíveis com o
    tipo de cozinha e dentro da janela sazonal."""
    return listar_cardapio(db, unidade_id)


@router.put("/{unidade_id}/estoque/{produto_id}", response_model=EstoqueOut)
def ajustar_estoque(
    unidade_id: int,
    produto_id: int,
    dados: EstoqueIn,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_perfil(Perfil.GERENTE, Perfil.ADMIN)),
):
    garantir_acesso_unidade(usuario, unidade_id)
    if not db.scalar(select(ItemCardapio).where(ItemCardapio.unidade_id == unidade_id, ItemCardapio.produto_id == produto_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Produto não pertence ao cardápio da unidade")
    estoque = db.scalar(select(Estoque).where(Estoque.unidade_id == unidade_id, Estoque.produto_id == produto_id))
    anterior = estoque.quantidade if estoque else 0
    if estoque is None:
        estoque = Estoque(unidade_id=unidade_id, produto_id=produto_id, quantidade=dados.quantidade)
        db.add(estoque)
    else:
        estoque.quantidade = dados.quantidade
    db.flush()
    auditoria.registrar(db, "AJUSTE_ESTOQUE", "Estoque", estoque.id, usuario.id,
                        unidade_id=unidade_id, produto_id=produto_id, anterior=anterior, novo=dados.quantidade)
    db.commit()
    return estoque
