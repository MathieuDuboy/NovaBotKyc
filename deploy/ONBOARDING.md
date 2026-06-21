# Nova — Onboarding nouveau dev (reprise A→Z)

Objectif : repartir de zéro avec **tes propres bots**, monter une **pré-prod (sandbox)**,
puis passer en **prod** avec les vrais credentials. Lis d'abord `ARCHITECTURE.md`.

---

## 0. Les 2 repos (ils vont ENSEMBLE)
- **Bot A — KYC** : repo `NovaBotKyc` → déployé dans `/opt/nova/kyc_bot`
- **Bot B — Carte** : repo `NovaBotCardSandBoxInter` → déployé dans `/opt/nova/interlace_bot`

Ils sont **côte à côte** sous `/opt/nova/` (certains outils lisent `../interlace_bot`).
Toute la doc d'exploitation est dans **`kyc_bot/deploy/`**.

```bash
mkdir -p /opt/nova && cd /opt/nova
git clone <url_NovaBotKyc> kyc_bot
git clone <url_NovaBotCardSandBoxInter> interlace_bot
```

## 1. Crée TES bots Telegram (BotFather)
1. `@BotFather` → `/newbot` ×2 → **Bot A (KYC)** et **Bot B (carte)**. Note les **tokens** + **@usernames**.
2. Pour chaque bot : `/setdomain` (ou via Mini App) si besoin, et active le **Menu/WebApp**.
3. Récupère **ton chat_id** (ex. via `@userinfobot`) → ce sera l'**admin**.

## 2. Récupère les credentials sandbox
- **Interlace** (sandbox) : `client_id`, `client_secret`, `account_id` (compte maître),
  `base_url` sandbox, et les **binId** des BIN proposés. (cf. `INTERLACE_V3_KYC_MAP.md` +
  `services/bins.py` / `services/interlace_kyc.py`.)
- **NovaBtc** : `access_key`, `secret_key`, `user_uuid`, + des **adresses de dépôt** du compte.
- **Sumsub** (via Interlace) : en sandbox, le KYC ne passe qu'avec les **documents de test
  officiels Sumsub** (passeport Allemagne, etc.) et un `idType` cohérent avec la nationalité.

## 3. Configure `params.json` (par bot — JAMAIS commité)
Copie `config/params.example.json` → `config/params.json` dans chaque bot, puis remplis.
**Champs essentiels :**

| Section / clé | Bot | Rôle |
|---|---|---|
| `telegram.bot_token` | A & B | token BotFather du bot |
| `telegram.bot_b_username` | A | @username (sans @) du Bot B → utilisé pour le **lien de handoff** |
| `telegram.admin_chat_ids` | A & B | liste des chat_id admin (droits étendus) |
| `interlace.mode` | A & B | `dev` (sandbox) ou `prod` |
| `interlace.<mode>.client_id/client_secret/account_id/base_url/bin` | A & B | creds Interlace (**identiques** sur les 2 bots = compte partagé) |
| `mysql.host/port/user/password/database` | A & B | base du bot (A: 3308, B: 3307 en sandbox Docker) |
| `api.port` | A & B | 3003 (A) / 3002 (B) |
| `api.miniapp_url` / `public_base_url` | A & B | URL HTTPS publique de la mini-app (tunnel/nginx) |
| `api.bot_a_url` | B | URL interne de Bot A (def `http://127.0.0.1:3003`) — handoff + profil |
| `api.kyc_bot_url` | B | lien Telegram du Bot A (écran « pas de carte » → KYC) |
| `api.admin_token` | A | secret pour `/api/admin/*` (enrollments, finalize) |
| `api.test_token` | B | secret pour `/api/test/*` (simulations) |
| `api.require_miniapp_auth` | B | **true en prod** (auth initData ; false = uid falsifiable) |
| `api.max_cards` | B | nb max de cartes par user (def 5) |
| `nova_api.access_key/secret_key/user_uuid/base_url/ws_url` | B | creds NovaBtc (dépôts) |
| `nova_deposits.min/max/fee_percent/fee_percent_interlace/fee_cash/virtual_card_fee` | B | bornes + frais de dépôt |
| `interlace_pool.threshold/max_pool` | B | seuil d'alerte « maître bas » |
| `testing.testing` | B | `true` = sandbox (WS NovaBtc **éteint**) ; `false` = prod |

## 4. Monte la pré-prod (sandbox)
Deux options :

**(a) VPS (recommandé, comme la prod)** → suis **`DEPLOY.md`** : Docker (MySQL/Mongo/Redis
par bot) + seed + venv + systemd + nginx + HTTPS. Reste en `interlace.mode=dev` et
`testing.testing=true`.

**(b) Local (dev rapide)** : `./start_sandbox.sh` dans chaque bot (lance Docker + l'app +
un tunnel HTTPS). Colle l'URL du tunnel dans `params.json` (`api.miniapp_url`).

Dans les deux cas, après le 1er lancement, applique les migrations :
```bash
cd kyc_bot       && ./venv/bin/python config/seed_sandbox.py
cd interlace_bot && ./venv/bin/python config/seed_sandbox.py
```

## 5. Teste de bout en bout (sandbox)
Suis **`DEMO_RUNBOOK.md`** et **`PARCOURS_ET_MESSAGES.md`**. Parcours minimal :
1. Bot A `/start` → mini-app KYC → docs de test Sumsub → KYC PASSED → carte créée → lien.
2. Ouvre le lien → Bot B → carte attribuée + adresse de dépôt dédiée.
3. Recharge : `/api/test/simulate_deposit_v3` (token) avec l'adresse de la carte → crédit + notif.
4. (Achat / OTP : `/api/test/*` de simulation.)

## 6. Passe en PROD
Suis **`PROD_CHECKLIST.md`** (la référence). En résumé :
1. `interlace.mode=prod` + creds Interlace prod (account_id/client_id/secret/binId).
2. `testing.testing=false` (active le WebSocket NovaBtc) + creds NovaBtc prod.
3. Importer les **vraies adresses** USDT-TRC20 du compte NovaBtc dans `pool` (modèle 1
   adresse = 1 carte).
4. **Désactiver `/api/test/*`** (kill-switch) + `require_miniapp_auth=true` + tokens forts.
5. Webhook Interlace → l'URL publique de **Bot A** (`/api/callback`).
6. `bot_b_username` / `kyc_bot_url` = les usernames de **tes** bots de prod.
7. Vérifs : services actifs, WS `WebSocket connection established`, parcours A→Z réel.

## 7. Exploitation courante
- Réaffecter un client à un autre Telegram : `deploy/reassign_user.py` (dry-run puis `--yes`).
- Lister/exporter les enrollments : `deploy/enrollments.py`.
- Surveiller : `journalctl -u nova-kyc -f` / `journalctl -u nova-card -f`.
- Reset bases (tests) : `DELETE` interlace_accounts/cards/topup_requests (+ reset `pool`).

## ⚠️ Pièges connus
- Un **token Telegram ne doit tourner qu'à UN endroit** (sinon `Conflict: terminated by other
  getUpdates`). Ne lance pas le même bot en local ET sur le VPS.
- `bot_b_username` (Bot A) **doit** correspondre au bot dont le **token** tourne sur Bot B,
  sinon le lien pointe vers un bot mort.
- Les **adresses du pool doivent appartenir au compte NovaBtc** écouté, sinon les dépôts
  n'arrivent jamais.
- Compte Interlace **partagé** par les 2 bots → mêmes creds des deux côtés.
