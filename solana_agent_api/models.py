"""
MongoDB models and fee configuration for Solana Agent.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from nanoid import generate

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
