#!/usr/bin/env python3
"""Admin — liste les enrollments / KYC (lecture directe en base Bot A).

Usage (depuis /opt/nova/kyc_bot) :
  ./venv/bin/python deploy/enrollments.py            # tout
  ./venv/bin/python deploy/enrollments.py pending    # en attente (PENDING/NONE)
  ./venv/bin/python deploy/enrollments.py rejected   # refusés (CANCELED/REJECTED...)
  ./venv/bin/python deploy/enrollments.py ready       # carte créée (PASSED + card)
"""
import json
import os
import sys

import pymysql

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
m = json.load(open(os.path.join(HERE, "config/params.json")))["mysql"]
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
    if flt == "ready":
        return bool(r.get("card_id"))
    return True


print(f"{'CRÉÉ':16} {'STATUT':9} {'EMAIL':26} {'OWNER':12} {'ADMIN':12} {'CARTE':5} ACCOUNT_ID")
print("-" * 120)
n = 0
for r in rows:
    if not keep(r):
        continue
    n += 1
    try:
        prof = json.loads(r.get("profile_json") or "{}")
    except Exception:
        prof = {}
    print(f"{str(r.get('created_at'))[:16]:16} "
          f"{(r.get('kyc_status') or '-'):9} "
          f"{(prof.get('email') or '-')[:25]:26} "
          f"{str(r.get('USER_ID') or '-'):12} "
          f"{str(r.get('created_by') or '-'):12} "
          f"{('oui' if r.get('card_id') else 'non'):5} "
          f"{r.get('account_id') or '-'}")
print(f"\n{n} enrollment(s) [{flt}]   (OWNER=client réclamant · ADMIN=créateur)")
