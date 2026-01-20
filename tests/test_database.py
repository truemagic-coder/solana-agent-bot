"""
Tests for database service operations.

Critical tests for user management, referral tracking, and swap recording.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId

from solana_agent_api.models import REFERRAL_CAP


class TestDatabaseServiceInit:
    """Test database service initialization."""
    
    @pytest.mark.asyncio
    async def test_indexes_created(self, mock_db_service):
        """Test that indexes are created on setup."""
        await mock_db_service.setup_indexes()
        
        # Check that create_index was called for each collection
        assert mock_db_service.users.create_index.called
        assert mock_db_service.referrals.create_index.called
        assert mock_db_service.swaps.create_index.called


class TestUserOperations:
    """Test user CRUD operations."""
    
    @pytest.mark.asyncio
    async def test_get_user_by_privy_id(self, mock_db_service, sample_user):
        """Test fetching user by Privy ID."""
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        
        user = await mock_db_service.get_user_by_privy_id(sample_user["privy_id"])
        
        assert user == sample_user
        mock_db_service.users.find_one.assert_called_once_with(
            {"privy_id": sample_user["privy_id"]}
        )
    
    @pytest.mark.asyncio
    async def test_get_user_by_privy_id_not_found(self, mock_db_service):
        """Test fetching non-existent user returns None."""
        mock_db_service.users.find_one = AsyncMock(return_value=None)
        
        user = await mock_db_service.get_user_by_privy_id("nonexistent")
        
        assert user is None
    
    @pytest.mark.asyncio
    async def test_get_user_by_wallet(self, mock_db_service, sample_user):
        """Test fetching user by wallet address."""
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        
        wallet = sample_user["wallet_address"]
        user = await mock_db_service.get_user_by_wallet(wallet)
        
        assert user == sample_user
        # Should lowercase the wallet address
        mock_db_service.users.find_one.assert_called_once_with(
            {"wallet_address": wallet.lower()}
        )
    
    @pytest.mark.asyncio
    async def test_get_user_by_tg_id(self, mock_db_service, sample_user):
        """Test fetching user by Telegram ID."""
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        
        user = await mock_db_service.get_user_by_tg_id(sample_user["tg_user_id"])
        
        assert user == sample_user
    
    @pytest.mark.asyncio
    async def test_get_user_by_referral_code(self, mock_db_service, sample_user):
        """Test fetching user by referral code."""
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        
        user = await mock_db_service.get_user_by_referral_code(sample_user["referral_code"])
        
        assert user == sample_user
        # Should uppercase the referral code
        mock_db_service.users.find_one.assert_called_once_with(
            {"referral_code": sample_user["referral_code"].upper()}
        )
    
    @pytest.mark.asyncio
    async def test_create_user_without_referral(self, mock_db_service):
        """Test creating user without referral."""
        mock_db_service.users.find_one = AsyncMock(return_value=None)  # No referrer found
        mock_db_service.users.insert_one = AsyncMock()
        
        user = await mock_db_service.create_user(
            privy_id="did:privy:new-user",
            wallet_address="NewWalletAddress123",
            tg_user_id=111222333,
        )
        
        assert user["privy_id"] == "did:privy:new-user"
        assert user["wallet_address"] == "newwalletaddress123"  # lowercased
        assert user["referred_by"] is None
        assert len(user["referral_code"]) == 8
        mock_db_service.users.insert_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_user_with_valid_referral(self, mock_db_service, sample_referrer):
        """Test creating user with valid referral code."""
        # First call returns referrer (for code lookup), second returns None (user doesn't exist)
        mock_db_service.users.find_one = AsyncMock(side_effect=[sample_referrer, None])
        mock_db_service.users.insert_one = AsyncMock()
        mock_db_service.referrals.insert_one = AsyncMock()
        
        user = await mock_db_service.create_user(
            privy_id="did:privy:new-referred-user",
            wallet_address="NewWallet456",
            referral_code_used=sample_referrer["referral_code"],
        )
        
        assert user["referred_by"] == sample_referrer["privy_id"]
        # Should create referral tracking record
        mock_db_service.referrals.insert_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_create_user_with_invalid_referral(self, mock_db_service):
        """Test creating user with invalid referral code (no matching referrer)."""
        mock_db_service.users.find_one = AsyncMock(return_value=None)  # No referrer found
        mock_db_service.users.insert_one = AsyncMock()
        
        user = await mock_db_service.create_user(
            privy_id="did:privy:new-user",
            wallet_address="NewWallet789",
            referral_code_used="INVALID_CODE",
        )
        
        # User created but without referral (invalid code ignored)
        assert user["referred_by"] is None
        # No referral record created
        mock_db_service.referrals.insert_one.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_update_user_tg_id(self, mock_db_service):
        """Test linking Telegram ID to user."""
        mock_db_service.users.update_one = AsyncMock(
            return_value=MagicMock(modified_count=1)
        )
        
        result = await mock_db_service.update_user_tg_id("did:privy:user", 123456)
        
        assert result is True
        mock_db_service.users.update_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_or_create_user_existing(self, mock_db_service, sample_user):
        """Test get_or_create returns existing user."""
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        
        user = await mock_db_service.get_or_create_user(
            privy_id=sample_user["privy_id"],
            wallet_address=sample_user["wallet_address"],
        )
        
        assert user == sample_user
        # Should not create new user
        mock_db_service.users.insert_one.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_or_create_user_new(self, mock_db_service):
        """Test get_or_create creates new user when not exists."""
        mock_db_service.users.find_one = AsyncMock(return_value=None)
        mock_db_service.users.insert_one = AsyncMock()
        
        user = await mock_db_service.get_or_create_user(
            privy_id="did:privy:brand-new",
            wallet_address="BrandNewWallet",
        )
        
        assert user["privy_id"] == "did:privy:brand-new"
        mock_db_service.users.insert_one.assert_called_once()


class TestReferralOperations:
    """Test referral tracking operations."""
    
    @pytest.mark.asyncio
    async def test_get_referral(self, mock_db_service, sample_referral):
        """Test fetching referral record."""
        mock_db_service.referrals.find_one = AsyncMock(return_value=sample_referral)
        
        referral = await mock_db_service.get_referral(
            sample_referral["referrer_privy_id"],
            sample_referral["referee_privy_id"],
        )
        
        assert referral == sample_referral
    
    @pytest.mark.asyncio
    async def test_get_referrals_by_referrer(self, mock_db_service, sample_referral):
        """Test fetching all referrals for a referrer."""
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[sample_referral])
        mock_db_service.referrals.find = MagicMock(return_value=mock_cursor)
        
        referrals = await mock_db_service.get_referrals_by_referrer(
            sample_referral["referrer_privy_id"]
        )
        
        assert len(referrals) == 1
        assert referrals[0] == sample_referral
    
    @pytest.mark.asyncio
    async def test_update_referral_earnings_normal(self, mock_db_service, sample_referral):
        """Test updating referral earnings below cap."""
        sample_referral["total_earned"] = 50.0
        sample_referral["capped"] = False
        mock_db_service.referrals.find_one = AsyncMock(return_value=sample_referral)
        mock_db_service.referrals.update_one = AsyncMock()
        
        result = await mock_db_service.update_referral_earnings(
            referrer_privy_id=sample_referral["referrer_privy_id"],
            referee_privy_id=sample_referral["referee_privy_id"],
            amount=25.0,
        )
        
        assert result is True
        mock_db_service.referrals.update_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_referral_earnings_hits_cap(self, mock_db_service, sample_referral):
        """Test updating referral earnings that hits cap."""
        sample_referral["total_earned"] = 290.0  # Close to cap
        sample_referral["capped"] = False
        mock_db_service.referrals.find_one = AsyncMock(return_value=sample_referral)
        mock_db_service.referrals.update_one = AsyncMock()
        
        result = await mock_db_service.update_referral_earnings(
            referrer_privy_id=sample_referral["referrer_privy_id"],
            referee_privy_id=sample_referral["referee_privy_id"],
            amount=20.0,  # Would push to $310, over cap
        )
        
        assert result is True
        # Should cap at $300
        call_args = mock_db_service.referrals.update_one.call_args
        update_doc = call_args[0][1]
        assert update_doc["$set"]["total_earned"] == REFERRAL_CAP
        assert update_doc["$set"]["capped"] is True
    
    @pytest.mark.asyncio
    async def test_update_referral_earnings_already_capped(self, mock_db_service, sample_referral):
        """Test that capped referrals don't update."""
        sample_referral["total_earned"] = 300.0
        sample_referral["capped"] = True
        mock_db_service.referrals.find_one = AsyncMock(return_value=sample_referral)
        
        result = await mock_db_service.update_referral_earnings(
            referrer_privy_id=sample_referral["referrer_privy_id"],
            referee_privy_id=sample_referral["referee_privy_id"],
            amount=50.0,
        )
        
        assert result is False
        mock_db_service.referrals.update_one.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_get_referral_stats(
        self, mock_db_service, sample_referrer, sample_referral, sample_referred_user
    ):
        """Test getting referral statistics for a user."""
        mock_db_service.users.find_one = AsyncMock(side_effect=[
            sample_referrer,  # First call for getting user
            sample_referred_user,  # Second call for referee details
        ])
        
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[sample_referral])
        mock_db_service.referrals.find = MagicMock(return_value=mock_cursor)
        
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(return_value=[])  # No pending payouts
        mock_db_service.payouts.aggregate = MagicMock(return_value=mock_agg_cursor)
        
        stats = await mock_db_service.get_referral_stats(sample_referrer["privy_id"])
        
        assert stats["referral_code"] == sample_referrer["referral_code"]
        assert stats["total_referrals"] == 1
        assert stats["total_earned"] == sample_referral["total_earned"]


class TestSwapOperations:
    """Test swap recording operations."""
    
    @pytest.mark.asyncio
    async def test_record_swap_new(self, mock_db_service, sample_user, sample_swap):
        """Test recording a new swap."""
        mock_db_service.swaps.find_one = AsyncMock(return_value=None)  # Not duplicate
        mock_db_service.users.find_one = AsyncMock(return_value=sample_user)
        mock_db_service.referrals.find_one = AsyncMock(return_value=None)  # No referral
        mock_db_service.swaps.insert_one = AsyncMock()
        mock_db_service.users.update_one = AsyncMock()
        mock_db_service.daily_volumes.update_one = AsyncMock()
        
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(return_value=[{"total": 1000.0}])
        mock_db_service.daily_volumes.aggregate = MagicMock(return_value=mock_agg_cursor)
        
        swap = await mock_db_service.record_swap(
            tx_signature=sample_swap["tx_signature"],
            wallet_address=sample_user["wallet_address"],
            input_token=sample_swap["input_token"],
            input_amount=sample_swap["input_amount"],
            output_token=sample_swap["output_token"],
            output_amount=sample_swap["output_amount"],
            volume_usd=sample_swap["volume_usd"],
        )
        
        assert swap is not None
        assert swap["tx_signature"] == sample_swap["tx_signature"]
        mock_db_service.swaps.insert_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_record_swap_duplicate(self, mock_db_service, sample_swap):
        """Test that duplicate swaps are rejected."""
        mock_db_service.swaps.find_one = AsyncMock(return_value=sample_swap)  # Already exists
        
        swap = await mock_db_service.record_swap(
            tx_signature=sample_swap["tx_signature"],
            wallet_address="any_wallet",
            input_token="any",
            input_amount=1.0,
            output_token="any",
            output_amount=1.0,
            volume_usd=1.0,
        )
        
        assert swap is None
        mock_db_service.swaps.insert_one.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_record_swap_unknown_wallet(self, mock_db_service):
        """Test that swaps from unknown wallets are rejected."""
        mock_db_service.swaps.find_one = AsyncMock(return_value=None)
        mock_db_service.users.find_one = AsyncMock(return_value=None)  # Unknown wallet
        
        swap = await mock_db_service.record_swap(
            tx_signature="new_sig",
            wallet_address="unknown_wallet",
            input_token="token_a",
            input_amount=100.0,
            output_token="token_b",
            output_amount=200.0,
            volume_usd=100.0,
        )
        
        assert swap is None
    
    @pytest.mark.asyncio
    async def test_record_swap_with_referrer(
        self, mock_db_service, sample_referred_user, sample_referral
    ):
        """Test recording swap from referred user updates referrer earnings."""
        mock_db_service.swaps.find_one = AsyncMock(return_value=None)
        mock_db_service.users.find_one = AsyncMock(return_value=sample_referred_user)
        mock_db_service.referrals.find_one = AsyncMock(return_value=sample_referral)
        mock_db_service.swaps.insert_one = AsyncMock()
        mock_db_service.referrals.update_one = AsyncMock()
        mock_db_service.users.update_one = AsyncMock()
        mock_db_service.daily_volumes.update_one = AsyncMock()
        
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(return_value=[{"total": 1000.0}])
        mock_db_service.daily_volumes.aggregate = MagicMock(return_value=mock_agg_cursor)
        
        swap = await mock_db_service.record_swap(
            tx_signature="new_swap_sig",
            wallet_address=sample_referred_user["wallet_address"],
            input_token="SOL",
            input_amount=10.0,
            output_token="USDC",
            output_amount=1000.0,
            volume_usd=1000.0,
        )
        
        assert swap is not None
        assert swap["referrer_privy_id"] == sample_referral["referrer_privy_id"]
        # Referrer should get 25% of 80% of 0.5% = 0.1% = $1.00 from $1000
        assert swap["referrer_amount"] == pytest.approx(1.0, rel=0.01)


class TestDailyVolumeTracking:
    """Test daily volume tracking for 30-day rolling window."""
    
    @pytest.mark.asyncio
    async def test_update_daily_volume(self, mock_db_service):
        """Test daily volume update."""
        mock_db_service.daily_volumes.update_one = AsyncMock()
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(return_value=[{"total": 5000.0}])
        mock_db_service.daily_volumes.aggregate = MagicMock(return_value=mock_agg_cursor)
        mock_db_service.users.update_one = AsyncMock()
        
        await mock_db_service.update_daily_volume("did:privy:user", 500.0)
        
        # Should upsert daily volume
        mock_db_service.daily_volumes.update_one.assert_called_once()
        call_args = mock_db_service.daily_volumes.update_one.call_args
        assert call_args[1]["upsert"] is True
        
        # Should update user's 30d volume
        mock_db_service.users.update_one.assert_called_once()


class TestPayoutOperations:
    """Test payout tracking operations."""
    
    @pytest.mark.asyncio
    async def test_get_pending_payouts(self, mock_db_service, sample_referrer):
        """Test fetching pending payouts."""
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(return_value=[
            {"_id": sample_referrer["privy_id"], "total_pending": 50.0}
        ])
        mock_db_service.swaps.aggregate = MagicMock(return_value=mock_agg_cursor)
        
        # No payouts sent yet
        mock_payouts_agg = MagicMock()
        mock_payouts_agg.to_list = AsyncMock(return_value=[])
        mock_db_service.payouts.aggregate = MagicMock(return_value=mock_payouts_agg)
        
        mock_db_service.users.find_one = AsyncMock(return_value=sample_referrer)
        
        pending = await mock_db_service.get_pending_payouts()
        
        assert len(pending) == 1
        assert pending[0]["privy_id"] == sample_referrer["privy_id"]
        assert pending[0]["pending_amount"] == 50.0
    
    @pytest.mark.asyncio
    async def test_create_payout(self, mock_db_service):
        """Test creating a payout record."""
        mock_db_service.payouts.insert_one = AsyncMock()
        
        payout = await mock_db_service.create_payout(
            privy_id="did:privy:referrer",
            wallet_address="ReferrerWallet123",
            amount_usd=50.0,
            amount_agent=500.0,
        )
        
        assert payout["privy_id"] == "did:privy:referrer"
        assert payout["amount_usd"] == 50.0
        assert payout["amount_agent"] == 500.0
        assert payout["status"] == "pending"
        mock_db_service.payouts.insert_one.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_mark_payout_sent(self, mock_db_service):
        """Test marking payout as sent."""
        mock_db_service.payouts.update_one = AsyncMock()
        
        payout_id = str(ObjectId())
        await mock_db_service.mark_payout_sent(payout_id, "tx_signature_123")
        
        mock_db_service.payouts.update_one.assert_called_once()
        call_args = mock_db_service.payouts.update_one.call_args
        update_doc = call_args[0][1]
        assert update_doc["$set"]["status"] == "sent"
        assert update_doc["$set"]["tx_signature"] == "tx_signature_123"
    
    @pytest.mark.asyncio
    async def test_mark_payout_failed(self, mock_db_service):
        """Test marking payout as failed."""
        mock_db_service.payouts.update_one = AsyncMock()
        
        payout_id = str(ObjectId())
        await mock_db_service.mark_payout_failed(payout_id)
        
        mock_db_service.payouts.update_one.assert_called_once()
        call_args = mock_db_service.payouts.update_one.call_args
        update_doc = call_args[0][1]
        assert update_doc["$set"]["status"] == "failed"
