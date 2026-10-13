from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Consentimento, Finalidade, Pedido, Perfil, Usuario
from app.schemas import ConsentimentoIn, ConsentimentoOut, SaldoOut
from app.security import exigir_perfil
from app.services import auditoria, fidelidade

router = APIRouter(tags=["Fidelidade e LGPD"])
cliente = exigir_perfil(Perfil.CLIENTE)


@router.get("/fidelidade/saldo", response_model=SaldoOut)
def saldo(db: Session = Depends(get_db), usuario: Usuario = Depends(cliente)):
    conta = fidelidade.obter_conta(db, usuario.id)
    db.commit()
    return SaldoOut(
        saldo_pontos=conta.saldo_pontos,
        consentimento_fidelidade=fidelidade.tem_consentimento(db, usuario.id, Finalidade.FIDELIDADE),
    )


@router.post("/lgpd/consentimentos", response_model=ConsentimentoOut, status_code=status.HTTP_201_CREATED)
def registrar_consentimento(dados: ConsentimentoIn, db: Session = Depends(get_db), usuario: Usuario = Depends(cliente)):
    registro = Consentimento(usuario_id=usuario.id, **dados.model_dump())
    db.add(registro)
    db.commit()
    return registro


@router.get("/lgpd/meus-dados")
def meus_dados(db: Session = Depends(get_db), usuario: Usuario = Depends(cliente)):
    # LGPD art. 18, II e V
    pedidos = db.scalars(select(Pedido).where(Pedido.cliente_id == usuario.id)).all()
    auditoria.registrar(db, "LGPD_EXPORTACAO_DADOS", "Usuario", usuario.id, usuario.id)
    db.commit()
    return {
        "usuario": {"nome": usuario.nome, "email": usuario.email, "data_nascimento": usuario.data_nascimento,
                    "criado_em": usuario.criado_em},
        "consentimentos": [ConsentimentoOut.model_validate(c).model_dump() for c in usuario.consentimentos],
        "pedidos": [{"id": p.id, "total": p.total, "status": p.status, "criado_em": p.criado_em} for p in pedidos],
    }


@router.delete("/lgpd/minha-conta", status_code=status.HTTP_204_NO_CONTENT)
def anonimizar_conta(db: Session = Depends(get_db), usuario: Usuario = Depends(cliente)):
    # anonimiza em vez de apagar: pedidos precisam ser mantidos (fiscal)
    usuario.nome = "Titular anonimizado"
    usuario.email = f"anonimizado-{usuario.id}@invalido.local"
    usuario.data_nascimento = None
    usuario.senha_hash = "!"
    usuario.anonimizado = True
    db.add(Consentimento(usuario_id=usuario.id, finalidade=Finalidade.FIDELIDADE, concedido=False, versao_termo="revogacao"))
    db.add(Consentimento(usuario_id=usuario.id, finalidade=Finalidade.MARKETING, concedido=False, versao_termo="revogacao"))
    auditoria.registrar(db, "LGPD_ANONIMIZACAO", "Usuario", usuario.id, usuario.id)
    db.commit()
