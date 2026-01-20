import pytest
from mongomock_motor import AsyncMongoMockClient

from solana_agent_api.database import DatabaseService
from solana_agent_api.models import REFERRAL_CAP


@pytest.fixture()
def db_service(monkeypatch):
    monkeypatch.setattr(
        "solana_agent_api.database.AsyncIOMotorClient",
        AsyncMongoMockClient,
    )
    return DatabaseService("mongodb://localhost:27017", "test_db")


@pytest.mark.asyncio
async def test_create_user_with_referral_creates_referral(db_service):
    referrer = await db_service.create_user("privy-referrer", wallet_address="WalletR")
    referral_code = referrer["referral_code"]

    new_user = await db_service.create_user(
        "privy-new",
        wallet_address="WalletN",
        referral_code_used=referral_code,
    )

    assert new_user["referred_by"] == referrer["privy_id"]
    referral = await db_service.get_referral(referrer["privy_id"], "privy-new")
    assert referral is not None


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


@pytest.mark.asyncio
async def test_update_referral_earnings_caps_at_limit(db_service):
    await db_service.create_user("privy-referrer")
    await db_service.create_user("privy-referee")
    await db_service.create_referral("privy-referrer", "privy-referee")

    await db_service.referrals.update_one(
        {"referrer_privy_id": "privy-referrer", "referee_privy_id": "privy-referee"},
        {"$set": {"total_earned": REFERRAL_CAP - 1.0}},
    )

    updated = await db_service.update_referral_earnings(
        referrer_privy_id="privy-referrer",
        referee_privy_id="privy-referee",
        amount=10.0,
    )

    referral = await db_service.get_referral("privy-referrer", "privy-referee")
    assert updated is True
    assert referral["total_earned"] == REFERRAL_CAP
    assert referral["capped"] is True
    assert referral["capped_at"] is not None


@pytest.mark.asyncio
async def test_record_swap_updates_volumes_and_referral(db_service):
    referrer = await db_service.create_user("privy-referrer", wallet_address="WalletR")
    referee = await db_service.create_user(
        "privy-referee",
        wallet_address="WalletF",
        referral_code_used=referrer["referral_code"],
    )

    swap = await db_service.record_swap(
        tx_signature="tx-1",
        wallet_address="WalletF",
        input_token="SOL",
        input_amount=1.0,
        output_token="USDC",
        output_amount=20.0,
        volume_usd=20.0,
    )

    assert swap is not None
    referral = await db_service.get_referral(referrer["privy_id"], referee["privy_id"])
    assert referral["total_earned"] > 0

    updated_user = await db_service.get_user_by_privy_id(referee["privy_id"])
    assert updated_user["last_trade_at"] is not None
    assert updated_user["volume_30d"] == 20.0
