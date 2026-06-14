"""
Test LIVE du chemin MoR : créer un cardholder en CONSUMER_MOR DIRECTEMENT sous le
compte maître (pas de register de sous-compte). On regarde la réponse pour savoir
ce que ça renvoie (cardholderId ?) et ce que ça exige encore (KYC ?).

⚠️ Écriture réelle (crée un cardholder). Usage : ./venv/bin/python simulate_mor_cardholder.py
"""
import json
from interlace_v3 import InterlaceV3, InterlaceV3Error


def show(tag, d):
    print(f"\n===== {tag} =====")
    try:
        print(json.dumps(d, indent=2, ensure_ascii=False)[:2500])
    except Exception:
        print(repr(d)[:2000])


def main():
    c = InterlaceV3.from_params("config/params.json", mode="dev")
    print("compte maître:", c.account_id)

    bins = c.list_bins()
    if not bins:
        print("❌ aucun BIN"); return
    b = bins[0]
    print("BIN choisi: id=", b.get("id"), "bin=", b.get("bin"), "network=", b.get("network"))

    payload = {
        "accountId": c.account_id,
        "binId": b.get("id"),
        "cardholderTier": "CONSUMER_MOR",
        "cardholderRole": "AUTHORIZED_REPRESENTATIVE",
        "firstName": "Jean", "lastName": "Dupont",
        "email": "mor.test+nova@example.com",
        "dob": "1990-05-21", "nationality": "FR",
        "phoneNumber": "612345678", "phoneCountryCode": "33",
        "address": {"line1": "1 rue de Test", "city": "Paris",
                    "country": "FR", "postalCode": "75001"},
    }
    print("\npayload create_cardholder:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    try:
        r = c._request("POST", "/open-api/v3/cardholders", json_body=payload)
        show("CREATE CARDHOLDER (CONSUMER_MOR)", r)
        ch_id = (r.get("id") or r.get("cardholderId")) if isinstance(r, dict) else None
        print("\n-> cardholderId =", ch_id)
        if ch_id:
            try:
                detail = c._request("GET", f"/open-api/v3/cardholders/{ch_id}")
                show("GET CARDHOLDER (statut/KYC)", detail)
            except InterlaceV3Error as e:
                print("get cardholder ->", e)
    except InterlaceV3Error as e:
        print("\n❌ create_cardholder ->", e)


if __name__ == "__main__":
    main()
