"""
Orchestration du flux KYC consumer/gateway (Interlace v3).

Relie le client v3 (interlace_v3.InterlaceV3) et la table interlace_accounts.
Deux temps :
  1. submit_enrollment_kyc(...)  — à l'envoi du formulaire mini app :
       register sous-compte -> upload pièce+selfie -> submit KYC.
       (le KYC part en revue ; la suite arrive par webhook)
  2. complete_after_kyc_passed(account_id) — sur webhook KYC.UPDATED=PASSED :
       initialize -> create_cardholder -> create_card -> persiste la carte.

⚠️ Les noms de champs de RÉPONSE (accountId/fileId/cardId) sont extraits de
façon défensive : à verrouiller via un test d'écriture live (cf. les `TODO live`).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple

import config
from interlace_v3 import InterlaceV3
from services.mysql_service import mysql_client
from telegram_bot.messaging import telegram_messaging
from utils.logger import logger


async def _notify(user_id, message: str) -> None:
    """Notifie l'utilisateur Telegram (best-effort, ne casse pas le flux)."""
    try:
        await telegram_messaging.send_card_notification(str(user_id), message)
    except Exception as e:
        logger.error(f"[interlace-kyc] notif user={user_id} échec: {e}")

# Statuts KYC stockés (alignés sur les events webhook KYC.UPDATED)
KYC_PENDING = "PENDING"
KYC_PASSED = "PASSED"
KYC_REJECTED = "REJECTED"


def _client() -> InterlaceV3:
    return InterlaceV3.from_params("config/params.json", mode=config.INTERLACE_MODE)


# ── helpers d'extraction défensifs (TODO live : confirmer les vrais champs) ───
def _extract_account_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        return data.get("id") or data.get("accountId") or data.get("account_id")
    return None


def _extract_file_ids(data: Any) -> List[str]:
    """L'upload renvoie un (ou des) fileId. Forme à confirmer live."""
    if isinstance(data, list):
        return [d.get("id") or d.get("fileId") for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        lst = data.get("list") or data.get("files") or data.get("data")
        if isinstance(lst, list):
            return [d.get("id") or d.get("fileId") for d in lst if isinstance(d, dict)]
        single = data.get("id") or data.get("fileId")
        return [single] if single else []
    return []


def _extract_cardholder_id(data: Any) -> Optional[str]:
    if isinstance(data, dict):
        return data.get("id") or data.get("cardholderId")
    return None


def _extract_card(data: Any) -> Tuple[Optional[str], Optional[str]]:
    """Renvoie (card_id, card_number). create_card peut renvoyer un tableau
    (batchCount) ou un objet unique."""
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


# ── normalisation du profil (formulaire mini app -> schéma cardholder v3) ──────
def _norm_gender(v: str) -> str:
    return "F" if str(v or "").strip().upper() in ("F", "FEMALE", "FEMME") else "M"


def _norm_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    """Mappe les champs du formulaire vers le schéma ConsumerMor v3."""
    a = p.get("address") or {}
    return {
        "firstName": p["firstName"], "lastName": p["lastName"], "email": p["email"],
        "dob": p.get("dob") or p.get("dateOfBirth"),
        "gender": _norm_gender(p.get("gender")),
        "nationality": (p.get("nationality") or "").upper(),
        "nationalId": p["nationalId"], "idType": p["idType"],
        "issueDate": p.get("issueDate"), "expiryDate": p.get("expiryDate"),
        "phoneNumber": p["phoneNumber"], "phoneCountryCode": p["phoneCountryCode"],
        "address": {
            "addressLine1": a.get("addressLine1") or a.get("line1"),
            "addressLine2": a.get("addressLine2") or a.get("line2"),
            "city": a.get("city"),
            "state": (a.get("state") or "")[:2],   # ≤2 car. (code état)
            "country": (a.get("country") or "").upper(),
            "postalCode": a.get("postalCode") or a.get("postal"),
        },
    }


# ── ÉTAPE 1 : à l'envoi du formulaire mini app (MoR) ──────────────────────────
async def submit_enrollment_kyc(
    user_id: int,
    profile: Dict[str, Any],
    id_front: Tuple[str, bytes, str],
    selfie: Tuple[str, bytes, str],
    id_back: Optional[Tuple[str, bytes, str]] = None,
    bin_id: Optional[str] = None,
) -> Dict[str, Any]:
    """MoR : uploade pièce+selfie puis crée le CARDHOLDER (KYC inclus) sous le
    compte maître. Pas de register/sous-compte. La carte se crée PLUS TARD,
    une fois le KYC PASSED (cf. complete_after_kyc_passed).
    Renvoie {success, cardholder_id, status, message}."""
    prof = _norm_profile(profile)

    def _work() -> Dict[str, Any]:
        c = _client()
        acc = c.account_id
        files = [id_front, selfie] + ([id_back] if id_back else [])
        up = c.upload_files(acc, files)
        fids = [f for f in _extract_file_ids(up) if f]
        if len(fids) < 2:
            raise RuntimeError(f"upload: fileIds insuffisants ({fids})")
        bid = bin_id or profile.get("bin")
        if not bid:
            bins = c.list_bins(acc)
            bid = bins[0]["id"] if bins else None
        ch = c.create_cardholder(
            account_id=acc, bin_id=bid, profile=prof,
            id_front_id=fids[0], selfie_id=fids[1],
            id_back_id=(fids[2] if (id_back and len(fids) > 2) else None))
        return {"cardholder_id": _extract_cardholder_id(ch),
                "status": (ch.get("status") if isinstance(ch, dict) else None)}

    try:
        r = await asyncio.to_thread(_work)
        if not r["cardholder_id"]:
            raise RuntimeError("cardholderId introuvable dans la réponse")
        await mysql_client.upsert_interlace_account(
            user_id, cardholder_id=r["cardholder_id"],
            kyc_status=(r["status"] or KYC_PENDING), bin=str(bin_id or profile.get("bin") or ""))
        logger.info(f"[interlace-kyc] user={user_id} cardholder={r['cardholder_id']} "
                    f"status={r['status']}")
        return {"success": True, "cardholder_id": r["cardholder_id"],
                "status": r["status"], "message": "KYC soumis, en cours de vérification."}
    except Exception as e:
        logger.error(f"[interlace-kyc] submit_enrollment_kyc user={user_id} échec: {e}")
        return {"success": False, "cardholder_id": None, "message": str(e)}


# ── ÉTAPE 2 : sur webhook KYC.UPDATED = PASSED ────────────────────────────────
async def complete_after_kyc_passed(cardholder_id: str, case_id: Optional[str] = None) -> Dict[str, Any]:
    """KYC approuvé (MoR) -> crée la CARTE pour le cardholder (déjà créé à
    l'inscription). Routé par cardholder_id (clé du webhook). Idempotent."""
    user_id = await mysql_client.get_user_id_by_cardholder_id(cardholder_id)
    if not user_id:
        logger.warning(f"[interlace-kyc] PASSED: cardholder {cardholder_id} non rattaché à un user")
        return {"success": False, "message": "cardholder inconnu"}

    acc = await mysql_client.get_interlace_account(user_id) or {}
    if acc.get("card_id"):
        logger.info(f"[interlace-kyc] cardholder {cardholder_id}: carte déjà créée, skip")
        return {"success": True, "user_id": user_id, "card_id": acc["card_id"], "skipped": True}

    def _work() -> Dict[str, Any]:
        c = _client()
        bin_value = acc.get("bin")
        bins = c.list_bins(c.account_id)
        chosen = next((b for b in bins
                       if str(b.get("id")) == str(bin_value) or str(b.get("bin")) == str(bin_value)),
                      (bins[0] if bins else None))
        bin_num = chosen.get("bin") if chosen else bin_value
        # carte prépayée rattachée au cardholder (sous le compte maître = MoR)
        card = c.create_card(bin=str(bin_num), cardholder_id=cardholder_id,
                             account_id=c.account_id, use_type="Virtual card")
        cid, cnum = _extract_card(card)
        return {"card_id": cid, "card_number": cnum}

    try:
        r = await asyncio.to_thread(_work)
        await mysql_client.upsert_interlace_account(
            user_id, card_id=r["card_id"], card_number=r["card_number"], kyc_status=KYC_PASSED)
        last4 = str(r.get("card_number") or "")[-4:]
        await _notify(user_id, (
            "✅ Ta vérification d'identité est validée et ta carte est prête"
            + (f" (•••• {last4})" if last4 else "")
            + " ! Ouvre l'application pour la consulter."))
        logger.info(f"[interlace-kyc] user={user_id} carte créée card_id={r['card_id']}")
        return {"success": True, "user_id": user_id, **r}
    except Exception as e:
        logger.error(f"[interlace-kyc] complete_after_kyc_passed cardholder={cardholder_id} échec: {e}")
        return {"success": False, "user_id": user_id, "message": str(e)}


async def handle_kyc_rejected(cardholder_id: str, reason: Optional[str] = None) -> Optional[int]:
    """KYC refusé -> statut REJECTED + notifie. Routé par cardholder_id."""
    user_id = await mysql_client.get_user_id_by_cardholder_id(cardholder_id)
    if user_id:
        await mysql_client.upsert_interlace_account(user_id, kyc_status=KYC_REJECTED)
        await _notify(user_id, (
            "❌ Ta vérification d'identité n'a pas pu être validée"
            + (f" ({reason})" if reason else "")
            + ". Tu peux réessayer avec /start."))
    logger.info(f"[interlace-kyc] KYC refusé cardholder={cardholder_id} user={user_id} raison={reason}")
    return user_id
