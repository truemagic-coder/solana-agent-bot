"""
Pytest fixtures and configuration for tests.
"""
import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# =============================================================================
# ASYNC FIXTURES
# =============================================================================

@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# MOCK DATA
# =============================================================================

@pytest.fixture
def sample_user():
    """Sample user document."""
    return {
        "privy_id": "did:privy:test-user-123",
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        "tg_user_id": 123456789,
        "referral_code": "ABC12345",
        "referred_by": None,
        "volume_30d": 5000.0,
        "created_at": datetime.utcnow(),
        "last_trade_at": datetime.utcnow(),
    }


@pytest.fixture
def sample_referrer():
    """Sample referrer user document."""
    return {
        "privy_id": "did:privy:referrer-456",
        "wallet_address": "9xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgBsU",
        "tg_user_id": 987654321,
        "referral_code": "REF98765",
        "referred_by": None,
        "volume_30d": 10000.0,
        "created_at": datetime.utcnow(),
        "last_trade_at": datetime.utcnow(),
    }


@pytest.fixture
def sample_referred_user(sample_referrer):
    """Sample referred user document."""
    return {
        "privy_id": "did:privy:referred-789",
        "wallet_address": "8xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgCsU",
        "tg_user_id": 111222333,
        "referral_code": "NEW54321",
        "referred_by": sample_referrer["privy_id"],
        "volume_30d": 1000.0,
        "created_at": datetime.utcnow(),
        "last_trade_at": datetime.utcnow(),
    }


@pytest.fixture
def sample_referral(sample_referrer, sample_referred_user):
    """Sample referral document."""
    return {
        "referrer_privy_id": sample_referrer["privy_id"],
        "referee_privy_id": sample_referred_user["privy_id"],
        "total_earned": 50.0,
        "cap": 300.0,
        "capped": False,
        "created_at": datetime.utcnow(),
        "capped_at": None,
    }


@pytest.fixture
def sample_swap():
    """Sample swap document."""
    return {
        "tx_signature": "5UfgVz3qJrLKshEYQJHQJUKxWCH1k5sJCp6bhBSYJvXKgkNJZ7TqVqJqMkJP5AJnCWY6v7QJGxKsNW8YQJHSjXKc",
        "user_privy_id": "did:privy:test-user-123",
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        "input_token": "So11111111111111111111111111111111111111112",  # WSOL
        "input_amount": 1.5,
        "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        "output_amount": 250.0,
        "volume_usd": 250.0,
        "fee_amount_usd": 1.25,  # 0.5% of 250
        "jupiter_amount": 0.25,  # 20% of 1.25
        "platform_amount": 0.55,  # 55% of remaining
        "referrer_privy_id": None,
        "referrer_amount": 0.0,
        "created_at": datetime.utcnow(),
    }


@pytest.fixture
def sample_helius_webhook_payload():
    """Sample Helius webhook payload for a swap."""
    return {
        "signature": "5UfgVz3qJrLKshEYQJHQJUKxWCH1k5sJCp6bhBSYJvXKgkNJZ7TqVqJqMkJP5AJnCWY6v7QJGxKsNW8YQJHSjXKc",
        "type": "SWAP",
        "timestamp": 1700000000,
        "slot": 250000000,
        "fee": 5000,
        "feePayer": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
        "nativeTransfers": [
            {
                "fromUserAccount": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
                "toUserAccount": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
                "amount": 1500000000,  # 1.5 SOL in lamports
            }
        ],
        "tokenTransfers": [
            {
                "fromUserAccount": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
                "toUserAccount": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
                "mint": "So11111111111111111111111111111111111111112",
                "tokenAmount": 1500000000,
            },
            {
                "fromUserAccount": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
                "toUserAccount": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",
                "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "tokenAmount": 250000000,  # 250 USDC with 6 decimals
            }
        ],
        "accountData": [],
        "events": {
            "swap": {
                "nativeInput": {
                    "amount": 1500000000,
                },
                "tokenOutputs": [
                    {
                        "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                        "amount": 250000000,
                    }
                ],
            }
        },
    }


# =============================================================================
# MOCK SERVICES
# =============================================================================

@pytest.fixture
def mock_http_client():
    """Mock httpx.AsyncClient for external API calls."""
    client = AsyncMock(spec=httpx.AsyncClient)
    return client


@pytest.fixture
def mock_birdeye_price_response():
    """Mock Birdeye price API response."""
    def make_response(price: float):
        return {
            "success": True,
            "data": {
                "value": price,
            }
        }
    return make_response


@pytest.fixture
def mock_birdeye_multi_price_response():
    """Mock Birdeye multi-price API response."""
    def make_response(prices: dict):
        return {
            "success": True,
            "data": {
                mint: {"value": price} for mint, price in prices.items()
            }
        }
    return make_response


@pytest.fixture
def mock_birdeye_metadata_response():
    """Mock Birdeye token metadata API response."""
    def make_response(decimals: int, symbol: str = "TOKEN"):
        return {
            "success": True,
            "data": {
                "decimals": decimals,
                "symbol": symbol,
                "name": f"Test {symbol}",
            }
        }
    return make_response


# =============================================================================
# DATABASE MOCKS
# =============================================================================

@pytest.fixture
def mock_collection():
    """Create a mock MongoDB collection."""
    def _create_collection():
        collection = AsyncMock()
        collection.find_one = AsyncMock(return_value=None)
        collection.insert_one = AsyncMock()
        collection.update_one = AsyncMock()
        collection.count_documents = AsyncMock(return_value=0)
        collection.aggregate = MagicMock()
        collection.aggregate.return_value.to_list = AsyncMock(return_value=[])
        collection.find = MagicMock()
        collection.find.return_value.to_list = AsyncMock(return_value=[])
        collection.create_index = AsyncMock()
        return collection
    return _create_collection


@pytest.fixture
def mock_db_service(mock_collection):
    """Create a mock DatabaseService."""
    from solana_agent_api.database import DatabaseService
    
    with patch.object(DatabaseService, '__init__', lambda self, *args, **kwargs: None):
        service = DatabaseService.__new__(DatabaseService)
        # Give each collection its own mock
        service.users = mock_collection()
        service.referrals = mock_collection()
        service.swaps = mock_collection()
        service.payouts = mock_collection()
        service.daily_volumes = mock_collection()
        service.client = MagicMock()
        service.db = MagicMock()
        return service


# =============================================================================
# SOLANA FIXTURES
# =============================================================================

@pytest.fixture
def sample_token_accounts():
    """Sample token account data for fee claiming."""
    from solders.pubkey import Pubkey
    
    return [
        {
            "pubkey": str(Pubkey.default()),
            "mint": "So11111111111111111111111111111111111111112",  # WSOL
            "balance": 1000000000,  # 1 SOL
            "decimals": 9,
            "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        },
        {
            "pubkey": str(Pubkey.default()),
            "mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "balance": 100000000,  # 100 USDC
            "decimals": 6,
            "token_program": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
        },
    ]


@pytest.fixture
def sample_rpc_response():
    """Sample Solana RPC response."""
    def make_response(result):
        return {
            "jsonrpc": "2.0",
            "id": 1,
            "result": result,
        }
    return make_response


# =============================================================================
# CONFIG MOCKS
# =============================================================================

@pytest.fixture
def mock_config():
    """Mock configuration for tests."""
    with patch('solana_agent_api.config.config') as mock:
        mock.MONGO_URL = "mongodb://localhost:27017"
        mock.MONGO_DB = "test_db"
        mock.BIRDEYE_API_KEY = "test-birdeye-key"
        mock.JUPITER_API_KEY = "test-jupiter-key"
        mock.JUPITER_REFERRAL_ULTRA_CODE = "11111111111111111111111111111111"
        mock.JUPITER_REFERRAL_TRIGGER_CODE = "22222222222222222222222222222222"
        mock.HELIUS_URL = "https://mainnet.helius-rpc.com/?api-key=test"
        mock.HELIUS_WEBHOOK_SECRET = "test-webhook-secret"
        mock.FEE_PAYER = None  # Don't use real keys in tests
        mock.FEE_PAYER_PUBLIC_KEY = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
        mock.WEB_APP_URL = "https://test.example.com"
        yield mock
