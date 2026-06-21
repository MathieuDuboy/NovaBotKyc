# Nova — Prise en main TOTALE par le client (autonomie complète)

Objectif : le client fait tourner **tout sur SES propres comptes/infra**, sans aucune
dépendance à l'opérateur initial (ni son VPS, ni son ngrok, ni son Google Sheets, ni ses
bots/comptes). Suivre **dans l'ordre**. (Détails techniques : `ONBOARDING.md` / `DEPLOY.md`
/ `PROD_CHECKLIST.md`.)

> ⚠️ À savoir : les **cartes déjà créées sur le compte Interlace de l'opérateur** ne se
> transfèrent PAS automatiquement vers le compte du client. En autonomie, le client
> **repart sur SON compte Interlace** (nouvelles cartes). Idem NovaBtc.

---

## PHASE 1 — Comptes & accès à créer (le client, en amont)
- [ ] **1.1 — Un VPS** à lui (Debian/Ubuntu, root SSH).
- [ ] **1.2 — 2 bots Telegram** via @BotFather : « Bot A (KYC) » + « Bot B (carte) » →
      note les **tokens** + **@usernames**.
- [ ] **1.3 — Son chat_id** Telegram (via @userinfobot) = l'**admin**.
- [ ] **1.4 — Un compte Interlace** (à SON nom) : `client_id`, `client_secret`,
      `account_id` (compte maître), `base_url`, et les **binId** des BIN. (Contrat Interlace
      au nom du client — étape business.)
- [ ] **1.5 — Un compte NovaBtc** : `access_key`, `secret_key`, `user_uuid`, et la
      **génération d'adresses** de dépôt USDT-TRC20 (il en faut un stock, ex. 5000).
- [ ] **1.6 — Exposition publique** : un **nom de domaine** (recommandé) OU un compte
      **ngrok** à lui (authtoken + domaine réservé). → voir Phase 5.
- [ ] **1.7 — (Optionnel) Google Sheets** : un projet Google Cloud + **service account**
      (fichier `credentials.json`) + un **Spreadsheet** partagé avec ce compte de service.
      Sinon : laisser vide → désactivé (non bloquant). **Le client GÈRE ses codes parrainage + voit la liste users via la feuille** : voir `REFERRALS_AND_USERS_SHEET.md` (outils `sync_referrals.py` / `export_users.py`).
- [ ] **1.8 — Accès au code** : propriété/accès des 2 repos Git transférés au client
      (`NovaBotKyc` + `NovaBotCardSandBoxInter`).

## PHASE 2 — Préparer le VPS
- [ ] **2.1** Installer : `docker` + `docker compose`, `git`, `python3-venv`, `nginx`, `certbot`.
- [ ] **2.2** Cloner les **2 repos** côte à côte :
      ```bash
      mkdir -p /opt/nova && cd /opt/nova
      git clone <repo_BotA> kyc_bot
      git clone <repo_BotB> interlace_bot
      ```
- [ ] **2.3** venv + dépendances par bot : `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`.

## PHASE 3 — Configurer (SES secrets)
- [ ] **3.1** Dans **chaque** bot : `cp config/params.example.json config/params.json`.
- [ ] **3.2** Remplir `params.json` avec **SES** valeurs (cf. tableau dans `ONBOARDING.md` §3) :
      - `telegram.bot_token` (A & B) + `telegram.bot_b_username` (A) + `telegram.admin_chat_ids`.
      - `interlace.<mode>.client_id/client_secret/account_id/base_url/bin` (**identiques** A & B).
      - `mysql.*` (host/port/user/password/database).
      - `nova_api.access_key/secret_key/user_uuid/base_url/ws_url` (B).
      - `api.miniapp_url`/`public_base_url` (URLs publiques — Phase 5), `api.kyc_bot_url` (B),
        `api.admin_token` (A), `api.test_token` (B), `api.require_miniapp_auth`.
      - `nova_deposits.*` (frais/bornes), `interlace_pool.*` (seuils), `testing.testing`.
      - (Optionnel) `google_sheets.spreadsheet_id` + chemin `credentials.json`.
- [ ] **3.3** `params.json` est **gitignoré** → ne JAMAIS le committer.

## PHASE 4 — Infra + déploiement
- [ ] **4.1** Démarrer l'infra Docker (MySQL/Mongo/Redis) de chaque bot (cf. `DEPLOY.md`).
- [ ] **4.2** Migrations / seed : `./venv/bin/python config/seed_sandbox.py` (les 2 bots).
- [ ] **4.3** systemd : installer `nova-kyc.service` + `nova-card.service`, `enable --now`.
- [ ] **4.4** Importer les **adresses NovaBtc** dans `pool` (modèle 1 adresse = 1 carte).

## PHASE 5 — Exposition publique (remplace ton ngrok)
**Option A — Domaine + nginx + HTTPS (recommandé, zéro dépendance ngrok) :**
- [ ] DNS du domaine → IP du VPS.
- [ ] nginx (reverse proxy 3003/3002) + Let's Encrypt (`certbot`) → URLs **stables** HTTPS.
- [ ] Renseigner ces URLs dans `params.json` (`api.miniapp_url`/`public_base_url`).

**Option B — ngrok du client :**
- [ ] Son **authtoken** ngrok + domaine réservé ; lancer l'agent ; mettre l'URL dans params.
- [ ] ⚠️ ngrok **free** affiche une page d'avertissement qui casse les mini-apps Telegram →
      prévoir un **plan payant** ou préférer l'Option A.

## PHASE 6 — Branchements externes (avec SES comptes)
- [ ] **6.1 — Webhook Interlace** (dashboard du client) → URL publique de **Bot A** `/api/callback`.
- [ ] **6.2 — BotFather** : pour chaque bot, régler le **Menu / WebApp URL** = mini-app publique.
- [ ] **6.3 — `bot_b_username`** (Bot A) = l'@username du bot dont le **token** tourne sur Bot B.
- [ ] **6.4 — NovaBtc** : confirmer que les adresses du `pool` appartiennent bien à SON compte.

## PHASE 7 — Passage en PROD (cf. `PROD_CHECKLIST.md`)
- [ ] `interlace.mode = prod` + creds Interlace prod.
- [ ] `testing.testing = false` (active le WebSocket NovaBtc) + creds NovaBtc prod.
- [ ] **Désactiver `/api/test/*`** (kill-switch) + `require_miniapp_auth = true` + tokens forts.
- [ ] Vérifs : services actifs, `WebSocket connection established`, webhook reçu.

## PHASE 8 — Vérification (cf. `PREPROD_TESTS.md` + `SCENARIO_TEST.md`)
- [ ] Dérouler le **scénario A→Z** (KYC → carte → recharge → achat refusé/validé → OTP → multi-cartes…).
- [ ] Smoke test minimal OK (KYC→carte→dépôt→achat).

## PHASE 9 — Coupure des dépendances (transfert de propriété)
- [ ] Propriété des **repos Git** transférée au client (l'opérateur retire ses accès).
- [ ] Le client est **seul détenteur** : VPS, domaine/ngrok, bots BotFather, compte Interlace,
      compte NovaBtc, service account Google, tous les secrets de `params.json`.
- [ ] L'opérateur **supprime** ses propres creds de toute config et **arrête** son VPS/ngrok/Sheet.
- [ ] Le client **change tous les secrets** par sécurité (rotation : tokens bots, admin_token,
      test_token, creds Interlace/NovaBtc, mots de passe MySQL).

---

### Récap des dépendances à éliminer
| Dépendance actuelle (opérateur) | Remplacée par (client) |
|---|---|
| VPS de l'opérateur | VPS du client |
| ngrok de l'opérateur | **Domaine + nginx + HTTPS** (ou ngrok du client) |
| Google Sheets de l'opérateur | Service account + Spreadsheet du client (ou désactivé) |
| Bots Telegram de l'opérateur | Bots BotFather du client |
| Compte Interlace de l'opérateur | Compte Interlace du client (cartes repartent de zéro) |
| Compte NovaBtc de l'opérateur | Compte + adresses NovaBtc du client |
| Repos Git de l'opérateur | Repos transférés/forkés au client |
| Secrets dans `params.json` | Tous remplacés par ceux du client |
