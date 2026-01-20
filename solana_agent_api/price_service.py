"""
Price service for fetching token prices and metadata from Birdeye.
"""
import logging
from typing import Optional, Dict, Tuple
import httpx

from solana_agent_api.config import config as app_config

logger = logging.getLogger(__name__)

# Birdeye API base URL
BIRDEYE_API_URL = "https://public-api.birdeye.so"

# Cache for prices (simple in-memory cache)
# In production, consider Redis with TTL
_price_cache: Dict[str, Tuple[float, float]] = {}  # mint -> (price, timestamp)
_decimals_cache: Dict[str, int] = {}  # mint -> decimals
CACHE_TTL_SECONDS = 60  # Cache prices for 60 seconds

# Known token addresses and their decimals
WRAPPED_SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"

# Pre-populate known token decimals
KNOWN_DECIMALS = {
    WRAPPED_SOL: 9,
    USDC: 6,
    USDT: 6,
    "11111111111111111111111111111111": 9,  # Native SOL (system program)
}


async def get_token_metadata(mint: str) -> Optional[Dict]:
    """
    Get token metadata including decimals from Birdeye.
    
    Args:
        mint: Token mint address
        
    Returns:
        Token metadata dict or None if not found
    """
    if not mint or mint == "unknown":
        return None
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BIRDEYE_API_URL}/defi/token_overview",
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
                    return data["data"]
            else:
                logger.warning(f"Birdeye token_overview API error: {response.status_code} for {mint}")
                
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching metadata for {mint}")
    except Exception as e:
        logger.error(f"Error fetching metadata for {mint}: {e}")
    
    return None


async def get_token_decimals(mint: str) -> int:
    """
    Get the number of decimals for a token.
    
    Args:
        mint: Token mint address
        
    Returns:
        Number of decimals (defaults to 9 if unknown)
    """
    if not mint or mint == "unknown":
        return 9  # Default to SOL decimals
    
    # Check known tokens first
    if mint in KNOWN_DECIMALS:
        return KNOWN_DECIMALS[mint]
    
    # Check cache
    if mint in _decimals_cache:
        return _decimals_cache[mint]
    
    # Fetch from Birdeye
    metadata = await get_token_metadata(mint)
    if metadata and "decimals" in metadata:
        decimals = int(metadata["decimals"])
        _decimals_cache[mint] = decimals
        return decimals
    
    # Default to 9 (SOL-like)
    logger.warning(f"Could not get decimals for {mint}, defaulting to 9")
    return 9


def lamports_to_tokens(amount: float, decimals: int) -> float:
    """
    Convert lamports (smallest unit) to token amount.
    
    Args:
        amount: Amount in lamports/smallest units
        decimals: Token decimals
        
    Returns:
        Amount in token units
    """
    if decimals == 0:
        return amount
    return amount / (10 ** decimals)


def is_likely_lamports(amount: float, decimals: int) -> bool:
    """
    Heuristic to determine if an amount is likely in lamports.
    
    If the amount is very large relative to typical token amounts,
    it's probably in lamports.
    
    Args:
        amount: The amount to check
        decimals: Token decimals
        
    Returns:
        True if likely lamports, False if likely token units
    """
    if amount <= 0:
        return False
    
    # If amount is larger than 10^decimals, it's likely lamports
    # e.g., for SOL (9 decimals), anything > 1 billion is likely lamports
    threshold = 10 ** decimals
    return amount >= threshold


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
    
    # Check cache first
    import time
    now = time.time()
    if mint in _price_cache:
        cached_price, cached_time = _price_cache[mint]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_price
    
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
                        # Cache the price
                        _price_cache[mint] = (price, now)
                        logger.debug(f"Got price for {mint[:8]}...: ${price}")
                        return float(price)
            else:
                logger.warning(f"Birdeye API error: {response.status_code} for {mint}")
                
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching price for {mint}")
    except Exception as e:
        logger.error(f"Error fetching price for {mint}: {e}")
    
    return None


async def get_multiple_token_prices(mints: list[str]) -> Dict[str, Optional[float]]:
    """
    Get USD prices for multiple tokens from Birdeye.
    
    Args:
        mints: List of token mint addresses
        
    Returns:
        Dict mapping mint to USD price (or None if not found)
    """
    if not mints:
        return {}
    
    # Filter out invalid mints and dedupe
    valid_mints = list(set(m for m in mints if m and m != "unknown"))
    
    if not valid_mints:
        return {}
    
    # Check cache first
    import time
    now = time.time()
    results = {}
    mints_to_fetch = []
    
    for mint in valid_mints:
        if mint in _price_cache:
            cached_price, cached_time = _price_cache[mint]
            if now - cached_time < CACHE_TTL_SECONDS:
                results[mint] = cached_price
                continue
        mints_to_fetch.append(mint)
    
    if not mints_to_fetch:
        return results
    
    try:
        # Birdeye multi-price endpoint
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BIRDEYE_API_URL}/defi/multi_price",
                params={"list_address": ",".join(mints_to_fetch)},
                headers={
                    "X-API-KEY": app_config.BIRDEYE_API_KEY,
                    "x-chain": "solana",
                },
                timeout=10.0,
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("success") and data.get("data"):
                    for mint, price_data in data["data"].items():
                        if price_data and "value" in price_data:
                            price = float(price_data["value"])
                            results[mint] = price
                            _price_cache[mint] = (price, now)
            else:
                logger.warning(f"Birdeye multi_price API error: {response.status_code}")
                # Fallback to individual fetches
                for mint in mints_to_fetch:
                    price = await get_token_price(mint)
                    if price is not None:
                        results[mint] = price
                        
    except Exception as e:
        logger.error(f"Error fetching multiple prices: {e}")
        # Fallback to individual fetches
        for mint in mints_to_fetch:
            price = await get_token_price(mint)
            if price is not None:
                results[mint] = price
    
    return results


async def calculate_swap_volume_usd(
    input_token: str,
    input_amount: float,
    output_token: str,
    output_amount: float,
) -> float:
    """
    Calculate the USD volume of a swap.
    Handles both lamports and token unit amounts automatically.
    Uses the input token price preferentially (more reliable for volume).
    
    Args:
        input_token: Input token mint
        input_amount: Input amount (may be in lamports or token units)
        output_token: Output token mint
        output_amount: Output amount (may be in lamports or token units)
        
    Returns:
        USD volume (uses larger of input/output value for accuracy)
    """
    # Get decimals for both tokens
    input_decimals = await get_token_decimals(input_token) if input_token else 9
    output_decimals = await get_token_decimals(output_token) if output_token else 9
    
    # Convert to token units if amounts appear to be in lamports
    input_tokens = input_amount
    output_tokens = output_amount
    
    if input_amount > 0 and is_likely_lamports(input_amount, input_decimals):
        input_tokens = lamports_to_tokens(input_amount, input_decimals)
        logger.debug(f"Converted input {input_amount} lamports to {input_tokens} tokens ({input_decimals} decimals)")
    
    if output_amount > 0 and is_likely_lamports(output_amount, output_decimals):
        output_tokens = lamports_to_tokens(output_amount, output_decimals)
        logger.debug(f"Converted output {output_amount} lamports to {output_tokens} tokens ({output_decimals} decimals)")
    
    # Get prices for both tokens
    prices = await get_multiple_token_prices([input_token, output_token])
    
    input_price = prices.get(input_token)
    output_price = prices.get(output_token)
    
    input_value = 0.0
    output_value = 0.0
    
    if input_price is not None and input_tokens > 0:
        input_value = input_price * input_tokens
        logger.debug(f"Input value: {input_tokens} tokens * ${input_price} = ${input_value}")
    
    if output_price is not None and output_tokens > 0:
        output_value = output_price * output_tokens
        logger.debug(f"Output value: {output_tokens} tokens * ${output_price} = ${output_value}")
    
    # Use the larger value (more accurate, accounts for slippage)
    # If neither available, return 0
    volume = max(input_value, output_value)
    
    if volume == 0 and (input_amount > 0 or output_amount > 0):
        logger.warning(
            f"Could not calculate USD volume for swap: "
            f"input={input_token[:8] if input_token else 'none'}... "
            f"({input_amount} raw -> {input_tokens} tokens), "
            f"output={output_token[:8] if output_token else 'none'}... "
            f"({output_amount} raw -> {output_tokens} tokens)"
        )
    else:
        logger.info(f"Calculated swap volume: ${volume:.2f}")
    
    return volume


def clear_price_cache():
    """Clear the price cache."""
    _price_cache.clear()


def clear_decimals_cache():
    """Clear the decimals cache."""
    _decimals_cache.clear()
