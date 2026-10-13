from datetime import date

from app.models import Estoque, Pedido, StatusPedido
from app.services import pedidos as servico_pedidos
from tests.conftest import enviar_webhook, registrar_cliente, token


def criar_pedido(client, headers, unidade_id, itens, canal="APP", chave=None, **extra):
    h = dict(headers)
    if chave:
        h["Idempotency-Key"] = chave
    return client.post("/pedidos", json={"unidade_id": unidade_id, "canal": canal, "itens": itens, **extra}, headers=h)


def pagar_e_aprovar(client, headers, pedido_id, evento="evt-ok"):
    r = client.post(f"/pagamentos/pedidos/{pedido_id}", json={"metodo": "PIX"}, headers=headers)
    assert r.status_code == 202, r.text
    assert enviar_webhook(client, r.json()["gateway_ref"], "APROVADO", evento).status_code == 200
    return r.json()


def test_ct01_registro_e_login_cliente(ctx):
    c = ctx["client"]
    h = registrar_cliente(c)
    me = c.get("/auth/me", headers=h).json()
    assert me["perfil"] == "CLIENTE"


def test_ct02_login_senha_errada_retorna_401_sem_revelar_motivo(ctx):
    r = ctx["client"].post("/auth/login", json={"email": "admin@raizes.com", "senha": "errada123"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Credenciais inválidas"


def test_ct03_endpoint_protegido_sem_token_retorna_401(ctx):
    assert ctx["client"].get("/pedidos/1").status_code == 401


def test_ct04_token_adulterado_retorna_401(ctx):
    h = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.assinatura-falsa"}
    assert ctx["client"].get("/auth/me", headers=h).status_code == 401


def test_ct05_cliente_nao_acessa_relatorio_da_matriz(ctx):
    c = ctx["client"]
    h = registrar_cliente(c)
    r = c.get("/relatorios/vendas", params={"inicio": "2026-01-01", "fim": "2026-12-31"}, headers=h)
    assert r.status_code == 403


def test_ct06_cardapio_respeita_tipo_de_cozinha(ctx):
    c, d = ctx["client"], ctx["dados"]
    nomes_sp = {i["nome"] for i in c.get(f"/unidades/{d['sp'].id}/cardapio").json()}
    nomes_recife = {i["nome"] for i in c.get(f"/unidades/{d['recife'].id}/cardapio").json()}
    assert "Cuscuz recheado" not in nomes_sp
    assert "Cuscuz recheado" in nomes_recife


def test_ct07_produto_sazonal_so_aparece_na_janela(ctx):
    with ctx["Sessao"]() as db:
        recife = ctx["dados"]["recife"].id
        ano = date.today().year
        junho = {i.nome for i in servico_pedidos.listar_cardapio(db, recife, date(ano, 6, 20))}
        outubro = {i.nome for i in servico_pedidos.listar_cardapio(db, recife, date(ano, 10, 20))}
    assert "Canjica junina" in junho
    assert "Canjica junina" not in outubro


def test_ct08_preco_varia_por_unidade(ctx):
    c, d = ctx["client"], ctx["dados"]
    preco = lambda u: next(i["preco"] for i in c.get(f"/unidades/{u}/cardapio").json() if i["nome"].startswith("Tapioca"))
    assert preco(d["recife"].id) == "18.00"
    assert preco(d["sp"].id) == "21.00"


def test_ct09_cliente_cria_pedido_pelo_app_e_estoque_e_baixado(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    r = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["tapioca"].id, "quantidade": 2},
                                            {"produto_id": d["suco"].id, "quantidade": 1}])
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["status"] == "AGUARDANDO_PAGAMENTO"
    assert corpo["total"] == "44.00"
    with ctx["Sessao"]() as db:
        est = db.query(Estoque).filter_by(unidade_id=d["recife"].id, produto_id=d["tapioca"].id).one()
        assert est.quantidade == 48


def test_ct10_pedido_com_mesma_idempotency_key_nao_duplica(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    itens = [{"produto_id": d["bolo"].id, "quantidade": 1}]
    r1 = criar_pedido(c, h, d["recife"].id, itens, chave="app-abc-123")
    r2 = criar_pedido(c, h, d["recife"].id, itens, chave="app-abc-123")
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    with ctx["Sessao"]() as db:
        assert db.query(Pedido).count() == 1


def test_ct11_estoque_insuficiente_retorna_409_e_nao_baixa_nada(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    hg = token(c, "gerente.recife@raizes.com")
    assert c.put(f"/unidades/{d['recife'].id}/estoque/{d['bolo'].id}", json={"quantidade": 3}, headers=hg).status_code == 200
    r = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["suco"].id, "quantidade": 1},
                                            {"produto_id": d["bolo"].id, "quantidade": 5}])
    assert r.status_code == 409
    with ctx["Sessao"]() as db:
        est = db.query(Estoque).filter_by(unidade_id=d["recife"].id, produto_id=d["suco"].id).one()
        assert est.quantidade == 50


def test_ct12_produto_indisponivel_na_unidade_retorna_422(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    r = criar_pedido(c, h, d["sp"].id, [{"produto_id": d["cuscuz"].id, "quantidade": 1}])
    assert r.status_code == 422


def test_ct13_canal_incompativel_com_perfil_retorna_403(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    r = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}], canal="BALCAO")
    assert r.status_code == 403


def test_ct14_totem_e_balcao_registram_pedido_da_propria_unidade(ctx):
    c, d = ctx["client"], ctx["dados"]
    itens = [{"produto_id": d["bolo"].id, "quantidade": 1}]
    assert criar_pedido(c, token(c, "totem01.recife@raizes.com"), d["recife"].id, itens, canal="TOTEM").status_code == 201
    assert criar_pedido(c, token(c, "atendente.recife@raizes.com"), d["recife"].id, itens, canal="BALCAO").status_code == 201
    r = criar_pedido(c, token(c, "atendente.recife@raizes.com"), d["sp"].id, itens, canal="BALCAO")
    assert r.status_code == 403


def test_ct15_cliente_nao_ve_pedido_de_outro_cliente(ctx):
    c, d = ctx["client"], ctx["dados"]
    h1 = registrar_cliente(c, "a@email.com")
    h2 = registrar_cliente(c, "b@email.com")
    pid = criar_pedido(c, h1, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}]).json()["id"]
    assert c.get(f"/pedidos/{pid}", headers=h2).status_code == 404


def test_ct16_fluxo_completo_pagamento_aprovado_ate_entrega(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["tapioca"].id, "quantidade": 1}]).json()["id"]
    pagar_e_aprovar(c, h, pid)
    assert c.get(f"/pedidos/{pid}", headers=h).json()["status"] == "PAGO"
    hc = token(c, "cozinha.recife@raizes.com")
    for st in ("EM_PREPARO", "PRONTO", "ENTREGUE"):
        assert c.patch(f"/pedidos/{pid}/status", json={"status": st}, headers=hc).status_code == 200
    assert c.get(f"/pedidos/{pid}", headers=h).json()["status"] == "ENTREGUE"


def test_ct17_pagamento_recusado_permite_nova_tentativa(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}]).json()["id"]
    ref = c.post(f"/pagamentos/pedidos/{pid}", json={"metodo": "CREDITO"}, headers=h).json()["gateway_ref"]
    enviar_webhook(c, ref, "RECUSADO", "evt-recusa")
    assert c.get(f"/pedidos/{pid}", headers=h).json()["status"] == "PAGAMENTO_RECUSADO"
    nova = c.post(f"/pagamentos/pedidos/{pid}", json={"metodo": "PIX"}, headers=h).json()
    assert nova["gateway_ref"] != ref
    enviar_webhook(c, nova["gateway_ref"], "APROVADO", "evt-aprova")
    assert c.get(f"/pedidos/{pid}", headers=h).json()["status"] == "PAGO"


def test_ct18_gateway_fora_do_ar_retorna_503_e_retentativa_funciona(ctx):
    c, d, gw = ctx["client"], ctx["dados"], ctx["gateway"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}]).json()["id"]
    gw.falhar = True
    r = c.post(f"/pagamentos/pedidos/{pid}", json={"metodo": "PIX"}, headers=h)
    assert r.status_code == 503 and r.headers["Retry-After"] == "5"
    gw.falhar = False
    r = c.post(f"/pagamentos/pedidos/{pid}", json={"metodo": "PIX"}, headers=h)
    assert r.status_code == 202 and r.json()["gateway_ref"]
    assert len(gw.cobrancas) == 1


def test_ct19_webhook_com_assinatura_invalida_retorna_401(ctx):
    r = enviar_webhook(ctx["client"], "gw_x", assinatura="0" * 64)
    assert r.status_code == 401


def test_ct20_webhook_duplicado_nao_credita_pontos_duas_vezes(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["cuscuz"].id, "quantidade": 1}]).json()["id"]
    ref = pagar_e_aprovar(c, h, pid, evento="evt-dup")["gateway_ref"]
    assert enviar_webhook(c, ref, "APROVADO", "evt-dup").json()["status"] == "DUPLICADO"
    assert c.get("/fidelidade/saldo", headers=h).json()["saldo_pontos"] == 22


def test_ct21_cozinha_nao_pode_pular_etapas(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}]).json()["id"]
    hc = token(c, "cozinha.recife@raizes.com")
    assert c.patch(f"/pedidos/{pid}/status", json={"status": "EM_PREPARO"}, headers=hc).status_code == 409
    assert c.patch(f"/pedidos/{pid}/status", json={"status": "PAGO"}, headers=hc).status_code == 422


def test_ct22_cancelamento_de_pedido_pago_exige_gerente_e_gera_auditoria_e_estorno(ctx):
    c, d, gw = ctx["client"], ctx["dados"], ctx["gateway"]
    h = registrar_cliente(c)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 2}]).json()["id"]
    pagar_e_aprovar(c, h, pid)
    motivo = {"motivo": "Cliente desistiu na fila"}
    assert c.post(f"/pedidos/{pid}/cancelar", json=motivo, headers=token(c, "atendente.recife@raizes.com")).status_code == 403
    r = c.post(f"/pedidos/{pid}/cancelar", json=motivo, headers=token(c, "gerente.recife@raizes.com"))
    assert r.status_code == 200 and r.json()["status"] == "CANCELADO"
    assert len(gw.estornos) == 1
    logs = c.get("/auditoria", params={"acao": "PEDIDO_CANCELADO"}, headers=token(c, "admin@raizes.com")).json()
    assert logs and '"Cliente desistiu na fila"' in logs[0]["detalhes"]
    with ctx["Sessao"]() as db:
        assert db.query(Estoque).filter_by(unidade_id=d["recife"].id, produto_id=d["bolo"].id).one().quantidade == 50


def test_ct23_desconto_manual_so_gerente_e_auditado(ctx):
    c, d = ctx["client"], ctx["dados"]
    ha = token(c, "atendente.recife@raizes.com")
    pid = criar_pedido(c, ha, d["recife"].id, [{"produto_id": d["tapioca"].id, "quantidade": 1}], canal="BALCAO").json()["id"]
    corpo = {"valor": "3.00", "motivo": "Atraso no preparo"}
    assert c.post(f"/pedidos/{pid}/desconto", json=corpo, headers=ha).status_code == 403
    r = c.post(f"/pedidos/{pid}/desconto", json=corpo, headers=token(c, "gerente.recife@raizes.com"))
    assert r.json()["total"] == "15.00"
    assert c.get("/auditoria", params={"acao": "DESCONTO_MANUAL"}, headers=token(c, "admin@raizes.com")).json()


def test_ct24_gerente_nao_ajusta_estoque_de_outra_unidade(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = token(c, "gerente.sp@raizes.com")
    assert c.put(f"/unidades/{d['recife'].id}/estoque/{d['bolo'].id}", json={"quantidade": 5}, headers=h).status_code == 403
    assert c.put(f"/unidades/{d['sp'].id}/estoque/{d['bolo'].id}", json={"quantidade": 5}, headers=h).status_code == 200


def test_ct25_sem_consentimento_nao_acumula_pontos(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c, aceita_fidelidade=False)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["cuscuz"].id, "quantidade": 1}]).json()["id"]
    pagar_e_aprovar(c, h, pid)
    saldo = c.get("/fidelidade/saldo", headers=h).json()
    assert saldo == {"saldo_pontos": 0, "consentimento_fidelidade": False}


def test_ct26_resgate_de_pontos_limitado_a_50_porcento(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    for i in range(10):
        pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["cuscuz"].id, "quantidade": 1}]).json()["id"]
        pagar_e_aprovar(c, h, pid, evento=f"evt-{i}")
    r = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["suco"].id, "quantidade": 1}], usar_pontos=220)
    corpo = r.json()
    assert corpo["desconto"] == "4.00" and corpo["total"] == "4.00"
    assert corpo["pontos_utilizados"] == 80
    assert c.get("/fidelidade/saldo", headers=h).json()["saldo_pontos"] == 140


def test_ct27_revogar_consentimento_interrompe_acumulo(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    c.post("/lgpd/consentimentos", json={"finalidade": "FIDELIDADE", "concedido": False}, headers=h)
    pid = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["cuscuz"].id, "quantidade": 1}]).json()["id"]
    pagar_e_aprovar(c, h, pid)
    assert c.get("/fidelidade/saldo", headers=h).json()["saldo_pontos"] == 0


def test_ct28_anonimizacao_remove_dados_pessoais_e_bloqueia_login(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c, "titular@email.com")
    criar_pedido(c, h, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}])
    assert c.get("/lgpd/meus-dados", headers=h).json()["usuario"]["email"] == "titular@email.com"
    assert c.delete("/lgpd/minha-conta", headers=h).status_code == 204
    assert c.post("/auth/login", json={"email": "titular@email.com", "senha": "Cliente@123"}).status_code == 401
    with ctx["Sessao"]() as db:
        assert db.query(Pedido).count() == 1


def test_ct29_relatorio_vendas_por_regiao_e_mais_vendidos(ctx):
    c, d = ctx["client"], ctx["dados"]
    h = registrar_cliente(c)
    p1 = criar_pedido(c, h, d["recife"].id, [{"produto_id": d["tapioca"].id, "quantidade": 3}]).json()["id"]
    pagar_e_aprovar(c, h, p1, "e1")
    p2 = criar_pedido(c, h, d["sp"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}]).json()["id"]
    pagar_e_aprovar(c, h, p2, "e2")
    criar_pedido(c, h, d["sp"].id, [{"produto_id": d["bolo"].id, "quantidade": 5}])
    ha = token(c, "admin@raizes.com")
    hoje = date.today().isoformat()
    vendas = c.get("/relatorios/vendas", params={"inicio": hoje, "fim": hoje, "agrupar_por": "regiao"}, headers=ha).json()
    assert {v["chave"]: v["faturamento"] for v in vendas} == {"NORDESTE": "54.00", "SUDESTE": "11.00"}
    top = c.get("/relatorios/produtos-mais-vendidos", params={"inicio": hoje, "fim": hoje}, headers=ha).json()
    assert top[0]["nome"] == "Tapioca de carne de sol" and top[0]["quantidade_vendida"] == 3


def test_ct30_listagem_da_fila_da_loja_e_paginada(ctx):
    c, d = ctx["client"], ctx["dados"]
    ht = token(c, "totem01.recife@raizes.com")
    for _ in range(5):
        criar_pedido(c, ht, d["recife"].id, [{"produto_id": d["bolo"].id, "quantidade": 1}], canal="TOTEM")
    r = c.get("/pedidos", params={"unidade_id": d["recife"].id, "limit": 2, "offset": 0},
              headers=token(c, "cozinha.recife@raizes.com")).json()
    assert r["total"] == 5 and len(r["itens"]) == 2
    assert c.get("/pedidos", params={"unidade_id": d["recife"].id, "limit": 500},
                 headers=token(c, "cozinha.recife@raizes.com")).status_code == 422
    assert StatusPedido.AGUARDANDO_PAGAMENTO.value == r["itens"][0]["status"]
