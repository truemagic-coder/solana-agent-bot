
import pytest
from unittest.mock import AsyncMock, MagicMock
from solana_agent_api.telegram_bot import TelegramBot

@pytest.mark.asyncio
async def test_transfer_to_user_without_wallet():
    """Test transfer to a user who exists but has no wallet address."""
    # Mock bot and dependencies
    mock_agent = MagicMock()
    mock_db = MagicMock()
    
    # Mock user found but wallet_address is None
    mock_db.get_user_by_username = AsyncMock(return_value={
        "privy_id": "test_id",
        "wallet_address": None,  # This causes the crash
        "tg_username": "walletbubbles"
    })
    
    bot = TelegramBot(mock_agent, mock_db)
    # Mock client reply
    bot.client.start = AsyncMock()
    
    # Mock event
    mock_event = MagicMock()
    mock_event.reply = AsyncMock()
    
    # Execute transfer - should NOT raise TypeError now
    try:
        await bot._handle_transfer(mock_event, 12345, "/transfer $2 SOL to @walletbubbles")
    except TypeError:
        pytest.fail("TypeError was raised! Fix failed.")
        
    # Verify proper error message was sent
    args, _ = mock_event.reply.call_args
    assert "don't have a wallet" in args[0] # Check for part of the error message
