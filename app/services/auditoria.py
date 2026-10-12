import json

from sqlalchemy.orm import Session

from app.models import LogAuditoria


def registrar(
    db: Session,
    acao: str,
    entidade: str,
    entidade_id: int | None,
    usuario_id: int | None,
    **detalhes,
) -> None:
    """Adiciona um registro de auditoria na MESMA transação da operação auditada:
    se a operação falhar e der rollback, o log também não é gravado (consistência)."""
    db.add(
        LogAuditoria(
            usuario_id=usuario_id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            detalhes=json.dumps(detalhes, default=str, ensure_ascii=False),
        )
    )
