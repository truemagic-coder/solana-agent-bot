"""
Tests for price service and volume calculations.

These tests ensure token prices and swap volumes are calculated correctly.
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

from solana_agent_api.price_service import (
    get_token_price,
    get_multiple_token_prices,
    get_token_decimals,
    get_token_metadata,
    calculate_swap_volume_usd,
    lamports_to_tokens,
    is_likely_lamports,
    clear_price_cache,
    clear_decimals_cache,
    KNOWN_DECIMALS,
    WRAPPED_SOL,
    USDC,
    USDT,
)


class TestKnownDecimals:
    """Test known token decimals are correctly defined."""
    
    def test_wsol_decimals(self):
        """WSOL has 9 decimals."""
        assert KNOWN_DECIMALS[WRAPPED_SOL] == 9
    
    def test_usdc_decimals(self):
        """USDC has 6 decimals."""
        assert KNOWN_DECIMALS[USDC] == 6
    
    def test_usdt_decimals(self):
        """USDT has 6 decimals."""
        assert KNOWN_DECIMALS[USDT] == 6


class TestLamportsConversion:
    """Test lamports to token conversion."""
    
    def test_sol_lamports_to_tokens(self):
        """Convert SOL lamports (9 decimals)."""
        lamports = 1_000_000_000  # 1 SOL
        tokens = lamports_to_tokens(lamports, 9)
        assert tokens == 1.0
    
    def test_usdc_smallest_to_tokens(self):
        """Convert USDC smallest units (6 decimals)."""
        smallest = 1_000_000  # 1 USDC
        tokens = lamports_to_tokens(smallest, 6)
        assert tokens == 1.0
    
    def test_fractional_lamports(self):
        """Convert fractional amounts."""
        lamports = 1_500_000_000  # 1.5 SOL
        tokens = lamports_to_tokens(lamports, 9)
        assert tokens == 1.5
    
    def test_zero_decimals(self):
        """Token with zero decimals."""
        amount = 100
        result = lamports_to_tokens(amount, 0)
        assert result == 100
    
    def test_zero_amount(self):
        """Zero amount stays zero."""
        result = lamports_to_tokens(0, 9)
        assert result == 0.0


class TestIsLikelyLamports:
    """Test heuristic for detecting lamport amounts."""
    
    def test_sol_lamports_detected(self):
        """1 billion should be detected as lamports for 9-decimal token."""
        assert is_likely_lamports(1_000_000_000, 9) is True
    
    def test_small_amounts_not_lamports(self):
        """Small amounts should not be flagged as lamports."""
        assert is_likely_lamports(1.5, 9) is False
        assert is_likely_lamports(100.0, 9) is False
    
    def test_usdc_lamports_detected(self):
        """1 million should be detected as lamports for 6-decimal token."""
        assert is_likely_lamports(1_000_000, 6) is True
    
    def test_boundary_case(self):
        """Test boundary at exactly 10^decimals."""
        # Exactly at threshold should be True
        assert is_likely_lamports(10**9, 9) is True
        # Just below should be False
        assert is_likely_lamports(10**9 - 1, 9) is False
    
    def test_zero_returns_false(self):
        """Zero amount should return False."""
        assert is_likely_lamports(0, 9) is False
    
    def test_negative_returns_false(self):
        """Negative amount should return False."""
        assert is_likely_lamports(-100, 9) is False


class TestGetTokenDecimals:
    """Test token decimals fetching."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear caches before each test."""
        clear_decimals_cache()
        clear_price_cache()
    
    @pytest.mark.asyncio
    async def test_known_token_returns_cached(self):
        """Known tokens should return immediately."""
        decimals = await get_token_decimals(WRAPPED_SOL)
        assert decimals == 9
        
        decimals = await get_token_decimals(USDC)
        assert decimals == 6
    
    @pytest.mark.asyncio
    async def test_unknown_token_returns_default(self):
        """Unknown token should return 9 as default."""
        with patch('solana_agent_api.price_service.get_token_metadata', return_value=None):
            decimals = await get_token_decimals("unknown_mint_address")
            assert decimals == 9
    
    @pytest.mark.asyncio
    async def test_invalid_input_returns_default(self):
        """Invalid/empty input should return default."""
        assert await get_token_decimals("") == 9
        assert await get_token_decimals("unknown") == 9
        assert await get_token_decimals(None) == 9


class TestGetTokenPrice:
    """Test token price fetching from Birdeye."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear caches before each test."""
        clear_price_cache()
        clear_decimals_cache()
    
    @pytest.mark.asyncio
    async def test_successful_price_fetch(self):
        """Test successful price fetch from Birdeye."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"value": 150.50}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            
            price = await get_token_price(WRAPPED_SOL)
            assert price == 150.50
    
    @pytest.mark.asyncio
    async def test_api_error_returns_none(self):
        """Test that API errors return None."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            
            price = await get_token_price(WRAPPED_SOL)
            assert price is None
    
    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        """Test that timeouts return None."""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            
            price = await get_token_price(WRAPPED_SOL)
            assert price is None
    
    @pytest.mark.asyncio
    async def test_invalid_input_returns_none(self):
        """Test invalid input returns None."""
        assert await get_token_price("") is None
        assert await get_token_price("unknown") is None
        assert await get_token_price(None) is None


class TestCalculateSwapVolumeUsd:
    """Test swap volume USD calculation."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear caches before each test."""
        clear_price_cache()
        clear_decimals_cache()
    
    @pytest.mark.asyncio
    async def test_sol_to_usdc_swap_lamports(self):
        """Test SOL->USDC swap with lamport amounts."""
        # Mock prices: SOL = $150, USDC = $1
        with patch('solana_agent_api.price_service.get_multiple_token_prices') as mock_prices:
            mock_prices.return_value = {
                WRAPPED_SOL: 150.0,
                USDC: 1.0,
            }
            
            # 1 SOL (in lamports) -> 150 USDC (in smallest units)
            volume = await calculate_swap_volume_usd(
                input_token=WRAPPED_SOL,
                input_amount=1_000_000_000,  # 1 SOL in lamports
                output_token=USDC,
                output_amount=150_000_000,  # 150 USDC in smallest units
            )
            
            # Should use max of input/output USD values
            # Input: 1 SOL * $150 = $150
            # Output: 150 USDC * $1 = $150
            assert volume == pytest.approx(150.0, rel=0.01)
    
    @pytest.mark.asyncio
    async def test_volume_uses_max_of_input_output(self):
        """Volume should use max of input/output values (for slippage)."""
        with patch('solana_agent_api.price_service.get_multiple_token_prices') as mock_prices:
            mock_prices.return_value = {
                WRAPPED_SOL: 150.0,
                USDC: 1.0,
            }
            
            # Swap with 1% slippage
            volume = await calculate_swap_volume_usd(
                input_token=WRAPPED_SOL,
                input_amount=1_000_000_000,  # 1 SOL = $150
                output_token=USDC,
                output_amount=148_500_000,  # 148.5 USDC (1.5% slippage)
            )
            
            # Should use input value ($150) not output ($148.5)
            assert volume == pytest.approx(150.0, rel=0.01)
    
    @pytest.mark.asyncio
    async def test_zero_amounts_return_zero(self):
        """Zero amounts should return zero volume."""
        volume = await calculate_swap_volume_usd(
            input_token=WRAPPED_SOL,
            input_amount=0,
            output_token=USDC,
            output_amount=0,
        )
        assert volume == 0.0
    
    @pytest.mark.asyncio
    async def test_missing_prices_return_zero(self):
        """Missing prices should result in zero volume."""
        with patch('solana_agent_api.price_service.get_multiple_token_prices') as mock_prices:
            mock_prices.return_value = {}  # No prices available
            
            volume = await calculate_swap_volume_usd(
                input_token="unknown_token",
                input_amount=1000,
                output_token="another_unknown",
                output_amount=2000,
            )
            assert volume == 0.0
    
    @pytest.mark.asyncio
    async def test_partial_price_data(self):
        """Should work with only one token price available."""
        with patch('solana_agent_api.price_service.get_multiple_token_prices') as mock_prices:
            # Only SOL price available
            mock_prices.return_value = {WRAPPED_SOL: 150.0}
            
            volume = await calculate_swap_volume_usd(
                input_token=WRAPPED_SOL,
                input_amount=1_000_000_000,  # 1 SOL
                output_token="unknown_token",
                output_amount=1000,
            )
            
            # Should use SOL value
            assert volume == pytest.approx(150.0, rel=0.01)
    
    @pytest.mark.asyncio
    async def test_token_amounts_not_lamports(self):
        """Test with amounts already in token units (not lamports)."""
        with patch('solana_agent_api.price_service.get_multiple_token_prices') as mock_prices:
            mock_prices.return_value = {
                WRAPPED_SOL: 150.0,
                USDC: 1.0,
            }
            
            # Small amounts that shouldn't be converted
            volume = await calculate_swap_volume_usd(
                input_token=WRAPPED_SOL,
                input_amount=1.0,  # 1 SOL (already in token units)
                output_token=USDC,
                output_amount=150.0,  # 150 USDC (already in token units)
            )
            
            # These small amounts shouldn't trigger lamports conversion
            # 1.0 < 10^9 so won't be converted
            assert volume == pytest.approx(150.0, rel=0.01)


class TestCacheBehavior:
    """Test price caching behavior."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear caches before each test."""
        clear_price_cache()
        clear_decimals_cache()
    
    @pytest.mark.asyncio
    async def test_price_is_cached(self):
        """Second call should use cached price."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"value": 150.0}
        }
        
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_client.return_value)
            mock_client.return_value.__aexit__ = AsyncMock()
            mock_client.return_value.get = AsyncMock(return_value=mock_response)
            
            # First call
            price1 = await get_token_price(WRAPPED_SOL)
            
            # Second call should use cache
            price2 = await get_token_price(WRAPPED_SOL)
            
            assert price1 == price2 == 150.0
            # API should only be called once
            assert mock_client.return_value.get.call_count == 1
    
    def test_clear_price_cache(self):
        """Test cache clearing."""
        from solana_agent_api.price_service import _price_cache
        
        # Clear first, then add something
        clear_price_cache()
        
        # Add something to cache
        _price_cache["test_mint"] = (100.0, 0)
        assert len(_price_cache) >= 1
        
        clear_price_cache()
        
        assert len(_price_cache) == 0
    
    def test_clear_decimals_cache(self):
        """Test decimals cache clearing."""
        from solana_agent_api.price_service import _decimals_cache
        
        # Clear first, then add something
        clear_decimals_cache()
        
        # Add something to cache
        _decimals_cache["test_mint"] = 9
        assert len(_decimals_cache) >= 1
        
        clear_decimals_cache()
        
        assert len(_decimals_cache) == 0
