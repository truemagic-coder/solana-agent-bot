from datetime import datetime

from solana_agent_api import models


def test_calculate_fee_split():
    split = models.calculate_fee_split(volume_usd=1000.0)
    assert split["gross_fee"] == 1000.0 * models.PLATFORM_FEE
    assert split["jupiter_amount"] == split["gross_fee"] * models.JUPITER_SPLIT
    assert split["platform_amount"] == split["gross_fee"] - split["jupiter_amount"]


def test_user_document_sets_optional_fields():
    doc = models.user_document(
        privy_id="did:privy:test",
        wallet_address="Wallet111",
        wallet_id="wallet-id",
        user_id="user-id",
        tg_user_id=123,
        tg_username="tester",
    )
    assert doc["privy_id"] == "did:privy:test"
    assert doc["wallet_address"] == "Wallet111"
    assert doc["wallet_id"] == "wallet-id"
    assert doc["user_id"] == "user-id"
    assert doc["tg_user_id"] == 123
    assert doc["tg_username"] == "tester"
    assert isinstance(doc["created_at"], datetime)


def test_payment_request_document_has_short_id():
    doc = models.payment_request_document(
        wallet_address="Wallet111",
        token_mint="Mint111",
        token_symbol="TEST",
        amount=1.23,
        amount_usd=4.56,
        is_private=True,
    )
    assert "_id" in doc
    assert len(doc["_id"]) == 10
    assert doc["status"] == "pending"
