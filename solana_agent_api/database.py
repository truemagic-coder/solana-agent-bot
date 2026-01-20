"""
Database service for MongoDB operations.
Handles users, referrals, swaps, and payouts.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from solana_agent_api.models import (
    user_document,
    referral_document,
    swap_document,
    payout_document,
    calculate_fee_split,
    REFERRAL_CAP,
    generate_referral_code,
)

logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self, mongo_url: str, database_name: str):
        self.client = AsyncIOMotorClient(mongo_url)
        self.db: AsyncIOMotorDatabase = self.client[database_name]
        
        # Collections
        self.users = self.db["users"]
        self.referrals = self.db["referrals"]
        self.swaps = self.db["swaps"]
        self.daily_volumes = self.db["daily_volumes"]
        self.payouts = self.db["payouts"]
        self.payment_requests = self.db["payment_requests"]
    
    async def setup_indexes(self):
        """Create necessary indexes for performance."""
        # Users indexes
        await self.users.create_index("privy_id", unique=True)
        await self.users.create_index("wallet_address")
        await self.users.create_index("wallet_id")
        await self.users.create_index("user_id")
        await self.users.create_index("tg_user_id", sparse=True)
        await self.users.create_index("referral_code", unique=True)
        
        # Referrals indexes
        await self.referrals.create_index("referrer_privy_id")
        await self.referrals.create_index("referee_privy_id", unique=True)
        await self.referrals.create_index([("referrer_privy_id", 1), ("capped", 1)])
        
        # Swaps indexes
        await self.swaps.create_index("tx_signature", unique=True)
        await self.swaps.create_index("user_privy_id")
        await self.swaps.create_index("wallet_address")
        await self.swaps.create_index("created_at")
        await self.swaps.create_index("referrer_privy_id", sparse=True)
        
        # Daily volumes indexes
        await self.daily_volumes.create_index([("user_privy_id", 1), ("date", 1)], unique=True)
        await self.daily_volumes.create_index("date")
        
        # Payouts indexes
        await self.payouts.create_index("privy_id")
        await self.payouts.create_index("status")
        await self.payouts.create_index("created_at")
        
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
    
    async def get_user_by_referral_code(self, referral_code: str) -> Optional[dict]:
        """Get user by their referral code."""
        return await self.users.find_one({"referral_code": referral_code.upper()})
    
    async def create_user(
        self,
        privy_id: str,
        wallet_address: Optional[str] = None,
        wallet_id: Optional[str] = None,
        user_id: Optional[str] = None,
        tg_user_id: Optional[int] = None,
        tg_username: Optional[str] = None,
        referral_code_used: Optional[str] = None,
    ) -> dict:
        """
        Create a new user, optionally with a referral.
        
        Args:
            privy_id: Privy user ID
            wallet_address: Solana wallet address (optional)
            tg_user_id: Telegram user ID (optional)
            tg_username: Telegram username (optional)
            referral_code_used: Referral code of the referrer (optional)
            
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
        
        # Handle referral logic if code used
        if referral_code_used:
            referrer = await self.get_user_by_referral_code(referral_code_used)
            if referrer:
                user_doc["referred_by"] = referrer["privy_id"]
                # Create referral record
                await self.create_referral(referrer["privy_id"], privy_id)
        
        # Create own referral code
        user_doc["referral_code"] = generate_referral_code()
        
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
        referral_code_used: Optional[str] = None,
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
            referral_code_used=referral_code_used,
        )

    # =========================================================================
    # REFERRAL OPERATIONS
    # =========================================================================
    
    async def create_referral(self, referrer_privy_id: str, referee_privy_id: str) -> Optional[dict]:
        """Create a referral relationship."""
        referral = referral_document(referrer_privy_id, referee_privy_id)
        try:
            await self.referrals.insert_one(referral)
            logger.info(f"Created referral: {referrer_privy_id} -> {referee_privy_id}")
            return referral
        except Exception as e:
            logger.error(f"Failed to create referral: {str(e)}")
            return None

    async def get_referral(self, referrer_privy_id: str, referee_privy_id: str) -> Optional[dict]:
        """Get referral record."""
        return await self.referrals.find_one({
            "referrer_privy_id": referrer_privy_id,
            "referee_privy_id": referee_privy_id,
        })
    
    async def get_referrals_by_referrer(self, referrer_privy_id: str) -> list:
        """Get all referrals for a referrer."""
        cursor = self.referrals.find({"referrer_privy_id": referrer_privy_id})
        return await cursor.to_list(length=None)
    
    async def get_referral_stats(self, privy_id: str) -> dict:
        """Get referral statistics for a user."""
        user = await self.get_user_by_privy_id(privy_id)
        if not user:
            return None
        
        referrals = await self.get_referrals_by_referrer(privy_id)
        
        total_earned = sum(r["total_earned"] for r in referrals)
        
        # Get pending payout amount
        pending_pipeline = [
            {"$match": {"privy_id": privy_id, "status": "pending"}},
            {"$group": {"_id": None, "total": {"$sum": "$amount_usd"}}}
        ]
        pending_result = await self.payouts.aggregate(pending_pipeline).to_list(1)
        pending_payout = pending_result[0]["total"] if pending_result else 0.0
        
        # Get referee details
        referee_stats = []
        for ref in referrals:
            referee = await self.get_user_by_privy_id(ref["referee_privy_id"])
            referee_stats.append({
                "wallet": referee["wallet_address"] if referee else "unknown",
                "earned": ref["total_earned"],
                "capped": ref["capped"],
                "created_at": ref["created_at"],
            })
        
        return {
            "referral_code": user["referral_code"],
            "referral_link": f"https://t.me/solana_agent_bot?start={user['referral_code']}",
            "total_referrals": len(referrals),
            "total_earned": total_earned,
            "pending_payout": pending_payout,
            "referrals": referee_stats,
        }
    
    async def update_referral_earnings(
        self,
        referrer_privy_id: str,
        referee_privy_id: str,
        amount: float,
    ) -> bool:
        """
        Update referral earnings and check cap.
        
        Returns:
            True if updated, False if already capped
        """
        referral = await self.get_referral(referrer_privy_id, referee_privy_id)
        if not referral or referral["capped"]:
            return False
        
        new_total = referral["total_earned"] + amount
        capped = new_total >= REFERRAL_CAP
        
        update = {
            "$set": {
                "total_earned": min(new_total, REFERRAL_CAP),
                "capped": capped,
            }
        }
        
        if capped:
            update["$set"]["capped_at"] = datetime.utcnow()
            # Adjust amount to not exceed cap
            amount = REFERRAL_CAP - referral["total_earned"]
        
        await self.referrals.update_one(
            {"referrer_privy_id": referrer_privy_id, "referee_privy_id": referee_privy_id},
            update
        )
        
        if capped:
            logger.info(f"Referral capped: {referrer_privy_id} -> {referee_privy_id}")
        
        return True

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
        Calculates fees and updates referral earnings.
        
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
        
        # Check if user has referrer and if capped
        referrer_privy_id = None
        referrer_capped = True
        
        if user.get("referred_by"):
            referral = await self.get_referral(user["referred_by"], user["privy_id"])
            if referral and not referral["capped"]:
                referrer_privy_id = user["referred_by"]
                referrer_capped = False
        
        # Calculate fees
        fee_split = calculate_fee_split(
            volume_usd=volume_usd,
            has_referrer=bool(referrer_privy_id),
            referrer_capped=referrer_capped,
        )
        
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
            referrer_privy_id=referrer_privy_id,
        )
        
        await self.swaps.insert_one(swap)
        logger.info(f"Recorded swap {tx_signature}: ${volume_usd:.2f}")
        
        # Update referral earnings
        if referrer_privy_id and fee_split["referrer_amount"] > 0:
            await self.update_referral_earnings(
                referrer_privy_id=referrer_privy_id,
                referee_privy_id=user["privy_id"],
                amount=fee_split["referrer_amount"],
            )
        
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
    # PAYOUT OPERATIONS
    # =========================================================================
    
    async def get_pending_payouts(self) -> list:
        """Get all referrers with pending earnings to pay out."""
        pipeline = [
            {"$match": {"referrer_privy_id": {"$ne": None}, "referrer_amount": {"$gt": 0}}},
            {"$group": {
                "_id": "$referrer_privy_id",
                "total_pending": {"$sum": "$referrer_amount"},
            }},
            {"$match": {"total_pending": {"$gt": 0}}},
        ]
        
        # Get unpaid swap totals
        unpaid = await self.swaps.aggregate(pipeline).to_list(length=None)
        
        # Subtract already paid amounts
        results = []
        for item in unpaid:
            privy_id = item["_id"]
            
            # Get total already paid
            paid_pipeline = [
                {"$match": {"privy_id": privy_id, "status": "sent"}},
                {"$group": {"_id": None, "total": {"$sum": "$amount_usd"}}}
            ]
            paid_result = await self.payouts.aggregate(paid_pipeline).to_list(1)
            total_paid = paid_result[0]["total"] if paid_result else 0.0
            
            pending = item["total_pending"] - total_paid
            if pending > 0:
                user = await self.get_user_by_privy_id(privy_id)
                if user:
                    results.append({
                        "privy_id": privy_id,
                        "wallet_address": user["wallet_address"],
                        "pending_amount": pending,
                    })
        
        return results
    
    async def create_payout(
        self,
        privy_id: str,
        wallet_address: str,
        amount_usd: float,
        amount_agent: float,
    ) -> dict:
        """Create a payout record."""
        payout = payout_document(
            privy_id=privy_id,
            wallet_address=wallet_address,
            amount_usd=amount_usd,
            amount_agent=amount_agent,
        )
        await self.payouts.insert_one(payout)
        return payout
    
    async def mark_payout_sent(self, payout_id: str, tx_signature: str):
        """Mark a payout as sent."""
        await self.payouts.update_one(
            {"_id": payout_id},
            {"$set": {
                "status": "sent",
                "tx_signature": tx_signature,
                "sent_at": datetime.utcnow(),
            }}
        )
    
    async def mark_payout_failed(self, payout_id: str):
        """Mark a payout as failed."""
        await self.payouts.update_one(
            {"_id": payout_id},
            {"$set": {"status": "failed"}}
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
