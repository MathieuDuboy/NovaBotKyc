"""
Orchestration du flux KYC GATEWAY consumer (Interlace v3).

Parcours (doc gateway-consumer-use), validé live pour la moitié haute :
  ÉTAPE 1 — submit_enrollment_kyc(...)  (à l'envoi du formulaire mini app) :
      2.1 register sous-compte (sous-marchand)  -> sub_id  [VALIDÉ live]
      upload pièce+selfie sur le sous-compte                [VALIDÉ live]
      2.2 submit KYC du sous-compte -> caseId, PENDING       [VALIDÉ live]
      (le KYC part en revue ; la suite arrive par webhook KYC.UPDATED)
  ÉTAPE 2 — complete_after_kyc_passed(account_id)  (sur webhook PASSED) :
      5  create_cardholder (sur le sous-compte, tier CONSUMER)
      6  create_prepaid_card -> persiste la carte
      ⚠️ À VALIDER live : exige un sous-compte au statut KYC PASSED. Aujourd'hui
      bloqué en sandbox (images bidon -> CANCELED ; simulate/kyc/review -> 902).

Routage webhook : par `account_id` du sous-compte (et non plus cardholder_id).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

import config
from interlace_v3 import InterlaceV3
from services.mysql_service import mysql_client
from telegram_bot.messaging import telegram_messaging
from utils.logger import logger

# ── BINs retenus (tous USD -> adresse US requise). value = binId Interlace ────
# ⚠️ Pour une carte PRÉPAYÉE il faut le binId de "type 1" (le type 0 -> erreur
# 070033 "card type invalid"). Validé live : ...4275 (type1) accepté par prepaid-card.
BIN_VISA_49387519 = "1833348583382454275"   # Visa, 3DS, carte physique (type 1 = prepaid)
BIN_MC_537100 = "1939632604887552001"        # Mastercard, 3DS (type 1 = prepaid)
DEFAULT_BIN_ID = BIN_MC_537100   # Bot A crée TOUJOURS la 1ère carte en 537100
# numéro BIN -> binId (les 2 produits proposés au client)
AVAILABLE_BINS = {"49387519": BIN_VISA_49387519, "537100": BIN_MC_537100}
# pays (ISO-2) -> binId (pas d'EUR dispo : tout retombe sur le défaut US)
REGION_BINS = {"US": DEFAULT_BIN_ID}

# Montant (USD) chargé sur la carte à sa création (10 + frais), PUIS retiré pour
# laisser la carte prête et à 0 (activation). Transféré maître -> sous-compte.
CARD_INITIAL_AMOUNT = 10

# Bot B (utilisation de la carte) — username Telegram (sans @) pour le lien de handoff.
# ⚠️ À REMPLACER par le vrai username du Bot B.
BOT_B_USERNAME = getattr(config, "BOT_B_USERNAME", None) or "novabotcardtestsandboxinterbot"


def _bin_for(profile: Dict[str, Any], bin_id: Optional[str]) -> str:
    """Choisit le binId : explicite > choix produit (profile['bin']) > pays > défaut."""
    if bin_id:
        return bin_id
    sel = str(profile.get("bin") or "")
    if sel in AVAILABLE_BINS:
        return AVAILABLE_BINS[sel]
    if sel:  # déjà un binId complet
        return sel
    country = (profile.get("address") or {}).get("country", "")
    return REGION_BINS.get(str(country).upper(), DEFAULT_BIN_ID)


# Statuts KYC stockés (alignés sur les events webhook KYC.UPDATED)
KYC_PENDING = "PENDING"
KYC_PASSED = "PASSED"
KYC_REJECTED = "REJECTED"


def _client() -> InterlaceV3:
    return InterlaceV3.from_params("config/params.json", mode=config.INTERLACE_MODE)


async def _notify(user_id, message: str) -> None:
    """Notifie l'utilisateur Telegram (best-effort, ne casse pas le flux)."""
    try:
        await telegram_messaging.send_card_notification(str(user_id), message)
    except Exception as e:
        logger.error(f"[interlace-kyc] notif user={user_id} échec: {e}")


# Messages du bot localisés (EN/FR/RU) — placeholders {extra}/{reason} optionnels.
MSGS = {
    "submitted": {
        "en": "✅ Your verification has been submitted. We're reviewing it — you'll be notified here shortly.",
        "fr": "✅ Ta vérification a bien été envoyée. On l'examine — tu seras notifié ici très vite.",
        "ru": "✅ Ваша проверка отправлена. Мы её проверяем — уведомление придёт сюда скоро.",
    },
    "passed": {
        "en": "✅ Your identity is verified and your card is ready{extra}! Open the app to view it.",
        "fr": "✅ Ta vérification est validée et ta carte est prête{extra} ! Ouvre l'application pour la consulter.",
        "ru": "✅ Личность подтверждена, карта готова{extra}! Откройте приложение, чтобы посмотреть.",
    },
    "ready": {
        "en": "✅ Verified — your card is ready{extra} (balance 0, ready to top up).\n👉 Open your card to view balance & withdraw: {link}",
        "fr": "✅ Vérifié — ta carte est prête{extra} (solde 0, prête à être rechargée).\n👉 Ouvre ta carte pour voir le solde & retirer : {link}",
        "ru": "✅ Подтверждено — карта готова{extra} (баланс 0, можно пополнять).\n👉 Откройте карту для баланса и вывода: {link}",
    },
    "rejected": {
        "en": "❌ Your verification couldn't be approved{reason}. You can try again with /start.",
        "fr": "❌ Ta vérification n'a pas pu être validée{reason}. Tu peux réessayer avec /start.",
        "ru": "❌ Проверка не пройдена{reason}. Можно повторить через /start.",
    },
}


def _msg(key: str, lang: Optional[str], **kw) -> str:
    d = MSGS[key]
    return d.get((lang or "en").split("-")[0].lower(), d["en"]).format(**kw)


async def _user_lang(user_id: int) -> str:
    """Langue choisie par l'user, stockée dans profile_json à la soumission."""
    acc = await mysql_client.get_interlace_account(user_id) or {}
    try:
        return json.loads(acc.get("profile_json") or "{}").get("lang") or "en"
    except Exception:
        return "en"


# ── helpers d'extraction défensifs ────────────────────────────────────────────
def _file_ids(data: Any) -> List[str]:
    if isinstance(data, list):
        return [d.get("id") or d.get("fileId") for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        lst = data.get("list") or data.get("files") or data.get("data")
        if isinstance(lst, list):
            return [d.get("id") or d.get("fileId") for d in lst if isinstance(d, dict)]
        single = data.get("id") or data.get("fileId")
        return [single] if single else []
    return []


def _extract_card(data: Any) -> Tuple[Optional[str], Optional[str]]:
    row = None
    if isinstance(data, list) and data:
        row = data[0]
    elif isinstance(data, dict):
        lst = data.get("list") or data.get("cards")
        row = (lst[0] if isinstance(lst, list) and lst else data)
    if isinstance(row, dict):
        return (row.get("id") or row.get("cardId"),
                row.get("number") or row.get("cardNo") or row.get("cardNumber"))
    return (None, None)


def _norm_gender(v: str) -> str:
    return "F" if str(v or "").strip().upper() in ("F", "FEMALE", "FEMME") else "M"


def _clean_state(s: Optional[str]) -> str:
    """L'API n'accepte que lettres/chiffres/espaces (ex. 'Gironde', 'NY').
    On remplace tout le reste (tirets, accents non gérés, ponctuation) par un espace.
    PAS de troncature à 2 car. (US=2 lettres, mais FR='Gironde' etc.)."""
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", (s or "")).strip()
    return re.sub(r"\s+", " ", s)


def _norm_account_kyc(p: Dict[str, Any]) -> Dict[str, Any]:
    """Mappe le formulaire mini app -> payload submit_account_kyc (Gateway).
    N'inclut PAS les fileId (ajoutés après l'upload). ssn requis si adresse US."""
    a = p.get("address") or {}
    country = (a.get("country") or "").upper()
    kyc: Dict[str, Any] = {
        "firstName": p["firstName"], "lastName": p["lastName"],
        "dateOfBirth": p.get("dateOfBirth") or p.get("dob"),
        "gender": _norm_gender(p.get("gender")),
        "nationality": (p.get("nationality") or "").upper(),
        "nationalId": p["nationalId"], "idType": p["idType"],
        "issueDate": p.get("issueDate"), "expiryDate": p.get("expiryDate"),
        "phoneNumber": p["phoneNumber"], "phoneCountryCode": p["phoneCountryCode"],
        "address": {
            "addressLine1": a.get("addressLine1") or a.get("line1"),
            "addressLine2": a.get("addressLine2") or a.get("line2"),
            "city": a.get("city"),
            "state": _clean_state(a.get("state")),
            "country": country,
            "postalCode": a.get("postalCode") or a.get("postal"),
        },
    }
    # SSN obligatoire pour une adresse US (9 chiffres)
    ssn = p.get("ssn")
    if country == "US":
        kyc["ssn"] = ssn or "000000000"  # placeholder sandbox si non collecté
    elif ssn:
        kyc["ssn"] = ssn
    return {k: v for k, v in kyc.items() if v is not None}


def _norm_cardholder_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    """Profil léger pour create_cardholder (le KYC est déjà porté par le sous-compte)."""
    a = p.get("address") or {}
    return {
        "firstName": p.get("firstName"), "lastName": p.get("lastName"),
        "email": p.get("email"), "dob": p.get("dob") or p.get("dateOfBirth"),
        "gender": _norm_gender(p.get("gender")),
        "nationality": (p.get("nationality") or "").upper(),
        "nationalId": p.get("nationalId"), "idType": p.get("idType"),
        "phoneNumber": p.get("phoneNumber"), "phoneCountryCode": p.get("phoneCountryCode"),
        "address": {
            "addressLine1": a.get("addressLine1") or a.get("line1"),
            "addressLine2": a.get("addressLine2") or a.get("line2"),
            "city": a.get("city"), "state": _clean_state(a.get("state")),
            "country": (a.get("country") or "").upper(),
            "postalCode": a.get("postalCode") or a.get("postal"),
        },
    }


# ── ÉTAPE 1 : à l'envoi du formulaire mini app (GATEWAY 2.1 + 2.2) ────────────
async def submit_enrollment_kyc(
    user_id: int,
    profile: Dict[str, Any],
    id_front: Tuple[str, bytes, str],
    selfie: Tuple[str, bytes, str],
    id_back: Optional[Tuple[str, bytes, str]] = None,
    bin_id: Optional[str] = None,
    admin_mode: bool = False,
) -> Dict[str, Any]:
    """GATEWAY : crée un SOUS-COMPTE pour l'utilisateur, uploade pièce+selfie,
    puis soumet le KYC du sous-compte. La carte se crée PLUS TARD, une fois le
    KYC PASSED (cf. complete_after_kyc_passed). Renvoie {success, account_id,
    status, message}."""

    def _work() -> Dict[str, Any]:
        c = _client()
        email = (profile.get("email") or f"user{user_id}@nova.local").strip()
        # SANDBOX : on uniquifie l'email par chat_id (+novaXXXX) pour éviter le
        # "Email already bound" d'Interlace en test (les sous-comptes persistent
        # même après un reset de notre base). En prod (mode!=dev) : email réel tel quel.
        if (getattr(config, "INTERLACE_MODE", "dev") == "dev" and not admin_mode
                and "@" in email):
            _local, _dom = email.rsplit("@", 1)
            _base = _local.split("+")[0]
            email = f"{_base}+nova{user_id}@{_dom}"
        name = (f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
                or f"user{user_id}")
        # 2.1 — sous-compte sous le compte maître
        sub = c.register_subaccount(
            email=email, name=name, parent_account_id=c.account_id,
            phone_number=profile.get("phoneNumber"),
            phone_country_code=profile.get("phoneCountryCode"))
        sub_id = sub.get("id") if isinstance(sub, dict) else None
        if not sub_id:
            raise RuntimeError(f"register: pas d'id de sous-compte ({sub})")
        # upload pièce + selfie SUR le sous-compte
        files = [id_front, selfie] + ([id_back] if id_back else [])
        fids = [f for f in _file_ids(c.upload_files(sub_id, files)) if f]
        if len(fids) < 2:
            raise RuntimeError(f"upload: fileIds insuffisants ({fids})")
        # 2.2 — KYC du sous-compte
        kyc = _norm_account_kyc(profile)
        kyc["idFrontId"] = fids[0]
        kyc["selfie"] = fids[1]
        if id_back and len(fids) > 2:
            kyc["idBackId"] = fids[2]
        res = c.submit_account_kyc(sub_id, kyc)
        return {"account_id": sub_id,
                "case_id": (res.get("caseId") if isinstance(res, dict) else None),
                "status": (res.get("status") if isinstance(res, dict) else None)}

    try:
        r = await asyncio.to_thread(_work)
        bid = _bin_for(profile, bin_id)
        if admin_mode:
            # enrollment NON réclamé : USER_ID NULL, créé par l'admin
            await mysql_client.create_enrollment(
                created_by=user_id, account_id=r["account_id"], kyc_case_id=r["case_id"],
                kyc_status=(r["status"] or KYC_PENDING), bin=str(bid),
                profile_json=json.dumps(profile, ensure_ascii=False))
        else:
            await mysql_client.upsert_interlace_account(
                user_id, account_id=r["account_id"], kyc_case_id=r["case_id"],
                kyc_status=(r["status"] or KYC_PENDING), bin=str(bid),
                profile_json=json.dumps(profile, ensure_ascii=False))
        logger.info(f"[interlace-kyc] user={user_id} sous-compte={r['account_id']} "
                    f"case={r['case_id']} status={r['status']} bin={bid}")
        # Confirmation immédiate dans le chat (avant le résultat du polling/webhook).
        await _notify(user_id, _msg("submitted", profile.get("lang")))
        return {"success": True, "account_id": r["account_id"],
                "status": r["status"], "message": "KYC soumis, en cours de vérification."}
    except Exception as e:
        logger.error(f"[interlace-kyc] submit_enrollment_kyc user={user_id} échec: {e}")
        return {"success": False, "account_id": None, "message": str(e)}


# ── ÉTAPE 2 : sur webhook KYC.UPDATED = PASSED (routé par account_id) ──────────
async def complete_after_kyc_passed(account_id: str, case_id: Optional[str] = None) -> Dict[str, Any]:
    """KYC du sous-compte approuvé -> crée le CARDHOLDER puis la CARTE.
    Routé par account_id (sous-compte). Idempotent. ⚠️ À valider live."""
    # account_id-centric : supporte le flux normal (USER_ID) ET les enrollments
    # admin (USER_ID NULL, created_by). On notifie l'owner s'il existe, sinon l'admin.
    acc = await mysql_client.get_account_by_account_id(account_id) or {}
    if not acc:
        logger.warning(f"[interlace-kyc] PASSED: sous-compte {account_id} inconnu en base")
        return {"success": False, "message": "sous-compte inconnu"}
    user_id = acc.get("USER_ID")
    notify_target = user_id or acc.get("created_by")
    is_admin_enroll = not user_id
    if acc.get("card_id"):
        logger.info(f"[interlace-kyc] sous-compte {account_id}: carte déjà créée, skip")
        return {"success": True, "user_id": user_id, "card_id": acc["card_id"], "skipped": True}

    def _work() -> Dict[str, Any]:
        c = _client()
        profile = json.loads(acc.get("profile_json") or "{}")
        bin_id = acc.get("bin") or DEFAULT_BIN_ID
        # 3 — provisionne l'Infinity account du sous-compte (tolère "déjà fait")
        try:
            c.initialize_account(account_id)
        except Exception as e:
            if "40000" not in str(e) and "repeat init" not in str(e).lower():
                raise
            logger.info(f"[interlace-kyc] sous-compte {account_id} déjà initialisé")
        # 5 — cardholder (1 sous-compte = 1 cardholder). Idempotent et anti-orphelin :
        # on réutilise celui en base, sinon on cherche un cardholder existant côté
        # Interlace (run précédent échoué après création), sinon on le crée.
        chid = acc.get("cardholder_id")
        if not chid:
            try:
                existing = c.list_cardholders(account_id)
            except Exception as e:
                logger.warning(f"[interlace-kyc] list_cardholders échec (non bloquant): {e}")
                existing = []
            if existing:
                chid = existing[0].get("id")
                logger.info(f"[interlace-kyc] cardholder existant réutilisé: {chid}")
            else:
                try:
                    ch = c.create_cardholder(account_id=account_id, bin_id=bin_id,
                                             profile=_norm_cardholder_profile(profile), tier="CONSUMER")
                    chid = ch.get("id") if isinstance(ch, dict) else None
                except Exception as e:
                    # course : déjà créé entre-temps -> on le récupère
                    if "010991" in str(e) or "Duplicate" in str(e).lower():
                        lst = c.list_cardholders(account_id)
                        chid = lst[0].get("id") if lst else None
                    if not chid:
                        raise
        if not chid:
            raise RuntimeError("cardholder: pas d'id")
        # 3b — alimente le sous-compte depuis le compte maître (si montant > 0)
        amount = CARD_INITIAL_AMOUNT
        if amount and float(amount) > 0:
            master_inf = c.get_infinity_wallet(c.account_id)
            sub_inf = None
            for _ in range(5):                       # l'Infinity account peut mettre 1-2s
                sub_inf = c.get_infinity_wallet(account_id)
                if sub_inf:
                    break
                time.sleep(1)
            if not (master_inf and sub_inf):
                raise RuntimeError("Infinity wallet introuvable (master/sub)")
            last_err = None
            for _ in range(6):                       # retry : race init + 500 transitoires Interlace
                try:
                    c.transfer_external(
                        from_account=c.account_id, from_balance_id=master_inf["id"],
                        to_account=account_id, to_balance_id=sub_inf["id"],
                        amount=amount, client_tx_id=f"nova-fund-{uuid.uuid4().hex[:10]}")
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(3)
            if last_err:
                raise last_err
        # 6 — carte prépayée rechargeable (virtuelle), chargée de `amount`
        card = c.create_prepaid_card(
            account_id=account_id, bin_id=bin_id, cardholder_id=chid,
            reference_id=f"nova-{user_id}-{uuid.uuid4().hex[:10]}",
            idempotency_key=str(uuid.uuid4()), card_mode="VIRTUAL_CARD",
            amount=(float(amount) if amount and float(amount) > 0 else None))
        cid = card.get("id") if isinstance(card, dict) else None
        cnum = card.get("cardLastFour") if isinstance(card, dict) else None
        # 7 — retrait de tout : on vide la carte -> 0 (carte prête/activée)
        emptied = "0.00"
        if cid:
            for _ in range(5):                       # le solde carte peut mettre 1-2s
                w = c.card_balance(account_id, cid)
                bal = float(w["available"]) if w and w.get("available") else 0.0
                if bal > 0:
                    c.card_transfer_out(account_id=account_id, card_id=cid,
                                        amount=f"{bal:.2f}",
                                        client_tx_id=f"empty-{uuid.uuid4().hex[:10]}")
                    emptied = f"{bal:.2f}"
                    break
                time.sleep(1)
        # 7b — sweep : on renvoie le solde du sous-compte au maître -> wallet à 0,
        # pour que l'user arrive sur Bot B avec TOUT à 0 (prêt à être chargé).
        try:
            time.sleep(1)
            sub_inf = c.get_infinity_wallet(account_id)
            avail = float((sub_inf or {}).get("available") or 0)
            if sub_inf and avail > 0:
                master_inf = c.get_infinity_wallet(c.account_id)
                if master_inf:
                    c.transfer_external(
                        from_account=account_id, from_balance_id=sub_inf["id"],
                        to_account=c.account_id, to_balance_id=master_inf["id"],
                        amount=f"{avail:.2f}", client_tx_id=f"sweep-{uuid.uuid4().hex[:10]}")
        except Exception as e:
            logger.warning(f"[interlace-kyc] sweep wallet->maître échec (non bloquant): {e}")
        return {"cardholder_id": chid, "card_id": cid, "card_number": cnum,
                "emptied": emptied}

    try:
        r = await asyncio.to_thread(_work)
        # 8 — handoff : token unique -> lien vers Bot B (utilisation de la carte)
        token = uuid.uuid4().hex
        link = f"https://t.me/{BOT_B_USERNAME}?start={token}"
        # sauvegarde PAR account_id (multi-enrollment safe)
        await mysql_client.update_account_by_account_id(
            account_id, cardholder_id=r["cardholder_id"], card_id=r["card_id"],
            card_number=r["card_number"], kyc_status=KYC_PASSED, handoff_token=token)
        last4 = str(r.get("card_number") or "")[-4:]
        try:
            prof = json.loads(acc.get("profile_json") or "{}")
        except Exception:
            prof = {}
        lang = (prof.get("lang") or "en")
        if is_admin_enroll:
            # enrollment admin : on envoie le lien à l'admin, identifié par email/nom
            who = prof.get("email") or f"{prof.get('firstName','')} {prof.get('lastName','')}".strip() or account_id
            if notify_target:
                await _notify(notify_target,
                              f"✅ Carte prête pour {who}"
                              + (f" (•••• {last4})" if last4 else "")
                              + f"\nLien à transmettre :\n{link}")
        else:
            await _notify(notify_target, _msg("ready", lang,
                                              extra=(f" (•••• {last4})" if last4 else ""), link=link))
        logger.info(f"[interlace-kyc] enrollment account={account_id} carte prête "
                    f"card_id={r['card_id']} owner={user_id} admin={acc.get('created_by')} token={token}")
        return {"success": True, "user_id": user_id, "link": link, **r}
    except Exception as e:
        logger.error(f"[interlace-kyc] complete_after_kyc_passed account={account_id} échec: {e}")
        return {"success": False, "user_id": user_id, "message": str(e)}


async def poll_and_finalize(user_id: int, account_id: str,
                            attempts: int = 45, interval: int = 8) -> None:
    """Fallback SANS webhook : interroge le KYC du sous-compte jusqu'à décision,
    puis crée la carte (PASSED) ou notifie le refus (CANCELED/REJECTED).
    Idempotent (complete_after_kyc_passed garde-fou card_id ; le webhook peut
    aussi déclencher, sans double-création)."""
    c = _client()
    for i in range(attempts):
        await asyncio.sleep(interval)
        try:
            cdd = await asyncio.to_thread(c.get_cdd_detail, account_id)
            k = cdd.get("kyc") if isinstance(cdd, dict) else None
            st = str((k or {}).get("status") or "").upper()
        except Exception as e:
            logger.warning(f"[interlace-kyc] poll {account_id} erreur: {e}")
            continue
        if st in ("PASSED", "APPROVED", "ACTIVE"):
            logger.info(f"[interlace-kyc] poll: {account_id} PASSED -> création carte")
            await complete_after_kyc_passed(account_id)
            return
        if st in ("CANCELED", "CANCELLED", "REJECTED", "FAILED", "DECLINED"):
            # SANDBOX : l'auto-review refuse toujours (factice). On MASQUE le refus
            # et on garde le statut PENDING (« vérification en cours ») jusqu'à la
            # validation manuelle d'Interlace -> webhook PASSED -> carte.
            if getattr(config, "TESTING_MODE", False):
                logger.info(f"[interlace-kyc] poll: {account_id} {st} -> SANDBOX, "
                            f"refus auto masqué (attente validation manuelle Interlace)")
                return
            logger.info(f"[interlace-kyc] poll: {account_id} {st} -> refus")
            await handle_kyc_rejected(account_id, reason=(k or {}).get("reason"))
            return
    logger.info(f"[interlace-kyc] poll {account_id}: timeout (toujours en revue)")


async def handle_kyc_rejected(account_id: str, reason: Optional[str] = None) -> Optional[int]:
    """KYC refusé -> statut REJECTED + notifie. Routé par account_id."""
    user_id = await mysql_client.get_user_id_by_account_id(account_id)
    if user_id:
        await mysql_client.set_kyc_status(account_id, KYC_REJECTED)
        lang = await _user_lang(user_id)
        await _notify(user_id, _msg("rejected", lang,
                                    reason=(f" ({reason})" if reason else "")))
    logger.info(f"[interlace-kyc] KYC refusé account={account_id} user={user_id} raison={reason}")
    return user_id
