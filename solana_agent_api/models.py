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


def bot_thought_document(
    tg_user_id: int,
    mode: str,
    strategy_prompt: str,
    prompt: str,
    raw_response: str,
    parsed_response: dict,
    context_snapshot: dict,
) -> dict:
    """Create a bot thought log document (AI reasoning + context)."""
    thought_id = generate(size=12)
    return {
        "_id": thought_id,
        "tg_user_id": tg_user_id,
        "mode": mode,
        "strategy_prompt": strategy_prompt,
        "prompt": prompt,
        "raw_response": raw_response,
        "parsed_response": parsed_response,
        "context_snapshot": context_snapshot,
        "timestamp": datetime.utcnow(),
    }


def trend_change_document(
    tg_user_id: int,
    previous_tokens: list,
    current_tokens: list,
    changed: bool,
    minutes_since_last: float,
) -> dict:
    """Create a trending-tokens change log document."""
    change_id = generate(size=12)
    return {
        "_id": change_id,
        "tg_user_id": tg_user_id,
        "previous_tokens": previous_tokens,
        "current_tokens": current_tokens,
        "changed": changed,
        "minutes_since_last": minutes_since_last,
        "timestamp": datetime.utcnow(),
    }


def paper_portfolio_document(initial_balance_usd: float = 1000.0) -> dict:
    """Create a paper trading portfolio document with starting USDC position."""
    return {
        "balance_usd": 0.0,
        "positions": [
            {
                "token_symbol": "USDC",
                "token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "amount": initial_balance_usd,
                "entry_price_usd": 1.0,
                "current_value_usd": initial_balance_usd,
            }
        ],  # [{token_symbol, token_address, amount, entry_price_usd, current_value_usd}]
        "initial_value_usd": initial_balance_usd,
        "created_at": datetime.utcnow(),
    }


def paper_order_document(
    tg_user_id: int,
    action: str,  # "buy" or "sell"
    token_symbol: str,
    token_address: str,
    amount_usd: float,
    price_target_usd: float,
) -> dict:
    """Create a paper trading order document."""
    order_id = generate(size=12)
    return {
        "_id": order_id,
        "tg_user_id": tg_user_id,
        "action": action,
        "token_symbol": token_symbol,
        "token_address": token_address,
        "amount_usd": amount_usd,
        "price_target_usd": price_target_usd,
        "status": "pending",  # "pending", "filled", "cancelled"
        "fill_price_usd": None,
        "filled_at": None,
        "created_at": datetime.utcnow(),
    }


def bot_action_document(
    tg_user_id: int,
    mode: str,
    action_type: str,
    token_symbol: str,
    token_address: str,
    amount_usd: float,
    price_target_usd: float,
    reasoning: str,
    context_snapshot: dict,
    execution: dict,
) -> dict:
    """Create a bot action log document."""
    action_id = generate(size=12)
    return {
        "_id": action_id,
        "tg_user_id": tg_user_id,
        "mode": mode,
        "action_type": action_type,
        "token_symbol": token_symbol,
        "token_address": token_address,
        "amount_usd": amount_usd,
        "price_target_usd": price_target_usd,
        "reasoning": reasoning,
        "context_snapshot": context_snapshot,
        "execution": execution,
        "timestamp": datetime.utcnow(),
    }
