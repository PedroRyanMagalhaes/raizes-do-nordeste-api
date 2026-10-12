"""Configurações da aplicação, lidas de variáveis de ambiente (12-Factor App).

Nenhum segredo fica fixo no código: os valores padrão servem apenas para
desenvolvimento local e testes.
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./raizes.db")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
    jwt_algorithm: str = "HS256"
    jwt_expiracao_minutos: int = int(os.getenv("JWT_EXPIRACAO_MINUTOS", "60"))
    # Segredo compartilhado com o gateway para assinar (HMAC) os webhooks.
    gateway_webhook_secret: str = os.getenv("GATEWAY_WEBHOOK_SECRET", "dev-webhook-secret")
    # Regras do programa de fidelidade
    pontos_por_real: int = 1
    pontos_por_real_desconto: int = 20  # 20 pontos = R$ 1,00 de desconto
    desconto_maximo_percentual: float = 0.5  # pontos cobrem no máximo 50% do pedido


settings = Settings()
