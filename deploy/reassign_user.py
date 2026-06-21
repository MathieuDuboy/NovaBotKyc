#!/usr/bin/env python3
"""reassign_user — réaffecte une carte/compte d'un user Telegram à un AUTRE.

Opération SENSIBLE (= prise de contrôle si mal utilisée). À lancer UNIQUEMENT par
un admin, APRÈS vérification d'identité du titulaire KYC.

Ce que ça fait : re-mappe le chat_id Telegram (USER_ID) old -> new dans les 2 bases
locales. La carte / le cardholder / le compte / les fonds (côté Interlace) NE
bougent PAS. Les adresses de dépôt restent liées aux mêmes cartes.

Tables mises à jour :
  Bot B (interlace) : interlace_accounts, cards, topup_requests, pool
  Bot A (kyc)       : interlace_accounts

Garde-fous :
  - le NOUVEAU chat_id doit être VIERGE (aucun compte/carte) -> sinon refus
    (contrainte UNIQUE + règle 1 cardholder par user).
  - l'ANCIEN doit exister -> sinon refus.
  - DRY-RUN par défaut : montre le plan. Ajoute --yes pour exécuter.
  - chaque base est mise à jour dans une TRANSACTION (rollback si erreur).
  - journal d'audit append-only (reassign_audit.log à côté du script).

Usage :
  ./venv/bin/python deploy/reassign_user.py <OLD_CHAT_ID> <NEW_CHAT_ID>          # dry-run
  ./venv/bin/python deploy/reassign_user.py <OLD_CHAT_ID> <NEW_CHAT_ID> --yes    # exécute
"""
import json
import os
import sys
from datetime import datetime

import pymysql

HERE = os.path.dirname(os.path.abspath(__file__))                 # .../kyc_bot/deploy
PARAMS_A = os.path.join(HERE, "..", "config", "params.json")               # Bot A
PARAMS_B = os.path.join(HERE, "..", "..", "interlace_bot", "config", "params.json")  # Bot B
AUDIT = os.path.join(HERE, "reassign_audit.log")

# (label, chemin params, tables à mettre à jour)
DBS = [
    ("Bot B (interlace)", PARAMS_B, ["interlace_accounts", "cards", "topup_requests", "pool"]),
    ("Bot A (kyc)",       PARAMS_A, ["interlace_accounts"]),
]


def _conn(params_path):
    m = json.load(open(params_path))["mysql"]
    return pymysql.connect(host=m["host"], port=int(m["port"]), user=m["user"],
                           password=m["password"], db=m["database"],
                           cursorclass=pymysql.cursors.DictCursor, autocommit=False)


def _count(cur, table, uid):
    cur.execute(f"SELECT COUNT(*) AS n FROM `{table}` WHERE `USER_ID`=%s", (uid,))
    return cur.fetchone()["n"]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_it = "--yes" in sys.argv
    if len(args) != 2:
        print(__doc__)
        sys.exit(1)
    try:
        old_id, new_id = int(args[0]), int(args[1])
    except ValueError:
        print("ERREUR: OLD_CHAT_ID et NEW_CHAT_ID doivent être des entiers.")
        sys.exit(1)
    if old_id == new_id:
        print("ERREUR: old == new."); sys.exit(1)

    print(f"\n=== Réaffectation  {old_id}  ->  {new_id}   ({'EXÉCUTION' if do_it else 'DRY-RUN'}) ===\n")

    conns = []
    plan = []          # (conn, label, tables)
    blocking = []
    has_source = False
    try:
        for label, ppath, tables in DBS:
            if not os.path.exists(ppath):
                print(f"  ⚠️  {label}: params introuvable ({ppath}) — ignoré.")
                continue
            c = _conn(ppath); conns.append(c); cur = c.cursor()
            # source (old) présent ? + garde-fou cible (new) vierge
            src = _count(cur, "interlace_accounts", old_id)
            tgt = _count(cur, "interlace_accounts", new_id)
            tgt_cards = _count(cur, "cards", new_id) if "cards" in tables else 0
            if src:
                has_source = True
            print(f"  {label}: old a {src} compte(s) | new a {tgt} compte(s)"
                  + (f", {tgt_cards} carte(s)" if "cards" in tables else ""))
            for t in tables:
                n = _count(cur, t, old_id)
                if n:
                    print(f"      - {t}: {n} ligne(s) à déplacer")
            if tgt or tgt_cards:
                blocking.append(f"{label}: le NOUVEAU chat_id a déjà un compte/carte")
            plan.append((c, label, tables))

        print()
        if not has_source:
            print("❌ ABANDON: l'ancien chat_id n'a AUCUN compte (rien à déplacer).")
            sys.exit(2)
        if blocking:
            print("❌ ABANDON (anti-conflit / règle 1 cardholder par user):")
            for b in blocking:
                print("   - " + b)
            print("\n   Le nouveau compte doit être VIERGE. Utilise un chat_id sans carte.")
            sys.exit(3)

        if not do_it:
            print("✅ DRY-RUN OK — aucun changement. Relance avec --yes pour exécuter.")
            sys.exit(0)

        # exécution : transaction par base
        total = 0
        for c, label, tables in plan:
            cur = c.cursor()
            try:
                moved = 0
                for t in tables:
                    cur.execute(f"UPDATE `{t}` SET `USER_ID`=%s WHERE `USER_ID`=%s",
                                (new_id, old_id))
                    moved += cur.rowcount
                c.commit()
                total += moved
                print(f"  ✅ {label}: {moved} ligne(s) déplacée(s).")
            except Exception as e:
                c.rollback()
                print(f"  ❌ {label}: ÉCHEC -> rollback ({e})")
                raise

        with open(AUDIT, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}\told={old_id}\tnew={new_id}\trows={total}\n")
        print(f"\n✅ Terminé. {total} lignes re-mappées. Audit -> {AUDIT}")
        print(f"   Le compte {new_id} peut faire /start sur le bot carte pour récupérer la carte.")
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
