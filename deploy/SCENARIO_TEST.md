# Nova — Scénario de test complet (A → Z, dans l'ordre)

Un seul client, déroulé chronologique exerçant **toutes** les fonctionnalités.
- **[CLIENT]** = action dans Telegram (le client).  **[ADMIN]** = commande SSH (toi).  **[VOIR]** = résultat attendu.
- Pré-requis : VPS à jour + bases reset + session préparée :
  ```bash
  cd /opt/nova/interlace_bot
  export B="http://127.0.0.1:3002"
  export T=$(./venv/bin/python -c "import json;print(json.load(open('config/params.json'))['api'].get('test_token',''))")
  ```
- Garde un terminal sur les logs :
  ```bash
  journalctl -u nova-kyc -u nova-card -f --no-pager | grep -iE "topup|deposit|credit|payment|3ds|otp|refill|carte|live=|prête|refus"
  ```
- Notations : `<CID>` = chat_id client, `<ADDR1>`/`<ADDR2>` = adresses des cartes, `<CARD1>`/`<CARD2>` = card_id.

---

## ACTE 1 — KYC & création de carte (Bot A)
1. **[CLIENT]** `/start` sur le **bot KYC** → ouvre la mini-app.
2. **[CLIENT]** met une date de naissance **> 65 ans** → **[VOIR]** bloqué (« 18 à 65 ans ») **avant** envoi. Corrige (âge valide).
3. **[CLIENT]** remplit + **documents de test Sumsub** → valide.
4. **[ADMIN/VOIR logs]** `live=PASSED` → `carte prête card_id=… token=…` (**un seul** message) → le client reçoit le **lien** `t.me/<botB>?start=…`.

> Test refus (optionnel) : refaire un KYC avec de mauvais docs → **[VOIR]** un **seul** message de refus.

## ACTE 2 — Réclamation de la carte (Bot B)
5. **[CLIENT]** ouvre **son** lien → **[VOIR]** choix **Claim for myself / I'm sharing it** (+ « (as admin) » si admin).
6. **[CLIENT]** « Claim for myself » → **[VOIR]** « ✅ Your card •••• …  is connected! » + solde **0.00** + bouton **Open my card**.
7. **[ADMIN]** lookup pour noter `<CID>`, `<CARD1>`, `<ADDR1>` :
   ```bash
   cd /opt/nova/interlace_bot && ./venv/bin/python - <<'PY'
   import json,pymysql
   m=json.load(open('config/params.json'))['mysql']
   c=pymysql.connect(host=m['host'],port=int(m['port']),user=m['user'],password=m['password'],db=m['database']);cur=c.cursor(pymysql.cursors.DictCursor)
   cur.execute("SELECT USER_ID,card_id,card_number FROM cards"); [print(r) for r in cur.fetchall()]
   cur.execute("SELECT nova_address,card_id FROM pool WHERE card_id IS NOT NULL"); [print(r) for r in cur.fetchall()]
   PY
   ```

## ACTE 3 — Paiement à VIDE → REFUSÉ (carte à 0)
8. **[ADMIN]** achat sans solde :
   ```bash
   curl -s -X POST "$B/api/test/simulate_auth" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"uid":<CID>,"amount":"12.50","merchant":"Amazon"}' | python3 -m json.tool
   ```
9. **[VOIR]** le client reçoit une notif **achat REFUSÉ** (solde insuffisant).

## ACTE 4 — Rechargement de la carte
10. **[CLIENT]** mini-app → **Top-up** → **[VOIR]** son **adresse + QR** (celle de la carte).
11. **[ADMIN]** simule le dépôt confirmé sur **son adresse** :
    ```bash
    curl -s -X POST "$B/api/test/simulate_deposit_v3" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"address":"<ADDR1>","amount":100}' | python3 -m json.tool
    ```
12. **[VOIR]** carte créditée (net après frais, ex. **85.98**) + notif « +85.98 USD added to your card ••XXXX ».
13. **[ADMIN]** idempotence — relance EXACTEMENT la même commande **avec le même `tx_id`** (récupéré dans la réponse précédente, champ `tx_id`) :
    ```bash
    curl -s -X POST "$B/api/test/simulate_deposit_v3" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"address":"<ADDR1>","amount":100,"tx_id":"<TX_PRECEDENT>"}' | python3 -m json.tool
    ```
    **[VOIR]** `skipped:true` (pas de double crédit).

## ACTE 5 — Paiement RÉUSSI (carte rechargée)
14. **[ADMIN]** même achat qu'à l'acte 3 :
    ```bash
    curl -s -X POST "$B/api/test/simulate_auth" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"uid":<CID>,"amount":"12.50","merchant":"Amazon"}' | python3 -m json.tool
    ```
15. **[VOIR]** notif **achat VALIDÉ** ; le solde de la carte diminue.

## ACTE 6 — OTP 3DS
16. **[ADMIN]**
    ```bash
    curl -s -X POST "$B/api/test/simulate_3ds" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"uid":<CID>,"otp":"123456","merchant":"Amazon 3DS"}' | python3 -m json.tool
    ```
17. **[VOIR]** le client reçoit le **code OTP `123456`** dans Telegram.

## ACTE 7 — Mini-app : transactions & freeze
18. **[CLIENT]** mini-app → **Transactions** → **[VOIR]** dépôt + achat refusé + achat validé (avec statuts).
19. **[CLIENT]** **Freeze** → **[VOIR]** carte gelée (badge) ; puis **Unfreeze**.

## ACTE 8 — 2e carte (multi-cartes, réseau, adresse dédiée)
20. **[CLIENT]** mini-app → **+** → **[VOIR]** écran réseau (logos Visa/Mastercard, 2 lignes centrées) → choisit un réseau.
21. **[CLIENT]** martèle **+** / les boutons → **[VOIR]** **une seule** création (« already in progress »).
22. **[ADMIN]** lookup (acte 7) → **[VOIR]** Carte 2 a une **adresse différente** `<ADDR2>`.
23. **[ADMIN]** dépôt sur **`<ADDR2>`** :
    ```bash
    curl -s -X POST "$B/api/test/simulate_deposit_v3" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"address":"<ADDR2>","amount":50}' | python3 -m json.tool
    ```
    **[VOIR]** c'est **Carte 2** qui est créditée (pas Carte 1) → routage par carte OK.

## ACTE 9 — Limite de cartes
24. **[CLIENT]** crée des cartes jusqu'à **5** ; à la **6e** → **[VOIR]** refus « Card limit reached (5 max) ».

## ACTE 10 — Cas FAMILLE (multi-KYC + 1 cardholder/user)
25. **[CLIENT]** refait un **2e KYC** (pour un proche) sur le bot KYC → reçoit un **2e lien**.
26. **[CLIENT]** ouvre **lui-même** ce 2e lien → **[VOIR]** refus « You already have a card account » (1 cardholder/user).
27. **[AUTRE COMPTE Telegram]** ouvre ce 2e lien → **[VOIR]** **attribution directe** (« card connected »).
28. **[AUTRE COMPTE]** rouvre le même lien → **[VOIR]** « already been used by another account ».

## ACTE 11 — Alerte « compte maître bas »
29. **[ADMIN]**
    ```bash
    curl -s -X POST "$B/api/test/check_infinity" -H "X-Test-Token: $T" -H "Content-Type: application/json" -d '{"simulate_balance":500}' | python3 -m json.tool
    ```
30. **[VOIR]** alerte admin Telegram (montant à recharger). (Rappel : refill auto = manuel.)

## ACTE 12 — Réaffectation vers un autre Telegram
31. **[ADMIN]** dry-run puis exécution :
    ```bash
    cd /opt/nova/kyc_bot
    ./venv/bin/python deploy/reassign_user.py <CID> <NOUVEAU_CID>          # plan
    ./venv/bin/python deploy/reassign_user.py <CID> <NOUVEAU_CID> --yes    # exécute
    ```
32. **[NOUVEAU COMPTE]** `/start` sur le bot carte → **[VOIR]** reconnecte la carte.
33. **[ANCIEN COMPTE]** `/start` → **[VOIR]** « no card » (accès transféré).

## ACTE 13 — /start sans carte (redirection KYC)
34. **[COMPTE VIERGE]** `/start` sur le bot carte → **[VOIR]** « No card available yet… Verify my identity » → bouton vers le bot KYC.

---

### Récap de la couverture
KYC (âge, docs, 1 msg) · carte (financement+sweep, pas de 070010/100100001) · claim (créateur/receveur, 1 cardholder, lien usage unique) · adresse-par-carte · recharge (frais, idempotence, routage par carte) · paiement **refusé puis validé** · OTP 3DS · transactions/freeze · multi-cartes + anti-spam + limite 5 · famille (multi-KYC) · alerte maître · réaffectation user · redirection KYC.
