"""
Crée un CARDHOLDER de test sur le compte démo Interlace (API v3) pour observer
le flux KYC : déclaratif direct, ou demande de documents / lien hébergé ?
Données bidon. Usage : ./venv/bin/python create_test_cardholder.py
"""
import json
import sys
from urllib.parse import urlparse

import requests

P = json.load(open("config/params.json"))
il = P["interlace"]["dev"]
_pu = urlparse((il.get("base_url") or "").strip())
base = f"{_pu.scheme}://{_pu.netloc}"
cid, csec, acc = il["client_id"], il["client_secret"], il["account_id"]


def show(tag, r, limit=2500):
    print(f"\n== {tag} ==")
    print("   status:", r.status_code)
    try:
        print("  ", json.dumps(r.json(), indent=2, ensure_ascii=False)[:limit])
    except Exception:
        print("  ", r.text[:limit])
    return r


# --- auth ---
r = requests.get(f"{base}/open-api/oauth/authorize", params={"clientId": cid}, timeout=30, allow_redirects=False)
code = r.json().get("code")
r = requests.post(f"{base}/open-api/oauth/access-token",
                  json={"clientId": cid, "clientSecret": csec, "code": code}, timeout=30)
tok = r.json().get("accessToken")
if not tok:
    print("❌ auth échouée"); show("access-token", r); sys.exit(1)
H = {"x-access-token": tok}
print("✅ authentifié")

# --- choisir un BIN ---
r = requests.get(f"{base}/open-api/v3/card/bins", params={"accountId": acc, "limit": "100", "page": "1"}, headers=H, timeout=30)
bins = (r.json().get("data") or {}).get("list") or []
if not bins:
    print("❌ aucun BIN"); sys.exit(1)
bin_id = bins[0]["id"]
print(f"   BIN choisi: id={bin_id} bin={bins[0].get('bin')} network={bins[0].get('network')}")

# --- tester chaque tier pour trouver celui du compte ---
base_payload = {
    "accountId": acc,
    "binId": bin_id,
    "cardholderRole": "AUTHORIZED_REPRESENTATIVE",
    "firstName": "Jean",
    "lastName": "Dupont",
    "email": "jean.dupont.test@example.com",
    "dob": "1990-05-21",
    "nationality": "FR",
    "phoneNumber": "612345678",
    "phoneCountryCode": "33",
}
accepted = None
for tier in ["CORPORATE_MANAGED", "NAMED_INDIVIDUAL", "CONSUMER_GATEWAY", "CONSUMER_MOR"]:
    payload = {**base_payload, "cardholderTier": tier}
    r = requests.post(f"{base}/open-api/v3/cardholders", json=payload, headers=H, timeout=60)
    show(f"CREATE cardholder (tier={tier})", r, limit=1200)
    if r.status_code in (200, 201):
        accepted = (tier, r)
        break

# --- relire le statut si accepté ---
if accepted:
    tier, r = accepted
    print(f"\n✅ TIER DU COMPTE = {tier}")
    try:
        data = r.json().get("data") or {}
        ch_id = data.get("id") or data.get("cardholderId")
        if ch_id:
            print(f"   cardholderId = {ch_id}")
            rd = requests.get(f"{base}/open-api/v3/cardholders/{ch_id}", headers=H, timeout=30)
            show("GET cardholder (statut KYC)", rd)
    except Exception as e:
        print("relecture impossible:", e)
else:
    print("\n⚠️ aucun tier accepté en l'état — voir les messages d'erreur ci-dessus.")
