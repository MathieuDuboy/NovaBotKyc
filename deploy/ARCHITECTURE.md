# Nova — Architecture (pour reprendre le projet de A à Z)

> **Commence ici** si tu reprends le projet. Cette page donne la vue d'ensemble,
> le modèle de données et les flux. Voir l'INDEX en bas pour les guides détaillés.

## 1. Vue d'ensemble : 2 bots, 2 repos
Le produit = un service de **cartes prépayées** piloté par Telegram, sur 2 bots
**séparés** (2 repos, 2 bases, 2 services) qui partagent **un même compte Interlace**.

| | Bot A — KYC | Bot B — Carte |
|---|---|---|
| Repo | `NovaBotKyc` (dossier `kyc_bot/`) | `NovaBotCardSandBoxInter` (dossier `interlace_bot/`) |
| Rôle | Onboarding, vérification d'identité (KYC), **création de la carte**, génération du **lien de handoff** | **Usage** de la carte : solde, recharge, transactions, freeze |
| Port API | 3003 | 3002 |
| Base MySQL | `nova` @ `:3308` | `nova` @ `:3307` |
| Service systemd | `nova-kyc` | `nova-card` |

```
   Client Telegram
        │  /start + mini-app KYC
        ▼
   ┌─────────┐   crée sous-compte + KYC + CARTE (Interlace)         ┌──────────────┐
   │  BOT A  │ ───────────────────────────────────────────────────▶│  Interlace   │
   │  (KYC)  │   puis génère le lien t.me/<BotB>?start=<token>      │ (cartes/KYC) │
   └────┬────┘                                                      └──────┬───────┘
        │ lien de handoff                                                  │ webhook KYC
        ▼                                                                  ▼ (validation)
   Client ouvre le lien                                            (reçu par Bot A /api/callback)
        ▼
   ┌─────────┐   réclame la carte, l'utilise (solde/recharge/tx)   ┌──────────────┐
   │  BOT B  │ ◀───── dépôts USDT (WebSocket) ──────────────────── │   NovaBtc    │
   │ (carte) │        crédite la bonne carte via Interlace          │ (dépôts TRC20)│
   └─────────┘                                                      └──────────────┘
```

## 2. Composants externes
- **Interlace** (`api.interlace.money`) : émetteur des cartes. OAuth2 (client_id/secret →
  token), API v3 GATEWAY. Gère sous-comptes, cardholders, cartes prépayées, wallets,
  transferts. **Un seul compte maître** ; chaque client = un **sous-compte** + 1 cardholder.
- **NovaBtc** (`api.novabtc.io`, doc `docs.novabtc.io`) : dépôts USDT-TRC20. Auth
  access_key/secret (HMAC). On écoute un **WebSocket** (`/zsu/ws/v1`, event `deposit`) ;
  génération d'adresses via `POST /api/v2/deposit_addresses`. → Bot B uniquement.
- **Telegram** : 2 bots (BotFather) + mini-apps (WebApp, auth `initData` HMAC).

## 3. Modèle de données (tables clés)
**Bot A (`nova:3308`)**
- `interlace_accounts` : 1 ligne par **enrollment**. `USER_ID` (chat_id, NULL tant que non
  réclamé), `created_by` (qui a fait le KYC), `account_id`, `cardholder_id`, `card_id`,
  `handoff_token`, `kyc_status` (NONE/PENDING/PROCESSING/PASSED/REJECTED), `profile_json`.

**Bot B (`nova:3307`)**
- `interlace_accounts` : ancre du client (1/user) : `USER_ID`, `account_id`, `cardholder_id`,
  `card_id` (carte primaire), `profile_json`, `selected_card_id`.
- `cards` : **N cartes** par user : `USER_ID`, `card_id`, `cardholder_id`, `card_number`,
  `bin`, `network`, `is_primary`.
- `topup_requests` : historique des dépôts (idempotence par `tx_id`).
- `pool` : **adresses de dépôt**. Modèle **1 adresse = 1 carte** : `nova_address`, `status`
  (free/used), `USER_ID`, `card_id`, `cardholder_id`, `assigned_at`.

> `USER_ID` = chat_id Telegram = mapping LOCAL. Interlace ne le connaît pas → pour changer
> le Telegram d'un client, voir `reassign_user.py` (re-mappe les 2 bases, Interlace inchangé).

## 4. Les flux clés

### A. KYC → carte (Bot A)
1. Mini-app KYC (`/kyc`) → `POST /api/kyc_submit` → crée un **sous-compte** Interlace +
   upload pièce/selfie + soumet le KYC (statut PENDING). Âge requis **18–65**.
2. Validation : **webhook** Interlace (`/api/callback`, confirmé via `get_cdd_detail`) **ou**
   `poll_and_finalize` (fallback). **Garde-fou idempotence** : claim atomique `PROCESSING`
   → un seul des deux chemins agit (pas de double création / double notif).
3. Sur PASSED → `complete_after_kyc_passed` : crée le **cardholder** + finance le sous-compte
   depuis le **maître** (montant carte **+ marge frais d'émission**), crée la **carte
   prépayée**, la vide, **sweep** le surplus vers le maître. → génère le **lien de handoff**
   `t.me/<bot_b_username>?start=<token>` envoyé au créateur (anglais).

### B. Réclamation de la carte (Bot B)
Ouverture du lien `?start=<token>` (`handle_card_link`) :
- **1 cardholder par user** : si déjà une carte → refus.
- Si **créateur** du lien → choix *Claim / Share* (« (as admin) » si admin). Si **receveur**
  → attribution directe. (cf. `PARCOURS_ET_MESSAGES.md` pour tous les textes.)
- À l'attribution : persiste la carte + **assigne une adresse de dépôt dédiée** (claim
  atomique dans `pool`).

### C. Recharge (Bot B) — modèle 1 adresse = 1 carte
1. Le client dépose des USDT-TRC20 sur **l'adresse de SA carte** (affichée dans la mini-app).
2. NovaBtc confirme → event WebSocket `deposit` (status `done`) → `credit_deposit`.
3. **Routage par adresse → carte EXACTE** (`pool.card_id`). Frais déduits, puis virement
   **maître → sous-compte → carte**. Notif au client avec le **last4** de la bonne carte.
   Idempotent par `tx_id`.
4. Après crédit : `check_master_infinity_threshold` **ALERTE** l'admin si le maître est bas
   (⚠️ **pas** de refill auto depuis une bourse — manuel pour l'instant).

## 5. Garde-fous / sécurité (déjà en place)
- KYC : claim `PROCESSING` atomique (1 notif, pas de double création / `070010` / `100100001`).
- Création carte : **verrou anti-spam** par user (pas de ponctions multiples du maître).
- 1 **cardholder par user** ; lien de handoff **à usage unique** ; adresse de dépôt **à usage
  unique** (1/carte) ; âge **18–65** ; endpoints `/api/test/*` à **désactiver en prod**
  (kill-switch) ; `require_miniapp_auth=true` en prod ; secrets dans `params.json` (gitignoré).

## 6. Outils d'exploitation (admin)
- `deploy/enrollments.py` : liste/export des enrollments (CSV).
- `deploy/reassign_user.py` : réaffecter un compte/cartes vers un autre user_id Telegram.
- Import du `pool` (5000 adresses) : `INSERT ... INTO pool (nova_address,status) VALUES (..,'free')`.
- Reset des bases : `DELETE` sur interlace_accounts/cards/topup_requests (+ reset `pool`).

## 7. INDEX de la documentation
| Doc | Contenu |
|---|---|
| **`ARCHITECTURE.md`** (ce fichier) | Vue d'ensemble, modèle de données, flux, garde-fous |
| **`ONBOARDING.md`** | Reprendre le projet : tes propres bots, creds, config, pré-prod → prod |
| `DEPLOY.md` | Déploiement VPS détaillé (Docker, systemd, nginx, HTTPS) — en sandbox |
| `PROD_CHECKLIST.md` | Passage en PROD (creds réels Interlace/NovaBtc, kill-switch, pool) |
| `PARCOURS_ET_MESSAGES.md` | Tous les parcours utilisateur + textes exacts des messages |
| `PREPROD_TESTS.md` | **Checklist ordonnée de tous les scénarios à tester** en pré-prod |
| `SANDBOX_COMMANDS.md` | **Mémo de commandes** (curl `/api/test/*`, logs, lookup client) pour les tests live |
| `DEMO_RUNBOOK.md` | Scénario de démo / test de bout en bout |
| `INTERLACE_V3_KYC_MAP.md` (racine repo) | Mapping du formulaire KYC vers l'API Interlace v3 |
