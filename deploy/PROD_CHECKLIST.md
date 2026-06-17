# Nova — Checklist de mise en production

Passage de l'environnement **sandbox** à la **prod**. À faire dans l'ordre.
Les deux bots partagent le **même compte Interlace** (1 seule URL de webhook).

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
- Mettre `testing.testing` = **false** (désactive le gate qui empêche `connect_websocket()`).
- Au boot, vérifier les logs : `WebSocket connection established` + `Socket.IO connected to …`.
- Remplir la table `pool` avec de **vraies adresses** USDT-TRC20 gérées par NovaBtc
  (les `TSandboxFakeAddr…` sont factices).

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

- 🅱️ `api.test_token` : garder un secret fort. **Idéalement, désactiver/retirer les
  `/api/test/*` en prod** (ils servent au debug). Sans token → déjà 403.
- 🅰️ `api.admin_token` : secret fort pour `finalize_kyc` (debug uniquement en prod).
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
