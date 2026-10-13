import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Perfil, Usuario

_ITERACOES = 390_000
_bearer = HTTPBearer(auto_error=False)


def gerar_hash_senha(senha: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt, _ITERACOES)
    return f"pbkdf2${_ITERACOES}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    try:
        _, iteracoes, salt_b64, hash_b64 = armazenado.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), base64.b64decode(salt_b64), int(iteracoes))
    return hmac.compare_digest(dk, base64.b64decode(hash_b64))


def criar_token(usuario: Usuario) -> str:
    payload = {
        "sub": str(usuario.id),
        "perfil": usuario.perfil.value,
        "unidade_id": usuario.unidade_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiracao_minutos),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def usuario_atual(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Usuario:
    nao_autorizado = HTTPException(status.HTTP_401_UNAUTHORIZED, "Token ausente ou inválido")
    if cred is None:
        raise nao_autorizado
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        raise nao_autorizado
    usuario = db.get(Usuario, int(payload["sub"]))
    if usuario is None or usuario.anonimizado:
        raise nao_autorizado
    return usuario


def exigir_perfil(*perfis: Perfil):
    def _verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.perfil not in perfis:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Perfil sem permissão para esta operação")
        return usuario

    return _verificar


def garantir_acesso_unidade(usuario: Usuario, unidade_id: int) -> None:
    if usuario.perfil == Perfil.ADMIN:
        return
    if usuario.perfil != Perfil.CLIENTE and usuario.unidade_id != unidade_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à sua unidade")
