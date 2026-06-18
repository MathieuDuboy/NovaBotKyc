"""
Commandes admin (Telegram) — pilotage des enrollments multi-KYC :
  /enrollments  — liste tous les enrollments (statut, email, état)
  /pending      — KYC en attente (+ account_id à donner à Interlace)
  /available    — cartes créées NON réclamées (+ liens à transmettre)
Réservées aux ADMIN_CHAT_IDS (filtre appliqué à l'enregistrement).
"""
import csv
import io
import json
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes

from services.mysql_service import mysql_client
from utils.logger import logger

_MAX = 40


def _email_name(r):
    try:
        p = json.loads(r.get("profile_json") or "{}")
    except Exception:
        p = {}
    name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
    return (p.get("email") or "—"), (name or "—")


async def cmd_enrollments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Génère et envoie un CSV téléchargeable de TOUS les enrollments."""
    try:
        from services.interlace_kyc import BOT_B_USERNAME
        rows = await mysql_client.list_all_enrollments()
        if not rows:
            await update.message.reply_text("Aucun enrollment pour l'instant.")
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["created_at", "email", "name", "kyc_status", "card_created",
                    "card_id", "account_id", "created_by_admin", "claimed_by_user", "link"])
        for r in rows:
            email, name = _email_name(r)
            tok = r.get("handoff_token")
            link = f"https://t.me/{BOT_B_USERNAME}?start={tok}" if tok else ""
            w.writerow([
                str(r.get("created_at") or ""), email, name,
                r.get("kyc_status") or "", "yes" if r.get("card_id") else "no",
                r.get("card_id") or "", r.get("account_id") or "",
                r.get("created_by") or "", r.get("USER_ID") or "", link,
            ])
        # utf-8-sig (BOM) -> accents corrects à l'ouverture dans Excel
        bio = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
        bio.name = f"enrollments_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.csv"
        await update.message.reply_document(
            document=bio, filename=bio.name,
            caption=f"📋 {len(rows)} enrollment(s) — statut · email · attribution · lien")
    except Exception as e:
        logger.error(f"[admin] /enrollments csv: {e}")
        await update.message.reply_text(f"Erreur : {e}")


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        rows = await mysql_client.execute_query_async(
            "SELECT * FROM interlace_accounts "
            "WHERE UPPER(COALESCE(`kyc_status`,'')) IN ('PENDING','NONE','') "
            "ORDER BY `created_at` DESC") or []
        if not rows:
            await update.message.reply_text("✅ Aucun KYC en attente.")
            return
        lines = [f"⏳ KYC en attente ({len(rows)})",
                 "account_id à faire valider chez Interlace :"]
        for r in rows[:_MAX]:
            email, _ = _email_name(r)
            lines.append(f"\n• {email}\n  {r.get('account_id') or '—'}")
        if len(rows) > _MAX:
            lines.append(f"\n… +{len(rows) - _MAX} autres")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"[admin] /pending: {e}")
        await update.message.reply_text(f"Erreur : {e}")


async def cmd_available(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        from services.interlace_kyc import BOT_B_USERNAME
        rows = await mysql_client.list_all_enrollments()
        av = [r for r in rows if r.get("card_id") and not r.get("USER_ID")]
        if not av:
            await update.message.reply_text("Aucune carte disponible non réclamée.")
            return
        lines = [f"🎟 Cartes prêtes NON réclamées ({len(av)})",
                 "liens à transmettre :"]
        for r in av[:_MAX]:
            email, _ = _email_name(r)
            tok = r.get("handoff_token")
            link = f"https://t.me/{BOT_B_USERNAME}?start={tok}" if tok else "(pas de lien)"
            lines.append(f"\n• {email}\n  {link}")
        await update.message.reply_text("\n".join(lines), disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[admin] /available: {e}")
        await update.message.reply_text(f"Erreur : {e}")
