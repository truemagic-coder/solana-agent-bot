"""
Live integration tests for Solana Agent API.

These tests run against real services - Birdeye, Jupiter, Grok, etc.
They require real API keys and a funded wallet.

IMPORTANT: These tests will execute real transactions on Solana mainnet!

Test wallet:
- Privy ID: cmdjl3j0f01jqjx0jg9adqgzb
- Wallet: EWogSwxu1my22oi9RNQmJTSerk6s7bTfYfzTpfwmsTBW

Run with:
    uv run pytest tests/integration/ -v -s --tb=short

Or specific tests:
    uv run pytest tests/integration/test_live.py::TestMarketData -v -s
    uv run pytest tests/integration/test_live.py::TestSwaps -v -s
"""

import asyncio
import logging
import pytest

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test timeout in seconds (LLM + tool calls can be slow)
TEST_TIMEOUT = 120  # 2 minutes per test

# Test wallet configuration
TEST_PRIVY_ID = "cmdjl3j0f01jqjx0jg9adqgzb"
TEST_WALLET = "EWogSwxu1my22oi9RNQmJTSerk6s7bTfYfzTpfwmsTBW"

# Well-known tokens for testing
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
AGENT_MINT = "5tFRno9GXBP5gt2Kjx2MeEaFL8zGBMw4cujTLGerpump"

# Minimum amounts for testing (in SOL)
MIN_SWAP_AMOUNT = 0.01  # 0.01 SOL ~ $2
MIN_LIMIT_AMOUNT = 0.01
MIN_DCA_AMOUNT = 0.01


@pytest.fixture(scope="function")
def event_loop():
    """Create an event loop for the test module."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="function")
async def solana_agent():
    """Initialize the Solana Agent for testing."""
    from solana_agent_api.main import solana_agent
    yield solana_agent


async def collect_response(agent, user_id: str, message: str, timeout: int = TEST_TIMEOUT) -> str:
    """Collect the full response from the agent with timeout."""
    full_response = ""
    
    async def _collect():
        nonlocal full_response
        async for chunk in agent.process(user_id, message):
            full_response += chunk
            # Print chunks as they come for visibility
            print(chunk, end="", flush=True)
        print()  # Newline after response
        return full_response
    
    try:
        return await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        print(f"\n[TIMEOUT after {timeout}s - partial response: {len(full_response)} chars]")
        if full_response:
            return full_response
        raise


# =============================================================================
# Market Data Tests (Birdeye MCP)
# =============================================================================


class TestMarketData:
    """Test Birdeye MCP integration for market data."""
    
    @pytest.mark.asyncio
    async def test_get_token_price(self, solana_agent):
        """Test fetching token price via Birdeye."""
        response = await collect_response(
            solana_agent, 
            TEST_PRIVY_ID,
            "What is the current price of $AGENT token?"
        )
        
        # Should contain price information
        assert any(word in response.lower() for word in ["price", "$", "usd", "sol"]), \
            f"Expected price info in response: {response}"
        
    @pytest.mark.asyncio
    async def test_get_token_info(self, solana_agent):
        """Test fetching token details."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            f"Tell me about the token with mint address {AGENT_MINT}"
        )
        
        # Should contain token info
        assert any(word in response.lower() for word in ["agent", "token", "supply", "holders"]), \
            f"Expected token info in response: {response}"
    
    @pytest.mark.asyncio
    async def test_get_wallet_holdings(self, solana_agent):
        """Test fetching wallet holdings."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "What tokens do I hold in my wallet?"
        )
        
        # Should show holdings or empty wallet message
        assert any(word in response.lower() for word in ["sol", "token", "balance", "hold", "wallet", "empty"]), \
            f"Expected holdings info in response: {response}"
    
    @pytest.mark.asyncio
    async def test_trending_tokens(self, solana_agent):
        """Test fetching trending tokens."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "What are the trending tokens on Solana right now?"
        )
        
        # Should contain trending info
        assert any(word in response.lower() for word in ["trending", "token", "volume", "trade"]), \
            f"Expected trending info in response: {response}"


# =============================================================================
# X Search Tests (Grok)
# =============================================================================


class TestXSearch:
    """Test Grok X search integration."""
    
    @pytest.mark.asyncio
    async def test_search_x_for_token(self, solana_agent):
        """Test searching X for token sentiment."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Search X for what people are saying about $AGENT token"
        )
        
        # Should contain search results
        assert len(response) > 50, f"Expected substantial response: {response}"
    
    @pytest.mark.asyncio
    async def test_search_crypto_news(self, solana_agent):
        """Test searching for crypto news."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Search the internet for latest Solana news"
        )
        
        # Should contain news info
        assert any(word in response.lower() for word in ["solana", "news", "announce", "update"]), \
            f"Expected news in response: {response}"


# =============================================================================
# Swap Tests (Jupiter Ultra)
# =============================================================================


class TestSwaps:
    """Test Jupiter Ultra swap integration.
    
    WARNING: These tests execute real swaps on mainnet!
    """
    
    @pytest.mark.asyncio
    async def test_get_swap_quote(self, solana_agent):
        """Test getting a swap quote (no execution)."""
        response = await collect_response(
            solana_agent, 
            TEST_PRIVY_ID,
            "How much USDC would I get for 0.01 SOL?"
        )        # Should contain quote info
        assert any(word in response.lower() for word in ["usdc", "receive", "get", "swap"]), \
            f"Expected quote in response: {response}"
    
    @pytest.mark.asyncio
    async def test_execute_small_swap(self, solana_agent):
        """Test executing a small swap.
        
        This swaps 0.01 SOL to USDC and back to minimize losses.
        """
        # First swap: SOL -> USDC
        response1 = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Swap 0.01 SOL to USDC"
        )
        
        # Should contain transaction confirmation
        assert any(word in response1.lower() for word in ["swap", "transaction", "success", "confirm", "usdc"]), \
            f"Expected swap confirmation: {response1}"
        
        # Check for transaction hash
        if "orbmarkets.io" in response1 or "solscan" in response1.lower():
            logger.info("Transaction link found in response")
        
        # Wait a moment for the transaction to confirm
        await asyncio.sleep(3)
        
        # Second swap: USDC -> SOL (to recover)
        response2 = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Swap all my USDC back to SOL"
        )
        
        assert any(word in response2.lower() for word in ["swap", "transaction", "success", "sol"]), \
            f"Expected swap confirmation: {response2}"


# =============================================================================
# Limit Order Tests (Jupiter Trigger)
# =============================================================================


class TestLimitOrders:
    """Test Jupiter Trigger limit order integration.
    
    WARNING: These tests create real limit orders on mainnet!
    """
    
    @pytest.mark.asyncio
    async def test_create_limit_order(self, solana_agent):
        """Test creating a limit order."""
        # Create a limit order to buy AGENT at a low price (unlikely to fill)
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Create a limit order to buy $AGENT with 0.01 SOL at 50% below current price"
        )
        
        # Should contain order confirmation
        assert any(word in response.lower() for word in ["order", "limit", "created", "trigger", "agent"]), \
            f"Expected order confirmation: {response}"
    
    @pytest.mark.asyncio
    async def test_list_limit_orders(self, solana_agent):
        """Test listing active limit orders."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Show me my active limit orders"
        )
        
        # Should list orders or say none
        assert any(word in response.lower() for word in ["order", "limit", "active", "none", "no order"]), \
            f"Expected order list: {response}"
    
    @pytest.mark.asyncio
    async def test_cancel_limit_order(self, solana_agent):
        """Test cancelling a limit order."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Cancel all my limit orders"
        )
        
        # Should confirm cancellation or say none to cancel
        assert any(word in response.lower() for word in ["cancel", "order", "none", "no order", "success"]), \
            f"Expected cancellation confirmation: {response}"


# =============================================================================
# DCA Tests (Jupiter Recurring)
# =============================================================================


class TestDCA:
    """Test Jupiter Recurring DCA integration.
    
    WARNING: These tests create real DCA orders on mainnet!
    """
    
    @pytest.mark.asyncio
    async def test_create_dca_order(self, solana_agent):
        """Test creating a DCA order."""
        # Create a small DCA order
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Set up a DCA to buy $AGENT with 0.01 SOL every day for 2 days"
        )
        
        # Should contain DCA confirmation
        assert any(word in response.lower() for word in ["dca", "recurring", "order", "created", "daily"]), \
            f"Expected DCA confirmation: {response}"
    
    @pytest.mark.asyncio
    async def test_list_dca_orders(self, solana_agent):
        """Test listing active DCA orders."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Show me my active DCA orders"
        )
        
        # Should list orders or say none
        assert any(word in response.lower() for word in ["dca", "recurring", "order", "none", "active"]), \
            f"Expected DCA list: {response}"
    
    @pytest.mark.asyncio
    async def test_cancel_dca_order(self, solana_agent):
        """Test cancelling a DCA order."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Cancel all my DCA orders"
        )
        
        # Should confirm cancellation or say none
        assert any(word in response.lower() for word in ["cancel", "dca", "order", "none", "success"]), \
            f"Expected cancellation confirmation: {response}"


# =============================================================================
# Wallet Tests
# =============================================================================


class TestWallet:
    """Test wallet operations."""
    
    @pytest.mark.asyncio
    async def test_get_wallet_address(self, solana_agent):
        """Test fetching user's wallet address."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "What is my wallet address?"
        )
        
        # Should contain wallet address
        assert TEST_WALLET.lower() in response.lower() or \
               any(word in response.lower() for word in ["wallet", "address"]), \
            f"Expected wallet address in response: {response}"
    
    @pytest.mark.asyncio
    async def test_check_sol_balance(self, solana_agent):
        """Test checking SOL balance."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "How much SOL do I have?"
        )
        
        # Should contain balance info
        assert any(word in response.lower() for word in ["sol", "balance", "have"]), \
            f"Expected balance in response: {response}"


# =============================================================================
# Token Analysis Tests
# =============================================================================


class TestTokenAnalysis:
    """Test token analysis tools."""
    
    @pytest.mark.asyncio
    async def test_rugcheck(self, solana_agent):
        """Test rugcheck on a token."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Rugcheck the $AGENT token"
        )
        
        # Should contain rugcheck info
        assert any(word in response.lower() for word in ["rug", "risk", "score", "check", "safe", "warning"]), \
            f"Expected rugcheck info: {response}"
    
    @pytest.mark.asyncio
    async def test_jupiter_shield(self, solana_agent):
        """Test Jupiter Shield analysis."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            f"Check the safety of token {AGENT_MINT} using Jupiter Shield"
        )
        
        # Should contain safety info
        assert len(response) > 20, f"Expected substantial response: {response}"
    
    @pytest.mark.asyncio
    async def test_token_search(self, solana_agent):
        """Test searching for tokens."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Search for tokens named BONK"
        )
        
        # Should return token results
        assert any(word in response.lower() for word in ["bonk", "token", "mint", "found"]), \
            f"Expected token search results: {response}"


# =============================================================================
# Full Flow Tests
# =============================================================================


class TestFullFlows:
    """Test complete user flows."""
    
    @pytest.mark.asyncio
    async def test_research_and_swap_flow(self, solana_agent):
        """Test a complete flow: research token, check price, swap."""
        # Step 1: Research
        response1 = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Tell me about the $AGENT token - what's the price and what are people saying about it on X?"
        )
        logger.info(f"Research response length: {len(response1)}")
        
        # Step 2: Check wallet
        response2 = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "How much SOL do I have available to trade?"
        )
        logger.info(f"Balance response: {response2[:200]}...")
        
        # All responses should be substantial
        assert len(response1) > 100, "Research response too short"
        assert len(response2) > 20, "Balance response too short"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Test error handling for edge cases."""
    
    @pytest.mark.asyncio
    async def test_invalid_token_address(self, solana_agent):
        """Test handling of invalid token address."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Tell me about token with address INVALID123"
        )
        
        # Should handle gracefully
        assert len(response) > 10, "Should provide some response"
    
    @pytest.mark.asyncio
    async def test_insufficient_balance_swap(self, solana_agent):
        """Test handling of swap with insufficient balance."""
        response = await collect_response(
            solana_agent,
            TEST_PRIVY_ID,
            "Swap 1000000 SOL to USDC"
        )
        
        # Should explain insufficient balance
        assert any(word in response.lower() for word in ["insufficient", "balance", "enough", "not enough", "don't have"]), \
            f"Expected insufficient balance message: {response}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
