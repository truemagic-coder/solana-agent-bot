"""
AI Trading Agent for automated paper/live trading.
Runs as a background task, executes trades based on AI analysis.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List

from .database import DatabaseService

logger = logging.getLogger(__name__)

# Default strategy prompt for users who haven't set one
DEFAULT_STRATEGY_PROMPT = """Active trading strategy (moderate/aggressive):
- Seek opportunity while managing risk (not overly conservative)
- Favor limit orders at support/resistance; also allow momentum entries for strong runners
- Prefer liquid tokens (>$100k liquidity) and Jupiter-verified assets when available
- Allow multiple concurrent positions when signals are strong
- Target position sizing around 10–20% of portfolio per trade when setup is strong
- Use stop-losses and take-profit targets based on TA levels
- Use trending tokens as candidates, but require TA confirmation
"""

# System rules the AI must follow
SYSTEM_TRADING_RULES = """
CRITICAL TRADING RULES (MUST FOLLOW):
1. Minimum order size is $5 USD (Jupiter limit)
2. Only trade Solana tokens; prefer Jupiter-verified tokens when available
3. Never exceed 25% of portfolio in a single position
4. Always use limit orders, never market orders
5. For paper mode: simulate orders, do not execute real trades
6. Explain your reasoning for every decision
7. If uncertain, default to HOLD - don't force trades
8. Consider existing open orders before placing new ones
9. Check token liquidity before trading - skip if <$50k
10. Default sizing guidance: target 10–20% of portfolio for strong setups, 5–10% for moderate setups
11. Limit entry guardrail: do NOT place a buy limit more than 25% below current price. If support is farther, choose HOLD or use the nearest support within 25%.
12. Momentum entries are allowed: for strong uptrends, you may place smaller laddered limit buys within 2–8% below current price (or at near-term supports) to catch runners.

RESPONSE FORMAT (JSON):
{
    "decisions": [
        {
            "action": "buy" | "sell" | "hold",
            "token_symbol": "...",
            "token_address": "...",
            "amount_usd": 10.0,
            "price_target_usd": 0.00002,
            "order_type": "limit",
            "reasoning": "RSI at 28 indicates oversold, EMA20 provides support at this level..."
        }
    ],
    "portfolio_summary": "Brief overview of current state and strategy alignment",
    "market_outlook": "Brief market sentiment from gems/trending analysis"
}
"""


class TradingAgent:
    def __init__(
        self,
        solana_agent,
        db_service: DatabaseService,
        telegram_bot=None,
        interval_seconds: int = 900,  # 15 minutes default
    ):
        self.solana_agent = solana_agent
        self.db = db_service
        self.telegram_bot = telegram_bot
        self.interval_seconds = interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def set_telegram_bot(self, telegram_bot):
        """Set telegram bot reference after initialization."""
        self.telegram_bot = telegram_bot

    async def start(self):
        """Start the trading agent background loop."""
        if self._running:
            logger.warning("Trading agent already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Trading agent started (interval: {self.interval_seconds}s)")

    async def stop(self):
        """Stop the trading agent."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Trading agent stopped")

    async def _run_loop(self):
        """Main trading loop."""
        while self._running:
            try:
                await self._run_cycle()
            except Exception as e:
                logger.error(f"Trading cycle error: {e}", exc_info=True)
            
            await self._sleep_until_next_interval()

    async def _sleep_until_next_interval(self):
        """Sleep until the next 15-minute wall-clock boundary."""
        now = datetime.utcnow()
        # Next quarter-hour boundary (00, 15, 30, 45)
        minutes = (now.minute // 15) * 15
        next_minute = minutes + 15
        if next_minute >= 60:
            next_time = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_time = now.replace(minute=next_minute, second=0, microsecond=0)

        sleep_seconds = max(0, (next_time - now).total_seconds())
        await asyncio.sleep(sleep_seconds)

    async def _run_cycle(self):
        """Run one trading cycle for all enabled users."""
        logger.info("Starting trading cycle...")
        
        # Get all users with trading enabled
        users = await self.db.get_trading_enabled_users()
        logger.info(f"Found {len(users)} users with trading enabled")
        
        for user in users:
            try:
                await self._process_user(user)
            except Exception as e:
                logger.error(f"Error processing user {user.get('tg_user_id')}: {e}", exc_info=True)

        # Check for paper order fills
        await self._check_paper_fills()
        
        logger.info("Trading cycle complete")

    async def _process_user(self, user: dict):
        """Process trading decisions for a single user."""
        tg_user_id = user.get("tg_user_id")
        trading_mode = user.get("trading_mode", "paper")
        strategy_prompt = user.get("trading_strategy_prompt") or DEFAULT_STRATEGY_PROMPT
        watchlist = user.get("trading_watchlist", [])
        
        logger.info(f"Processing user {tg_user_id} (mode: {trading_mode})")
        
        # Build user context
        user_id = f"telegram:{tg_user_id}"
        wallet_address = user.get("wallet_address")
        if not wallet_address:
            logger.warning(f"User {tg_user_id} has no wallet address, skipping")
            return

        # Gather context for AI
        context = await self._gather_context(user, wallet_address, watchlist)
        
        # Build the AI prompt
        prompt = self._build_trading_prompt(strategy_prompt, context, trading_mode)
        prompt = f"[TRADING_MODE] [RESPOND_JSON_ONLY] {prompt}"
        
        # Get AI decision
        response = ""
        try:
            async for chunk in self.solana_agent.process(user_id, prompt):
                response += chunk
        except Exception as e:
            logger.error(f"AI processing error for user {tg_user_id}: {e}")
            return

        # Parse AI response
        decisions = self._parse_ai_response(response)

        # Ensure summaries exist for bot thoughts
        if isinstance(decisions, dict):
            if not decisions.get("portfolio_summary"):
                decisions["portfolio_summary"] = self._build_portfolio_summary(context)
            if not decisions.get("market_outlook"):
                decisions["market_outlook"] = self._build_market_outlook(context)

        # Log AI thinking for this cycle (even if no actions)
        await self.db.log_bot_thoughts(
            tg_user_id=tg_user_id,
            mode=trading_mode,
            strategy_prompt=strategy_prompt,
            prompt=prompt,
            raw_response=response,
            parsed_response=decisions or {},
            context_snapshot={
                "portfolio_value_usd": context.get("portfolio_value_usd"),
                "open_orders": context.get("open_orders"),
                "ta_results": context.get("ta_results"),
                "gems": context.get("gems"),
                "timestamp": context.get("timestamp"),
            },
        )

        if not decisions:
            logger.info(f"No actionable decisions for user {tg_user_id}")
            return

        # Execute decisions
        for decision in decisions.get("decisions", []):
            await self._execute_decision(user, decision, context, trading_mode, decisions)

    async def _gather_context(self, user: dict, wallet_address: str, watchlist: List[str]) -> dict:
        """Gather all context needed for AI trading decision."""
        tg_user_id = user.get("tg_user_id")
        user_id = f"telegram:{tg_user_id}"
        trading_mode = user.get("trading_mode", "paper")
        
        context = {
            "portfolio": [],
            "paper_portfolio": None,
            "open_orders": [],
            "ta_results": {},
            "gems": [],
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        # Get portfolio (paper or real based on mode)
        if trading_mode == "paper":
            paper_portfolio = user.get("paper_portfolio")
            if paper_portfolio:
                if not paper_portfolio.get("positions"):
                    paper_portfolio = await self.db.ensure_paper_portfolio_usdc(tg_user_id)
                context["paper_portfolio"] = paper_portfolio
                context["portfolio_value_usd"] = await self._calculate_paper_value(paper_portfolio)
            else:
                # Initialize paper portfolio if not exists
                await self.db.initialize_paper_portfolio(tg_user_id)
                context["paper_portfolio"] = {
                    "balance_usd": 1000.0,
                    "positions": [
                        {
                            "token_symbol": "USDC",
                            "token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                            "amount": 1000.0,
                            "entry_price_usd": 1.0,
                            "current_value_usd": 1000.0,
                        }
                    ],
                    "initial_value_usd": 1000.0,
                }
                context["portfolio_value_usd"] = 1000.0
        else:
            # Get real portfolio via agent
            try:
                portfolio_response = ""
                async for chunk in self.solana_agent.process(
                    user_id,
                    f"[RESPOND_JSON_ONLY] Get wallet holdings for {wallet_address}. Return JSON: {{\"holdings\": [{{\"token\": \"...\", \"amount\": ..., \"value_usd\": ...}}], \"total_value_usd\": ...}}"
                ):
                    portfolio_response += chunk
                context["portfolio"] = self._parse_json_response(portfolio_response)
            except Exception as e:
                logger.error(f"Failed to get portfolio: {e}")

        async def _collect_response(prompt: str) -> str:
            data = ""
            async for chunk in self.solana_agent.process(user_id, prompt):
                data += chunk
            return data

        # Run open orders + gems in parallel
        try:
            if trading_mode == "paper":
                pending = await self.db.get_user_paper_orders(tg_user_id, status="pending")
                context["open_orders"] = {
                    "orders": [
                        {
                            "order_id": o.get("_id"),
                            "token": o.get("token_symbol"),
                            "side": o.get("action"),
                            "amount_usd": o.get("amount_usd"),
                            "target_price": o.get("price_target_usd"),
                        }
                        for o in pending
                    ]
                }
                # Also compute reserved cash for pending buys
                reserved = sum([o.get("amount_usd", 0) for o in pending if (o.get("action") or "").lower() == "buy"])
                context["reserved_cash_usd"] = reserved
            else:
                orders_prompt = f"[RESPOND_JSON_ONLY] List all open limit orders for wallet_id {user.get('wallet_id')} and wallet_public_key {wallet_address}. Return JSON: {{\"orders\": [{{\"order_id\": \"...\", \"token\": \"...\", \"side\": \"buy/sell\", \"amount_usd\": ..., \"target_price\": ...}}]}}"
                orders_task = asyncio.create_task(_collect_response(orders_prompt))
                orders_response = await orders_task
                context["open_orders"] = self._parse_json_response(orders_response)

            gems_prompt = "[RESPOND_JSON_ONLY] Run /gems analysis. Return JSON with top trending tokens: {\"gems\": [{\"token\": \"...\", \"address\": \"...\", \"reason\": \"...\", \"risk_level\": \"low/medium/high\"}]}"
            gems_task = asyncio.create_task(_collect_response(gems_prompt))
            gems_response = await gems_task
            context["gems"] = self._parse_json_response(gems_response)
        except Exception as e:
            logger.error(f"Failed to get open orders or gems: {e}")

        # Log how often trending tokens change
        try:
            current_gems = context.get("gems", {}).get("gems", []) or []
            current_tokens = [g.get("token") for g in current_gems if g.get("token")]
            previous_tokens = user.get("last_gems", []) or []
            last_gems_at = user.get("last_gems_at")

            changed = set(current_tokens) != set(previous_tokens)
            minutes_since_last = 0.0
            if last_gems_at and hasattr(last_gems_at, "timestamp"):
                minutes_since_last = max(0.0, (datetime.utcnow() - last_gems_at).total_seconds() / 60.0)

            await self.db.log_trend_change(
                tg_user_id=tg_user_id,
                previous_tokens=previous_tokens,
                current_tokens=current_tokens,
                changed=changed,
                minutes_since_last=minutes_since_last,
            )

            # Store latest gems on user
            await self.db.users.update_one(
                {"tg_user_id": tg_user_id},
                {"$set": {"last_gems": current_tokens, "last_gems_at": datetime.utcnow()}}
            )
        except Exception as e:
            logger.error(f"Failed to log trend changes: {e}")

        # Get TA for portfolio tokens + watchlist
        tokens_to_analyze = set(watchlist)
        
        if trading_mode == "paper" and context.get("paper_portfolio"):
            for pos in context["paper_portfolio"].get("positions", []):
                tokens_to_analyze.add(pos.get("token_symbol", ""))
        elif context.get("portfolio"):
            holdings = context["portfolio"].get("holdings", [])
            for h in holdings:
                tokens_to_analyze.add(h.get("token", ""))
        
        # Add top gems to analysis
        gems_data = context.get("gems", {})
        for gem in gems_data.get("gems", [])[:5]:
            tokens_to_analyze.add(gem.get("token", ""))

        tokens_to_analyze.discard("")  # Remove empty strings
        
        async def _run_ta(token: str):
            try:
                ta_prompt = (
                    f"[RESPOND_JSON_ONLY] Run technical analysis on {token}. "
                    "Return the full JSON output from the technical_analysis tool (do NOT summarize)."
                )
                ta_response = await _collect_response(ta_prompt)
                ta_data = self._parse_json_response(ta_response)
                if ta_data:
                    context["ta_results"][token] = ta_data
            except Exception as e:
                logger.error(f"Failed to get TA for {token}: {e}")

        if tokens_to_analyze:
            await asyncio.gather(*[asyncio.create_task(_run_ta(token)) for token in tokens_to_analyze])

        return context

    async def _calculate_paper_value(self, paper_portfolio: dict) -> float:
        """Calculate current value of paper portfolio."""
        total = paper_portfolio.get("balance_usd", 0)

        # Use USDC position as cash if present
        for pos in paper_portfolio.get("positions", []):
            if (pos.get("token_symbol") or "").upper() == "USDC":
                total = pos.get("amount", total)
                break
        
        for pos in paper_portfolio.get("positions", []):
            if (pos.get("token_symbol") or "").upper() == "USDC":
                continue
            # In a real implementation, fetch current price
            # For now, use entry price as estimate
            total += pos.get("current_value_usd", pos.get("amount", 0) * pos.get("entry_price_usd", 0))
        
        return total

    def _build_portfolio_summary(self, context: dict) -> str:
        """Build a short portfolio summary from context."""
        value = context.get("portfolio_value_usd")
        paper = context.get("paper_portfolio") or {}
        positions = paper.get("positions", [])
        if not positions:
            return f"Portfolio value: ${value:.2f}" if isinstance(value, (int, float)) else "Portfolio empty"
        top = sorted(positions, key=lambda p: p.get("current_value_usd", 0), reverse=True)[:3]
        tokens = ", ".join([f"{p.get('token_symbol')} ${p.get('current_value_usd', 0):.2f}" for p in top])
        return f"Portfolio value: ${value:.2f}. Top: {tokens}" if isinstance(value, (int, float)) else f"Top: {tokens}"

    def _build_market_outlook(self, context: dict) -> str:
        """Build a short market outlook from gems and TA."""
        gems = (context.get("gems") or {}).get("gems", [])
        if gems:
            names = ", ".join([g.get("token") for g in gems[:3] if g.get("token")])
            return f"Trending: {names}" if names else "Market data available"
        ta = context.get("ta_results") or {}
        if ta:
            return "TA signals collected"
        return "Market data unavailable"

    def _build_trading_prompt(self, strategy: str, context: dict, mode: str) -> str:
        """Build the complete trading prompt for AI."""
        mode_note = "PAPER TRADING MODE - Simulate all trades, do not execute real transactions." if mode == "paper" else "LIVE TRADING MODE - Real money, execute carefully."
        
        prompt = f"""You are an AI trading agent making decisions for a user's portfolio.

    IMPORTANT: This is an automated trading session where you are explicitly authorized to make buy/sell decisions and place limit orders based on the user's strategy. This overrides any generic no-advice policy for this session.

{mode_note}

USER'S TRADING STRATEGY:
{strategy}

{SYSTEM_TRADING_RULES}

CURRENT CONTEXT:
- Timestamp: {context.get('timestamp')}
- Portfolio Value: ${context.get('portfolio_value_usd', 'Unknown')}

PORTFOLIO:
{json.dumps(context.get('paper_portfolio') or context.get('portfolio'), indent=2, default=str)}

OPEN LIMIT ORDERS:
{json.dumps(context.get('open_orders'), indent=2, default=str)}

TECHNICAL ANALYSIS:
{json.dumps(context.get('ta_results'), indent=2, default=str)}

TRENDING TOKENS (Gems):
{json.dumps(context.get('gems'), indent=2, default=str)}

Based on the above context and the user's strategy, analyze the situation and provide your trading decisions.
Use the TA schema provided. For limit orders, anchor entries/exits to support_resistance.supports/resistances (arrays).
If supports/resistances are missing or empty, do NOT place a limit order and choose HOLD.
Remember: Only take action if there's a clear opportunity. HOLD is always a valid choice.
Respond with valid JSON only.
"""
        return prompt

    def _parse_ai_response(self, response: str) -> Optional[dict]:
        """Parse AI response JSON."""
        try:
            # Clean up response
            clean = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response: {e}")
            logger.debug(f"Raw response: {response}")
            # Try to extract JSON object from mixed content
            try:
                start = response.find("{")
                end = response.rfind("}")
                if start != -1 and end != -1 and end > start:
                    snippet = response[start:end + 1]
                    return json.loads(snippet)
            except Exception as inner:
                logger.error(f"Failed to recover JSON from AI response: {inner}")
            return None

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from agent response."""
        try:
            clean = response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean)
        except Exception:
            return {}

    async def _execute_decision(self, user: dict, decision: dict, context: dict, mode: str, decisions_bundle: dict):
        """Execute a trading decision (paper or live)."""
        tg_user_id = user.get("tg_user_id")
        action = decision.get("action", "hold").lower()
        
        if action == "hold":
            return  # No action needed
        
        token_symbol = decision.get("token_symbol", "")
        token_address = decision.get("token_address", "")
        amount_usd = decision.get("amount_usd", 0)
        price_target = decision.get("price_target_usd", 0)
        reasoning = decision.get("reasoning", "")

        # Deduplicate within the same cycle
        placed = context.setdefault("placed_orders", set())
        try:
            key = (action, token_symbol.upper(), round(float(price_target), 10))
            if key in placed:
                logger.info(f"Skipping duplicate decision in cycle for {token_symbol} {action} at {price_target}")
                return
        except Exception:
            key = None

        # Skip if a matching open order already exists
        open_orders = context.get("open_orders", {}) or {}
        existing_orders = open_orders.get("orders", []) if isinstance(open_orders, dict) else []
        for order in existing_orders:
            try:
                side = (order.get("side") or "").lower()
                token = (order.get("token") or order.get("token_symbol") or "").upper()
                target = float(order.get("target_price") or order.get("price_target_usd") or 0)
                if side == action and token_symbol and token == token_symbol.upper() and abs(target - float(price_target)) < 1e-10:
                    logger.info(f"Skipping duplicate order for {token_symbol} {action} at {price_target}")
                    return
            except Exception:
                continue

        # Prevent overspending in paper mode by reserving cash for pending buys
        if mode == "paper" and action == "buy":
            paper_portfolio = context.get("paper_portfolio") or {}
            balance = float(paper_portfolio.get("balance_usd", 0) or 0)
            for pos in paper_portfolio.get("positions", []) or []:
                if (pos.get("token_symbol") or "").upper() == "USDC":
                    balance = float(pos.get("amount", balance) or balance)
                    break
            reserved = float(context.get("reserved_cash_usd", 0) or 0)
            available = balance - reserved
            if amount_usd > available:
                logger.info(f"Skipping buy: insufficient available cash (available=${available:.2f}, requested=${amount_usd:.2f})")
                return

        if key is not None:
            placed.add(key)
        
        # Validate minimum order size
        if amount_usd < 5:
            logger.info(f"Skipping order < $5: {amount_usd}")
            return

        # Log the action
        action_doc = {
            "tg_user_id": tg_user_id,
            "mode": mode,
            "action_type": action,
            "token_symbol": token_symbol,
            "token_address": token_address,
            "amount_usd": amount_usd,
            "price_target_usd": price_target,
            "reasoning": reasoning,
            "ai_thoughts": {
                "portfolio_summary": decisions_bundle.get("portfolio_summary"),
                "market_outlook": decisions_bundle.get("market_outlook"),
                "decision_reasoning": reasoning,
            },
            "context_snapshot": {
                "portfolio_value_usd": context.get("portfolio_value_usd"),
                "ta_summary": context.get("ta_results", {}).get(token_symbol, {}),
            },
            "execution": {},
            "timestamp": datetime.utcnow(),
        }

        if mode == "paper":
            # Paper trading - create paper order
            paper_order = await self.db.create_paper_order(
                tg_user_id=tg_user_id,
                action=action,
                token_symbol=token_symbol,
                token_address=token_address,
                amount_usd=amount_usd,
                price_target_usd=price_target,
            )
            action_doc["execution"] = {
                "paper_order_id": paper_order.get("_id"),
                "status": "pending",
            }

            # Update reserved cash and placed orders for this cycle
            if action == "buy":
                context["reserved_cash_usd"] = float(context.get("reserved_cash_usd", 0) or 0) + float(amount_usd)
            # already marked in placed_orders
            
            thoughts_line = ""
            if decisions_bundle.get("portfolio_summary") or decisions_bundle.get("market_outlook"):
                thoughts_line = (
                    f"\n🧠 Thoughts: {decisions_bundle.get('portfolio_summary', '')} "
                    f"| {decisions_bundle.get('market_outlook', '')}"
                )

            # Notify user
            await self._notify_user(
                tg_user_id,
                f"🤖 [PAPER] Order placed:\n"
                f"{'📈 BUY' if action == 'buy' else '📉 SELL'} ${amount_usd:.2f} of {token_symbol}\n"
                f"Target price: ${price_target:.8f}\n"
                f"Reasoning: {reasoning[:500]}..."
                f"{thoughts_line}"
            )
        else:
            # Live trading - execute via solana_agent
            user_id = f"telegram:{tg_user_id}"
            wallet_id = user.get("wallet_id")
            
            if action == "buy":
                order_prompt = f"Set limit order: buy ${amount_usd} of {token_symbol} at ${price_target} using wallet_id {wallet_id}"
            else:
                order_prompt = f"Set limit order: sell ${amount_usd} of {token_symbol} at ${price_target} using wallet_id {wallet_id}"
            
            try:
                result = ""
                async for chunk in self.solana_agent.process(user_id, order_prompt):
                    result += chunk
                
                action_doc["execution"] = {
                    "result": result,
                    "status": "submitted",
                }

                thoughts_line = ""
                if decisions_bundle.get("portfolio_summary") or decisions_bundle.get("market_outlook"):
                    thoughts_line = (
                        f"\n🧠 Thoughts: {decisions_bundle.get('portfolio_summary', '')} "
                        f"| {decisions_bundle.get('market_outlook', '')}"
                    )
                
                # Notify user
                await self._notify_user(
                    tg_user_id,
                    f"🤖 [LIVE] Order submitted:\n"
                    f"{'📈 BUY' if action == 'buy' else '📉 SELL'} ${amount_usd:.2f} of {token_symbol}\n"
                    f"Target price: ${price_target:.8f}\n"
                    f"Reasoning: {reasoning[:500]}...\n\n"
                    f"{thoughts_line}\n\n"
                    f"Result: {result[:300]}"
                )
            except Exception as e:
                action_doc["execution"] = {
                    "error": str(e),
                    "status": "failed",
                }
                logger.error(f"Failed to execute live order: {e}")

        # Save action to database
        await self.db.log_bot_action(action_doc)

    async def _check_paper_fills(self):
        """Check if any paper orders should be filled based on current prices."""
        pending_orders = await self.db.get_pending_paper_orders()
        
        for order in pending_orders:
            tg_user_id = order.get("tg_user_id")
            token_symbol = order.get("token_symbol")
            token_address = order.get("token_address")
            action = order.get("action")
            price_target = order.get("price_target_usd", 0)
            amount_usd = order.get("amount_usd", 0)
            
            # Get current price
            user_id = f"telegram:{tg_user_id}"
            try:
                price_response = ""
                async for chunk in self.solana_agent.process(
                    user_id,
                    f"[RESPOND_JSON_ONLY] Get current price for {token_address or token_symbol}. Return: {{\"price_usd\": ...}}"
                ):
                    price_response += chunk
                
                price_data = self._parse_json_response(price_response)
                current_price = price_data.get("price_usd", 0)
                
                if not current_price:
                    continue

                # Check if order should fill
                should_fill = False
                if action == "buy" and current_price <= price_target:
                    should_fill = True
                elif action == "sell" and current_price >= price_target:
                    should_fill = True
                
                if should_fill:
                    # Fill the paper order
                    await self.db.fill_paper_order(
                        order_id=order.get("_id"),
                        fill_price_usd=current_price,
                    )
                    
                    # Update paper portfolio
                    await self.db.update_paper_portfolio_on_fill(
                        tg_user_id=tg_user_id,
                        action=action,
                        token_symbol=token_symbol,
                        token_address=token_address,
                        amount_usd=amount_usd,
                        fill_price_usd=current_price,
                    )
                    
                    # Notify user
                    await self._notify_user(
                        tg_user_id,
                        f"🤖 [PAPER] Order FILLED! ✅\n"
                        f"{'📈 BOUGHT' if action == 'buy' else '📉 SOLD'} ${amount_usd:.2f} of {token_symbol}\n"
                        f"Fill price: ${current_price:.8f}\n"
                        f"Target was: ${price_target:.8f}"
                    )
            except Exception as e:
                logger.error(f"Error checking paper fill for order {order.get('_id')}: {e}")

    async def _notify_user(self, tg_user_id: int, message: str):
        """Send notification to user via Telegram."""
        if not self.telegram_bot:
            logger.warning(f"No telegram bot, can't notify user {tg_user_id}")
            return
        
        try:
            await self.telegram_bot.client.send_message(tg_user_id, message)
        except Exception as e:
            logger.error(f"Failed to notify user {tg_user_id}: {e}")


async def run_trading_agent(solana_agent, db_service: DatabaseService, telegram_bot=None):
    """Create and run the trading agent."""
    agent = TradingAgent(solana_agent, db_service, telegram_bot)
    await agent.start()
    return agent
