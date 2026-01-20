import pytest

from solana_agent_api import price_service


@pytest.mark.asyncio
async def test_calculate_swap_volume_usd_prefers_larger_value(monkeypatch):
    async def fake_get_token_decimals(_mint: str) -> int:
        return 9

    async def fake_get_multiple_token_prices(_mints):
        return {
            "input": 2.0,  # $2 per token
            "output": 1.0,  # $1 per token
        }

    monkeypatch.setattr(price_service, "get_token_decimals", fake_get_token_decimals)
    monkeypatch.setattr(price_service, "get_multiple_token_prices", fake_get_multiple_token_prices)

    volume = await price_service.calculate_swap_volume_usd(
        input_token="input",
        input_amount=1_000_000_000,  # 1 token in lamports
        output_token="output",
        output_amount=3_000_000_000,  # 3 tokens in lamports
    )

    # input value = 1 * $2 = $2, output value = 3 * $1 = $3
    assert volume == 3.0


def test_lamports_to_tokens_and_is_likely_lamports():
    assert price_service.lamports_to_tokens(1_000_000_000, 9) == 1.0
    assert price_service.lamports_to_tokens(123, 0) == 123
    assert price_service.is_likely_lamports(1_000_000_000, 9) is True
    assert price_service.is_likely_lamports(0.5, 9) is False
