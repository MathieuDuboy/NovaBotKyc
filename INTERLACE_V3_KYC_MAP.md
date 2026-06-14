# Interlace v3 — Cartographie du flux KYC + carte (mode CONSUMER / gateway)

> Méthode retenue : **A — collecte directe** (on uploade pièce + selfie nous-mêmes,
> pas de SumSub). Collecte via **formulaire unique de la mini app**.
> Base API sandbox : `https://api-sandbox.interlace.money`.
> ⚠️ Les schémas de réponse exacts (champs renvoyés) + quelques enums sont à
> confirmer en test live pendant le dev (la doc publique ne les détaille pas tous).

## Auth (à faire une fois, token 24h)
1. `GET /open-api/oauth/authorize?clientId=<id>` → `{ code }`
2. `POST /open-api/oauth/access-token` `{clientId, clientSecret, code}` → `{accessToken, refreshToken, expiresIn:86400}`
3. Header sur chaque appel : **`x-access-token: <accessToken>`**

## Séquence end-to-end (par utilisateur qui veut une carte)

| # | Étape | Endpoint | Déclenché par |
|---|---|---|---|
| 1 | Créer le sous-compte | `POST /open-api/v1/accounts/register` | backend (après submit formulaire) |
| 2 | Upload pièce + selfie | `POST /open-api/v3/files/upload` | backend (images de la mini app) |
| 3 | Soumettre le KYC | `POST /open-api/v3/accounts/{accountId}/kyc` | backend |
| 4 | ⏳ Attendre le résultat | webhook **`KYC.UPDATED`** | Interlace → notre webhook |
| 5 | (si approuvé) Initialiser le compte | `POST /open-api/v2/accounts/{id}/initialization` | backend |
| 6 | Créer le cardholder | `POST /open-api/v2/cards/{accountId}/cardholder` | backend |
| 7 | Créer la carte | `POST /open-api/v2/cards` (`type:PrepaidCard`) | backend |
| 8 | Carte prête | webhook **`CARD.CREATED`** | Interlace → notre webhook |

## Détail des endpoints

### 1) register — `POST /open-api/v1/accounts/register`
- Requis : `email`, `name`. Optionnels : `phone` (+indicatif), `parentAccountId`.
- Renvoie : un **accountId** (le sous-compte de l'utilisateur). *(schéma exact à confirmer live)*

### 2) upload files — `POST /open-api/v3/files/upload` (multipart)
- Champs : `files` (tableau de fichiers, requis), `accountId` (requis).
- Renvoie : des **fileId** → réutilisés comme `idFrontId`, `selfie`, `idBackId`. *(format réponse à confirmer live)*

### 3) submit KYC — `POST /open-api/v3/accounts/{accountId}/kyc`
- **Requis** : `firstName, lastName, dateOfBirth, gender, nationality, nationalId, idType, issueDate, expiryDate, address(obj), idFrontId, selfie, phoneNumber, phoneCountryCode, sourceType="api"`
- **Optionnels** : `idBackId` (inutile pour passeport), `occupation, annualSalary, accountPurpose, expectedMonthlyVolume, ssn`
- `idFrontId` / `selfie` = fileId de l'étape 2.

### 5) initialize — `POST /open-api/v2/accounts/{id}/initialization`
- Après KYC approuvé → crée le compte Infinity / wallets. *(corps exact à confirmer)*

### 6) create cardholder (consumer) — `POST /open-api/v2/cards/{accountId}/cardholder`
- **Requis** : `cardholderTier` (consumer → à confirmer la valeur : `CONSUMER_GATEWAY`/`CONSUMER_MOR`), `cardholderRole` (`DEPARTMENT|PROJECT|AUTHORIZED_REPRESENTATIVE`), `firstName, lastName, email, phoneNumber, phoneCountryCode, nationality, dob, address`
- Optionnel : `cardholderLabel`, `profileId` (MoR only). Renvoie : **cardholderId**.

### 7) create card — `POST /open-api/v2/cards`
- **Requis** : `type:"PrepaidCard"`, `bin`, `batchCount`, `useType`, `cardholderId`
- Optionnels : `accountId, cost` (recharge initiale), `cardMode:"VirtualCard"`, `label, clientTransactionId, phoneCode, phone, ssn`
- Renvoie : **cardId** + statut. *(à confirmer live)*

### Lecture
- BIN dispo : `GET /open-api/v3/card/bins?accountId=` (binId = champ `id`) — **vérifié live** (5 BIN Master/Visa USD).
- Statut KYB/KYC : `GET /open-api/v3/accounts/cdd/detail/{accountId}` — **vérifié live** (`kyc.status`, `kyb[].status` = PASSED).

## Webhooks (réception des statuts) — **vérifié via doc**
- Interlace POST sur notre URL ; on répond `{"received": true}` **sous 5s** ; idempotent ; retries (10s→2h, 16x).
- **Signature** : header `Signature` = Base64( **HMAC-SHA256(`resource`, clientSecret)** ), + `Timestamp`, `Signature-Method: HMAC-SHA256`.
- **Payload** : `{ id, eventType, code, message, resource (JSON stringifié), apiVersion, createTime }`.
- **Events utiles pour nous** :
  - `ACCOUNT.REGISTERED`
  - **`KYC.UPDATED`** (résultat KYC) / `KYB.UPDATED`
  - **`CARDHOLDER.CREATED` / `CARDHOLDER.UPDATED`**
  - **`CARD.CREATED`** / `CARD.UPDATED` / `CARD.DELETED`
  - `CARD_TRANSACTION.CREATED` / `CARD_TRANSACTION.UPDATED`
  - `CARD.3DS.OTP`

## Ce que le formulaire mini app doit collecter (mappé sur le KYC)
Texte : `firstName, lastName, email, phoneCountryCode, phoneNumber, dateOfBirth, gender,
nationality, idType, nationalId (n° pièce), issueDate, expiryDate, address{line1, city, country, postalCode}`.
Fichiers (caméra/upload) : **photo pièce recto** (`idFrontId`), **selfie** (`selfie`),
+ **verso** (`idBackId`) si carte d'identité (pas passeport).

## À confirmer en test live pendant le dev
- Schémas de réponse exacts (register → accountId ; upload → fileId ; card → cardId).
- Valeur `cardholderTier` consommateur + où se règle `programType` (register/initialize ?).
- Enums `gender`, `idType` ; ordre exact register→KYC→initialize ; si `initialize` avant ou après KYC approuvé.

## Implémentation — répartition
- **Bot** : langue + code parrainage + bouton « obtenir ma carte » (ouvre mini app). Affiche « vérif en cours » / « carte prête » / « refusé » (déclenché par webhook).
- **Mini app** : formulaire unique (champs + upload pièce + selfie) → POST vers notre backend.
- **Backend** : register → upload → submit KYC → (webhook KYC.UPDATED) → initialize → cardholder → card. Vérif signature webhook HMAC.
- **Base** : par user → `account_id` (sous-compte), `cardholder_id`, `card_id`, `kyc_status`, mapping `account_id → user` (pour router le webhook).
