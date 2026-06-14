"""
Simulation LIVE du flux consumer v3 de bout en bout (sur le compte démo Interlace),
pilotée par le client v3 — sans bot, sans mini app, sans BDD.

Étapes : register (sous-compte) -> upload pièce+selfie (images bidon) ->
submit KYC -> get cdd/detail (statut) -> si validé : initialize -> create_cardholder
-> create_card. Affiche CHAQUE réponse brute pour verrouiller les champs.

⚠️ Écritures réelles sur le compte démo. Usage : ./venv/bin/python simulate_kyc_flow.py
"""
import base64
import json
import sys
import time

from interlace_v3 import InterlaceV3, InterlaceV3Error

# Image PNG 1x1 valide (bidon) pour les uploads pièce/selfie.
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def show(tag, data):
    print(f"\n===== {tag} =====")
    try:
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2500])
    except Exception:
        print(repr(data)[:2000])


def main():
    c = InterlaceV3.from_params("config/params.json", mode="dev")
    print(f"base={c.base}  account(master)={c.account_id}")

    # 1) register sous-compte
    try:
        reg = c.register_subaccount(
            email="sim.kyc.test+nova@example.com", name="Jean Dupont",
            phone="+33612345678", parent_account_id=c.account_id)
    except InterlaceV3Error as e:
        print("❌ register échec:", e); sys.exit(1)
    show("1) REGISTER (cherche accountId)", reg)
    acc = (reg.get("id") or reg.get("accountId") or reg.get("account_id")) if isinstance(reg, dict) else None
    print("-> accountId =", acc)
    if not acc:
        print("❌ accountId introuvable — stop."); sys.exit(1)

    # 2) upload pièce (recto) + selfie
    try:
        up = c.upload_files(acc, [
            ("id_front.png", _PNG_1x1, "image/png"),
            ("selfie.png", _PNG_1x1, "image/png"),
        ])
    except InterlaceV3Error as e:
        print("❌ upload échec:", e); sys.exit(1)
    show("2) UPLOAD (cherche fileId)", up)

    # 3) submit KYC
    kyc = {
        "firstName": "Jean", "lastName": "Dupont", "dateOfBirth": "1990-05-21",
        "gender": "MALE", "nationality": "FR", "nationalId": "12AB34567",
        "idType": "PASSPORT", "issueDate": "2018-01-01", "expiryDate": "2030-01-01",
        "phoneNumber": "612345678", "phoneCountryCode": "33",
        "address": {"line1": "1 rue de Test", "city": "Paris", "country": "FR", "postalCode": "75001"},
        # idFrontId / selfie : à remplir depuis la réponse upload (forme à confirmer)
    }
    # tente d'injecter les fileId si on les trouve
    def _ids(d):
        if isinstance(d, list): return [x.get("id") or x.get("fileId") for x in d if isinstance(x, dict)]
        if isinstance(d, dict):
            for k in ("list", "files", "data"):
                if isinstance(d.get(k), list): return [x.get("id") or x.get("fileId") for x in d[k] if isinstance(x, dict)]
            return [d.get("id") or d.get("fileId")] if (d.get("id") or d.get("fileId")) else []
        return []
    fids = [f for f in _ids(up) if f]
    if len(fids) >= 2:
        kyc["idFrontId"], kyc["selfie"] = fids[0], fids[1]
        print("-> fileIds injectés:", fids[:2])
    else:
        print("⚠️ fileIds non extraits — submit KYC tentée sans (verra l'erreur de champs).")
    try:
        sk = c.submit_kyc(acc, kyc)
        show("3) SUBMIT KYC", sk)
    except InterlaceV3Error as e:
        print("3) SUBMIT KYC -> erreur:", e)

    # 4) statut KYC
    time.sleep(2)
    try:
        cdd = c.get_cdd_detail(acc)
        show("4) CDD / statut KYC", cdd)
    except InterlaceV3Error as e:
        print("4) cdd/detail -> erreur:", e)

    print("\n(Arrêt avant initialize/cardholder/create_card — on regarde d'abord "
          "le statut KYC. Si PASSED, on enchaîne la création de carte.)")


if __name__ == "__main__":
    main()
