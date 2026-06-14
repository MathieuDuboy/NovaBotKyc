# interlace/resources/models.py
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from sqlalchemy import create_engine

import config


# Core Resources
@dataclass
class Money:
    """Represents an Interlace Money object"""
    amount: str
    currency: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Money':
        return cls(
            amount=data.get('amount'),
            currency=data.get('currency')
        )


@dataclass
class Source:
    """Represents an Interlace Source object"""
    type: str
    currency: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Source':
        return cls(
            type=data.get('type'),
            currency=data.get('currency')
        )


@dataclass
class Destination:
    """Represents an Interlace Destination object"""
    type: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Destination':
        return cls(
            type=data.get('type')
        )


@dataclass
class Account:
    """Represents an Interlace Account object"""
    id: str
    type: str  # SubAccount, MasterAccount
    status: str  # Active, Frozen, Inactive
    name: str
    display_id: str
    kyc_status: str  # Pending, Request, Passed, Canceled, Na
    card_kyb_status: str  # Pending, Request, Passed, Canceled, Na
    create_time: datetime
    message: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Account':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            type=data.get('type', ''),
            status=data.get('status', ''),
            name=data.get('name', ''),
            display_id=data.get('displayId', ''),
            kyc_status=data.get('kycStatus', ''),
            card_kyb_status=data.get('cardKybStatus', ''),
            create_time=create_time,
            message=data.get('message')
        )


@dataclass
class User:
    """Represents an Interlace User object"""
    id: str
    create_time: datetime
    status: str  # Active, Frozen, Inactive
    phone: Optional[str] = None
    email: Optional[str] = None
    name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            create_time=create_time,
            status=data.get('status', ''),
            phone=data.get('phone'),
            email=data.get('email'),
            name=data.get('name')
        )


@dataclass
class FaceAuthentication:
    """Represents an Interlace Face Authentication object"""
    account_id: str
    status: str  # Na, Pending, Success, Fail
    reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FaceAuthentication':
        return cls(
            account_id=data.get('accountId', ''),
            status=data.get('status', ''),
            reason=data.get('reason', "")
        )


@dataclass
class Transfer:
    """Represents an Interlace Transfer object"""
    id: str
    account_id: str
    source: Source
    destination: Destination
    amount: Money
    fee: Money
    status: str  # Pending, Closed, Fail
    create_time: datetime
    update_time: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transfer':
        create_time_str = data.get('createTime', '')
        update_time_str = data.get('updateTime', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        update_time = (datetime.fromisoformat(update_time_str.replace('Z', '+00:00'))
                       if update_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            source=Source.from_dict(data.get('source', {})),
            destination=Destination.from_dict(data.get('destination', {})),
            amount=Money.from_dict(data.get('amount', {})),
            fee=Money.from_dict(data.get('fee', {})),
            status=data.get('status', ''),
            create_time=create_time,
            update_time=update_time
        )


@dataclass
class Balance:
    """Represents an Interlace Balance object"""
    id: str
    account_id: str
    available: float
    pending: float
    frozen: float
    currency: str
    create_time: datetime
    wallet_type: str  # Card, Budget, QuantumAccount, GlobalAccount, CryptoAsset

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Balance':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            available=float(data.get('available', 0)),
            pending=float(data.get('pending', 0)),
            frozen=float(data.get('frozen', 0)),
            currency=data.get('currency', ''),
            create_time=create_time,
            wallet_type=data.get('walletType', '')
        )


# Infinity Card Resources
@dataclass
class Budget:
    """Represents an Interlace Budget object"""
    id: str
    account_id: str
    name: str
    balance_id: str
    expiry_date: datetime
    status: str  # Active, Frozen, Inactive
    create_time: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Budget':
        create_time_str = data.get('createTime', '')
        expiry_date_str = data.get('expiryDate', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        expiry_date = (datetime.fromisoformat(expiry_date_str.replace('Z', '+00:00'))
                       if expiry_date_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            name=data.get('name', ''),
            balance_id=data.get('balanceId', ''),
            expiry_date=expiry_date,
            status=data.get('status', ''),
            create_time=create_time
        )


@dataclass
class Card:
    """Represents an Interlace Card object"""
    id: str
    account_id: str
    token: str
    status: str  # Active, Frozen, Inactive
    currency: str
    provider: str
    user_name: str
    create_time: datetime
    card_no_last_four: str
    balance_id: str
    card_address: Optional[str] = None
    label: Optional[str] = None
    budget_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Card':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            token=data.get('token', ''),
            status=data.get('status', ''),
            currency=data.get('currency', ''),
            provider=data.get('provider', ''),
            user_name=data.get('userName', ''),
            create_time=create_time,
            card_no_last_four=data.get('cardNoLastFour', ''),
            balance_id=data.get('balanceId', ''),
            card_address=data.get('cardAddress'),
            label=data.get('label'),
            budget_id=data.get('budgetId')
        )


@dataclass
class CardDetails:
    """Represents detailed information for an Interlace Card"""
    id: str
    account_id: str
    token: str
    status: str  # Active, Frozen, Inactive
    currency: str
    provider: str
    user_name: str
    create_time: datetime
    card_no_last_four: str
    balance_id: str
    card_no: str
    expiry_date: str
    cvv: str
    available_balance: float
    frozen_balance: float
    blocked: bool
    card_address: Optional[str] = None
    label: Optional[str] = None
    budget_id: Optional[str] = None
    pin: Optional[str] = None
    activation_date: Optional[datetime] = None
    expiration_date: Optional[datetime] = None
    daily_limit: Optional[float] = None
    monthly_limit: Optional[float] = None
    allowed_merchants: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CardDetails':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        activation_date_str = data.get('activationDate', '')
        activation_date = (datetime.fromisoformat(activation_date_str.replace('Z', '+00:00'))
                           if activation_date_str else None)

        expiration_date_str = data.get('expirationDate', '')
        expiration_date = (datetime.fromisoformat(expiration_date_str.replace('Z', '+00:00'))
                           if expiration_date_str else None)

        # Format expiry date from month and year
        exp_month = data.get('expMonth', '')
        exp_year = data.get('expYear', '')
        expiry_date = f"{exp_month}/{exp_year[-2:]}" if exp_month and exp_year else ''

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            token=data.get('token', ''),
            status=data.get('status', ''),
            currency=data.get('currency', ''),
            provider=data.get('provider', ''),
            user_name=data.get('userName', ''),
            create_time=create_time,
            card_no_last_four=data.get('cardNoLastFour', ''),
            balance_id=data.get('balanceId', ''),
            card_no=data.get('cardNo', ''),
            expiry_date=expiry_date,
            cvv=data.get('cvv', ''),
            available_balance=float(
                data.get(
                    'availableBalance',
                    0)),
            frozen_balance=float(
                data.get(
                    'frozenBalance',
                    0)),
            blocked=data.get('blocked', False),
            card_address=data.get('cardAddress'),
            label=data.get('label'),
            budget_id=data.get('budgetId'),
            pin=data.get('pin'),
            activation_date=activation_date,
            expiration_date=expiration_date,
            daily_limit=float(
                data.get(
                    'dailyLimit',
                    0)) if data.get('dailyLimit') else None,
            monthly_limit=float(
                data.get(
                    'monthlyLimit',
                    0)) if data.get('monthlyLimit') else None,
            allowed_merchants=data.get('allowedMerchants')
        )


@dataclass
class CardTransaction:
    """Represents an Interlace Card Transaction object

    Fields match the Interlace API specification from:
    https://developer.interlace.money/reference/getcardtransaction
    """
    id: str
    account_id: str
    card_id: str
    currency: str
    amount: float
    fee: float
    type: str  # Consumption, TransferIn, TransferOut, Credit, Reversal, Frozen, UnFrozen
    client_transaction_id: Optional[str]
    status: str  # Pending, Closed, Fail
    transaction_time: datetime
    create_time: datetime
    detail: Optional[str]
    remark: Optional[str]
    transaction_currency: Optional[str]
    transaction_amount: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the transaction to a dictionary format suitable for pandas DataFrame."""
        return {
            'id': self.id,
            'account_id': self.account_id,
            'card_id': self.card_id,
            'currency': self.currency,
            'amount': self.amount,
            'fee': self.fee,
            'type': self.type,
            'client_transaction_id': self.client_transaction_id,
            'status': self.status,
            'transaction_time': self.transaction_time,
            'create_time': self.create_time,
            'detail': self.detail,
            'remark': self.remark,
            'transaction_currency': self.transaction_currency,
            'transaction_amount': self.transaction_amount
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CardTransaction':
        """Create a CardTransaction instance from a dictionary.

        Args:
            data: Dictionary containing transaction data from Interlace API

        Returns:
            CardTransaction instance
        """
        # Parse datetime fields with proper timezone handling
        def parse_datetime(dt_str: str) -> datetime:
            if not dt_str:
                return datetime.now(timezone.utc)
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            card_id=data.get('cardId', ''),
            currency=data.get('currency', ''),
            amount=float(data.get('amount', 0)),
            fee=float(data.get('fee', 0)),
            type=data.get('type', ''),
            client_transaction_id=data.get('clientTransactionId'),
            status=data.get('status', ''),
            transaction_time=parse_datetime(data.get('transactionTime', '')),
            create_time=parse_datetime(data.get('createTime', '')),
            detail=data.get('detail'),
            remark=data.get('remark'),
            transaction_currency=data.get('transactionCurrency', ''),
            transaction_amount=float(data.get('transactionAmount', 0))
        )


@dataclass
class Fee:
    """Represents an Interlace Fee object"""
    amount: str
    currency: str
    fee_type: str  # HANDLING

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Fee':
        return cls(
            amount=data.get('amount', ''),
            currency=data.get('currency', ''),
            fee_type=data.get('feeType', '')
        )


@dataclass
class RefundInfo:
    """Represents an Interlace Refund object"""
    amount: str
    currency: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RefundInfo':
        return cls(
            amount=data.get('amount', ''),
            currency=data.get('currency', '')
        )


@dataclass
class Payment:
    """Represents an Interlace Payment object"""
    client_transaction_id: str
    business_id: str
    business_type: str  # GLOBAL_ACCOUNT, CRYPTO_ASSET
    balance_id: str
    payee_id: str
    from_amount: float
    from_currency: str
    to_amount: float
    to_currency: str
    status: str  # PENDING, CLOSED, FAIL
    message: str
    create_time: int  # timestamp in milliseconds
    fees: Fee
    refund: Optional[RefundInfo] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Payment':
        return cls(
            client_transaction_id=data.get('clientTransactionId', ''),
            business_id=data.get('businessId', ''),
            business_type=data.get('businessType', ''),
            balance_id=data.get('balanceId', ''),
            payee_id=data.get('payeeId', ''),
            from_amount=float(data.get('fromAmount', 0)),
            from_currency=data.get('fromCurrency', ''),
            to_amount=float(data.get('toAmount', 0)),
            to_currency=data.get('toCurrency', ''),
            status=data.get('status', ''),
            message=data.get('message', ''),
            create_time=int(data.get('createTime', 0)),
            fees=Fee.from_dict(data.get('fees', {})),
            refund=(RefundInfo.from_dict(data.get('refund', {}))
                    if data.get('refund') else None)
        )


@dataclass
class Acquiring:
    """Represents an Interlace Acquiring object"""
    trade_no: str
    merchant_trade_no: str
    currency: str
    amount: str
    status: str  # PENDING, READY, PAID, FAILED, etc.
    transaction_type: str  # PAYMENT, REFUND
    create_time: str
    complete_time: str
    channel_id: str
    merchant_customer_id: str
    sub_merchant_id: str
    description: str
    error_code: Optional[str] = None
    error_msg: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Acquiring':
        return cls(
            trade_no=data.get('tradeNo', ''),
            merchant_trade_no=data.get('merchantTradeNo', ''),
            currency=data.get('currency', ''),
            amount=data.get('amount', ''),
            status=data.get('status', ''),
            transaction_type=data.get('transactionType', ''),
            create_time=data.get('createTime', ''),
            complete_time=data.get('completeTime', ''),
            channel_id=data.get('channelId', ''),
            merchant_customer_id=data.get('merchantCustomerId', ''),
            sub_merchant_id=data.get('subMerchantId', ''),
            description=data.get('description', ''),
            error_code=data.get('errorCode'),
            error_msg=data.get('errorMsg')
        )


@dataclass
class BudgetTransaction:
    """Represents an Interlace Budget Transaction object"""
    id: str
    budget_id: str
    amount: float
    currency: str
    transaction_type: str  # EXPENSE, INCOME, TRANSFER
    status: str  # PENDING, COMPLETED, FAILED
    create_time: datetime
    update_time: Optional[datetime] = None
    description: Optional[str] = None
    reference_id: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BudgetTransaction':
        create_time_str = data.get('createTime', '')
        update_time_str = data.get('updateTime', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        update_time = (datetime.fromisoformat(update_time_str.replace('Z', '+00:00'))
                       if update_time_str else None)

        return cls(
            id=data.get('id', ''),
            budget_id=data.get('budgetId', ''),
            amount=float(data.get('amount', 0)),
            currency=data.get('currency', ''),
            transaction_type=data.get('transactionType', ''),
            status=data.get('status', ''),
            create_time=create_time,
            update_time=update_time,
            description=data.get('description'),
            reference_id=data.get('referenceId')
        )


@dataclass
class Cardholder:
    """Represents an Interlace Cardholder object"""
    id: str
    account_id: str
    first_name: str
    last_name: str
    status: str  # ACTIVE, INACTIVE
    create_time: datetime
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[Dict[str, str]] = None
    date_of_birth: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Cardholder':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            first_name=data.get('firstName', ''),
            last_name=data.get('lastName', ''),
            status=data.get('status', ''),
            create_time=create_time,
            email=data.get('email'),
            phone=data.get('phone'),
            address=data.get('address'),
            date_of_birth=data.get('dateOfBirth')
        )


@dataclass
class BankAccount:
    """Represents an Interlace Bank Account object"""
    id: str
    account_id: str
    account_number: str
    bank_name: str
    status: str  # ACTIVE, PENDING, SUSPENDED
    create_time: datetime
    currency: str
    account_type: Optional[str] = None  # CHECKING, SAVINGS
    routing_number: Optional[str] = None
    swift_code: Optional[str] = None
    iban: Optional[str] = None
    bank_code: Optional[str] = None
    bank_address: Optional[Dict[str, str]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BankAccount':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            account_number=data.get('accountNumber', ''),
            bank_name=data.get('bankName', ''),
            status=data.get('status', ''),
            create_time=create_time,
            currency=data.get('currency', ''),
            account_type=data.get('accountType'),
            routing_number=data.get('routingNumber'),
            swift_code=data.get('swiftCode'),
            iban=data.get('iban'),
            bank_code=data.get('bankCode'),
            bank_address=data.get('bankAddress')
        )


@dataclass
class GlobalAccountTransaction:
    """Represents an Interlace Global Account Transaction object"""
    id: str
    account_id: str
    amount: float
    currency: str
    transaction_type: str  # DEPOSIT, WITHDRAWAL, TRANSFER
    status: str  # PENDING, COMPLETED, FAILED
    create_time: datetime
    update_time: Optional[datetime] = None
    reference_id: Optional[str] = None
    bank_account_id: Optional[str] = None
    fee: Optional[Money] = None
    description: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GlobalAccountTransaction':
        create_time_str = data.get('createTime', '')
        update_time_str = data.get('updateTime', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        update_time = (datetime.fromisoformat(update_time_str.replace('Z', '+00:00'))
                       if update_time_str else None)

        # Handle fee object if present
        fee = Money.from_dict(data.get('fee')) if data.get('fee') else None

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            amount=float(data.get('amount', 0)),
            currency=data.get('currency', ''),
            transaction_type=data.get('transactionType', ''),
            status=data.get('status', ''),
            create_time=create_time,
            update_time=update_time,
            reference_id=data.get('referenceId'),
            bank_account_id=data.get('bankAccountId'),
            fee=fee,
            description=data.get('description')
        )


@dataclass
class Wallet:
    """Represents an Interlace Crypto Wallet object"""
    id: str
    account_id: str
    address: str
    chain: str  # ETH, TRX, BTC, etc.
    currency: str  # USDT, USDC, BTC, ETH, etc.
    create_time: datetime
    status: str  # ACTIVE, INACTIVE
    label: Optional[str] = None
    balance: Optional[float] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Wallet':
        create_time_str = data.get('createTime', '')
        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            address=data.get('address', ''),
            chain=data.get('chain', ''),
            currency=data.get('currency', ''),
            create_time=create_time,
            status=data.get('status', ''),
            label=data.get('label'),
            balance=float(data.get('balance', 0)) if data.get('balance') else None
        )


@dataclass
class Deposit:
    """Represents an Interlace Deposit object"""
    id: str
    account_id: str
    transaction_hash: str
    amount: float
    currency: str
    chain: str
    wallet_id: str
    status: str  # PENDING, CONFIRMED, COMPLETED, FAILED
    create_time: datetime
    update_time: Optional[datetime] = None
    confirmation_count: Optional[int] = None
    total_confirmations_required: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Deposit':
        create_time_str = data.get('createTime', '')
        update_time_str = data.get('updateTime', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        update_time = (datetime.fromisoformat(update_time_str.replace('Z', '+00:00'))
                       if update_time_str else None)

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            transaction_hash=data.get('transactionHash', ''),
            amount=float(data.get('amount', 0)),
            currency=data.get('currency', ''),
            chain=data.get('chain', ''),
            wallet_id=data.get('walletId', ''),
            status=data.get('status', ''),
            create_time=create_time,
            update_time=update_time,
            confirmation_count=data.get('confirmationCount'),
            total_confirmations_required=data.get('totalConfirmationsRequired')
        )


@dataclass
class Withdrawal:
    """Represents an Interlace Withdrawal object"""
    id: str
    account_id: str
    destination_address: str
    amount: float
    currency: str
    chain: str
    status: str  # PENDING, PROCESSING, COMPLETED, FAILED
    create_time: datetime
    update_time: Optional[datetime] = None
    transaction_hash: Optional[str] = None
    fee: Optional[Money] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Withdrawal':
        create_time_str = data.get('createTime', '')
        update_time_str = data.get('updateTime', '')

        create_time = (datetime.fromisoformat(create_time_str.replace('Z', '+00:00'))
                       if create_time_str else datetime.now())
        update_time = (datetime.fromisoformat(update_time_str.replace('Z', '+00:00'))
                       if update_time_str else None)

        # Handle fee object if present
        fee = Money.from_dict(data.get('fee')) if data.get('fee') else None

        return cls(
            id=data.get('id', ''),
            account_id=data.get('accountId', ''),
            destination_address=data.get('destinationAddress', ''),
            amount=float(data.get('amount', 0)),
            currency=data.get('currency', ''),
            chain=data.get('chain', ''),
            status=data.get('status', ''),
            create_time=create_time,
            update_time=update_time,
            transaction_hash=data.get('transactionHash'),
            fee=fee
        )
