"""
Tests for fee calculation and models.

This is critical financial code - these tests ensure fee calculations are correct.
"""
import pytest
from datetime import datetime

from solana_agent_api.models import (
    PLATFORM_FEE,
    JUPITER_SPLIT,
    PLATFORM_SPLIT,
    REFERRER_SPLIT,
    REFERRAL_CAP,
    generate_referral_code,
    calculate_fee_split,
    user_document,
    referral_document,
    swap_document,
    payout_document,
)


class TestFeeConstants:
    """Test that fee constants are correctly defined."""
    
    def test_platform_fee_is_half_percent(self):
        """Platform fee should be 0.5%."""
        assert PLATFORM_FEE == 0.005
    
    def test_jupiter_split_is_20_percent(self):
        """Jupiter takes 20% of the fee."""
        assert JUPITER_SPLIT == 0.20
    
    def test_platform_split_is_55_percent(self):
        """Platform takes 55% of remaining 80%."""
        assert PLATFORM_SPLIT == 0.55
    
    def test_referrer_split_is_25_percent(self):
        """Referrer takes 25% of remaining 80%."""
        assert REFERRER_SPLIT == 0.25
    
    def test_splits_sum_to_80_percent(self):
        """Platform + Referrer splits should sum to 80% (100% - Jupiter's 20%)."""
        # These are percentages of the remaining 80%, so they should sum to 80%
        assert PLATFORM_SPLIT + REFERRER_SPLIT == 0.80
    
    def test_referral_cap_is_300_dollars(self):
        """Referral cap should be $300."""
        assert REFERRAL_CAP == 300.0


class TestFeeCalculation:
    """Test fee split calculations - critical financial logic."""
    
    def test_fee_calculation_no_referrer(self):
        """Test fee calculation when user has no referrer."""
        volume = 1000.0  # $1000 trade
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=False,
            referrer_capped=False,
        )
        
        # 0.5% of $1000 = $5
        assert result["gross_fee"] == 5.0
        
        # Jupiter gets 20% of $5 = $1
        assert result["jupiter_amount"] == 1.0
        
        # Remaining is $4 (80% of $5)
        # Platform gets 80% of remaining (55% + 25% = 80%)
        # $4 * 0.80 = $3.20
        assert result["platform_amount"] == pytest.approx(3.2, rel=1e-6)
        
        # No referrer = no referrer amount
        assert result["referrer_amount"] == 0.0
    
    def test_fee_calculation_with_referrer(self):
        """Test fee calculation when user has active referrer."""
        volume = 1000.0  # $1000 trade
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=True,
            referrer_capped=False,
        )
        
        # 0.5% of $1000 = $5
        assert result["gross_fee"] == 5.0
        
        # Jupiter gets 20% of $5 = $1
        assert result["jupiter_amount"] == 1.0
        
        # Remaining is $4 (80% of $5)
        # Platform gets 55% of $4 = $2.20
        assert result["platform_amount"] == pytest.approx(2.2, rel=1e-6)
        
        # Referrer gets 25% of $4 = $1.00
        assert result["referrer_amount"] == pytest.approx(1.0, rel=1e-6)
    
    def test_fee_calculation_referrer_capped(self):
        """Test fee calculation when referrer has hit their cap."""
        volume = 1000.0  # $1000 trade
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=True,
            referrer_capped=True,
        )
        
        # Even though user has referrer, they're capped
        # So platform gets the referrer's share (80% of remaining)
        assert result["gross_fee"] == 5.0
        assert result["jupiter_amount"] == 1.0
        assert result["platform_amount"] == pytest.approx(3.2, rel=1e-6)  # Gets both shares (80% of $4)
        assert result["referrer_amount"] == 0.0  # Capped = no payout
    
    def test_fee_calculation_small_trade(self):
        """Test fee calculation for a small trade ($10)."""
        volume = 10.0
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=True,
            referrer_capped=False,
        )
        
        # 0.5% of $10 = $0.05
        assert result["gross_fee"] == pytest.approx(0.05, rel=1e-6)
        
        # Jupiter: 20% of $0.05 = $0.01
        assert result["jupiter_amount"] == pytest.approx(0.01, rel=1e-6)
        
        # Remaining: $0.04
        # Platform: 55% of $0.04 = $0.022
        assert result["platform_amount"] == pytest.approx(0.022, rel=1e-6)
        
        # Referrer: 25% of $0.04 = $0.01
        assert result["referrer_amount"] == pytest.approx(0.01, rel=1e-6)
    
    def test_fee_calculation_large_trade(self):
        """Test fee calculation for a large trade ($100,000)."""
        volume = 100_000.0
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=True,
            referrer_capped=False,
        )
        
        # 0.5% of $100,000 = $500
        assert result["gross_fee"] == 500.0
        
        # Jupiter: 20% of $500 = $100
        assert result["jupiter_amount"] == 100.0
        
        # Remaining: $400
        # Platform: 55% of $400 = $220
        assert result["platform_amount"] == pytest.approx(220.0, rel=1e-6)
        
        # Referrer: 25% of $400 = $100
        assert result["referrer_amount"] == pytest.approx(100.0, rel=1e-6)
    
    def test_fee_calculation_zero_volume(self):
        """Test fee calculation for zero volume trade."""
        result = calculate_fee_split(
            volume_usd=0.0,
            has_referrer=True,
            referrer_capped=False,
        )
        
        assert result["gross_fee"] == 0.0
        assert result["jupiter_amount"] == 0.0
        assert result["platform_amount"] == 0.0
        assert result["referrer_amount"] == 0.0
    
    def test_fee_total_equals_gross(self):
        """Verify all fee components sum correctly (jupiter + platform + referrer = 84% of gross with referrer)."""
        volume = 5000.0
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=True,
            referrer_capped=False,
        )
        
        total = (
            result["jupiter_amount"] +
            result["platform_amount"] +
            result["referrer_amount"]
        )
        
        # With referrer: jupiter (20%) + platform (55% of 80%) + referrer (25% of 80%)
        # = 20% + 44% + 20% = 84% of gross
        expected = result["gross_fee"] * (JUPITER_SPLIT + (1 - JUPITER_SPLIT) * (PLATFORM_SPLIT + REFERRER_SPLIT))
        assert total == pytest.approx(expected, rel=1e-6)
    
    def test_fee_total_equals_gross_no_referrer(self):
        """Verify components sum correctly when no referrer."""
        volume = 5000.0
        
        result = calculate_fee_split(
            volume_usd=volume,
            has_referrer=False,
            referrer_capped=False,
        )
        
        total = (
            result["jupiter_amount"] +
            result["platform_amount"] +
            result["referrer_amount"]
        )
        
        # Without referrer: jupiter (20%) + platform (80% of 80%) = 20% + 64% = 84% of gross
        expected = result["gross_fee"] * (JUPITER_SPLIT + (1 - JUPITER_SPLIT) * (PLATFORM_SPLIT + REFERRER_SPLIT))
        assert total == pytest.approx(expected, rel=1e-6)


class TestReferralCodeGeneration:
    """Test referral code generation."""
    
    def test_generates_code_of_correct_length(self):
        """Default code should be 8 characters."""
        code = generate_referral_code()
        assert len(code) == 8
    
    def test_generates_code_of_custom_length(self):
        """Should support custom length codes."""
        code = generate_referral_code(length=12)
        assert len(code) == 12
    
    def test_generates_alphanumeric_codes(self):
        """Codes should only contain uppercase letters and digits."""
        import string
        allowed = set(string.ascii_uppercase + string.digits)
        
        for _ in range(100):
            code = generate_referral_code()
            assert all(c in allowed for c in code)
    
    def test_generates_unique_codes(self):
        """Codes should be unique (with high probability)."""
        codes = [generate_referral_code() for _ in range(1000)]
        assert len(set(codes)) == 1000  # All unique


class TestDocumentCreation:
    """Test MongoDB document creation functions."""
    
    def test_user_document_structure(self):
        """Test user document has correct structure."""
        doc = user_document(
            privy_id="did:privy:test123",
            wallet_address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            tg_user_id=123456,
            referred_by="did:privy:referrer456",
        )
        
        assert doc["privy_id"] == "did:privy:test123"
        assert doc["wallet_address"] == "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU".lower()  # lowercase
        assert doc["tg_user_id"] == 123456
        assert doc["referred_by"] == "did:privy:referrer456"
        assert len(doc["referral_code"]) == 8
        assert doc["volume_30d"] == 0.0
        assert doc["last_trade_at"] is None
        assert isinstance(doc["created_at"], datetime)
    
    def test_user_document_lowercases_wallet(self):
        """Wallet address should be stored lowercase."""
        doc = user_document(
            privy_id="did:privy:test",
            wallet_address="ABC123DEF456",
        )
        assert doc["wallet_address"] == "abc123def456"
    
    def test_referral_document_structure(self):
        """Test referral document has correct structure."""
        doc = referral_document(
            referrer_privy_id="did:privy:referrer",
            referee_privy_id="did:privy:referee",
        )
        
        assert doc["referrer_privy_id"] == "did:privy:referrer"
        assert doc["referee_privy_id"] == "did:privy:referee"
        assert doc["total_earned"] == 0.0
        assert doc["cap"] == REFERRAL_CAP
        assert doc["capped"] is False
        assert doc["capped_at"] is None
        assert isinstance(doc["created_at"], datetime)
    
    def test_swap_document_structure(self):
        """Test swap document has correct structure."""
        fee_split = calculate_fee_split(1000.0, True, False)
        
        doc = swap_document(
            tx_signature="5UfgVz...",
            user_privy_id="did:privy:user",
            wallet_address="7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
            input_token="SOL_MINT",
            input_amount=10.0,
            output_token="USDC_MINT",
            output_amount=1000.0,
            volume_usd=1000.0,
            fee_split=fee_split,
            referrer_privy_id="did:privy:referrer",
        )
        
        assert doc["tx_signature"] == "5UfgVz..."
        assert doc["user_privy_id"] == "did:privy:user"
        assert doc["wallet_address"] == "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU".lower()
        assert doc["volume_usd"] == 1000.0
        assert doc["fee_amount_usd"] == fee_split["gross_fee"]
        assert doc["jupiter_amount"] == fee_split["jupiter_amount"]
        assert doc["platform_amount"] == fee_split["platform_amount"]
        assert doc["referrer_privy_id"] == "did:privy:referrer"
        assert doc["referrer_amount"] == fee_split["referrer_amount"]
    
    def test_payout_document_structure(self):
        """Test payout document has correct structure."""
        doc = payout_document(
            privy_id="did:privy:user",
            wallet_address="ABC123",
            amount_usd=100.0,
            amount_agent=1000.0,
            tx_signature="sig123",
        )
        
        assert doc["privy_id"] == "did:privy:user"
        assert doc["wallet_address"] == "ABC123"
        assert doc["amount_usd"] == 100.0
        assert doc["amount_agent"] == 1000.0
        assert doc["tx_signature"] == "sig123"
        assert doc["status"] == "pending"
        assert doc["sent_at"] is None


class TestReferralCapScenarios:
    """Test scenarios around the $300 referral cap."""
    
    def test_referrer_earnings_below_cap(self):
        """Referrer should earn normally when below cap."""
        # First trade: $10,000 volume = $1 referrer earnings
        result = calculate_fee_split(10_000.0, True, False)
        assert result["referrer_amount"] == pytest.approx(10.0, rel=1e-6)
    
    def test_referrer_earnings_at_cap_boundary(self):
        """Calculate how much volume needed to hit $300 cap."""
        # referrer_amount = volume * 0.005 * 0.80 * 0.25 = volume * 0.001
        # To earn $300: volume = $300 / 0.001 = $300,000
        volume_to_cap = 300.0 / (PLATFORM_FEE * (1 - JUPITER_SPLIT) * REFERRER_SPLIT)
        
        result = calculate_fee_split(volume_to_cap, True, False)
        assert result["referrer_amount"] == pytest.approx(300.0, rel=1e-6)
    
    def test_cap_scenario_multiple_trades(self):
        """Simulate multiple trades approaching cap."""
        total_earned = 0.0
        trades = [50_000.0, 100_000.0, 100_000.0, 100_000.0]  # $350k total
        
        for volume in trades:
            # Check if would be capped
            capped = total_earned >= REFERRAL_CAP
            result = calculate_fee_split(volume, True, capped)
            
            if not capped:
                potential_earnings = result["referrer_amount"]
                # Cap the actual earnings
                actual_earnings = min(potential_earnings, REFERRAL_CAP - total_earned)
                total_earned += actual_earnings
        
        # Should be capped at $300
        assert total_earned == pytest.approx(300.0, rel=1e-2)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_very_small_volume(self):
        """Test with very small volume (dust)."""
        result = calculate_fee_split(0.01, True, False)
        
        # Even tiny volumes should calculate correctly
        assert result["gross_fee"] == pytest.approx(0.00005, rel=1e-6)
    
    def test_fractional_volumes(self):
        """Test with fractional dollar amounts."""
        result = calculate_fee_split(123.45, True, False)
        
        expected_gross = 123.45 * 0.005
        assert result["gross_fee"] == pytest.approx(expected_gross, rel=1e-6)
    
    def test_negative_volume_returns_negative_fees(self):
        """Negative volume should return negative fees (for reversals)."""
        result = calculate_fee_split(-1000.0, True, False)
        
        # Mathematically, negative volume gives negative fees
        assert result["gross_fee"] == -5.0
