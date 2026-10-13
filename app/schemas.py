from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Canal, Finalidade, Perfil, StatusPagamento, StatusPedido, TipoCozinha


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegistroIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    email: EmailStr
    senha: str = Field(min_length=8, max_length=128)
    data_nascimento: date | None = None
    aceita_fidelidade: bool = False  # consentimento explícito, nunca pré-marcado


class LoginIn(BaseModel):
    email: EmailStr
    senha: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioOut(ORM):
    id: int
    nome: str
    email: str
    perfil: Perfil
    unidade_id: int | None


class UnidadeOut(ORM):
    id: int
    nome: str
    cidade: str
    uf: str
    regiao: str
    tipo_cozinha: TipoCozinha


class ItemCardapioOut(BaseModel):
    produto_id: int
    nome: str
    categoria: str
    preco: Decimal
    variacao_regional: str | None
    sazonal: bool
    estoque_disponivel: int


class EstoqueIn(BaseModel):
    quantidade: int = Field(ge=0)


class EstoqueOut(ORM):
    unidade_id: int
    produto_id: int
    quantidade: int


class ItemPedidoIn(BaseModel):
    produto_id: int
    quantidade: int = Field(gt=0, le=50)


class PedidoIn(BaseModel):
    unidade_id: int
    canal: Canal
    itens: list[ItemPedidoIn] = Field(min_length=1, max_length=30)
    usar_pontos: int = Field(default=0, ge=0)


class ItemPedidoOut(ORM):
    produto_id: int
    quantidade: int
    preco_unitario: Decimal


class PedidoOut(ORM):
    id: int
    unidade_id: int
    cliente_id: int | None
    canal: Canal
    status: StatusPedido
    subtotal: Decimal
    desconto: Decimal
    total: Decimal
    pontos_utilizados: int
    criado_em: datetime
    itens: list[ItemPedidoOut]


class StatusPedidoIn(BaseModel):
    status: StatusPedido


class CancelamentoIn(BaseModel):
    motivo: str = Field(min_length=5, max_length=300)


class DescontoIn(BaseModel):
    valor: Decimal = Field(gt=0, decimal_places=2)
    motivo: str = Field(min_length=5, max_length=300)


class PaginaPedidos(BaseModel):
    total: int
    limit: int
    offset: int
    itens: list[PedidoOut]


class PagamentoIn(BaseModel):
    metodo: str = Field(pattern="^(PIX|CREDITO|DEBITO)$")


class PagamentoOut(ORM):
    id: int
    pedido_id: int
    valor: Decimal
    status: StatusPagamento
    metodo: str
    gateway_ref: str | None


class WebhookIn(BaseModel):
    evento_id: str
    gateway_ref: str
    resultado: str = Field(pattern="^(APROVADO|RECUSADO)$")


class ConsentimentoIn(BaseModel):
    finalidade: Finalidade
    concedido: bool
    versao_termo: str = "v1"


class ConsentimentoOut(ORM):
    finalidade: Finalidade
    concedido: bool
    versao_termo: str
    registrado_em: datetime


class SaldoOut(BaseModel):
    saldo_pontos: int
    consentimento_fidelidade: bool


class LinhaVendas(BaseModel):
    chave: str
    quantidade_pedidos: int
    faturamento: Decimal


class LinhaProduto(BaseModel):
    produto_id: int
    nome: str
    quantidade_vendida: int


class LogAuditoriaOut(ORM):
    id: int
    usuario_id: int | None
    acao: str
    entidade: str
    entidade_id: int | None
    detalhes: str
    criado_em: datetime
