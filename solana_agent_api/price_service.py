"""
Simple price service for fetching SOL/USDC prices from Birdeye.
Used for Privacy Cash fee calculations.
"""
import logging
from typing import Optional

import httpx

from solana_agent_api.config import config as app_config

logger = logging.getLogger(__name__)

# Birdeye API base URL
BIRDEYE_API_URL = "https://public-api.birdeye.so"

# Known token addresses
WRAPPED_SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


async def get_token_price(mint: str) -> Optional[float]:
    """
    Get the USD price of a token from Birdeye.

    Args:
        mint: Token mint address

    Returns:
        USD price or None if not found
    """
    if not mint or mint == "unknown":
        return None

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BIRDEYE_API_URL}/defi/price",
                params={"address": mint},
                headers={
                    "X-API-KEY": app_config.BIRDEYE_API_KEY,
                    "x-chain": "solana",
                },
                timeout=10.0,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("data"):
                    price = data["data"].get("value")
                    if price is not None:
                        logger.debug(f"Got price for {mint[:8]}...: ${price}")
                        return float(price)
            else:
                logger.warning(f"Birdeye API error: {response.status_code} for {mint}")

    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching price for {mint}")
    except Exception as e:
        logger.error(f"Error fetching price for {mint}: {e}")

    return None


async def get_sol_price() -> Optional[float]:
    """Get the current SOL price in USD."""
    return await get_token_price(WRAPPED_SOL)


async def get_usdc_price() -> Optional[float]:
    """Get the current USDC price in USD (should be ~1.0)."""
    return await get_token_price(USDC)


async def sol_to_usdc(sol_amount: float) -> Optional[float]:
    """
    Convert a SOL amount to USDC equivalent.

    Args:
        sol_amount: Amount in SOL

    Returns:
        Equivalent amount in USDC, or None if price unavailable
    """
    sol_price = await get_sol_price()
    if sol_price is None:
        return None
    # SOL price is in USD, USDC is ~1 USD, so SOL * price = USDC equivalent
    return sol_amount * sol_price
