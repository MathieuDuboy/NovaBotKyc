# Nova — Checklist de tests pré-prod (sandbox)

À dérouler **dans l'ordre**. Coche au fur et à mesure. En sandbox : KYC avec les
**documents de test Sumsub**, dépôts/achats via les **endpoints `/api/test/*`**
(token requis). Logs : `journalctl -u nova-kyc -f` et `journalctl -u nova-card -f`.

---

## Phase 0 — Prérequis / boot
- [ ] `systemctl is-active nova-kyc nova-card` → `active` / `active`
- [ ] Migrations passées (`seed_sandbox.py` sur les 2 bots) — colonnes `pool` présentes
- [ ] Bases reset propre (interlace_accounts/cards/topup_requests vidés, `pool` en `free`)
- [ ] Mini-apps KYC + carte se chargent en **HTTPS** (tunnel/nginx OK)
- [ ] Bot A et Bot B ont des **tokens différents** et pollent **sans** `Conflict: terminated by other getUpdates`
- [ ] `pool` contient des adresses `status='free'`
- [ ] `bot_b_username` (Bot A) = le bot dont le token tourne sur Bot B
- [ ] Ton `chat_id` est bien dans `admin_chat_ids`

## Phase 1 — KYC & création de carte (Bot A)
- [ ] `/start` Bot A → la mini-app KYC s'ouvre
- [ ] Âge **< 18 ou > 65** → **bloqué AVANT envoi** (message « 18 à 65 ans »)
- [ ] Soumission valide (docs test Sumsub, âge OK) → statut PENDING (enrollment créé)
- [ ] KYC **PASSED** → carte créée → **1 seul** message « carte prête » + lien `t.me/<BotB>?start=…`
- [ ] KYC **REJECTED** (mauvais docs) → **1 seul** message de refus (pas de doublon)
- [ ] Logs création : **pas de `070010`**, **pas de `100100001`** ; financement maître→sous **+ sweep** OK
- [ ] **Multi-KYC famille** : refaire 2–3 KYC depuis le même compte → 2–3 enrollments + **liens distincts**

## Phase 2 — Réclamation du lien (Bot B)
- [ ] **Créateur** ouvre son lien → choix **Claim / Share** (+ « (as admin) » si admin)
- [ ] **Claim for myself** → « ✅ Your card •••• … is connected! » + solde + bouton Open
- [ ] **I'm sharing it** → « 🔗 Not claimed. Forward the link… »
- [ ] **Receveur** (autre compte Telegram) ouvre un lien → **attribution directe**
- [ ] Rouvrir un lien **déjà réclamé** (autre compte) → « already been used by another account »
- [ ] User **ayant déjà une carte** ouvre un 2e lien → refus « You already have a card account »
- [ ] Token **invalide/expiré** → « Invalid or expired card link »

## Phase 3 — Adresse de dépôt par carte
- [ ] À l'attribution, une **adresse** est liée à la carte (`pool`: `status=used`, `card_id` rempli)
- [ ] Mini-app carte affiche **l'adresse + QR** de cette carte
- [ ] Une 2e carte → une **adresse différente**

## Phase 4 — Recharge / top-up (Bot B)
- [ ] `POST /api/test/simulate_deposit_v3` (token) avec **l'adresse de la carte A** → crédite **CARD A** + message avec le **last4 de A**
- [ ] Montant net = dépôt **− frais** (vérifier le détail dans la réponse / logs)
- [ ] **Idempotence** : rejouer le même `tx_id` → `skip`
- [ ] Dépôt sur **l'adresse de la carte B** → crédite **CARD B** (pas A)
- [ ] Dépôt **hors bornes** (min/max) → message « out of range », pas de crédit

## Phase 5 — Multi-cartes
- [ ] « **+** » → écran **choix réseau** : logos Visa/Mastercard + texte **centré sur 2 lignes**
- [ ] Création OK jusqu'à **5 cartes** ; la **6e** refusée (`card_limit`)
- [ ] **Anti-spam** : marteler « + » / les boutons réseau → **une seule** création (« already in progress »), maître ponctionné **une seule fois**
- [ ] Échec création → le **maître est remboursé** (sweep), statut repart propre
- [ ] **Scroll auto** : cliquer +, Transactions, Top-up → l'écran activé remonte au **centre**
- [ ] Chaque carte garde **son** adresse → recharge ciblée par carte

## Phase 6 — Transactions / 3DS OTP
- [ ] `simulate_auth` achat **validé** → notif « payment » avec last4
- [ ] Achat **refusé** → notif « declined »
- [ ] Achat **en attente** → notif « pending »
- [ ] **3DS OTP** simulé → l'OTP arrive bien à l'user (par carte)
- [ ] Mini-app : la transaction apparaît dans **Transactions**
- [ ] **Freeze / Unfreeze** la carte → badge/état à jour

## Phase 7 — Compte maître / alerte refill
- [ ] `POST /api/test/check_infinity` avec `simulate_balance` **bas** → **alerte admin** Telegram (montant à recharger)
- [ ] Solde maître **suffisant** → **pas** d'alerte
- [ ] (Rappel : le refill auto depuis une bourse **n'existe pas** — alerte manuelle uniquement)

## Phase 8 — Admin / exploitation
- [ ] `reassign_user.py <old> <new>` (dry-run) → plan correct, **aucun** changement
- [ ] `reassign_user.py <old> <new> --yes` → bascule ; le **nouveau** compte `/start` → reconnecte la carte
- [ ] Garde-fous : cible **non vierge** → refus ; source **vide** → refus
- [ ] `enrollments.py` → export **CSV** des enrollments + liens

## Phase 9 — Sécurité / robustesse
- [ ] `/api/test/*` **sans token** → **403**
- [ ] `require_miniapp_auth=true` : appel mini-app **sans initData valide** → refusé
- [ ] **Pool épuisé** (toutes adresses `used`) → log « POOL ÉPUISÉ » (carte créée quand même, adresse assignée plus tard via `/api/card`)
- [ ] `/start` **sans carte** → écran « Verify my identity » → ouvre le bot KYC
- [ ] `/start` **avec carte** → reconnexion (carte + solde)
- [ ] Reset des bases puis re-test rapide d'un parcours complet (non-régression)

---

### Parcours « golden path » minimal (smoke test rapide)
1. KYC (âge OK, docs test) → PASSED → lien.
2. Ouvrir le lien sur Bot B → carte connectée + adresse dédiée.
3. `simulate_deposit_v3` sur l'adresse → carte créditée + message last4.
4. `simulate_auth` → notif d'achat.
✅ Si ces 4 étapes passent, le cœur fonctionne.
