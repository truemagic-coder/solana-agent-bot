"""
Database service for MongoDB operations.
Handles users and swaps.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from solana_agent_api.models import (
    user_document,
    swap_document,
    calculate_fee_split,
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
    # SWAP OPERATIONS
    # =========================================================================
    
    async def record_swap(
        self,
        tx_signature: str,
        wallet_address: str,
        input_token: str,
        input_amount: float,
        output_token: str,
        output_amount: float,
        volume_usd: float,
    ) -> Optional[dict]:
        """
        Record a swap from Helius webhook.
        Calculates fees and updates user volume.
        
        Returns:
            Swap document if successful, None if duplicate
        """
        # Check for duplicate
        existing = await self.swaps.find_one({"tx_signature": tx_signature})
        if existing:
            logger.warning(f"Duplicate swap: {tx_signature}")
            return None
        
        # Get user by wallet
        user = await self.get_user_by_wallet(wallet_address)
        if not user:
            logger.warning(f"Unknown wallet for swap: {wallet_address}")
            return None
        
        # Calculate fees
        fee_split = calculate_fee_split(volume_usd=volume_usd)
        
        # Create swap record
        swap = swap_document(
            tx_signature=tx_signature,
            user_privy_id=user["privy_id"],
            wallet_address=wallet_address,
            input_token=input_token,
            input_amount=input_amount,
            output_token=output_token,
            output_amount=output_amount,
            volume_usd=volume_usd,
            fee_split=fee_split,
        )
        
        await self.swaps.insert_one(swap)
        logger.info(f"Recorded swap {tx_signature}: ${volume_usd:.2f}")
        
        # Update user's last trade time
        await self.users.update_one(
            {"privy_id": user["privy_id"]},
            {"$set": {"last_trade_at": datetime.utcnow()}}
        )
        
        # Update daily volume
        await self.update_daily_volume(user["privy_id"], volume_usd)
        
        return swap
    
    async def update_daily_volume(self, user_privy_id: str, volume_usd: float):
        """Update daily volume for rolling 30d calculation."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        await self.daily_volumes.update_one(
            {"user_privy_id": user_privy_id, "date": today},
            {"$inc": {"volume_usd": volume_usd}},
            upsert=True,
        )
        
        # Update user's 30d volume
        thirty_days_ago = today - timedelta(days=30)
        pipeline = [
            {"$match": {
                "user_privy_id": user_privy_id,
                "date": {"$gte": thirty_days_ago}
            }},
            {"$group": {"_id": None, "total": {"$sum": "$volume_usd"}}}
        ]
        result = await self.daily_volumes.aggregate(pipeline).to_list(1)
        volume_30d = result[0]["total"] if result else 0.0
        
        await self.users.update_one(
            {"privy_id": user_privy_id},
            {"$set": {"volume_30d": volume_30d}}
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
