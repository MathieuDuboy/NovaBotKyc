"""
Sonde la config du compte Interlace via la NOUVELLE API v3 (auth OAuth2).
Lit les creds dans config/params.json (bloc interlace.dev) et affiche :
  - le statut KYB/KYC du compte (cdd/detail)
  - les BIN disponibles (pour voir le tier / les exigences KYC)
Lecture seule : ne crée rien. Usage : ./venv/bin/python probe_interlace_v3.py
"""
import json
import sys
from urllib.parse import urlparse, parse_qs

import requests

P = json.load(open("config/params.json"))
il = P["interlace"]["dev"]
# On ne garde que scheme://host (on ignore tout suffixe /open-api/... éventuel).
_raw_base = (il.get("base_url") or "").strip()
_pu = urlparse(_raw_base if "://" in _raw_base else "https://" + _raw_base)
base = f"{_pu.scheme}://{_pu.netloc}" if _pu.netloc else _raw_base.rstrip("/")
cid = il.get("client_id")
csec = il.get("client_secret")
acc = il.get("account_id")


def need(k, v):
    if not v or "<" in str(v):
        print(f"❌ '{k}' non rempli dans params.json (interlace.dev). Complète-le puis relance.")
        sys.exit(1)


for k, v in [("base_url", base), ("client_id", cid), ("client_secret", csec), ("account_id", acc)]:
    need(k, v)


def show(r, limit=2500):
    print("   status:", r.status_code)
    ct = r.headers.get("content-type", "")
    if ct.startswith("application/json"):
        try:
            print("  ", json.dumps(r.json(), indent=2, ensure_ascii=False)[:limit])
            return
        except Exception:
            pass
    print("  ", r.text[:limit])


print(f"== base: {base} ==")

# 1) authorize -> code
print("\n== 1) OAuth authorize (récupère le code) ==")
r = requests.get(f"{base}/open-api/oauth/authorize", params={"clientId": cid},
                 timeout=30, allow_redirects=False)
show(r, 600)
code = None
try:
    j = r.json()
    code = j.get("code") or (j.get("data") or {}).get("code")
except Exception:
    pass
if not code:
    loc = r.headers.get("Location") or r.headers.get("location")
    if loc:
        code = parse_qs(urlparse(loc).query).get("code", [None])[0]
        print("   code depuis redirect:", code)
if not code:
    print("❌ Pas de code récupéré — voir la réponse ci-dessus (le flux authorize a peut-être changé).")
    sys.exit(1)

# 2) access-token
print("\n== 2) OAuth access-token ==")
r = requests.post(f"{base}/open-api/oauth/access-token",
                  json={"clientId": cid, "clientSecret": csec, "code": code}, timeout=30)
show(r, 600)
tok = None
try:
    j = r.json()
    tok = j.get("accessToken") or (j.get("data") or {}).get("accessToken")
except Exception:
    pass
if not tok:
    print("❌ Pas d'accessToken — auth échouée.")
    sys.exit(1)
print(f"   ✅ accessToken obtenu (len={len(tok)})")
H = {"x-access-token": tok}

# 3) statut KYB/KYC du compte
print("\n== 3) Statut KYB/KYC du compte (cdd/detail) ==")
r = requests.get(f"{base}/open-api/v3/accounts/cdd/detail/{acc}", headers=H, timeout=30)
show(r)

# 4) BIN disponibles (tier / exigences)
print("\n== 4) BIN disponibles (tier / KYC) ==")
r = requests.get(f"{base}/open-api/v3/card/bins", params={"accountId": acc, "limit": "100", "page": "1"},
                 headers=H, timeout=30)
show(r)

print("\n== Fin de la sonde ==")
