# Nova — Parcours utilisateur & messages

Référence des **parcours possibles** (création KYC, attribution de carte) et des
**textes exacts** envoyés par les bots. Concerne les 2 bots :

- **Bot A** (KYC) = `@novabotcardtestsandboxinterbot`'s companion — onboarding,
  vérification d'identité, création de la carte, génération du lien.
- **Bot B** (carte) = `@novabotcardtestsandboxinterbot` — réception du lien,
  attribution de la carte, utilisation (solde, recharge…).

## Modèle (règles de base)
- **Tout le monde** peut créer un KYC (modèle « famille ») → chaque KYC validé =
  une carte + un **lien de handoff** à distribuer.
- **1 seul cardholder par compte Telegram** : impossible de réclamer une 2ᵉ carte.
- **Lien à usage unique** : le 1ᵉʳ qui le réclame le prend ; ensuite il est verrouillé.
- Le **créateur** d'un lien a le choix *réclamer / partager* ; tout autre receveur
  est attribué **directement**.
- Âge requis : **18–65 ans** (bloqué dans le formulaire ; Interlace refuse hors limites).
- Jusqu'à **5 cartes** par cardholder ensuite (sur Bot B).

---

## 🅰️ BOT A — Création du KYC

```
Formulaire KYC (n'importe qui)         → enrollment créé
  âge 18-65, vrais docs                   USER_ID = vide
                                          created_by = celui qui remplit
        │
        ▼  Interlace vérifie (webhook + poll de secours)
   ┌────────────┬─────────────┐
 PASSED      REJECTED
   │            │
 carte créée  notif refus
 + lien        au créateur
 au créateur
```

Le **créateur** (celui qui a rempli le formulaire) reçoit (toujours en anglais) :

| Résultat | Message |
|---|---|
| **PASSED** | `✅ Verified — your card is ready (•••• 1234) (balance 0, ready to top up).`<br>`👉 Open your card to view balance & withdraw: https://t.me/<bot_carte>?start=<TOKEN>` |
| **REJECTED** (enrollment) | `❌ KYC refusé pour <email> (<raison>)` |
| **REJECTED** (carte déjà réclamée par un user) | `❌ Your verification couldn't be approved (<raison>). You can try again with /start.` (langue de l'user) |

> Un seul message par décision (garde-fou d'idempotence : webhook + poll ne notifient
> qu'une fois). Plus d'erreurs `070010` / `100100001` (financement carte + frais fiabilisé).

---

## 🅱️ BOT B — Ouverture d'un lien `?start=<token>`

Le comportement dépend de **qui** clique :

### 1. Tu as déjà une carte (1 cardholder max)
> ⚠️ You already have a card account. This link is for someone else — forward it to them.

### 2. Tu es le CRÉATEUR du lien (`created_by` = toi)
On te demande quoi faire :
> This is a card link YOU created **(as admin)**. Claim it for your account, or just share it (it will be assigned to the first person who opens it).
> What do you want?
>
> `[✅ Claim for myself]` `[🔗 I'm just sharing it]`

- *« (as admin) »* s'affiche **uniquement** si tu es réellement admin. Un créateur
  non-admin voit : *« This is a card link YOU created. »*
- **✅ Claim for myself** → `⏳ Claiming this card for your account…` puis le message
  « carte connectée » (voir §3).
- **🔗 I'm just sharing it** →
  > 🔗 Not claimed. Forward the link to your client — they'll be assigned the card when they open it.

### 3. Tu as REÇU le lien (pas créateur, pas encore de carte) → attribution directe
> ✅ Your card •••• 1234 is connected!
> 💳 Card balance: 0.00 USD  👛 Wallet: 0.00 USD
>
> `[💳 Open my card]`

### 4. Le lien a déjà été réclamé par quelqu'un d'autre
> ⚠️ This card link has already been used by another account.

### 5. Token invalide / expiré (depuis le bouton Claim)
> ⚠️ Invalid or expired card link.

---

## 🅱️ BOT B — `/start` SANS lien

| Cas | Message |
|---|---|
| Carte existante | Reconnexion → message « carte connectée » (§3) + `[💳 Open my card]` |
| Pas de carte | `No card available yet.`<br>`You haven't completed identity verification (KYC) yet. Tap below to verify your identity and get your Nova card 👇`<br>`[🪪 Verify my identity]` → ouvre le bot KYC |

---

## Tableau récapitulatif des cas Bot B

| Qui clique | Condition | Résultat | Message clé |
|---|---|---|---|
| N'importe qui | a déjà une carte | refus | « You already have a card account… » |
| Créateur | pas de carte | choix | « This is a card link YOU created (as admin)… » + 2 boutons |
| Créateur → Claim | — | attribution | « Your card •••• … is connected! » |
| Créateur → Share | — | rien réclamé | « Not claimed. Forward the link… » |
| Receveur | pas de carte, lien libre | attribution directe | « Your card •••• … is connected! » |
| Receveur | lien déjà pris | refus | « This card link has already been used… » |
| N'importe qui | token invalide | erreur | « Invalid or expired card link. » |
| `/start` sans lien | a une carte | reconnexion | « Your card •••• … is connected! » |
| `/start` sans lien | pas de carte | redirection KYC | « No card available yet… Verify my identity » |

---

*Doc générée pour l'état du code : Bot A `15939a5`, Bot B `5667d69` (modèle famille,
1 cardholder/user, lien à usage unique, âge 18–65).*
