import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def agora() -> datetime:
    return datetime.now(timezone.utc)


class Perfil(str, enum.Enum):
    CLIENTE = "CLIENTE"
    TOTEM = "TOTEM"
    ATENDENTE = "ATENDENTE"
    COZINHA = "COZINHA"
    GERENTE = "GERENTE"
    ADMIN = "ADMIN"


class TipoCozinha(str, enum.Enum):
    COMPLETA = "COMPLETA"
    REDUZIDA = "REDUZIDA"


class Canal(str, enum.Enum):
    APP = "APP"
    TOTEM = "TOTEM"
    BALCAO = "BALCAO"
    PICKUP = "PICKUP"


class StatusPedido(str, enum.Enum):
    AGUARDANDO_PAGAMENTO = "AGUARDANDO_PAGAMENTO"
    PAGAMENTO_RECUSADO = "PAGAMENTO_RECUSADO"
    PAGO = "PAGO"
    EM_PREPARO = "EM_PREPARO"
    PRONTO = "PRONTO"
    ENTREGUE = "ENTREGUE"
    CANCELADO = "CANCELADO"


class StatusPagamento(str, enum.Enum):
    PENDENTE = "PENDENTE"
    APROVADO = "APROVADO"
    RECUSADO = "RECUSADO"
    ESTORNO_SOLICITADO = "ESTORNO_SOLICITADO"


class Finalidade(str, enum.Enum):
    FIDELIDADE = "FIDELIDADE"
    MARKETING = "MARKETING"


class Unidade(Base):
    __tablename__ = "unidades"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    cidade: Mapped[str] = mapped_column(String(80))
    uf: Mapped[str] = mapped_column(String(2))
    regiao: Mapped[str] = mapped_column(String(20), index=True)
    tipo_cozinha: Mapped[TipoCozinha] = mapped_column(Enum(TipoCozinha))
    ativa: Mapped[bool] = mapped_column(Boolean, default=True)

    cardapio: Mapped[list["ItemCardapio"]] = relationship(back_populates="unidade")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(200))
    perfil: Mapped[Perfil] = mapped_column(Enum(Perfil))
    unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    data_nascimento: Mapped[date | None] = mapped_column(Date)
    anonimizado: Mapped[bool] = mapped_column(Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)

    conta_fidelidade: Mapped["ContaFidelidade | None"] = relationship(back_populates="usuario")
    consentimentos: Mapped[list["Consentimento"]] = relationship(back_populates="usuario")


class Produto(Base):
    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    descricao: Mapped[str] = mapped_column(String(300), default="")
    categoria: Mapped[str] = mapped_column(String(40))
    preco_base: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    requer_cozinha_completa: Mapped[bool] = mapped_column(Boolean, default=False)
    # null = o ano todo
    disponivel_de: Mapped[date | None] = mapped_column(Date)
    disponivel_ate: Mapped[date | None] = mapped_column(Date)


class ItemCardapio(Base):
    __tablename__ = "itens_cardapio"
    __table_args__ = (UniqueConstraint("unidade_id", "produto_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    preco: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    variacao_regional: Mapped[str | None] = mapped_column(String(200))

    unidade: Mapped[Unidade] = relationship(back_populates="cardapio")
    produto: Mapped[Produto] = relationship()


class Estoque(Base):
    __tablename__ = "estoques"
    __table_args__ = (UniqueConstraint("unidade_id", "produto_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    quantidade: Mapped[int] = mapped_column(Integer, default=0)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)


class Pedido(Base):
    __tablename__ = "pedidos"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    criado_por_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    canal: Mapped[Canal] = mapped_column(Enum(Canal))
    status: Mapped[StatusPedido] = mapped_column(Enum(StatusPedido), index=True)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    desconto: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    pontos_utilizados: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)

    itens: Mapped[list["ItemPedido"]] = relationship(back_populates="pedido", cascade="all, delete-orphan")
    pagamentos: Mapped[list["Pagamento"]] = relationship(back_populates="pedido")


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    produto_id: Mapped[int] = mapped_column(ForeignKey("produtos.id"))
    quantidade: Mapped[int] = mapped_column(Integer)
    # preço no momento da compra
    preco_unitario: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    pedido: Mapped[Pedido] = relationship(back_populates="itens")
    produto: Mapped[Produto] = relationship()


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id"), index=True)
    valor: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    status: Mapped[StatusPagamento] = mapped_column(Enum(StatusPagamento))
    metodo: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    gateway_ref: Mapped[str | None] = mapped_column(String(80), unique=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, onupdate=agora)

    pedido: Mapped[Pedido] = relationship(back_populates="pagamentos")


class EventoGateway(Base):
    __tablename__ = "eventos_gateway"

    id: Mapped[int] = mapped_column(primary_key=True)
    evento_id: Mapped[str] = mapped_column(String(80), unique=True)
    recebido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


class ContaFidelidade(Base):
    __tablename__ = "contas_fidelidade"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), unique=True)
    saldo_pontos: Mapped[int] = mapped_column(Integer, default=0)

    usuario: Mapped[Usuario] = relationship(back_populates="conta_fidelidade")
    transacoes: Mapped[list["TransacaoPontos"]] = relationship(back_populates="conta")


class TransacaoPontos(Base):
    __tablename__ = "transacoes_pontos"

    id: Mapped[int] = mapped_column(primary_key=True)
    conta_id: Mapped[int] = mapped_column(ForeignKey("contas_fidelidade.id"), index=True)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos.id"))
    pontos: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(20))  # ACUMULO, RESGATE, ESTORNO
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)

    conta: Mapped[ContaFidelidade] = relationship(back_populates="transacoes")


class Consentimento(Base):
    # só insere, nunca atualiza
    __tablename__ = "consentimentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    finalidade: Mapped[Finalidade] = mapped_column(Enum(Finalidade))
    concedido: Mapped[bool] = mapped_column(Boolean)
    versao_termo: Mapped[str] = mapped_column(String(20))
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)

    usuario: Mapped[Usuario] = relationship(back_populates="consentimentos")


class LogAuditoria(Base):
    __tablename__ = "logs_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    acao: Mapped[str] = mapped_column(String(60), index=True)
    entidade: Mapped[str] = mapped_column(String(40))
    entidade_id: Mapped[int | None] = mapped_column(Integer)
    detalhes: Mapped[str] = mapped_column(Text, default="{}")
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
