import pytest
from mongomock_motor import AsyncMongoMockClient

from solana_agent_api.database import DatabaseService


@pytest.fixture()
def db_service(monkeypatch):
    monkeypatch.setattr(
        "solana_agent_api.database.AsyncIOMotorClient",
        AsyncMongoMockClient,
    )
    return DatabaseService("mongodb://localhost:27017", "test_db")


@pytest.mark.asyncio
async def test_get_or_create_user_updates_missing_fields(db_service):
    await db_service.create_user("privy-1")

    user = await db_service.get_or_create_user(
        "privy-1",
        wallet_address="Wallet111",
        wallet_id="wallet-id",
        user_id="user-id",
        tg_user_id=123,
        tg_username="tester",
    )

    assert user["wallet_address"] == "Wallet111"
    assert user["wallet_id"] == "wallet-id"
    assert user["user_id"] == "user-id"
    assert user["tg_user_id"] == 123
    assert user["tg_username"] == "tester"
