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

    def list_wallets(self, account_id: Optional[str] = None) -> List[dict]:
        """Soldes d'un compte. objectType : 0=Infinity, 1=Budget, 2=carte prépayée.
        GET /open-api/v3/cards/wallets — VALIDÉ live."""
        acc = account_id or self.account_id
        data = self._request("GET", "/open-api/v3/cards/wallets", params={"accountId": acc})
        return data.get("list", []) if isinstance(data, dict) else (data or [])

    def get_infinity_wallet(self, account_id: Optional[str] = None) -> Optional[dict]:
        """Le wallet Infinity (objectType 0) d'un compte : {id(=balanceId), available, currency}."""
        for w in self.list_wallets(account_id):
            if w.get("objectType") == 0 or w.get("walletType") == 0:
                return w
        return None

    # ── ÉCRITURES — flux GATEWAY consumer (validé live, cf. doc gateway-consumer-use)
    # Parcours : 2.1 register sous-compte -> 2.2 KYC sous-compte (PASS requis)
    #            -> 5 cardholder (sur le sous-compte) -> 6 prepaid-card.
    def register_subaccount(self, *, email: str, name: str, parent_account_id: str,
                            phone_number: Optional[str] = None,
                            phone_country_code: Optional[str] = None) -> dict:
        """Step 2.1 — crée un sous-compte (sous-marchand) sous le compte maître.
        VALIDÉ live : POST /open-api/v3/accounts/register -> {id, displayId, status:'ACTIVE'}."""
        body: Dict[str, Any] = {"email": email, "name": name,
                                "parentAccountId": parent_account_id}
        if phone_number:
            body["phoneNumber"] = phone_number
        if phone_country_code:
            body["phoneCountryCode"] = phone_country_code
        return self._request("POST", "/open-api/v3/accounts/register", json_body=body)

    def upload_files(self, account_id: str, file_tuples: List[Tuple[str, bytes, str]]) -> Any:
        """file_tuples : liste de (filename, contenu_bytes, content_type). Renvoie les fileId."""
        files = [("files", (fn, content, ct)) for (fn, content, ct) in file_tuples]
        return self._request("POST", "/open-api/v3/files/upload",
                             data={"accountId": account_id}, files=files)

    def initialize_account(self, account_id: str) -> Any:
        """Provisionne l'Infinity account d'un sous-compte (après KYC PASSED).
        VALIDÉ live : POST /open-api/v2/accounts/{id}/initialization -> true.
        Sans ça, créer une carte échoue (010021 'account balance does not exist')."""
        return self._request("POST", f"/open-api/v2/accounts/{account_id}/initialization")

    def transfer_external(self, *, from_account: str, from_balance_id: str,
                          to_account: str, to_balance_id: str, amount,
                          client_tx_id: str, currency: str = "USD") -> Any:
        """Transfert entre comptes (maître -> sous-compte). VALIDÉ live (code 000000,
        status CLOSED, fee 0). POST /open-api/v3/business/transfer/external.
        businessType 0 = Infinity account de part et d'autre."""
        return self._request("POST", "/open-api/v3/business/transfer/external", json_body={
            "clientTransactionId": client_tx_id, "amount": str(amount),
            "from": {"id": from_balance_id, "accountId": from_account,
                     "currency": currency, "businessType": 0},
            "to": {"id": to_balance_id, "accountId": to_account,
                   "currency": currency, "businessType": 0},
        })

    def submit_account_kyc(self, account_id: str, kyc: dict) -> Any:
        """Step 2.2 — soumet le KYC du sous-compte. VALIDÉ live.
        kyc attend : firstName, lastName, dateOfBirth (YYYY-MM-DD), gender ('M'/'F'),
        nationality (ISO-2), nationalId, idType (PASSPORT…), issueDate, expiryDate,
        address {addressLine1, city, state, country, postalCode}, idFrontId, selfie,
        phoneNumber, phoneCountryCode ; ssn (9 chiffres) OBLIGATOIRE si adresse US ;
        idBackId optionnel. Renvoie {caseId, accountId, status:'PENDING'}."""
        payload = {"sourceType": "api", **kyc}
        return self._request("POST", f"/open-api/v3/accounts/{account_id}/kyc", json_body=payload)

    # alias rétro-compat
    submit_kyc = submit_account_kyc

    def simulate_kyc_review(self, account_id: str, status: str = "Passed",
                            message: str = "sandbox") -> Any:
        """SANDBOX uniquement — force le résultat KYC d'un sous-compte (Passed/Canceled).
        ⚠️ Renvoie actuellement code 902 sur notre compte (flag à activer côté Interlace)."""
        return self._request("POST", "/open-api/v3/vcc/simulate/kyc/review",
                             json_body={"accountId": account_id, "status": status,
                                        "message": message})

    def create_cardholder(self, *, account_id: str, bin_id: str, profile: dict,
                          tier: str = "CONSUMER") -> Any:
        """Step 5 — crée un cardholder sur un sous-compte DÉJÀ KYC-PASSED (mode Gateway).
        tier = 'CONSUMER'. Le KYC étant porté par le sous-compte, le cardholder est léger.
        Si le sous-compte n'est pas PASSED -> 'No KYC information (010787)'.
        profile : firstName, lastName, email, dob, gender, nationality, phoneNumber,
        phoneCountryCode, address (+ nationalId/idType si exigés). À VALIDER live sur
        un sous-compte PASSED. Renvoie {id (cardholderId), status, cardBinList}."""
        body: Dict[str, Any] = {
            "accountId": account_id, "binId": bin_id, "cardholderTier": tier,
            "firstName": profile["firstName"], "lastName": profile["lastName"],
            "email": profile.get("email"), "dob": profile.get("dob"),
            "gender": profile.get("gender"), "nationality": profile.get("nationality"),
            "phoneNumber": profile.get("phoneNumber"),
            "phoneCountryCode": profile.get("phoneCountryCode"),
        }
        if profile.get("address"):
            body["address"] = profile["address"]
        for k in ("nationalId", "idType", "issueDate", "expiryDate", "occupation"):
            if profile.get(k):
                body[k] = profile[k]
        return self._request("POST", "/open-api/v3/cardholders",
                             json_body={k: v for k, v in body.items() if v is not None})

    def get_cardholder(self, cardholder_id: str, account_id: Optional[str] = None) -> dict:
        """Statut du cardholder (PENDING/ACTIVE/INACTIVE + rejectReason)."""
        return self._request("GET", f"/open-api/v3/cardholders/{cardholder_id}",
                             params={"accountId": account_id or self.account_id})

    def list_cardholders(self, account_id: str, page: int = 1, limit: int = 10) -> List[dict]:
        """Cardholders d'un sous-compte (1 sous-compte = 1 cardholder en consumer).
        Sert à récupérer un cardholder déjà créé (idempotence/orphelin)."""
        data = self._request("GET", "/open-api/v3/cardholders",
                             params={"accountId": account_id, "page": str(page), "limit": str(limit)})
        return data.get("list", []) if isinstance(data, dict) else (data or [])

    def create_prepaid_card(self, *, account_id: str, bin_id: str, cardholder_id: str,
                            reference_id: str, idempotency_key: str,
                            card_mode: str = "VIRTUAL_CARD", amount: Optional[float] = None,
                            use_type: Optional[str] = None, label: Optional[str] = None) -> Any:
        """Step 6.1 — émet une carte prépayée. POST /open-api/v3/prepaid-card.
        card_mode : 'VIRTUAL_CARD' | 'PHYSICAL_CARD'. referenceId = id unique côté nous.
        Header Idempotency-Key requis. À VALIDER live (besoin d'un cardholder approuvé)."""
        body: Dict[str, Any] = {
            "accountId": account_id, "binId": bin_id, "cardholderId": cardholder_id,
            "referenceId": reference_id, "cardMode": card_mode,
        }
        if amount is not None:
            body["amount"] = amount
        if use_type:
            body["useType"] = use_type
        if label:
            body["label"] = label
        headers = {"x-access-token": self._ensure_token(),
                   "Idempotency-Key": idempotency_key}
        url = f"{self.base}/open-api/v3/prepaid-card"
        r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            raise InterlaceV3Error(f"POST /open-api/v3/prepaid-card: HTTP {r.status_code}: {r.text[:200]}",
                                   http=r.status_code)
        if isinstance(j, dict) and "code" in j and j.get("code") not in (None, "000000", 0, "0"):
            raise InterlaceV3Error(f"POST /open-api/v3/prepaid-card: {j.get('message')} (code {j.get('code')})",
                                   code=str(j.get("code")), http=r.status_code)
        return j.get("data", j) if isinstance(j, dict) else j

    def card_transfer_in(self, *, account_id: str, card_id: str, amount,
                         client_tx_id: str) -> Any:
        """Recharge la carte depuis l'Infinity account du sous-compte.
        POST /open-api/v3/cards/transfer-in {accountId, cardId, clientTransactionId, amount}."""
        return self._request("POST", "/open-api/v3/cards/transfer-in", json_body={
            "accountId": account_id, "cardId": card_id,
            "clientTransactionId": client_tx_id, "amount": str(amount)})

    def card_transfer_out(self, *, account_id: str, card_id: str, amount,
                          client_tx_id: str) -> Any:
        """Retire des fonds de la carte vers l'Infinity account du sous-compte.
        VALIDÉ live : POST /open-api/v3/cards/transfer-out (fee 0, status CLOSED)."""
        return self._request("POST", "/open-api/v3/cards/transfer-out", json_body={
            "accountId": account_id, "cardId": card_id,
            "clientTransactionId": client_tx_id, "amount": str(amount)})

    def card_balance(self, account_id: str, card_id: Optional[str] = None) -> Optional[dict]:
        """Wallet d'une carte prépayée (objectType 2). Si card_id, filtre dessus."""
        for w in self.list_wallets(account_id):
            if w.get("objectType") == 2:
                return w
        return None

    # ── vérif signature webhook ───────────────────────────────────────────────
    @staticmethod
    def verify_webhook_signature(resource: str, signature_header: str, client_secret: str) -> bool:
        """resource = champ `resource` brut du payload (string). Signature = Base64(HMAC-SHA256)."""
        if not signature_header:
            return False
        digest = hmac.new(client_secret.encode(), resource.encode(), hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return hmac.compare_digest(expected, signature_header)
