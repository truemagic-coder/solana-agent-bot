"""
RQ tasks for background job processing.

This module contains synchronous wrapper functions for async operations,
designed to be executed by RQ workers.
"""

import asyncio
import logging
from datetime import datetime

from redis import Redis
from rq import Queue

from .config import config

logger = logging.getLogger(__name__)


def get_redis_connection() -> Redis:
    """Get Redis connection from config."""
    return Redis.from_url(config.REDIS_URL)


def get_queue(name: str = "default") -> Queue:
    """Get an RQ queue."""
    return Queue(name, connection=get_redis_connection())


# =============================================================================
# Fee Claiming Tasks
# =============================================================================


def claim_jupiter_fees_task() -> dict:
    """
    RQ task to claim all Jupiter referral fees.
    
    This runs the full fee claiming process:
    1. Claims from Ultra referral account
    2. Claims from Trigger/Swap referral account
    3. Sweeps all tokens to the agent wallet
    
    Returns:
        dict with results of the claim operation
    """
    from .fee_claim_service import FeeClaimService
    
    logger.info("Starting Jupiter fee claim task")
    
    async def _run():
        async with FeeClaimService() as service:
            results = {
                "ultra": {"claimed": [], "errors": []},
                "trigger": {"claimed": [], "errors": []},
                "sweep": {"swept": [], "errors": []},
            }
            
            # Claim Ultra fees
            if config.JUPITER_REFERRAL_ULTRA_CODE:
                logger.info("Claiming Ultra referral fees...")
                ultra_results = await service.claim_for_referral(
                    config.JUPITER_REFERRAL_ULTRA_CODE,
                    project_type="ultra"
                )
                results["ultra"] = ultra_results
                
            # Claim Trigger/Swap fees
            if config.JUPITER_REFERRAL_TRIGGER_CODE:
                logger.info("Claiming Trigger/Swap referral fees...")
                trigger_results = await service.claim_for_referral(
                    config.JUPITER_REFERRAL_TRIGGER_CODE,
                    project_type="trigger"
                )
                results["trigger"] = trigger_results
            
            # Sweep all to agent wallet
            logger.info("Sweeping tokens to agent wallet...")
            sweep_results = await service.sweep_all_to_agent()
            results["sweep"] = sweep_results
            
            return results
    
    try:
        results = asyncio.run(_run())
        logger.info(f"Fee claim task completed: {results}")
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "results": results,
        }
    except Exception as e:
        logger.exception(f"Fee claim task failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


def run_daily_payout_task() -> dict:
    """
    RQ task to run the daily payout process.
    
    This runs the full payout process:
    1. Claims all Jupiter fees
    2. Calculates referrer payouts
    3. Sends SOL to referrers
    4. Records payouts in the database
    
    Returns:
        dict with results of the payout operation
    """
    from .fee_claim_service import FeeClaimService
    
    logger.info("Starting daily payout task")
    
    async def _run():
        async with FeeClaimService() as service:
            return await service.run_daily_payout()
    
    try:
        results = asyncio.run(_run())
        logger.info(f"Daily payout task completed: {results}")
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "results": results,
        }
    except Exception as e:
        logger.exception(f"Daily payout task failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


def check_referral_balances_task() -> dict:
    """
    RQ task to check balances in referral token accounts.
    
    Returns:
        dict with token account balances for each referral account
    """
    from .fee_claim_service import FeeClaimService
    
    logger.info("Checking referral account balances")
    
    async def _run():
        async with FeeClaimService() as service:
            results = {"ultra": [], "trigger": []}
            
            if config.JUPITER_REFERRAL_ULTRA_CODE:
                accounts = await service.get_referral_token_accounts(
                    config.JUPITER_REFERRAL_ULTRA_CODE,
                    project_type="ultra"
                )
                results["ultra"] = [
                    {
                        "mint": acc["mint"],
                        "balance": acc["balance"],
                        "token_program": acc["token_program"],
                    }
                    for acc in accounts
                ]
                
            if config.JUPITER_REFERRAL_TRIGGER_CODE:
                accounts = await service.get_referral_token_accounts(
                    config.JUPITER_REFERRAL_TRIGGER_CODE,
                    project_type="trigger"
                )
                results["trigger"] = [
                    {
                        "mint": acc["mint"],
                        "balance": acc["balance"],
                        "token_program": acc["token_program"],
                    }
                    for acc in accounts
                ]
            
            return results
    
    try:
        results = asyncio.run(_run())
        logger.info(f"Balance check completed: {results}")
        return {
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
            "balances": results,
        }
    except Exception as e:
        logger.exception(f"Balance check failed: {e}")
        return {
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e),
        }


# =============================================================================
# Task Scheduling Helpers
# =============================================================================


def enqueue_claim_fees():
    """Enqueue a fee claim job to run now."""
    queue = get_queue("high")
    return queue.enqueue(claim_jupiter_fees_task, job_timeout="30m")


def enqueue_daily_payout():
    """Enqueue a daily payout job to run now."""
    queue = get_queue("high")
    return queue.enqueue(run_daily_payout_task, job_timeout="1h")


def enqueue_balance_check():
    """Enqueue a balance check job to run now."""
    queue = get_queue("default")
    return queue.enqueue(check_referral_balances_task, job_timeout="5m")
