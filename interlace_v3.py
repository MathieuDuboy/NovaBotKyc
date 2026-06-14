"""
Client Interlace API v3 (mode CONSUMER / gateway) — propre, autonome.
Remplace l'ancien module v1 `interlace/`. Auth OAuth2 + header x-access-token.
Couvre le flux : register -> upload -> submit KYC -> initialize -> cardholder -> card,
+ lectures (bins, cdd) + vérif de signature des webhooks.

Réf : interlace_bot/INTERLACE_V3_KYC_MAP.md
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


class InterlaceV3Error(Exception):
    def __init__(self, message: str, *, code: Optional[str] = None, http: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.http = http


class InterlaceV3:
    """Client v3. Gère l'access-token (cache + renouvellement automatique)."""

    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 account_id: Optional[str] = None, timeout: int = 30):
        pu = urlparse(base_url if "://" in base_url else "https://" + base_url)
        self.base = f"{pu.scheme}://{pu.netloc}" if pu.netloc else base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.account_id = account_id
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_exp: float = 0.0

    # ── construction depuis params.json ──────────────────────────────────────
    @classmethod
    def from_params(cls, params_path: str = "config/params.json", mode: str = "dev") -> "InterlaceV3":
        p = json.load(open(params_path))
        il = p["interlace"][mode]
        return cls(il["base_url"], il["client_id"], il["client_secret"], il.get("account_id"))

    # ── auth OAuth2 (authorize -> access-token) ───────────────────────────────
    def _authenticate(self) -> None:
        r = requests.get(f"{self.base}/open-api/oauth/authorize",
                         params={"clientId": self.client_id}, timeout=self.timeout,
                         allow_redirects=False)
        code = None
        try:
            code = r.json().get("code")
        except Exception:
            pass
        if not code:
            raise InterlaceV3Error(f"authorize: pas de code (HTTP {r.status_code}): {r.text[:200]}",
                                   http=r.status_code)
        r = requests.post(f"{self.base}/open-api/oauth/access-token",
                          json={"clientId": self.client_id, "clientSecret": self.client_secret,
                                "code": code}, timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            raise InterlaceV3Error(f"access-token: réponse non-JSON (HTTP {r.status_code})", http=r.status_code)
        tok = j.get("accessToken") or (j.get("data") or {}).get("accessToken")
        if not tok:
            raise InterlaceV3Error(f"access-token: pas d'accessToken: {r.text[:200]}", http=r.status_code)
        self._token = tok
        # marge de sécurité de 5 min avant l'expiration réelle
        self._token_exp = time.monotonic() + float(j.get("expiresIn", 86400)) - 300

    def _ensure_token(self) -> str:
        if not self._token or time.monotonic() >= self._token_exp:
            self._authenticate()
        return self._token  # type: ignore[return-value]

    # ── couche requête signée ─────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, params: Optional[dict] = None,
                 json_body: Optional[dict] = None, files=None, data=None) -> Any:
        headers = {"x-access-token": self._ensure_token()}
        url = f"{self.base}{path}"
        r = requests.request(method, url, headers=headers, params=params, json=json_body,
                             files=files, data=data, timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            if not r.ok:
                raise InterlaceV3Error(f"{method} {path}: HTTP {r.status_code}: {r.text[:200]}", http=r.status_code)
            return r.text
        # enveloppe {code, message, data}
        if isinstance(j, dict) and "code" in j and j.get("code") not in (None, "000000", 0, "0"):
            raise InterlaceV3Error(f"{method} {path}: {j.get('message')} (code {j.get('code')})",
                                   code=str(j.get("code")), http=r.status_code)
        if not r.ok:
            raise InterlaceV3Error(f"{method} {path}: HTTP {r.status_code}: {r.text[:200]}", http=r.status_code)
        return j.get("data", j) if isinstance(j, dict) else j

    # ── LECTURES (validées live) ──────────────────────────────────────────────
    def get_cdd_detail(self, account_id: Optional[str] = None) -> dict:
        acc = account_id or self.account_id
        return self._request("GET", f"/open-api/v3/accounts/cdd/detail/{acc}")

    def list_bins(self, account_id: Optional[str] = None, limit: int = 100, page: int = 1) -> List[dict]:
        acc = account_id or self.account_id
        data = self._request("GET", "/open-api/v3/card/bins",
                             params={"accountId": acc, "limit": str(limit), "page": str(page)})
        return data.get("list", []) if isinstance(data, dict) else (data or [])

    # ── ÉCRITURES (flux consumer) ─────────────────────────────────────────────
    def register_subaccount(self, email: str, name: str, phone: Optional[str] = None,
                            parent_account_id: Optional[str] = None) -> dict:
        body = {"email": email, "name": name}
        if phone:
            body["phone"] = phone
        if parent_account_id:
            body["parentAccountId"] = parent_account_id
        return self._request("POST", "/open-api/v1/accounts/register", json_body=body)

    def upload_files(self, account_id: str, file_tuples: List[Tuple[str, bytes, str]]) -> Any:
        """file_tuples : liste de (filename, contenu_bytes, content_type). Renvoie les fileId."""
        files = [("files", (fn, content, ct)) for (fn, content, ct) in file_tuples]
        return self._request("POST", "/open-api/v3/files/upload",
                             data={"accountId": account_id}, files=files)

    def submit_kyc(self, account_id: str, kyc: dict) -> Any:
        payload = {"sourceType": "api", **kyc}
        return self._request("POST", f"/open-api/v3/accounts/{account_id}/kyc", json_body=payload)

    def initialize_account(self, account_id: str) -> Any:
        return self._request("POST", f"/open-api/v2/accounts/{account_id}/initialization")

    def create_cardholder(self, *, account_id: str, bin_id: str, profile: dict,
                          id_front_id: str, selfie_id: str,
                          id_back_id: Optional[str] = None, tier: str = "CONSUMER") -> Any:
        """Crée un cardholder (KYC inclus) — schéma ConsumerMor v3 VALIDÉ live.

        profile attend : firstName, lastName, email, dob (YYYY-MM-DD), gender ("M"/"F"),
        nationality (ISO-2), nationalId, idType (ex. PASSPORT), phoneNumber,
        phoneCountryCode, address {addressLine1, city, state (≤2 car.), country (ISO-2),
        postalCode, addressLine2?} ; optionnels : issueDate, expiryDate, occupation.
        ⚠️ Le BIN impose le pays de l'adresse (ex. BIN 556766 = adresse US obligatoire).
        Renvoie data {id (cardholderId), status (PENDING/...), ...}."""
        body = {
            "accountId": account_id, "binId": bin_id, "cardholderTier": tier,
            "firstName": profile["firstName"], "lastName": profile["lastName"],
            "email": profile["email"], "dob": profile["dob"], "gender": profile["gender"],
            "nationality": profile["nationality"], "nationalId": profile["nationalId"],
            "idType": profile["idType"], "address": profile["address"],
            "phoneNumber": profile["phoneNumber"], "phoneCountryCode": profile["phoneCountryCode"],
            "idFrontId": id_front_id, "selfie": selfie_id,
        }
        for k in ("issueDate", "expiryDate", "occupation"):
            if profile.get(k):
                body[k] = profile[k]
        if id_back_id:
            body["idBackId"] = id_back_id
        return self._request("POST", "/open-api/v3/cardholders", json_body=body)

    def get_cardholder(self, cardholder_id: str, account_id: Optional[str] = None) -> dict:
        """Statut KYC du cardholder (PENDING/PASSED/REJECTED + rejectReason)."""
        return self._request("GET", f"/open-api/v3/cardholders/{cardholder_id}",
                             params={"accountId": account_id or self.account_id})

    def create_card(self, *, bin: str, cardholder_id: str, use_type: str = "Virtual card",
                    batch_count: int = 1, account_id: Optional[str] = None,
                    cost: Optional[float] = None, label: Optional[str] = None,
                    client_transaction_id: Optional[str] = None) -> Any:
        body: Dict[str, Any] = {
            "type": "PrepaidCard", "bin": bin, "batchCount": batch_count,
            "useType": use_type, "cardholderId": cardholder_id, "cardMode": "VirtualCard",
        }
        if account_id or self.account_id:
            body["accountId"] = account_id or self.account_id
        if cost is not None:
            body["cost"] = cost
        if label:
            body["label"] = label
        if client_transaction_id:
            body["clientTransactionId"] = client_transaction_id
        return self._request("POST", "/open-api/v2/cards", json_body=body)

    # ── vérif signature webhook ───────────────────────────────────────────────
    @staticmethod
    def verify_webhook_signature(resource: str, signature_header: str, client_secret: str) -> bool:
        """resource = champ `resource` brut du payload (string). Signature = Base64(HMAC-SHA256)."""
        if not signature_header:
            return False
        digest = hmac.new(client_secret.encode(), resource.encode(), hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, signature_header)
