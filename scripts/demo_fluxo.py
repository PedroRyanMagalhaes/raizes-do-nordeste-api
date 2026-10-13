import json
import sys
import uuid

import httpx

sys.path.insert(0, ".")
from app.services.pagamentos import assinar  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=BASE, timeout=10)


def chamar(metodo, url, titulo, **kw):
    r = c.request(metodo, url, **kw)
    print(f"\n### {titulo}\n> {metodo} {url}  ->  HTTP {r.status_code}")
    if r.content:
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:900])
    return r


def login(email, senha="Senha@123"):
    return {"Authorization": "Bearer " + c.post("/auth/login", json={"email": email, "senha": senha}).json()["access_token"]}


email = f"cliente.{uuid.uuid4().hex[:6]}@email.com"
chamar("POST", "/auth/registrar", "1. Cliente se cadastra com consentimento de fidelidade",
       json={"nome": "Ana Souza", "email": email, "senha": "Cliente@123", "aceita_fidelidade": True})
hc = login(email, "Cliente@123")
unidades = chamar("GET", "/unidades", "2. Lista unidades").json()
recife = unidades[1]["id"] if "Recife" in unidades[1]["nome"] else unidades[0]["id"]
menu = chamar("GET", f"/unidades/{recife}/cardapio", "3. Cardápio da unidade Recife").json()
tapioca = next(i for i in menu if i["nome"].startswith("Tapioca"))["produto_id"]
chave = uuid.uuid4().hex
pedido = chamar("POST", "/pedidos", "4. Pedido pelo APP (com Idempotency-Key)",
                json={"unidade_id": recife, "canal": "APP", "itens": [{"produto_id": tapioca, "quantidade": 2}]},
                headers={**hc, "Idempotency-Key": chave}).json()
chamar("POST", "/pedidos", "5. Reenvio da mesma requisição (rede instável) -> mesmo pedido, HTTP 200",
       json={"unidade_id": recife, "canal": "APP", "itens": [{"produto_id": tapioca, "quantidade": 2}]},
       headers={**hc, "Idempotency-Key": chave})
pag = chamar("POST", f"/pagamentos/pedidos/{pedido['id']}", "6. Solicita pagamento PIX ao gateway externo",
             json={"metodo": "PIX"}, headers=hc).json()
corpo = json.dumps({"evento_id": uuid.uuid4().hex, "gateway_ref": pag["gateway_ref"], "resultado": "APROVADO"}).encode()
chamar("POST", "/pagamentos/webhook", "7. Gateway confirma via webhook assinado (HMAC)", content=corpo,
       headers={"X-Signature": assinar(corpo), "Content-Type": "application/json"})
chamar("POST", "/pagamentos/webhook", "8. Webhook com assinatura falsa -> 401", content=corpo,
       headers={"X-Signature": "0" * 64, "Content-Type": "application/json"})
hk = login("cozinha.recife@raizes.com")
for st in ("EM_PREPARO", "PRONTO", "ENTREGUE"):
    chamar("PATCH", f"/pedidos/{pedido['id']}/status", f"9. Cozinha/atendimento: {st}", json={"status": st}, headers=hk)
chamar("GET", "/fidelidade/saldo", "10. Saldo de pontos do cliente", headers=hc)
ha = login("admin@raizes.com")
chamar("GET", "/relatorios/vendas?inicio=2026-01-01&fim=2026-12-31&agrupar_por=regiao", "11. Matriz: vendas por região", headers=ha)
chamar("GET", "/auditoria?limit=3", "12. Matriz: trilha de auditoria", headers=ha)
