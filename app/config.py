import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./raizes.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_expiracao_minutos: int = int(os.getenv("JWT_EXPIRACAO_MINUTOS", "60"))
    gateway_webhook_secret: str = os.getenv("GATEWAY_WEBHOOK_SECRET", "dev-webhook-secret")
    fuso_horario: str = os.getenv("FUSO_HORARIO", "America/Sao_Paulo")
    pontos_por_real: int = 1
    pontos_por_real_desconto: int = 20
    desconto_maximo_percentual: float = 0.5


settings = Settings()
