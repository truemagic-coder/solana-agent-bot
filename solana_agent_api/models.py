"""
MongoDB models and fee configuration for Solana Agent.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from nanoid import generate


# =============================================================================



# =============================================================================
# FEE CONFIGURATION
# =============================================================================

PLATFORM_FEE = 0.005          # 0.5% flat fee on all trades
JUPITER_SPLIT = 0.20          # Jupiter takes 20% of fee


def calculate_fee_split(volume_usd: float) -> dict:
    """
    Calculate the fee split for a trade.
    
    Args:
        volume_usd: Trade volume in USD
    
    Returns:
        Dict with fee breakdown
    """
    gross_fee = volume_usd * PLATFORM_FEE
    jupiter_amount = gross_fee * JUPITER_SPLIT
    platform_amount = gross_fee - jupiter_amount
    
    return {
        "gross_fee": gross_fee,
        "jupiter_amount": jupiter_amount,
        "platform_amount": platform_amount,
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
    


class UserResponse(BaseModel):
    privy_id: str
    wallet_address: str
    wallet_id: Optional[str] = None
    user_id: Optional[str] = None
    tg_user_id: Optional[int] = None
    volume_30d: float = 0.0
    created_at: datetime
    last_trade_at: Optional[datetime] = None


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
) -> dict:
    """Create a user document for MongoDB."""
    doc = {
        "privy_id": privy_id,
        "created_at": datetime.utcnow(),
        "volume_30d": 0.0,
        "last_trade_at": None,
        "wallet_address": None,
        "wallet_id": None,
        "user_id": None,
        "tg_user_id": None,
        "tg_username": None,
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
        
    return doc


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
        "created_at": datetime.utcnow(),
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
