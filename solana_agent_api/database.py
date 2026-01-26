"""
Database service for MongoDB operations.
Handles users and swaps.
"""
import logging
from datetime import datetime
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from solana_agent_api.models import (
    user_document,
    paper_portfolio_document,
    paper_order_document,
)

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, mongo_url: str, database_name: str):
        self.client = AsyncIOMotorClient(mongo_url)
        self.db: AsyncIOMotorDatabase = self.client[database_name]
        
        # Collections
        self.users = self.db["users"]
        self.swaps = self.db["swaps"]
        self.daily_volumes = self.db["daily_volumes"]
        self.payment_requests = self.db["payment_requests"]
        self.paper_orders = self.db["paper_orders"]
        self.bot_actions = self.db["bot_actions"]
    
    async def setup_indexes(self):
        """Create necessary indexes for performance."""
        # Users indexes
        await self.users.create_index("privy_id", unique=True)
        await self.users.create_index("wallet_address")
        await self.users.create_index("wallet_id")
        await self.users.create_index("user_id")
        await self.users.create_index("tg_user_id", sparse=True)
        
        # Swaps indexes
        await self.swaps.create_index("tx_signature", unique=True)
        await self.swaps.create_index("user_privy_id")
        await self.swaps.create_index("wallet_address")
        await self.swaps.create_index("created_at")
        
        # Daily volumes indexes
        await self.daily_volumes.create_index([("user_privy_id", 1), ("date", 1)], unique=True)
        await self.daily_volumes.create_index("date")
        
        # Paper orders indexes
        await self.paper_orders.create_index("tg_user_id")
        await self.paper_orders.create_index("status")
        await self.paper_orders.create_index([("tg_user_id", 1), ("status", 1)])
        
        # Bot actions indexes
        await self.bot_actions.create_index("tg_user_id")
        await self.bot_actions.create_index("timestamp")
        await self.bot_actions.create_index([("tg_user_id", 1), ("timestamp", -1)])
        
        logger.info("Database indexes created")

    # =========================================================================
    # USER OPERATIONS
    # =========================================================================
    
    async def get_user_by_privy_id(self, privy_id: str) -> Optional[dict]:
        """Get user by Privy ID."""
        return await self.users.find_one({"privy_id": privy_id})
    
    async def get_user_by_wallet(self, wallet_address: str) -> Optional[dict]:
        """Get user by wallet address."""
        return await self.users.find_one({"wallet_address": wallet_address})

    async def get_user_by_wallet_address(self, wallet_address: str) -> Optional[dict]:
        """Alias for get_user_by_wallet (support legacy calls)."""
        return await self.get_user_by_wallet(wallet_address)

    async def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get user by Telegram username (case-insensitive)."""
        # Remove @ if present
        username = username.lstrip('@')
        print(f"DEBUG: Looking up user by username: {username}")
        # Case insensitive regex search
        user = await self.users.find_one({
            "tg_username": {"$regex": f"^{username}$", "$options": "i"}
        })
        print(f"DEBUG: Lookup result: {user['wallet_address'] if user else 'None'}")
        return user
    
    async def get_user_by_tg_id(self, tg_user_id: int) -> Optional[dict]:
        """Get user by Telegram user ID."""
        return await self.users.find_one({"tg_user_id": tg_user_id})
    
    async def create_user(
        self,
        privy_id: str,
        wallet_address: Optional[str] = None,
        wallet_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tg_user_id: Optional[int] = None,
        tg_username: Optional[str] = None,
    ) -> dict:
        """
        Create a new user.
        
        Args:
            privy_id: Privy user ID
            wallet_address: Solana wallet address (optional)
            tg_user_id: Telegram user ID (optional)
            tg_username: Telegram username (optional)
        Returns:
            Created user document
        """
        # Create user document
        user_doc = user_document(
            privy_id=privy_id,
            wallet_address=wallet_address,
            wallet_id=wallet_id,
            user_id=user_id,
            tg_user_id=tg_user_id,
            tg_username=tg_username,
        )
        
        # Insert user
        await self.users.insert_one(user_doc)
        logger.info(f"Created new user: {privy_id}")
        
        return user_doc

    async def update_user_tg_details(self, privy_id: str, tg_user_id: int, tg_username: Optional[str] = None) -> bool:
        """Link Telegram ID and username to user account."""
        update_data = {"tg_user_id": tg_user_id}
        if tg_username:
            update_data["tg_username"] = tg_username
            
        result = await self.users.update_one(
            {"privy_id": privy_id},
            {"$set": update_data}
        )
        return result.modified_count > 0

    async def update_user_tg_id(self, privy_id: str, tg_user_id: int) -> bool:
        """Alias for update_user_tg_details (legacy support)."""
        return await self.update_user_tg_details(privy_id, tg_user_id)
        
    async def update_user_username(self, tg_user_id: int, tg_username: str) -> bool:
        """Update Telegram username for a user by TG ID."""
        # Find user first to see if they exist
        user = await self.users.find_one({"tg_user_id": tg_user_id})
        if not user:
            # Try to find by partial match or log warning?
            # Actually, we might have users created by wallet address but not linked to TG ID yet? 
            # (No, current flow requires TG ID for Privy ID creation usually).
            print(f"DEBUG: Update username failed - User not found for TG ID: {tg_user_id}")
            return False
            
        result = await self.users.update_one(
            {"tg_user_id": tg_user_id},
            {"$set": {"tg_username": tg_username}}
        )
        print(f"DEBUG: Updated username for {tg_user_id} to {tg_username}. Modified: {result.modified_count}")
        return result.modified_count > 0
    
    async def get_or_create_user(
        self,
        privy_id: str,
        wallet_address: Optional[str] = None,
        wallet_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tg_user_id: Optional[int] = None,
        tg_username: Optional[str] = None,
    ) -> dict:
        """Get existing user or create new one."""
        user = await self.get_user_by_privy_id(privy_id)
        if user:
            # Update TG ID/Username if provided and not set or changed
            update_data = {}
            if tg_user_id and user.get("tg_user_id") != tg_user_id:
                update_data["tg_user_id"] = tg_user_id
            if tg_username and user.get("tg_username") != tg_username:
                update_data["tg_username"] = tg_username
            
            # CRITICAL FIX: Update wallet address if it was missing but is now provided
            if wallet_address and not user.get("wallet_address"):
                update_data["wallet_address"] = wallet_address

            # Update wallet ID if it was missing but is now provided
            if wallet_id and not user.get("wallet_id"):
                update_data["wallet_id"] = wallet_id

            # Update Privy DID (user_id) if it was missing but is now provided
            if user_id and not user.get("user_id"):
                update_data["user_id"] = user_id
                
            if update_data:
                await self.users.update_one(
                    {"privy_id": privy_id},
                    {"$set": update_data}
                )
                # Update local user object to reflect changes
                user.update(update_data)
                    
            return user
        
        return await self.create_user(
            privy_id=privy_id,
            wallet_address=wallet_address,
            wallet_id=wallet_id,
            user_id=user_id,
            tg_user_id=tg_user_id,
            tg_username=tg_username,
        )

    # =========================================================================
    # PAYMENT REQUEST OPERATIONS
    # =========================================================================

    async def create_payment_request(
        self,
        wallet_address: str,
        token_mint: str,
        token_symbol: str,
        amount: float,
        amount_usd: float = 0.0,
        is_private: bool = False,
    ) -> str:
        """Create a payment request and return its ID."""
        from solana_agent_api.models import payment_request_document
        
        request = payment_request_document(
            wallet_address=wallet_address,
            token_mint=token_mint,
            token_symbol=token_symbol,
            amount=amount,
            amount_usd=amount_usd,
            is_private=is_private,
        )
        
        # Ensure ID uniqueness (highly likely, but safe to check)
        while await self.payment_requests.find_one({"_id": request["_id"]}):
            request = payment_request_document(
                wallet_address,
                token_mint,
                token_symbol,
                amount,
                amount_usd,
                is_private,
            )
            
        await self.payment_requests.insert_one(request)
        return request["_id"]

    async def mark_payment_request_sent(self, request_id: str):
        """Mark a payment request as sent."""
        await self.payment_requests.update_one(
            {"_id": request_id},
            {"$set": {"status": "sent", "sent_at": datetime.utcnow()}}
        )

    async def get_payment_request(self, request_id: str) -> Optional[dict]:
        """Get payment request by ID."""
        try:
            return await self.payment_requests.find_one({"_id": request_id})
        except Exception:
            return None

    # =========================================================================
    # TRADING AGENT OPERATIONS
    # =========================================================================

    async def get_trading_enabled_users(self) -> list:
        """Get all users with trading enabled.
        
        Paper mode: Any user with trading_mode='paper' (no whitelist needed)
        Live mode: Only users with trading_mode='live' AND live_trading_allowed=True
        """
        cursor = self.users.find({
            "$or": [
                # Paper trading - anyone can do it
                {"trading_mode": "paper"},
                # Live trading - requires whitelist
                {"trading_mode": "live", "live_trading_allowed": True}
            ]
        })
        return await cursor.to_list(length=None)

    async def initialize_paper_portfolio(self, tg_user_id: int, initial_balance: float = 1000.0):
        """Initialize paper trading portfolio for a user."""
        paper_portfolio = paper_portfolio_document(initial_balance)
        await self.users.update_one(
            {"tg_user_id": tg_user_id},
            {"$set": {"paper_portfolio": paper_portfolio}}
        )
        return paper_portfolio

    async def get_paper_portfolio(self, tg_user_id: int) -> Optional[dict]:
        """Get user's paper trading portfolio."""
        user = await self.get_user_by_tg_id(tg_user_id)
        if user:
            return user.get("paper_portfolio")
        return None

    async def create_paper_order(
        self,
        tg_user_id: int,
        action: str,
        token_symbol: str,
        token_address: str,
        amount_usd: float,
        price_target_usd: float,
    ) -> dict:
        """Create a paper trading order."""
        order = paper_order_document(
            tg_user_id=tg_user_id,
            action=action,
            token_symbol=token_symbol,
            token_address=token_address,
            amount_usd=amount_usd,
            price_target_usd=price_target_usd,
        )
        await self.paper_orders.insert_one(order)
        return order

    async def get_pending_paper_orders(self) -> list:
        """Get all pending paper orders."""
        cursor = self.paper_orders.find({"status": "pending"})
        return await cursor.to_list(length=None)

    async def get_user_paper_orders(self, tg_user_id: int, status: Optional[str] = None) -> list:
        """Get paper orders for a specific user."""
        query = {"tg_user_id": tg_user_id}
        if status:
            query["status"] = status
        cursor = self.paper_orders.find(query).sort("created_at", -1)
        return await cursor.to_list(length=None)

    async def fill_paper_order(self, order_id: str, fill_price_usd: float):
        """Mark a paper order as filled."""
        await self.paper_orders.update_one(
            {"_id": order_id},
            {
                "$set": {
                    "status": "filled",
                    "fill_price_usd": fill_price_usd,
                    "filled_at": datetime.utcnow(),
                }
            }
        )

    async def cancel_paper_order(self, order_id: str):
        """Cancel a paper order."""
        await self.paper_orders.update_one(
            {"_id": order_id},
            {"$set": {"status": "cancelled"}}
        )

    async def update_paper_portfolio_on_fill(
        self,
        tg_user_id: int,
        action: str,
        token_symbol: str,
        token_address: str,
        amount_usd: float,
        fill_price_usd: float,
    ):
        """Update paper portfolio when an order fills."""
        user = await self.get_user_by_tg_id(tg_user_id)
        if not user:
            return
        
        paper_portfolio = user.get("paper_portfolio", {})
        positions = paper_portfolio.get("positions", [])
        balance = paper_portfolio.get("balance_usd", 0)
        
        if action == "buy":
            # Deduct from balance, add to positions
            balance -= amount_usd
            
            # Calculate token amount
            token_amount = amount_usd / fill_price_usd if fill_price_usd > 0 else 0
            
            # Check if position exists
            existing_pos = None
            for pos in positions:
                if pos.get("token_symbol") == token_symbol:
                    existing_pos = pos
                    break
            
            if existing_pos:
                # Average into existing position
                old_amount = existing_pos.get("amount", 0)
                old_value = old_amount * existing_pos.get("entry_price_usd", 0)
                new_total_value = old_value + amount_usd
                new_total_amount = old_amount + token_amount
                new_avg_price = new_total_value / new_total_amount if new_total_amount > 0 else 0
                
                existing_pos["amount"] = new_total_amount
                existing_pos["entry_price_usd"] = new_avg_price
                existing_pos["current_value_usd"] = new_total_amount * fill_price_usd
            else:
                # Create new position
                positions.append({
                    "token_symbol": token_symbol,
                    "token_address": token_address,
                    "amount": token_amount,
                    "entry_price_usd": fill_price_usd,
                    "current_value_usd": amount_usd,
                })
        
        elif action == "sell":
            # Find position and reduce
            for pos in positions:
                if pos.get("token_symbol") == token_symbol:
                    sell_amount = amount_usd / fill_price_usd if fill_price_usd > 0 else 0
                    pos["amount"] = max(0, pos.get("amount", 0) - sell_amount)
                    pos["current_value_usd"] = pos["amount"] * fill_price_usd
                    
                    # Add proceeds to balance
                    balance += amount_usd
                    
                    # Remove position if fully sold
                    if pos["amount"] <= 0:
                        positions.remove(pos)
                    break
        
        # Update portfolio
        paper_portfolio["balance_usd"] = balance
        paper_portfolio["positions"] = positions
        
        await self.users.update_one(
            {"tg_user_id": tg_user_id},
            {"$set": {"paper_portfolio": paper_portfolio}}
        )

    async def log_bot_action(self, action: dict):
        """Log a bot trading action."""
        await self.bot_actions.insert_one(action)

    async def get_user_bot_actions(self, tg_user_id: int, limit: int = 50) -> list:
        """Get recent bot actions for a user."""
        cursor = self.bot_actions.find({"tg_user_id": tg_user_id}).sort("timestamp", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def update_user_trading_settings(
        self,
        tg_user_id: int,
        trading_enabled: Optional[bool] = None,
        trading_mode: Optional[str] = None,
        trading_strategy_prompt: Optional[str] = None,
        trading_watchlist: Optional[list] = None,
    ) -> bool:
        """Update user's trading settings."""
        update_data = {}
        if trading_enabled is not None:
            update_data["trading_enabled"] = trading_enabled
        if trading_mode is not None:
            update_data["trading_mode"] = trading_mode
        if trading_strategy_prompt is not None:
            update_data["trading_strategy_prompt"] = trading_strategy_prompt
        if trading_watchlist is not None:
            update_data["trading_watchlist"] = trading_watchlist
        
        if not update_data:
            return False
        
        result = await self.users.update_one(
            {"tg_user_id": tg_user_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
