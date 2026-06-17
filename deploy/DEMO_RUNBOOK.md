# Nova — Runbook de démo (sandbox)

Le client fait le parcours **dans Telegram** ; toi tu déclenches les **3 événements
d'argent** en simulation. Voici QUAND il te ping et QUOI lancer.

## Pré-réglages (une fois)
```bash
URL=https://card.107.189.16.79.nip.io      # Bot B (carte)
A_URL=http://127.0.0.1:3003                 # Bot A (KYC), depuis le VPS
TOK=<api.test_token de Bot B>
ATOK=<api.admin_token de Bot A>
```

Récupérer l'**uid** (chat_id) et les **card_id** du client :
```bash
# uid = chat_id Telegram du client (visible dans les logs au /start, ou il te le donne)
journalctl -u nova-card -n 200 | grep -iE "card_b|user="     # repère son chat_id
# ses cartes :
curl -s "$URL/api/test/wallets?uid=<UID>" -H "X-Test-Token: $TOK" | python3 -m json.tool
```

---

## 📞 Moment 1 — après qu'il a SOUMIS le formulaire KYC
But : approuver le KYC pour que sa carte soit créée.
1. Approuver le sous-compte côté **Interlace** (validation manuelle sandbox).
2. Récupérer son `account_id` (logs Bot A au submit) :
   ```bash
   journalctl -u nova-kyc -n 200 | grep -iE "sous-compte|account"
   ```
3. Finaliser → crée cardholder + carte + envoie le lien handoff au client :
   ```bash
   curl -s -X POST "$A_URL/api/admin/finalize_kyc?account_id=<ACCOUNT_ID>" \
     -H "X-Admin-Token: $ATOK" | python3 -m json.tool
   ```
   → le client reçoit son lien carte. (Carte créée en **BIN 537100**.)

## 📞 Moment 2 — quand il veut voir un RECHARGEMENT
But : son solde monte + il reçoit la notif « +X USD ».
```bash
# (il a ouvert "Recharger" et choisi sa carte -> selected_card_id est posé)
curl -s -X POST "$URL/api/test/simulate_deposit_v3" \
  -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"uid":<UID>,"amount":100}' | python3 -m json.tool
```
→ 1ᵉʳ dépôt 100 → **net 67** (frais 4% + 4 + carte virtuelle 25) ; suivants → **92**.
Le client voit le solde grimper + notif « ✅ +X USD ajoutés ».

## 📞 Moment 3 — quand il veut voir un ACHAT + notif
Il faut d'abord financer la carte (sinon l'achat est refusé), attendre ~3 s, puis acheter.
```bash
CARD=<CARD_ID du client>   # via /api/test/wallets
# financer
curl -s -X POST "$URL/api/test/fund_card" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"uid":<UID>,"card_id":"'$CARD'","amount":"50"}' >/dev/null ; sleep 3
# achat qui PASSE -> notif "Payment"
curl -s -X POST "$URL/api/test/simulate_auth" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"card_id":"'$CARD'","amount":"12.50","merchant":"Amazon"}' | python3 -m json.tool
# achat REFUSÉ (montant > solde) -> notif "declined" + ligne rouge
curl -s -X POST "$URL/api/test/simulate_auth" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"card_id":"'$CARD'","amount":"9999","merchant":"Apple"}' | python3 -m json.tool
```
> Si « Card suspended » : la carte est gelée → la débloquer :
> `curl -s -X POST "$URL/api/card/unfreeze" -H "Content-Type: application/json" -d '{"uid":<UID>,"card_id":"'$CARD'"}'`

## 📞 Moment 4 — parcours « achat 3DS » complet (OTP puis validation)
Reproduit un vrai achat en ligne avec vérification 3DS : le client reçoit l'**OTP**,
puis la **notif de transaction**. (En prod, les 2 arrivent d'Interlace sur le même
achat ; le bot ne fait que les relayer — la saisie de l'OTP se fait sur la page du
marchand. En sandbox on déclenche les 2 à la main.)
```bash
CARD=<CARD_ID du client>
# 0) carte financée (sinon refus)
curl -s -X POST "$URL/api/test/fund_card" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"uid":<UID>,"card_id":"'$CARD'","amount":"50"}' >/dev/null ; sleep 3
# 1) OTP 3DS (langue auto du user ; forcer avec "lang":"fr"/"en"/"ru" si besoin)
curl -s -X POST "$URL/api/test/simulate_3ds" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"card_id":"'$CARD'","otp":"487213","amount":29.90,"merchant":"Amazon"}' >/dev/null
# 2) transaction validée -> notif "Payment"
sleep 2
curl -s -X POST "$URL/api/test/simulate_auth" -H 'Content-Type: application/json' -H "X-Test-Token: $TOK" \
  -d '{"card_id":"'$CARD'","amount":"29.90","merchant":"Amazon"}' | python3 -m json.tool
```
→ Le client voit dans l'ordre : 🔐 « Vérification 3DS — Code : 487213 », puis 💳 « Payment 29.90 USD · Amazon ».
- OTP seul (sans paiement) : juste l'étape 1.
- Le bot **transmet** l'OTP, il ne le valide pas (validation = page marchand / Interlace).

---

## Ce que le client fait SEUL (aucun ping)
Langue, formulaire KYC, ouverture mini-app, retourner la carte (PAN/CVV), voir solde,
bloquer/débloquer, historique, footer (support/tarifs/légal), **ajouter une carte +
choix réseau**, basculer entre cartes, écran « Recharger » (adresse + QR).

## Non simulable en sandbox (prod uniquement)
Vrai dépôt USDT on-chain (listener WS off), vrai achat 3DS chez un marchand réel.
> La **réception de l'OTP** EST simulable (Moment 4) : Interlace n'a pas d'endpoint
> de simulation 3DS, mais on injecte l'événement de notre côté → le client reçoit
> bien le code dans Telegram, dans sa langue. Le handler est identique en prod.
```
