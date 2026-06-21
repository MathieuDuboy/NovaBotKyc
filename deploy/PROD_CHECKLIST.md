# Nova — Checklist de mise en production

Passage de l'environnement **sandbox** à la **prod**. À faire dans l'ordre.
Les deux bots partagent le **même compte Interlace** (1 seule URL de webhook).

> 🔑 **`params.json` n'est PAS dans git** (gitignoré). Pour la prod, il est **remis en
> main propre** par l'opérateur, puis **édité À LA MAIN sur le VPS** :
> `nano /opt/nova/interlace_bot/config/params.json` (et `/opt/nova/kyc_bot/config/params.json`),
> on renseigne les valeurs prod (sections ci-dessous), puis `systemctl restart nova-kyc nova-card`.
> Idem `config/credentials.json` (service account Google) : déposé à la main, jamais committé.

> Légende : 🅰️ = Bot A (kyc_bot, :3003) · 🅱️ = Bot B (interlace_bot, :3002)

---

## 1. Interlace — passage en prod

🅰️🅱️ Dans `config/params.json` des **deux** bots, section `interlace` :
```json
"interlace": {
  "mode": "prod",
  "prod": {
    "bin": "<BIN prod>",
    "base_url": "https://api.interlace.money",
    "account_id": "<account_id prod>",
    "client_id": "<client_id prod>",
    "client_secret": "<client_secret prod>"
  }
}
```
- `account_id` / `client_id` / `client_secret` **identiques** sur les 2 bots (compte partagé).
- Vérifier les **binId prod** dans `interlace_bot/services/bins.py` et `kyc_bot/services/interlace_kyc.py` (les binId sandbox ne sont pas forcément valides en prod).

## 2. Webhook Interlace

Dans le dashboard Interlace (Notification/Webhook URL), pointer vers **Bot B** :
```
https://<domaine-card>/api/callback
```
- Bot B reroute automatiquement les events d'onboarding (KYC/cardholder/account) vers Bot A en interne.
- En prod, le **KYC est validé par webhook réel** → `complete_after_kyc_passed` se déclenche tout seul (plus d'approbation manuelle). `finalize_kyc` ne sert plus qu'au debug.

## 3. NovaBtc — dépôts réels (🅱️)

`config/params.json` Bot B :
```json
"nova_api": {
  "access_key": "<clé prod>",
  "secret_key": "<secret prod>",
  "user_uuid": "<uuid du compte NovaBtc>",
  "base_url": "https://api.novabtc.io",
  "ws_url": "wss://api.novabtc.io"
}
```
- ⚠️ **NOUVELLE CLÉ/SECRET API NovaBtc** (écoute des dépôts) : mettre la `access_key`
  + `secret_key` **de prod** (et `user_uuid` si le compte a changé). Ce sont CES creds
  qui authentifient le WebSocket. Après changement : `systemctl restart nova-card`.
- Mettre `testing.testing` = **false** (sinon le WebSocket NE se connecte PAS — donc
  changer la clé ne sert à rien tant que testing=true).
- Au boot, vérifier les logs : `WebSocket connection established` + `Socket.IO connected to …`.
- **Pool d'adresses (modèle 1 adresse = 1 carte)** : importer les **5000 vraies adresses**
  USDT-TRC20 **du compte NovaBtc ci-dessus** dans la table `pool` (status `free`).
  Elles DOIVENT appartenir à ce compte, sinon les dépôts n'arrivent jamais au bot.
  Import : `INSERT IGNORE INTO pool (nova_address,status) VALUES (<addr>,'free')`
  (script CSV fourni). Chaque carte créée « claim » ensuite une adresse libre.
  Les `TSandboxFakeAddr…` sont factices (sandbox).

## 4. Frais & limites de dépôt (🅱️)

`config/params.json` Bot B, section `nova_deposits` — ajuster aux valeurs réelles :
```json
"nova_deposits": {
  "min": 100, "max": 100000,
  "fee_percent": 0.025, "fee_percent_interlace": 0.015,
  "fee_cash": 4, "virtual_card_fee": 6, "open_card_initial_amount": 10
}
```

## 5. Sécurité des endpoints

- 🅱️ ⚠️ **DÉSACTIVER complètement les `/api/test/*` en prod** (PRIORITÉ). Ces endpoints
  (`fund_card`, `simulate_auth`, `simulate_deposit_v3`, `simulate_deposit`, `wallets`,
  `check_infinity`) **créent/déplacent de la valeur sur n'importe quelle carte** et sont
  exposés publiquement. Un token fort ne suffit pas : prévoir un **kill-switch** (ne pas
  enregistrer ces routes si prod / `TESTING_MODE` off). En attendant : token `api.test_token`
  fort obligatoire (sans token → 403).
- 🅱️ `api.require_miniapp_auth` = **true** en prod (auth init_data ; false = uid falsifiable).
- 🅰️ `api.admin_token` : secret fort pour `finalize_kyc` + `/api/admin/enrollments`
  (ce dernier expose emails/liens de TOUS les users → idéalement restreindre par IP/VPN).
- Tokens via `openssl rand -hex 16`. `params.json` est gitignoré (jamais commité).

## 6. Liens & langue

- 🅱️ `api.kyc_bot_url` : lien Telegram du **bot KYC de prod** (`https://t.me/<bot_kyc>`).
- 🅰️ `BOT_B_USERNAME` (kyc_bot/services/interlace_kyc.py) : username du **bot carte de prod**.
- 🅱️ `api.miniapp_url` / `public_base_url` : domaine public de prod (HTTPS).

## 7. Vérifications finales

```bash
# Bot A et Bot B démarrent
systemctl is-active nova-kyc nova-card
# WS NovaBtc connecté (Bot B)
journalctl -u nova-card | grep -i "WebSocket connection established"
# endpoints de test verrouillés (403 sans token)
curl -s -o /dev/null -w "%{http_code}\n" "https://<domaine-card>/api/test/wallets?uid=1"
```

Parcours de bout en bout : onboarding KYC → carte créée (BIN 537100) → handoff →
mini app → dépôt USDT réel → crédit + notif → achat → notif/OTP.

---

### État actuel (sandbox, juin 2026) — VALIDÉ
Multi-cartes (choix BIN, cross-réseau), top-up par carte (frais exacts), achats +
notifications (validé/en attente/refusé), OTP 3DS câblé, messages localisés fr/en/ru,
endpoints sensibles protégés par token. Reste : étapes 1→4 ci-dessus + OTP 3DS sur
vrai achat online.
