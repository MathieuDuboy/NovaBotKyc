#!/usr/bin/env python3
"""Admin — liste les enrollments / KYC (lecture directe en base Bot A).

Usage (depuis /opt/nova/kyc_bot) :
  ./venv/bin/python deploy/enrollments.py            # tout
  ./venv/bin/python deploy/enrollments.py pending    # en attente
  ./venv/bin/python deploy/enrollments.py rejected   # refusés
  ./venv/bin/python deploy/enrollments.py unclaimed  # carte créée MAIS non réclamée (+ liens)
"""
import json
import os
import sys

import pymysql

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
params = json.load(open(os.path.join(HERE, "config/params.json")))
m = params["mysql"]
BOT_B = (params.get("telegram", {}).get("bot_b_username")
         or "novabotcardtestsandboxinterbot")
flt = (sys.argv[1].lower() if len(sys.argv) > 1 else "all")

PENDING = ("PENDING", "NONE", "")
REJECTED = ("REJECTED", "CANCELED", "CANCELLED", "FAILED", "DECLINED")

conn = pymysql.connect(host=m["host"], port=int(m["port"]), user=m["user"],
                       password=m["password"], db=m["database"],
                       cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()
cur.execute("SELECT * FROM interlace_accounts ORDER BY created_at DESC")
rows = cur.fetchall()


def keep(r):
    st = str(r.get("kyc_status") or "").upper()
    if flt == "pending":
        return st in PENDING
    if flt == "rejected":
        return st in REJECTED
    if flt == "unclaimed":               # carte créée mais aucun user ne l'a réclamée
        return bool(r.get("card_id")) and not r.get("USER_ID")
    return True


def info(r):
    try:
        p = json.loads(r.get("profile_json") or "{}")
    except Exception:
        p = {}
    name = f"{p.get('firstName', '')} {p.get('lastName', '')}".strip()
    return (p.get("email") or "-"), (name or "-")


n = 0
if flt == "unclaimed":
    print("Validés NON réclamés (lien à transmettre) :\n")
    for r in rows:
        if not keep(r):
            continue
        n += 1
        email, name = info(r)
        tok = r.get("handoff_token")
        link = f"https://t.me/{BOT_B}?start={tok}" if tok else "(pas de token)"
        print(f"• {email}  |  {name}\n  {link}\n")
else:
    print(f"{'STATUT':10} {'EMAIL':30} NOM PRÉNOM")
    print("-" * 70)
    for r in rows:
        if not keep(r):
            continue
        n += 1
        email, name = info(r)
        print(f"{(r.get('kyc_status') or '-'):10} {email[:29]:30} {name}")
print(f"\n{n} enrollment(s) [{flt}]")
