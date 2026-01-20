"""
MongoDB models and fee configuration for Solana Agent referral system.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import secrets
import string
from nanoid import generate


# =============================================================================



# =============================================================================
# FEE CONFIGURATION
# =============================================================================

PLATFORM_FEE = 0.005          # 0.5% flat fee on all trades
JUPITER_SPLIT = 0.20          # Jupiter takes 20% of fee
PLATFORM_SPLIT = 0.55         # Platform takes 55% of remaining 80%
REFERRER_SPLIT = 0.25         # Referrer takes 25% of remaining 80%
REFERRAL_CAP = 300.0          # $300 lifetime cap per referral


def generate_referral_code(length: int = 8) -> str:
    """Generate a unique referral code."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def calculate_fee_split(volume_usd: float, has_referrer: bool, referrer_capped: bool) -> dict:
    """
    Calculate the fee split for a trade.
    
    Args:
        volume_usd: Trade volume in USD
        has_referrer: Whether the user has a referrer
        referrer_capped: Whether the referrer has hit their cap
    
    Returns:
        Dict with fee breakdown
    """
    gross_fee = volume_usd * PLATFORM_FEE
    jupiter_amount = gross_fee * JUPITER_SPLIT
    remaining = gross_fee * (1 - JUPITER_SPLIT)  # 80% of gross
    
    if has_referrer and not referrer_capped:
        platform_amount = remaining * PLATFORM_SPLIT
        referrer_amount = remaining * REFERRER_SPLIT
    else:
        # No referrer or capped - platform keeps referrer's share
        platform_amount = remaining * (PLATFORM_SPLIT + REFERRER_SPLIT)
        referrer_amount = 0.0
    
    return {
        "gross_fee": gross_fee,
        "jupiter_amount": jupiter_amount,
        "platform_amount": platform_amount,
        "referrer_amount": referrer_amount,
    }


# =============================================================================
# PYDANTIC MODELS (for API validation)
# =============================================================================

class UserCreate(BaseModel):
    privy_id: str
    wallet_address: str
    wallet_id: Optional[str] = None
    user_id: Optional[str] = None
    tg_user_id: Optional[int] = None
    referred_by_code: Optional[str] = None  # Referral code used at signup


class UserResponse(BaseModel):
    privy_id: str
    wallet_address: str
    wallet_id: Optional[str] = None
    user_id: Optional[str] = None
    tg_user_id: Optional[int] = None
    referral_code: str
    referred_by: Optional[str] = None
    volume_30d: float = 0.0
    created_at: datetime
    last_trade_at: Optional[datetime] = None


class ReferralStats(BaseModel):
    referral_code: str
    referral_link: str
    total_referrals: int
    total_earned: float
    pending_payout: float
    referrals: list  # List of referee stats


class SwapRecord(BaseModel):
    tx_signature: str
    user_privy_id: str
    wallet_address: str
    input_token: str
    input_amount: float
    output_token: str
    output_amount: float
    volume_usd: float
    fee_amount_usd: float
    jupiter_amount: float
    platform_amount: float
    referrer_privy_id: Optional[str] = None
    referrer_amount: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HeliusWebhookPayload(BaseModel):
    """Helius enhanced webhook payload for swap transactions."""
    signature: str
    type: str  # "SWAP"
    timestamp: int
    slot: int
    fee: int
    feePayer: str
    nativeTransfers: list
    tokenTransfers: list
    accountData: list
    events: dict  # Contains swap details


# =============================================================================
# MONGODB DOCUMENT SCHEMAS
# =============================================================================

def user_document(
    privy_id: str,
    wallet_address: Optional[str] = None,
    wallet_id: Optional[str] = None,
    user_id: Optional[str] = None,
    tg_user_id: Optional[int] = None,
    tg_username: Optional[str] = None,
    referred_by: Optional[str] = None,
) -> dict:
    """Create a user document for MongoDB."""
    doc = {
        "privy_id": privy_id,
        "created_at": datetime.utcnow(),
        "referral_code": generate_referral_code(),
        "volume_30d": 0.0,
        "last_trade_at": None,
        "wallet_address": None,
        "wallet_id": None,
        "user_id": None,
        "tg_user_id": None,
        "tg_username": None,
        "referred_by": None,
    }
    
    if wallet_address:
        doc["wallet_address"] = wallet_address

    if wallet_id:
        doc["wallet_id"] = wallet_id

    if user_id:
        doc["user_id"] = user_id
    
    if tg_user_id:
        doc["tg_user_id"] = tg_user_id
        
    if tg_username:
        doc["tg_username"] = tg_username
        
    if referred_by:
        doc["referred_by"] = referred_by
        
    return doc


def referral_document(
    referrer_privy_id: str,
    referee_privy_id: str,
) -> dict:
    """Create a referral tracking document for MongoDB."""
    return {
        "referrer_privy_id": referrer_privy_id,
        "referee_privy_id": referee_privy_id,
        "total_earned": 0.0,
        "cap": REFERRAL_CAP,
        "capped": False,
        "created_at": datetime.utcnow(),
        "capped_at": None,
    }


def swap_document(
    tx_signature: str,
    user_privy_id: str,
    wallet_address: str,
    input_token: str,
    input_amount: float,
    output_token: str,
    output_amount: float,
    volume_usd: float,
    fee_split: dict,
    referrer_privy_id: Optional[str] = None,
) -> dict:
    """Create a swap document for MongoDB."""
    return {
        "tx_signature": tx_signature,
        "user_privy_id": user_privy_id,
        "wallet_address": wallet_address,
        "input_token": input_token,
        "input_amount": input_amount,
        "output_token": output_token,
        "output_amount": output_amount,
        "volume_usd": volume_usd,
        "fee_amount_usd": fee_split["gross_fee"],
        "jupiter_amount": fee_split["jupiter_amount"],
        "platform_amount": fee_split["platform_amount"],
        "referrer_privy_id": referrer_privy_id,
        "referrer_amount": fee_split["referrer_amount"],
        "created_at": datetime.utcnow(),
    }


def payout_document(
    privy_id: str,
    wallet_address: str,
    amount_usd: float,
    amount_agent: float,
    tx_signature: Optional[str] = None,
) -> dict:
    """Create a payout document for MongoDB."""
    return {
        "privy_id": privy_id,
        "wallet_address": wallet_address,
        "amount_usd": amount_usd,
        "amount_agent": amount_agent,
        "tx_signature": tx_signature,
        "status": "pending",  # pending | sent | failed
        "created_at": datetime.utcnow(),
        "sent_at": None,
    }


def daily_volume_document(
    user_privy_id: str,
    date: datetime,
    volume_usd: float,
) -> dict:
    """Create a daily volume document for rolling 30d calculations."""
    return {
        "user_privy_id": user_privy_id,
        "date": date.replace(hour=0, minute=0, second=0, microsecond=0),
        "volume_usd": volume_usd,
    }


def payment_request_document(
    wallet_address: str,
    token_mint: str,
    token_symbol: str,
    amount: float,
    amount_usd: float = 0.0,
    is_private: bool = False,
) -> dict:
    """Create a payment request document for MongoDB."""
    req_id = generate(size=10)  # Short unique ID using NanoID
    return {
        "_id": req_id,
        "wallet_address": wallet_address,
        "token_mint": token_mint,
        "token_symbol": token_symbol,
        "amount": amount,
        "amount_usd": amount_usd,
        "is_private": is_private,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }
