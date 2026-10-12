from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Consentimento, Finalidade, Perfil, Usuario
from app.schemas import LoginIn, RegistroIn, TokenOut, UsuarioOut
from app.security import criar_token, gerar_hash_senha, usuario_atual, verificar_senha

router = APIRouter(prefix="/auth", tags=["Autenticação"])


@router.post("/registrar", response_model=UsuarioOut, status_code=status.HTTP_201_CREATED)
def registrar(dados: RegistroIn, db: Session = Depends(get_db)):
    """Cadastro público cria SEMPRE perfil CLIENTE (evita escalonamento de privilégio)."""
    if db.scalar(select(Usuario).where(Usuario.email == dados.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "E-mail já cadastrado")
    usuario = Usuario(
        nome=dados.nome,
        email=dados.email.lower(),
        senha_hash=gerar_hash_senha(dados.senha),
        perfil=Perfil.CLIENTE,
        data_nascimento=dados.data_nascimento,
    )
    db.add(usuario)
    db.flush()
    db.add(Consentimento(usuario_id=usuario.id, finalidade=Finalidade.FIDELIDADE,
                         concedido=dados.aceita_fidelidade, versao_termo="v1"))
    db.commit()
    return usuario


@router.post("/login", response_model=TokenOut)
def login(dados: LoginIn, db: Session = Depends(get_db)):
    usuario = db.scalar(select(Usuario).where(Usuario.email == dados.email.lower()))
    # Mesma mensagem para e-mail inexistente e senha errada (evita enumeração de usuários).
    if usuario is None or usuario.anonimizado or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciais inválidas")
    return TokenOut(access_token=criar_token(usuario))


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(usuario_atual)):
    return usuario
