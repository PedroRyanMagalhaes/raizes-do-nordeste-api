from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import Estoque, ItemCardapio, Perfil, Produto, TipoCozinha, Unidade, Usuario
from app.security import gerar_hash_senha

SENHA_PADRAO = "Senha@123"


def popular(db: Session, ano: int | None = None) -> dict[str, object]:
    ano = ano or date.today().year
    recife = Unidade(nome="Raízes Recife - Casa Forte", cidade="Recife", uf="PE", regiao="NORDESTE", tipo_cozinha=TipoCozinha.COMPLETA)
    sp = Unidade(nome="Raízes São Paulo - Paulista", cidade="São Paulo", uf="SP", regiao="SUDESTE", tipo_cozinha=TipoCozinha.REDUZIDA)
    db.add_all([recife, sp])

    tapioca = Produto(nome="Tapioca de carne de sol", categoria="TAPIOCAS", preco_base=Decimal("18.00"))
    cuscuz = Produto(nome="Cuscuz recheado", categoria="CUSCUZ", preco_base=Decimal("22.00"), requer_cozinha_completa=True)
    bolo = Produto(nome="Bolo de macaxeira", categoria="DOCES", preco_base=Decimal("9.50"))
    suco = Produto(nome="Suco de cajá", categoria="BEBIDAS", preco_base=Decimal("8.00"))
    canjica = Produto(nome="Canjica junina", categoria="DOCES", preco_base=Decimal("10.00"),
                      disponivel_de=date(ano, 6, 1), disponivel_ate=date(ano, 7, 31))
    db.add_all([tapioca, cuscuz, bolo, suco, canjica])
    db.flush()

    cardapio = [
        (recife, tapioca, "18.00", None), (recife, cuscuz, "22.00", "Com queijo coalho"),
        (recife, bolo, "9.50", None), (recife, suco, "8.00", None), (recife, canjica, "10.00", None),
        (sp, tapioca, "21.00", None), (sp, cuscuz, "25.00", None),
        (sp, bolo, "11.00", None), (sp, suco, "9.50", "Polpa congelada"),
    ]
    for unidade, produto, preco, variacao in cardapio:
        db.add(ItemCardapio(unidade_id=unidade.id, produto_id=produto.id, preco=Decimal(preco), variacao_regional=variacao))
        db.add(Estoque(unidade_id=unidade.id, produto_id=produto.id, quantidade=50))

    hash_ = gerar_hash_senha(SENHA_PADRAO)
    usuarios = {
        "admin": Usuario(nome="Matriz", email="admin@raizes.com", senha_hash=hash_, perfil=Perfil.ADMIN),
        "gerente": Usuario(nome="Gerente Recife", email="gerente.recife@raizes.com", senha_hash=hash_, perfil=Perfil.GERENTE, unidade_id=recife.id),
        "atendente": Usuario(nome="Atendente Recife", email="atendente.recife@raizes.com", senha_hash=hash_, perfil=Perfil.ATENDENTE, unidade_id=recife.id),
        "cozinha": Usuario(nome="Cozinha Recife", email="cozinha.recife@raizes.com", senha_hash=hash_, perfil=Perfil.COZINHA, unidade_id=recife.id),
        "totem": Usuario(nome="Totem 01 Recife", email="totem01.recife@raizes.com", senha_hash=hash_, perfil=Perfil.TOTEM, unidade_id=recife.id),
        "gerente_sp": Usuario(nome="Gerente SP", email="gerente.sp@raizes.com", senha_hash=hash_, perfil=Perfil.GERENTE, unidade_id=sp.id),
    }
    db.add_all(usuarios.values())
    db.commit()
    return {"recife": recife, "sp": sp, "tapioca": tapioca, "cuscuz": cuscuz, "bolo": bolo, "suco": suco,
            "canjica": canjica, **usuarios}


if __name__ == "__main__":
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as sessao:
        popular(sessao)
    print(f"Banco populado. Usuários de teste com senha {SENHA_PADRAO}")
