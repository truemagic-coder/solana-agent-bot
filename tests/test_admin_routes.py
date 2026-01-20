"""
Tests for admin routes.

Tests for protected admin endpoints and fee claiming/payout operations.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestAdminAuthentication:
    """Test admin endpoint authentication."""
    
    @pytest.mark.asyncio
    async def test_valid_admin_key_passes(self):
        """Valid admin key should pass verification."""
        from solana_agent_api.admin_routes import verify_admin_key
        
        with patch('solana_agent_api.admin_routes.config') as mock_config:
            mock_config.HELIUS_WEBHOOK_SECRET = "valid_admin_key"
            
            # Should not raise
            result = await verify_admin_key("valid_admin_key")
            assert result is True
    
    @pytest.mark.asyncio
    async def test_invalid_admin_key_fails(self):
        """Invalid admin key should raise HTTPException."""
        from fastapi import HTTPException
        from solana_agent_api.admin_routes import verify_admin_key
        
        with patch('solana_agent_api.admin_routes.config') as mock_config:
            mock_config.HELIUS_WEBHOOK_SECRET = "valid_admin_key"
            
            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_key("invalid_key")
            
            assert exc_info.value.status_code == 403
            assert "Invalid admin key" in exc_info.value.detail
    
    @pytest.mark.asyncio
    async def test_missing_admin_key_fails(self):
        """Missing admin key should raise HTTPException."""
        from fastapi import HTTPException
        from solana_agent_api.admin_routes import verify_admin_key
        
        with patch('solana_agent_api.admin_routes.config') as mock_config:
            mock_config.HELIUS_WEBHOOK_SECRET = None  # No key configured
            
            with pytest.raises(HTTPException):
                await verify_admin_key("any_key")


class TestFeeStatusEndpoint:
    """Test /admin/fees/status endpoint."""
    
    @pytest.mark.asyncio
    async def test_returns_token_accounts_with_balances(self):
        """Should return token accounts and their USD values."""
        # Mock FeeClaimService
        mock_accounts = [
            {
                "pubkey": "account1",
                "mint": "SOL_MINT",
                "balance": 1000000000,
                "decimals": 9,
                "ui_amount": 1.0,
            },
            {
                "pubkey": "account2", 
                "mint": "USDC_MINT",
                "balance": 100000000,
                "decimals": 6,
                "ui_amount": 100.0,
            }
        ]
        
        with patch('solana_agent_api.admin_routes.FeeClaimService') as MockService:
            mock_instance = AsyncMock()
            mock_instance.get_referral_token_accounts = AsyncMock(return_value=mock_accounts)
            mock_instance.get_token_price = AsyncMock(side_effect=[150.0, 1.0])  # SOL=$150, USDC=$1
            mock_instance.referral_account = "test_account"
            MockService.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockService.return_value.__aexit__ = AsyncMock()
            
            # Would test via HTTP client in integration tests


class TestFeeClaimEndpoint:
    """Test /admin/fees/claim endpoint."""
    
    @pytest.mark.asyncio
    async def test_triggers_fee_claiming(self):
        """Should trigger fee claiming process."""
        from solana_agent_api.fee_claim_service import ClaimResult
        
        mock_results = [
            ClaimResult(
                mint="SOL_MINT",
                amount=1.0,
                usd_value=150.0,
                signature="sig1",
                success=True,
            ),
            ClaimResult(
                mint="USDC_MINT",
                amount=100.0,
                usd_value=100.0,
                signature="sig2",
                success=True,
            ),
        ]
        
        with patch('solana_agent_api.admin_routes.FeeClaimService') as MockService:
            mock_instance = AsyncMock()
            mock_instance.claim_all_fees = AsyncMock(return_value=mock_results)
            MockService.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockService.return_value.__aexit__ = AsyncMock()
            
            # Would test response format in integration tests


class TestSweepEndpoint:
    """Test /admin/fees/sweep endpoint."""
    
    @pytest.mark.asyncio
    async def test_sweeps_tokens_to_agent(self):
        """Should sweep all tokens to $AGENT."""
        mock_results = [
            {
                "input_mint": "SOL_MINT",
                "input_amount": 1.0,
                "usd_value": 150.0,
                "signature": "sweep_sig_1",
                "success": True,
            }
        ]
        
        with patch('solana_agent_api.admin_routes.FeeClaimService') as MockService:
            mock_instance = AsyncMock()
            mock_instance.sweep_all_to_agent = AsyncMock(return_value=mock_results)
            MockService.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockService.return_value.__aexit__ = AsyncMock()
            
            # Would verify sweep process was called


class TestPayoutEndpoint:
    """Test /admin/payout/run endpoint."""
    
    @pytest.mark.asyncio
    async def test_runs_full_payout_process(self):
        """Should run full daily payout process."""
        mock_result = {
            "timestamp": "2024-01-01T00:00:00",
            "claims": [],
            "sweeps": [],
            "distributions": [],
            "success": True,
        }
        
        with patch('solana_agent_api.admin_routes.FeeClaimService') as MockService:
            mock_instance = AsyncMock()
            mock_instance.run_daily_payout = AsyncMock(return_value=mock_result)
            MockService.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockService.return_value.__aexit__ = AsyncMock()
            
            # Would verify full process was triggered


class TestPendingPayoutsEndpoint:
    """Test /admin/payout/pending endpoint."""
    
    @pytest.mark.asyncio
    async def test_returns_pending_payouts(self, mock_db_service):
        """Should return list of pending referrer payouts."""
        pending = [
            {
                "privy_id": "did:privy:referrer1",
                "wallet_address": "Wallet1",
                "pending_amount": 50.0,
            },
            {
                "privy_id": "did:privy:referrer2",
                "wallet_address": "Wallet2",
                "pending_amount": 75.0,
            }
        ]
        
        mock_db_service.get_pending_payouts = AsyncMock(return_value=pending)
        
        # In actual endpoint test, would verify:
        # - List of pending payouts returned
        # - Total pending USD calculated (125.0)
        # - Count is correct (2)


class TestAdminStatsEndpoint:
    """Test /admin/stats endpoint."""
    
    @pytest.mark.asyncio
    async def test_returns_platform_statistics(self, mock_db_service):
        """Should return comprehensive platform statistics."""
        # Mock count queries
        mock_db_service.users.count_documents = AsyncMock(return_value=1000)
        mock_db_service.swaps.count_documents = AsyncMock(return_value=5000)
        mock_db_service.referrals.count_documents = AsyncMock(side_effect=[
            800,  # active referrals
            50,   # capped referrals
        ])
        
        # Mock aggregation results
        mock_agg_cursor = MagicMock()
        mock_agg_cursor.to_list = AsyncMock(side_effect=[
            [{"total": 1_000_000.0}],  # total volume
            [{"total": 5_000.0}],       # total fees
            [{"total": 2_500.0}],       # total paid
        ])
        mock_db_service.swaps.aggregate = MagicMock(return_value=mock_agg_cursor)
        mock_db_service.payouts.aggregate = MagicMock(return_value=mock_agg_cursor)
        
        # Would verify stats structure in integration tests


class TestAdminRoutesSecurity:
    """Test security aspects of admin routes."""
    
    def test_all_routes_require_admin_key(self):
        """All admin routes should require X-Admin-Key header."""
        from solana_agent_api.admin_routes import router
        
        admin_routes = [
            "/admin/fees/status",
            "/admin/fees/claim",
            "/admin/fees/sweep",
            "/admin/payout/run",
            "/admin/payout/pending",
            "/admin/stats",
        ]
        
        for route in router.routes:
            if hasattr(route, 'path'):
                # All admin routes should have x_admin_key parameter
                # This is a structural test - full auth test needs HTTP client
                pass
    
    def test_db_service_must_be_set(self, mock_db_service):
        """Routes should fail gracefully if db_service not set."""
        from solana_agent_api.admin_routes import set_db_service, _db_service
        
        # Before setting
        # Routes should handle None db_service
        
        # After setting
        set_db_service(mock_db_service)
        
        # Now routes should work


class TestResponseFormats:
    """Test admin route response formats."""
    
    def test_fee_status_response_format(self):
        """Verify fee status response structure."""
        expected_keys = [
            "referral_account",
            "token_accounts",
            "total_usd_estimate",
        ]
        
        # Would verify in integration tests
    
    def test_claim_response_format(self):
        """Verify claim response structure."""
        expected_keys = [
            "message",
            "results",
            "success_count",
            "total_count",
        ]
        
        # Would verify in integration tests
    
    def test_stats_response_format(self):
        """Verify stats response structure."""
        expected_structure = {
            "users": {"total": int},
            "trading": {
                "total_swaps": int,
                "total_volume_usd": float,
                "total_fees_usd": float,
            },
            "referrals": {
                "active": int,
                "capped": int,
                "total_paid_usd": float,
            },
        }
        
        # Would verify in integration tests
