# Nova — Mémo commandes sandbox (pendant les tests client)

Toutes les commandes se lancent **sur le VPS en SSH**, en local sur Bot B (`127.0.0.1:3002`).
Les endpoints `/api/test/*` sont protégés par le header **`X-Test-Token`** (= `api.test_token`).

## 0. Préparer le shell (une fois par session SSH)
```bash
cd /opt/nova/interlace_bot
export B="http://127.0.0.1:3002"
export T=$(./venv/bin/python -c "import json;print(json.load(open('config/params.json'))['api'].get('test_token',''))")
echo "token chargé: ${T:0:4}…"   # doit afficher 4 caractères, pas vide
```

## 1. Surveiller les logs (laisse tourner dans un terminal)
```bash
# tout (KYC + carte)
journalctl -u nova-kyc -u nova-card -f --no-pager
# ou filtré sur le top-up / achats / OTP :
journalctl -u nova-card -f --no-pager | grep -iE "topup|deposit|credit|payment|3ds|otp|refill|carte|adresse"
# KYC côté Bot A :
journalctl -u nova-kyc -f --no-pager | grep -iE "PAYLOAD KYC|live=|carte prête|refus|070010|100100001"
```

## 2. Quand le client appelle — retrouver son uid / carte / adresse
```bash
cd /opt/nova/interlace_bot && ./venv/bin/python - <<'PY'
import json,pymysql
m=json.load(open('config/params.json'))['mysql']
c=pymysql.connect(host=m['host'],port=int(m['port']),user=m['user'],password=m['password'],db=m['database']);cur=c.cursor(pymysql.cursors.DictCursor)
cur.execute("SELECT USER_ID,card_id,card_number,network,is_primary FROM cards ORDER BY USER_ID,is_primary DESC")
print("=== CARTES ==="); [print(r) for r in cur.fetchall()]
cur.execute("SELECT nova_address,USER_ID,card_id,status FROM pool WHERE card_id IS NOT NULL")
print("=== ADRESSES (1 par carte) ==="); [print(r) for r in cur.fetchall()]
PY
```

## 3. Phase 4 — Simuler un DÉPÔT (recharge) sur l'adresse de la carte
```bash
# routage PAR CARTE (recommandé) : on passe l'ADRESSE de la carte
curl -s -X POST "$B/api/test/simulate_deposit_v3" -H "X-Test-Token: $T" -H "Content-Type: application/json" \
  -d '{"address":"<ADRESSE_DE_LA_CARTE>","amount":100}' | python3 -m json.tool
# variante par uid (utilise l'adresse legacy/sélectionnée — moins précis) :
#  -d '{"uid":<CHAT_ID>,"amount":100}'
```
→ attendu : `ok:true`, la **bonne carte** créditée (net après frais), message « +XX USD added to your card ••XXXX ». Rejouer le même `tx_id` → `skipped`.

## 4. Phase 6 — Simuler un ACHAT (autorisation)
⚠️ Pour un achat **approuvé**, la carte doit avoir du **solde** (recharge-la d'abord, ou `fund_card` ci-dessous).
```bash
curl -s -X POST "$B/api/test/simulate_auth" -H "X-Test-Token: $T" -H "Content-Type: application/json" \
  -d '{"uid":<CHAT_ID>,"amount":"12.50","merchant":"Amazon"}' | python3 -m json.tool
# ou cibler une carte précise :
#  -d '{"card_id":"<CARD_ID>","amount":"12.50","merchant":"Amazon"}'
```
→ attendu : transaction créée + **notif** d'achat au client (validé / refusé selon solde).

## 5. Phase 6 — Simuler un OTP 3DS (le client reçoit le code)
```bash
curl -s -X POST "$B/api/test/simulate_3ds" -H "X-Test-Token: $T" -H "Content-Type: application/json" \
  -d '{"uid":<CHAT_ID>,"otp":"123456","amount":9.99,"merchant":"Amazon 3DS"}' | python3 -m json.tool
```
→ attendu : le client reçoit le message OTP `123456` dans Telegram.

## 6. Phase 7 — Simuler « compte maître bas » (alerte admin)
```bash
curl -s -X POST "$B/api/test/check_infinity" -H "X-Test-Token: $T" -H "Content-Type: application/json" \
  -d '{"simulate_balance":500}' | python3 -m json.tool
```
→ attendu : alerte admin Telegram (montant à recharger). Sans body / solde haut → pas d'alerte.

## 7. Outils debug
```bash
# Wallets bruts d'un user (voir soldes carte/sous-compte)
curl -s "$B/api/test/wallets?uid=<CHAT_ID>" -H "X-Test-Token: $T" | python3 -m json.tool

# Créditer une carte SANS frais (pour préparer un achat approuvé)
curl -s -X POST "$B/api/test/fund_card" -H "X-Test-Token: $T" -H "Content-Type: application/json" \
  -d '{"uid":<CHAT_ID>,"card_id":"<CARD_ID>","amount":50}' | python3 -m json.tool
```

## 8. Réaffecter un client à un autre Telegram (si besoin)
```bash
cd /opt/nova/kyc_bot
./venv/bin/python deploy/reassign_user.py <ANCIEN_CHAT_ID> <NOUVEAU_CHAT_ID>        # dry-run
./venv/bin/python deploy/reassign_user.py <ANCIEN_CHAT_ID> <NOUVEAU_CHAT_ID> --yes # exécute
```

## Ordre conseillé pendant un appel client
1. (terminal 1) logs en `-f`.
2. Client fait son KYC + ouvre son lien → tu vois la carte + l'adresse en base (cmd 2).
3. Client veut tester une recharge → cmd 3 avec **son adresse**.
4. Client veut un achat → cmd 4 (recharge-le avant si besoin, cmd 7 `fund_card`).
5. OTP → cmd 5.
> ⚠️ Ces endpoints `/api/test/*` doivent être **désactivés en prod** (cf. PROD_CHECKLIST §5).
