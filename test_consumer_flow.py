"""
Test LIVE du flux consommateur (gateway) sur le compte démo :
  1) register  -> crée un sous-compte (sous-marchand) de test
  2) submit KYC -> observe les champs/documents exigés (sans vrais fichiers)
But : voir concrètement comment le KYC se déclenche. Données bidon.
"""
import json
from urllib.parse import urlparse
import requests

P = json.load(open("config/params.json"))
il = P["interlace"]["dev"]
_pu = urlparse((il.get("base_url") or "").strip())
base = f"{_pu.scheme}://{_pu.netloc}"
cid, csec, acc = il["client_id"], il["client_secret"], il["account_id"]


def show(tag, r, limit=1800):
    print(f"\n== {tag} ==  (HTTP {r.status_code})")
    try:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:limit])
    except Exception:
        print(r.text[:limit])
    try:
        return r.json()
    except Exception:
        return {}


# auth
r = requests.get(f"{base}/open-api/oauth/authorize", params={"clientId": cid}, timeout=30, allow_redirects=False)
code = r.json().get("code")
tok = requests.post(f"{base}/open-api/oauth/access-token",
                    json={"clientId": cid, "clientSecret": csec, "code": code}, timeout=30).json().get("accessToken")
H = {"x-access-token": tok}
print("✅ authentifié")

# 1) register sous-marchand de test
reg_payload = {
    "email": "consumer.test+nova@example.com",
    "programType": "CONSUMER USE - GATEWAY",
    "firstName": "Jean",
    "lastName": "Dupont",
    "country": "FR",
}
r = requests.post(f"{base}/open-api/v1/accounts/register", json=reg_payload, headers=H, timeout=60)
j = show("1) REGISTER sous-marchand", r)
new_acc = (j.get("data") or {}).get("id") or (j.get("data") or {}).get("accountId")
print("   -> nouvel accountId:", new_acc)

# 2) tentative de submit KYC (sans fichiers) pour voir les champs exigés
target = new_acc or acc
kyc_payload = {
    "firstName": "Jean", "lastName": "Dupont", "dateOfBirth": "1990-05-21",
    "gender": "MALE", "nationality": "FR", "nationalId": "1234567890",
    "idType": "PASSPORT", "issueDate": "2018-01-01", "expiryDate": "2030-01-01",
    "phoneNumber": "612345678", "phoneCountryCode": "33",
    "address": {"line1": "1 rue de Test", "city": "Paris", "country": "FR", "postalCode": "75001"},
    "sourceType": "api",
}
r = requests.post(f"{base}/open-api/v3/accounts/{target}/kyc", json=kyc_payload, headers=H, timeout=60)
show(f"2) SUBMIT KYC (sans idFrontId/selfie) sur {target}", r)
