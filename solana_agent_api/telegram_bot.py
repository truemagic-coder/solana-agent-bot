"""
Telegram bot for Solana Agent.
Private chat only - uses Telegram user ID directly with Privy server-side wallet creation.
No Mini App required.
"""
import base64
import json
import logging
import re
from decimal import Decimal, ROUND_DOWN
from io import BytesIO
from typing import Optional, Tuple

import segno
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.bots import SetBotMenuButtonRequest
from telethon.tl.types import BotMenuButtonDefault

from .config import config as app_config
from .database import DatabaseService
from . import price_service

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, solana_agent, db_service: DatabaseService):
        self.solana_agent = solana_agent
        self.db = db_service
        # Use StringSession (in-memory) to avoid file-based session conflicts during deploys
        self.client = TelegramClient(
            StringSession(),
            app_config.TELEGRAM_API_ID,
            app_config.TELEGRAM_API_HASH
        )
        self.bot_username: Optional[str] = None
        self._menu_context: dict = {}  # Track menu context per user
        
        # Register handlers
        self._register_handlers()
    
    def _register_handlers(self):
        """Register message handlers."""
        
        @self.client.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
        async def handle_private_message(event):
            """Handle all private messages."""
            await self._handle_message(event)
        
        @self.client.on(events.NewMessage(incoming=True, func=lambda e: not e.is_private))
        async def handle_group_message(event):
            """Ignore group messages completely."""
            return
    
    def _get_user_id(self, tg_user_id: int) -> str:
        """
        Convert Telegram user ID to the user ID format used by Privy/solana-agent.
        Privy uses 'telegram:<user_id>' format for Telegram-linked users.
        """
        return f"telegram:{tg_user_id}"

    def _format_decimal(self, value: Decimal, decimals: int = 9) -> str:
        quant = Decimal(10) ** -decimals
        rounded = value.quantize(quant, rounding=ROUND_DOWN)
        formatted = format(rounded, 'f')
        return formatted.rstrip('0').rstrip('.') if '.' in formatted else formatted

    async def _privacy_cash_fee_details(self, amount: float, token_symbol: str, usd_value: float = 0.0) -> dict:
        """
        Return fee and net amount details for Privacy Cash transfers.
        
        Privacy Cash fee structure:
        - 0.35% of transfer amount (in the transfer token)
        - 0.006 SOL flat fee (converted to USDC for USDC transfers)
        """
        try:
            amount_decimal = Decimal(str(amount))
        except Exception:
            amount_decimal = Decimal("0")

        fee_rate = Decimal("0.0035")  # 0.35%
        fee_token = amount_decimal * fee_rate
        fee_sol_amount = Decimal("0.006")  # 0.006 SOL flat fee

        token_symbol = (token_symbol or "").upper()

        # For USDC transfers, convert the 0.006 SOL fee to USDC
        fee_sol_in_token = Decimal("0")
        if token_symbol == "SOL":
            fee_sol_in_token = fee_sol_amount
        elif token_symbol == "USDC":
            # Convert 0.006 SOL to USDC using current SOL price
            sol_to_usdc = await price_service.sol_to_usdc(float(fee_sol_amount))
            if sol_to_usdc is not None:
                fee_sol_in_token = Decimal(str(sol_to_usdc))
            else:
                # Fallback: estimate SOL at ~$200 if API fails
                fee_sol_in_token = fee_sol_amount * Decimal("200")
                logger.warning("Could not fetch SOL price, using $200 estimate for fee calculation")

        # Total fee in transfer token
        total_fee = fee_token + fee_sol_in_token
        net_amount = amount_decimal - total_fee

        if net_amount < 0:
            net_amount = Decimal("0")

        net_usd = None
        if usd_value and amount_decimal > 0:
            try:
                net_usd = Decimal(str(usd_value)) * (net_amount / amount_decimal)
            except Exception:
                net_usd = None

        return {
            "token_symbol": token_symbol,
            "fee_percentage": fee_token,
            "fee_sol_in_token": fee_sol_in_token,
            "total_fee": total_fee,
            "net_amount": net_amount,
            "net_usd": net_usd,
        }

    async def _privacy_cash_fee_lines(self, amount: float, token_symbol: str, usd_value: float = 0.0) -> Tuple[str, str]:
        """Return (fees_line, net_line) strings for Privacy Cash transfers."""
        details = await self._privacy_cash_fee_details(amount, token_symbol, usd_value=usd_value)

        token_symbol = details["token_symbol"]
        total_fee_str = self._format_decimal(details["total_fee"], 6)
        net_amount_str = self._format_decimal(details["net_amount"], 6)

        if token_symbol:
            fees_line = f"Fees: {total_fee_str} {token_symbol}"
            net_line = f"Recipient receives: {net_amount_str} {token_symbol}"
        else:
            fees_line = "Fees: ~0.006 SOL"
            net_line = ""

        if details["net_usd"] is not None:
            net_usd_str = self._format_decimal(details["net_usd"], 2)
            net_line = f"{net_line} (~${net_usd_str})" if net_line else ""

        return fees_line, net_line
    
    async def send_payment_notification(
        self,
        user_id: str,
        amount: float,
        token_symbol: str,
        sender_address: str,
        tx_signature: str,
        usd_value: float = 0.0,
    ):
        """Send a payment notification to a user via Telegram."""
        try:
            # Extract Telegram user ID from the user_id format "telegram:<tg_user_id>"
            if user_id.startswith("telegram:"):
                tg_user_id = int(user_id.replace("telegram:", ""))
            else:
                logger.warning(f"Cannot parse user_id: {user_id}")
                return
            
            # Try to get sender username from database
            sender_user = await self.db.get_user_by_wallet_address(sender_address)
            sender_display = f"@{sender_user['tg_username']}" if (sender_user and sender_user.get('tg_username')) else f"<code>{sender_address[:8]}...{sender_address[-4:]}</code>"
            
            # Format amount nicely
            amount_str = f"{amount:.9f}".rstrip('0').rstrip('.')
            usd_str = f" (~${usd_value:.2f})" if usd_value else ""
            
            # Build notification message
            explorer_link = f"https://orbmarkets.io/tx/{tx_signature}"
            message = (
                f"💰 <b>Payment Received!</b>\n\n"
                f"<b>From:</b> {sender_display}\n"
                f"<b>Amount:</b> {amount_str} {token_symbol}{usd_str}\n\n"
                f"<a href='{explorer_link}'>View on Explorer</a>"
            )
            
            # Send message via Telegram
            await self.client.send_message(tg_user_id, message, parse_mode='html')
            logger.info(f"Sent payment notification to {tg_user_id}: {amount_str} {token_symbol} from {sender_address[:8]}...")
            
        except Exception as e:
            logger.error(f"Failed to send payment notification to {user_id}: {e}")

    async def send_private_payment_notification(
        self,
        recipient_tg_user_id: int,
        amount: float,
        token_symbol: str,
        sender_display: str,
        usd_value: float = 0.0,
    ):
        """Send a private payment notification (no public tx)."""
        try:
            amount_decimal = Decimal(str(amount)) if amount else Decimal("0")
            amount_str = self._format_decimal(amount_decimal, 9)
            fees_line, net_line = await self._privacy_cash_fee_lines(amount, token_symbol, usd_value=usd_value)
            amount_line = f"<b>Amount:</b> {amount_str} {token_symbol}\n" if token_symbol else ""
            net_line = f"<b>{net_line}</b>\n" if net_line else ""

            message = (
                f"🔒 <b>Private Payment Received</b>\n\n"
                f"<b>From:</b> {sender_display}\n"
                f"{amount_line}"
                f"{net_line}"
                f"{fees_line}\n"
                f"\nThis transfer is private and has no public explorer link."
            )

            await self.client.send_message(recipient_tg_user_id, message, parse_mode='html')
            logger.info(
                f"Sent private payment notification to {recipient_tg_user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send private payment notification to {recipient_tg_user_id}: {e}")

    async def send_private_payment_sent_notification(
        self,
        payer_tg_user_id: int,
        amount: float,
        token_symbol: str,
        recipient_display: str,
        usd_value: float = 0.0,
    ):
        """Send a confirmation notification to the payer that their private payment was sent."""
        try:
            amount_decimal = Decimal(str(amount)) if amount else Decimal("0")
            amount_str = self._format_decimal(amount_decimal, 9)
            fees_line, net_line = await self._privacy_cash_fee_lines(amount, token_symbol, usd_value=usd_value)
            usd_str = f" (~${usd_value:.2f})" if usd_value else ""

            message = (
                f"✅ <b>Private Payment Sent</b>\n\n"
                f"<b>To:</b> {recipient_display}\n"
                f"<b>Amount:</b> {amount_str} {token_symbol}{usd_str}\n"
                f"{fees_line}\n"
                f"<b>{net_line}</b>\n"
                f"\nThis transfer is private and has no public explorer link."
            )

            await self.client.send_message(payer_tg_user_id, message, parse_mode='html')
            logger.info(
                f"Sent private payment sent notification to payer {payer_tg_user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send private payment sent notification to {payer_tg_user_id}: {e}")

    async def send_payment_sent_notification(
        self,
        payer_tg_user_id: int,
        amount: float,
        token_symbol: str,
        recipient_display: str,
        tx_signature: str,
        usd_value: float = 0.0,
    ):
        """Send a confirmation notification to the payer that their payment was sent (non-private)."""
        try:
            amount_str = f"{amount:.9f}".rstrip('0').rstrip('.')
            usd_str = f" (~${usd_value:.2f})" if usd_value else ""

            explorer_link = f"https://orbmarkets.io/tx/{tx_signature}"
            message = (
                f"✅ <b>Payment Sent</b>\n\n"
                f"<b>To:</b> {recipient_display}\n"
                f"<b>Amount:</b> {amount_str} {token_symbol}{usd_str}\n\n"
                f"<a href='{explorer_link}'>View on Explorer</a>"
            )

            await self.client.send_message(payer_tg_user_id, message, parse_mode='html')
            logger.info(
                f"Sent payment sent notification to payer {payer_tg_user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to send payment sent notification to {payer_tg_user_id}: {e}")
    
    async def _handle_message(self, event):
        """Process incoming private messages."""
        tg_user_id = event.sender_id
        message_text = event.message.message.strip()
        logger.info(f"Received message from {tg_user_id}: {message_text[:50]}...")
        
        # Ensure user exists in DB and capture username
        try:
            sender = await event.get_sender()
            username = getattr(sender, 'username', None)
            logger.info(f"DEBUG: Sender ID: {tg_user_id}, Username: {username}")
            
            # Get Privy ID from TG ID
            privy_id = self._get_user_id(tg_user_id)
            
            # Create/Get user (initially without wallet address if new)
            # This ensures we capture the username immediately
            await self.db.get_or_create_user(
                privy_id=privy_id,
                wallet_address=None, # Will be filled later by agent or if already exists
                tg_user_id=tg_user_id,
                tg_username=username
            )
        except Exception as e:
            logger.error(f"Error ensuring user exists for {tg_user_id}: {e}")
        
        # Check for menu button clicks FIRST (before slash commands or agent processing)
        if await self._handle_menu_button(event, tg_user_id, message_text):
            return

        # Handle slash commands (always override any pending menu state)
        if message_text.startswith('/'):
            self._menu_context.pop(tg_user_id, None)
            await self._handle_command(event, tg_user_id, message_text)
            return

        # Check if user is in a menu input state and handle accordingly
        if tg_user_id in self._menu_context and self._menu_context[tg_user_id].get('awaiting_input'):
            context = self._menu_context.pop(tg_user_id)  # Clear context
            awaiting = context.get('awaiting_input')

            if awaiting == 'price':
                await self._handle_price(event, tg_user_id, message_text)
                return
            elif awaiting == 'swap':
                await self._handle_swap(event, tg_user_id, message_text)
                return
            elif awaiting == 'limit':
                await self._handle_limit(event, tg_user_id, message_text)
                return
            elif awaiting == 'ta':
                await self._handle_ta(event, tg_user_id, message_text)
                return
            elif awaiting == 'rugcheck':
                await self._handle_rugcheck(event, tg_user_id, message_text)
                return
            elif awaiting == 'buzz':
                await self._handle_buzz(event, tg_user_id, message_text)
                return
            elif awaiting == 'lookup':
                await self._handle_lookup(event, tg_user_id, message_text)
                return
            elif awaiting == 'transfer':
                await self._handle_private_transfer(event, tg_user_id, message_text)
                return
            elif awaiting == 'accept':
                await self._handle_private_accept(event, tg_user_id, message_text)
                return
            elif awaiting == 'private_transfer':
                await self._handle_private_transfer(event, tg_user_id, message_text)
                return
            elif awaiting == 'private_accept':
                await self._handle_private_accept(event, tg_user_id, message_text, token_override=context.get('token'))
                return
            elif awaiting == 'private_accept_amount':
                await self._handle_private_accept_amount(event, tg_user_id, message_text)
                return
            elif awaiting == 'private_accept_token':
                await self._handle_private_accept_token(event, tg_user_id, message_text, context)
                return
            elif awaiting == 'private_pay_confirm':
                request_id = context.get('request_id')
                if message_text.lower() in ("pay", "✅ pay", "✅ pay privately") or message_text.startswith("✅ Pay"):
                    request = await self.db.get_payment_request(request_id) if request_id else None
                    if not request:
                        await event.reply("⚠️ Payment request not found or expired.", buttons=Button.clear())
                        await self._show_main_menu(event)
                        return
                    await self._execute_private_payment_request(event, tg_user_id, request)
                    return
                if message_text.lower() in ("cancel", "❌ cancel"):
                    self._menu_context.pop(tg_user_id, None)
                    await event.reply("Private payment cancelled.", buttons=Button.clear())
                    await self._show_main_menu(event)
                    return
                await event.reply("Please confirm by tapping ✅ Pay or reply with 'pay'.")
                self._menu_context[tg_user_id] = context
                return
            elif awaiting == 'pay_confirm':
                self._menu_context.pop(tg_user_id, None)
                await event.reply("⚠️ Non-private payments are disabled. Use private payment requests instead.", buttons=Button.clear())
                await self._show_main_menu(event)
                return
            elif awaiting == 'shield_deposit':
                await self._handle_shield_deposit(event, tg_user_id, message_text)
                return
            elif awaiting == 'shield_withdraw':
                await self._handle_shield_withdraw(event, tg_user_id, message_text)
                return
            elif awaiting == 'shield_balance':
                await self._handle_shield_balance(event, tg_user_id, message_text)
                return

        # Handle privacy cash natural language shortcuts
        lowered = message_text.lower()
        if lowered.startswith('private transfer'):
            args = message_text[len('private transfer'):].strip()
            await self._handle_private_transfer(event, tg_user_id, args)
            return
        if lowered.startswith('transfer '):
            args = message_text[len('transfer'):].strip()
            await self._handle_private_transfer(event, tg_user_id, args)
            return
        if lowered.startswith('private accept'):
            args = message_text[len('private accept'):].strip()
            await self._handle_private_accept(event, tg_user_id, args)
            return
        if lowered.startswith('shield deposit'):
            args = message_text[len('shield deposit'):].strip()
            await self._handle_shield_deposit(event, tg_user_id, args)
            return
        if lowered.startswith('shield withdraw'):
            args = message_text[len('shield withdraw'):].strip()
            await self._handle_shield_withdraw(event, tg_user_id, args)
            return
        if lowered.startswith('shield balance'):
            args = message_text[len('shield balance'):].strip()
            await self._handle_shield_balance(event, tg_user_id, args)
            return
        
        # Process message with Solana Agent
        # Privy will auto-create wallet on first tool use
        await self._process_agent_message(event, tg_user_id, message_text)
    
    async def _handle_menu_button(self, event, tg_user_id: int, message_text: str) -> bool:
        """
        Check if message is a menu button click and handle it.
        Returns True if handled, False if should continue normal processing.
        """
        # Main menu buttons
        if message_text == "💰 Trading":
            await self._show_trading_menu(event)
            return True
        elif message_text == "🔍 Research":
            await self._show_research_menu(event)
            return True
        elif message_text == "👛 Wallet":
            await self._show_wallet_menu(event)
            return True
        elif message_text == "⚙️ More":
            await self._show_more_menu(event)
            return True
        elif message_text == "◀️ Back to Menu":
            await self._show_main_menu(event)
            return True
        
        # Trading menu buttons
        elif message_text == "💵 Price Check":
            await event.reply("📌 Type the token symbol or address:\n\nExample: SOL or BONK")
            self._menu_context[tg_user_id] = {'awaiting_input': 'price'}
            return True
        elif message_text == "🔄 Swap":
            await event.reply("📌 Tell me what you'd like to swap:\n\nExample: Swap 1 SOL for USDC")
            self._menu_context[tg_user_id] = {'awaiting_input': 'swap'}
            return True
        elif message_text == "📊 Limit Order":
            await event.reply("📌 Describe your limit order:\n\nExample: Buy BONK at -5% for 10 USDC")
            self._menu_context[tg_user_id] = {'awaiting_input': 'limit'}
            return True
        elif message_text == "📈 My Orders":
            await self._handle_orders(event, tg_user_id)
            return True
        
        # Research menu buttons
        elif message_text == "💎 Gems":
            await self._handle_gems(event, tg_user_id)
            return True
        elif message_text == "📉 Technical Analysis":
            await event.reply("📌 Which token would you like to analyze?\n\nExample: SOL or BONK")
            self._menu_context[tg_user_id] = {'awaiting_input': 'ta'}
            return True
        elif message_text == "🛡️ Rugcheck":
            await event.reply("📌 Which token would you like to check?\n\nExample: BONK")
            self._menu_context[tg_user_id] = {'awaiting_input': 'rugcheck'}
            return True
        elif message_text == "🐦 Buzz/Sentiment":
            await event.reply("📌 Which token's social sentiment would you like to check?\n\nExample: SOL")
            self._menu_context[tg_user_id] = {'awaiting_input': 'buzz'}
            return True
        elif message_text == "👀 Wallet Lookup":
            await event.reply("📌 Enter the wallet address to look up:\n\nExample: 6qfHeaUu1tUiEyKLRHKCPt5YzGfkkHZ34R1np3Mue81y")
            self._menu_context[tg_user_id] = {'awaiting_input': 'lookup'}
            return True
        
        # Wallet menu buttons
        elif message_text == "💼 Portfolio":
            await self._handle_wallet(event, tg_user_id)
            return True
        elif message_text == "🔒 Transfer":
            await event.reply("📌 Send a private transfer:\n\nExample: transfer 0.1 SOL to @username or to wallet address")
            self._menu_context[tg_user_id] = {'awaiting_input': 'private_transfer'}
            return True
        elif message_text == "📱 Request Payment":
            await event.reply("📌 Enter the amount to request privately:\n\nExample: 10")
            self._menu_context[tg_user_id] = {'awaiting_input': 'private_accept_amount'}
            return True
        elif message_text == "🕵️ Privacy":
            await self._show_privacy_menu(event)
            return True
        elif message_text == "💳 Buy $AGENT":
            await self._handle_buy(event, tg_user_id)
            return True
        elif message_text == "💰 Sell to Fiat":
            await self._handle_sell(event, tg_user_id)
            return True
        
        # More menu buttons
        elif message_text == "🗑️ Clear History":
            await self._handle_purge(event, tg_user_id)
            return True
        elif message_text == "❓ Help":
            await self._show_main_menu(event)
            return True
        elif message_text == "📞 Support":
            await event.reply("📞 Need help?\n\nVisit: https://t.me/my_solana_agent")
            return True
        elif message_text == "🔒 Private Transfer":
            await event.reply("📌 Send a private transfer:\n\nExample: transfer $5 USDC to @walletbubbles")
            self._menu_context[tg_user_id] = {'awaiting_input': 'private_transfer'}
            return True
        elif message_text == "📥 Private Accept":
            await event.reply("📌 Enter the amount to request privately:\n\nExample: 10")
            self._menu_context[tg_user_id] = {'awaiting_input': 'private_accept_amount'}
            return True
        elif message_text in ("🪙 SOL", "🪙 USDC", "SOL", "USDC"):
            context = self._menu_context.pop(tg_user_id, None)
            if context and context.get('awaiting_input') == 'private_accept_token':
                await self._handle_private_accept_token(event, tg_user_id, message_text, context)
                return True
        elif message_text == "🛡️ Shield Deposit":
            await event.reply("📌 Shield (deposit) funds privately:\n\nExample: shield deposit 0.5 SOL")
            self._menu_context[tg_user_id] = {'awaiting_input': 'shield_deposit'}
            return True
        elif message_text == "🛡️ Shield Withdraw":
            await event.reply("📌 Unshield (withdraw) to a wallet:\n\nExample: shield withdraw 0.1 SOL to 6qfHea...")
            self._menu_context[tg_user_id] = {'awaiting_input': 'shield_withdraw'}
            return True
        elif message_text == "📊 Shield Balance":
            await event.reply("📌 Check shielded balance:\n\nExample: shield balance SOL")
            self._menu_context[tg_user_id] = {'awaiting_input': 'shield_balance'}
            return True
        
        # Handle cancel button as fallback (when user clicks it without pending context)
        elif message_text == "❌ Cancel":
            self._menu_context.pop(tg_user_id, None)
            await event.reply("Cancelled.", buttons=Button.clear())
            await self._show_main_menu(event)
            return True
        
        # Not a menu button
        return False
    
    async def _handle_command(self, event, tg_user_id: int, message_text: str):
        """Handle slash commands."""
        parts = message_text.split(maxsplit=1)
        command = parts[0].lower().split('@')[0]  # Handle /cmd@botname
        args = parts[1] if len(parts) > 1 else ""
        
        # Slash commands
        if command == '/start':
            await self._handle_start(event, tg_user_id, args)
        elif command == '/help' or command == '/menu':
            await self._handle_help(event)
        elif command == '❌' and 'cancel' in args.lower():
             await event.reply("Payment cancelled.", buttons=Button.clear())
        elif command == '/wallet':
            await self._handle_wallet(event, tg_user_id)
        elif command == '/orders':
            await self._handle_orders(event, tg_user_id)
        elif command == '/purge':
            await self._handle_purge(event, tg_user_id)
        elif command == '/gems':
            await self._handle_gems(event, tg_user_id)
        elif command == '/rugcheck':
            await self._handle_rugcheck(event, tg_user_id, args)
        elif command == '/ta':
            await self._handle_ta(event, tg_user_id, args)
        elif command == '/lookup':
            await self._handle_lookup(event, tg_user_id, args)
        elif command == '/buzz':
            await self._handle_buzz(event, tg_user_id, args)
        elif command == '/buy':
            await self._handle_buy(event, tg_user_id)
        elif command == '/sell':
            await self._handle_sell(event, tg_user_id)
        elif command == '/price':
            await self._handle_price(event, tg_user_id, args)
        elif command == '/swap':
            await self._handle_swap(event, tg_user_id, args)
        elif command == '/limit':
            await self._handle_limit(event, tg_user_id, args)
        elif command == '/accept':
            await self._handle_private_accept(event, tg_user_id, args)
        elif command == '/transfer':
            await self._handle_private_transfer(event, tg_user_id, args)
        elif command == '/private' or command == '/privacy':
            await self._show_privacy_menu(event)
        elif command == '/private_transfer':
            await self._handle_private_transfer(event, tg_user_id, args)
        elif command == '/private_accept':
            await self._handle_private_accept(event, tg_user_id, args)
        elif command == '/shield_deposit':
            await self._handle_shield_deposit(event, tg_user_id, args)
        elif command == '/shield_withdraw':
            await self._handle_shield_withdraw(event, tg_user_id, args)
        elif command == '/shield_balance':
            await self._handle_shield_balance(event, tg_user_id, args)
        else:
            # Treat unknown commands as regular messages
            await self._process_agent_message(event, tg_user_id, message_text)
    
    async def _handle_start(self, event, tg_user_id: int, args: str):
        """Handle /start command, including deep link payment requests."""
        # Check for private payment deep link: pay_priv_{request_id}
        if args.startswith('pay_priv_'):
            request_id = args.replace('pay_priv_', '')
            request = await self.db.get_payment_request(request_id)
            if not request or not request.get("is_private"):
                await event.reply("⚠️ Private payment request not found or expired.")
                return

            recipient_wallet = request['wallet_address']
            token_symbol = request['token_symbol']
            amount = request['amount']
            usd_value = request.get('amount_usd', 0.0)

            usd_str = f" (~${usd_value:.2f})" if usd_value else ""

            recipient_display = "this user"
            try:
                recipient_user = await self.db.get_user_by_wallet_address(recipient_wallet)
                if recipient_user and recipient_user.get('tg_username'):
                    recipient_display = f"@{recipient_user['tg_username']}"
            except Exception:
                pass

            await event.reply(
                f"🔒 <b>Private Payment Request</b>\n\n"
                f"<b>Amount:</b> {amount} {token_symbol}{usd_str}\n"
                f"<b>To:</b> {recipient_display}\n\n"
                f"Tap to pay privately:",
                parse_mode='html',
                buttons=[
                    [Button.text(f"✅ Pay {amount} {token_symbol} (Private)", resize=True, single_use=True)],
                    [Button.text("❌ Cancel", resize=True, single_use=True)]
                ]
            )
            self._menu_context[tg_user_id] = {
                'awaiting_input': 'private_pay_confirm',
                'request_id': request_id
            }
            return

        # Non-private payment requests are disabled
        if args.startswith('pay_'):
            await event.reply("⚠️ Non-private payments are disabled. Use private payment requests instead.")
            return
        
        # Legacy support or other deep links can go here if needed
        
        # Normal /start - welcome message
        existing_user = await self.db.get_user_by_tg_id(tg_user_id)
        existing_wallet = existing_user.get("wallet_address") if existing_user else None
        if existing_wallet:
            buy_link = f"https://sol-pay.co/buy?walletAddress={existing_wallet}"
            welcome_message = (
                "👋 <b>Welcome back!</b>\n\n"
                "✅ Your Solana wallet is already set up.\n"
                f"👛 <b>Your Wallet:</b> <code>{existing_wallet}</code>\n\n"
                "🔄 <b>Swaps are gasless</b> — you don't need SOL for fees.\n\n"
                "💳 <b>Buy $AGENT with card</b>:\n"
                f"👉 {buy_link}"
            )
            await event.reply(welcome_message, parse_mode='html')
            await self._show_main_menu(event)
            return

        user_id = self._get_user_id(tg_user_id)
        
        response = ""
        try:
            async with self.client.action(event.chat_id, 'typing', delay=4):
                async for chunk in self.solana_agent.process(
                    user_id,
                    "[RESPOND_JSON_ONLY] Return a JSON object with: {\"user_id\": \"<privy_did>\", \"wallet_id\": \"<wallet_id (NOT a did:privy:... value)>\", \"wallet_address\": \"<address>\", \"wallet_public_key\": \"<address>\", \"welcome_message\": \"<welcome message with swaps gasless note, show wallet address, and fiat on-ramp link using https://sol-pay.co/buy?walletAddress=<address>\"}"
                ):
                    response += chunk
        except Exception:
            async for chunk in self.solana_agent.process(
                user_id,
                "[RESPOND_JSON_ONLY] Return a JSON object with: {\"user_id\": \"<privy_did>\", \"wallet_id\": \"<wallet_id (NOT a did:privy:... value)>\", \"wallet_address\": \"<address>\", \"wallet_public_key\": \"<address>\", \"welcome_message\": \"<welcome message with swaps gasless note, show wallet address, and fiat on-ramp link using https://sol-pay.co/buy?walletAddress=<address>\"}"
            ):
                response += chunk
        
        # Parse JSON response
        import json
        clean_json = response.replace('```json', '').replace('```', '').strip()
        
        try:
            data = json.loads(clean_json)
            user_id = data.get('user_id')
            wallet_id = data.get('wallet_id')
            wallet_address = data.get('wallet_address')
            wallet_public_key = data.get('wallet_public_key')
            welcome_message = data.get('welcome_message', response)
            
            # Prefer wallet_public_key if wallet_address is missing
            if not wallet_address and wallet_public_key:
                wallet_address = wallet_public_key

            # Strip HTML tags from wallet address if present
            if wallet_address:
                wallet_address = wallet_address.replace('<code>', '').replace('</code>', '').strip()

            # If wallet_id was incorrectly returned as a Privy DID, move it to user_id
            if wallet_id and wallet_id.startswith("did:privy:"):
                if not user_id:
                    user_id = wallet_id
                wallet_id = None
            
            # Store wallet in database
            if wallet_address:
                try:
                    update_fields = {}
                    user = await self.db.get_user_by_tg_id(tg_user_id)
                    if user:
                        if not user.get("wallet_address"):
                            update_fields["wallet_address"] = wallet_address
                        if wallet_id and not user.get("wallet_id"):
                            update_fields["wallet_id"] = wallet_id
                        if user_id and not user.get("user_id"):
                            update_fields["user_id"] = user_id
                        if update_fields:
                            await self.db.users.update_one(
                                {"tg_user_id": tg_user_id},
                                {"$set": update_fields}
                            )
                    else:
                        await self.db.users.update_one(
                            {"tg_user_id": tg_user_id},
                            {"$set": {"wallet_address": wallet_address, "wallet_id": wallet_id, "user_id": user_id}},
                            upsert=True
                        )
                    logger.info(f"Stored wallet from /start for {tg_user_id}: {wallet_address} (wallet_id={wallet_id}, user_id={user_id})")
                except Exception as e:
                    logger.error(f"Failed to store wallet for {tg_user_id}: {e}")
            
            await event.reply(welcome_message, parse_mode='html')
            
            # Show menu after welcome
            await self._show_main_menu(event)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse /start response for {tg_user_id}: {e}")
            await event.reply(response)
            # Still show menu even if there was an error
            await self._show_main_menu(event)
    
    async def _handle_help(self, event):
        """Handle /help command - show main menu."""
        await self._show_main_menu(event)
    
    async def _show_main_menu(self, event):
        """Show the main menu with category buttons."""
        menu_text = (
            "🤖 <b>Solana Agent Menu</b>\n\n"
            "Select a category or use natural language:"
        )
        
        buttons = [
            [Button.text("💰 Trading", resize=True), Button.text("🔍 Research", resize=True)],
            [Button.text("👛 Wallet", resize=True), Button.text("⚙️ More", resize=True)],
        ]
        
        await event.reply(menu_text, buttons=buttons, parse_mode='html')
    
    async def _show_trading_menu(self, event):
        """Show trading commands menu."""
        menu_text = (
            "💰 <b>Trading Commands</b>\n\n"
            "Choose an action:"
        )
        
        buttons = [
            [Button.text("💵 Price Check", resize=True), Button.text("🔄 Swap", resize=True)],
            [Button.text("📊 Limit Order", resize=True), Button.text("📈 My Orders", resize=True)],
            [Button.text("◀️ Back to Menu", resize=True)]
        ]
        
        await event.reply(menu_text, buttons=buttons, parse_mode='html')
    
    async def _show_research_menu(self, event):
        """Show research commands menu."""
        menu_text = (
            "🔍 <b>Research Commands</b>\n\n"
            "Choose an action:"
        )
        
        buttons = [
            [Button.text("💎 Gems", resize=True), Button.text("📉 Technical Analysis", resize=True)],
            [Button.text("🛡️ Rugcheck", resize=True), Button.text("🐦 Buzz/Sentiment", resize=True)],
            [Button.text("👀 Wallet Lookup", resize=True)],
            [Button.text("◀️ Back to Menu", resize=True)]
        ]
        
        await event.reply(menu_text, buttons=buttons, parse_mode='html')
    
    async def _show_wallet_menu(self, event):
        """Show wallet commands menu."""
        menu_text = (
            "👛 <b>Wallet Commands</b>\n\n"
            "Choose an action:"
        )
        
        buttons = [
            [Button.text("💼 Portfolio", resize=True), Button.text("🔒 Transfer", resize=True)],
            [Button.text("📱 Request Payment", resize=True), Button.text("🕵️ Privacy", resize=True)],
            [Button.text("💳 Buy $AGENT", resize=True), Button.text("💰 Sell to Fiat", resize=True)],
            [Button.text("◀️ Back to Menu", resize=True)]
        ]
        
        await event.reply(menu_text, buttons=buttons, parse_mode='html')

    async def _show_privacy_menu(self, event):
        """Show privacy cash commands menu."""
        menu_text = (
            "🕵️ <b>Privacy Cash</b>\n\n"
            "Private transfers and shielded balances (SOL/USDC)."
        )

        buttons = [
            [Button.text("🔒 Private Transfer", resize=True)],
            [Button.text("📥 Private Accept", resize=True)],
            [Button.text("🛡️ Shield Deposit", resize=True), Button.text("🛡️ Shield Withdraw", resize=True)],
            [Button.text("📊 Shield Balance", resize=True)],
            [Button.text("◀️ Back to Menu", resize=True)]
        ]

        await event.reply(menu_text, buttons=buttons, parse_mode='html')
    
    async def _show_more_menu(self, event):
        """Show more options menu."""
        menu_text = (
            "⚙️ <b>More Options</b>\n\n"
            "Choose an action:"
        )
        
        buttons = [
            [Button.text("🗑️ Clear History", resize=True)],
            [Button.text("❓ Help", resize=True), Button.text("📞 Support", resize=True)],
            [Button.text("◀️ Back to Menu", resize=True)]
        ]
        
        await event.reply(menu_text, buttons=buttons, parse_mode='html')
    
    async def _handle_wallet(self, event, tg_user_id: int):
        """Handle /wallet command - ask agent for full portfolio with PnL."""
        user_id = self._get_user_id(tg_user_id)
        _, wallet_address_from_db = await self._get_wallet_info(tg_user_id)
        if not wallet_address_from_db:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return
        
        response = ""
        try:
            async with self.client.action(event.chat_id, 'typing', delay=4):
                async for chunk in self.solana_agent.process(
                    user_id,
                    f"[RESPOND_JSON_ONLY] Use wallet_address '{wallet_address_from_db}'. Return a JSON object with: {{\"wallet_address\": \"<address>\", \"portfolio_text\": \"<full portfolio response with balances and PnL>\"}}"
                ):
                    response += chunk
        except Exception:
            async for chunk in self.solana_agent.process(
                user_id,
                f"[RESPOND_JSON_ONLY] Use wallet_address '{wallet_address_from_db}'. Return a JSON object with: {{\"wallet_address\": \"<address>\", \"portfolio_text\": \"<full portfolio response with balances and PnL>\"}}"
            ):
                response += chunk
        
        # Parse JSON response
        import json
        clean_json = response.replace('```json', '').replace('```', '').strip()
        
        try:
            data = json.loads(clean_json)
            wallet_address = data.get('wallet_address') or wallet_address_from_db
            portfolio_text = data.get('portfolio_text', response)
            
            # Strip HTML tags from wallet address if present
            if wallet_address:
                wallet_address = wallet_address.replace('<code>', '').replace('</code>', '').strip()
            
            # Store wallet in database
            if wallet_address and wallet_address != wallet_address_from_db:
                try:
                    await self.db.users.update_one(
                        {"tg_user_id": tg_user_id},
                        {"$set": {"wallet_address": wallet_address}},
                        upsert=True
                    )
                    logger.info(f"Stored wallet for {tg_user_id}: {wallet_address}")
                except Exception as e:
                    logger.error(f"Failed to store wallet for {tg_user_id}: {e}")
            
            await self._send_long_message(event, portfolio_text)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse wallet response for {tg_user_id}: {e}")
            await self._send_long_message(event, response)
    
    async def _handle_orders(self, event, tg_user_id: int):
        """Handle /orders command - ask agent to list limit orders."""
        await self._process_agent_message(event, tg_user_id, "[RESPOND IN ENGLISH] What are my active limit orders?")
    
    async def _handle_gems(self, event, tg_user_id: int):
        """Handle /gems command - show top 3 gem tokens."""
        await self._process_agent_message(event, tg_user_id, "[RESPOND IN ENGLISH] Show me the top 3 gem tokens right now. Use Birdeye token_trending. For each show: name, symbol, CA, price, market cap, and chart link (https://birdeye.so/solana/token/{CA}). Keep it brief.")
    
    async def _handle_rugcheck(self, event, tg_user_id: int, args: str):
        """Handle /rugcheck command - check token safety by symbol or address."""
        if not args.strip():
            await event.reply("Usage: /rugcheck <symbol or address>\n\nExample:\n/rugcheck BONK\n/rugcheck DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Do a safety check on this token: {args.strip()}. Call ALL these IN PARALLEL for speed: jupiter_shield, birdeye token_security, and birdeye token_overview. From token_security get: freezeAuthority, mutableMetadata, top10HolderPercent, jupStrictList. Show: Jupiter strict list status, warnings, freeze authority, mutable metadata, liquidity, holders, top 10 holder %. Give a clear safe/caution/high-risk verdict.")

    async def _handle_ta(self, event, tg_user_id: int, args: str):
        """Handle /ta command - technical analysis for a token."""
        if not args.strip():
            await event.reply("Usage: /ta <symbol or address> [timeframe]\n\nTimeframes: 1m, 5m, 15m, 30m, 1h, 2h, 4h, 8h, 1d\nDefault: 4h\n\nExample:\n/ta SOL\n/ta BONK 1h\n/ta DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 1d")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Run technical analysis on: {args.strip()}. Use the technical_analysis tool. If a symbol is given, first search for the token address. Interpret the raw values: RSI>70=overbought, RSI<30=oversold, MACD above signal=bullish, ADX>25=strong trend, price above EMAs=bullish structure. Show key indicators with interpretation. Always include the caution that this is NOT a buy/sell recommendation - NFA/DYOR.")

    async def _handle_lookup(self, event, tg_user_id: int, args: str):
        """Handle /lookup command - lookup holdings of any wallet address."""
        if not args.strip():
            await event.reply("Usage: /lookup <wallet address>\n\nExample:\n/lookup 6qfHeaUu1tUiEyKLRHKCPt5YzGfkkHZ34R1np3Mue81y")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Look up the full holdings and PnL for this wallet: {args.strip()}. Call birdeye wallet_token_list AND wallet_pnl_summary IN PARALLEL. Show ALL tokens with amounts and USD values, plus the PnL summary.")

    async def _handle_buzz(self, event, tg_user_id: int, args: str):
        """Handle /buzz command - get social sentiment from X for a token."""
        if not args.strip():
            await event.reply("Usage: /buzz <symbol or address>\n\nExample:\n/buzz BONK\n/buzz SOL")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Get the social sentiment and buzz on X/Twitter for this token: {args.strip()}. Use search_internet with the X search to find recent posts and sentiment. Summarize the overall mood (bullish/bearish/neutral), key topics being discussed, and notable influencer mentions if any. Note: this may take 30-60 seconds.")

    async def _handle_buy(self, event, tg_user_id: int):
        """Handle /buy command - get the buy link for $AGENT."""
        _, wallet_address = await self._get_wallet_info(tg_user_id)
        if not wallet_address:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return
        buy_link = f"https://sol-pay.co/buy?walletAddress={wallet_address}"
        message = (
            "💳 <b>Buy $AGENT with Card</b>\n\n"
            "Click here to buy $AGENT directly with your card:\n"
            f"👉 {buy_link}\n\n"
            "⚠️ Note:\n"
            "• Only $AGENT is available for purchase\n"
            "• Provider fees apply (shown before confirming)\n"
            "• Availability varies by region/payment method"
        )
        await event.reply(message, parse_mode='html')

    async def _handle_sell(self, event, tg_user_id: int):
        """Handle /sell command - get the sell link for USDC."""
        _, wallet_address = await self._get_wallet_info(tg_user_id)
        if not wallet_address:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return
        sell_link = f"https://sol-pay.co/sell?walletAddress={wallet_address}"
        message = (
            "💵 <b>Sell USDC for Fiat</b>\n\n"
            "Click here to cash out your USDC:\n"
            f"👉 {sell_link}\n\n"
            "⚠️ Important:\n"
            "• Default coin to sell is USDC (most widely supported)\n"
            "• Swap your tokens to USDC first before selling!\n"
            "• Provider fees apply (shown before confirming)\n"
            "• Availability varies by region/payment method"
        )
        await event.reply(message, parse_mode='html')

    async def _handle_price(self, event, tg_user_id: int, args: str):
        """Handle /price command - quick price check."""
        if not args.strip():
            await event.reply("Usage: /price <symbol or address>\n\nExample:\n/price SOL\n/price BONK")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Get the price for: {args.strip()}. Show: token address, price, 24h change %, market cap, and chart link (https://birdeye.so/solana/token/ADDRESS). Keep it brief.")

    async def _handle_swap(self, event, tg_user_id: int, args: str):
        """Handle /swap command - quick swap."""
        if not args.strip():
            await event.reply("Usage: /swap <amount> <from_token> for <to_token>\n\nExamples:\n/swap 1 SOL for USDC\n/swap 100 USDC for BONK\n/swap $50 of SOL for BONK")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Execute this swap: {args.strip()}")

    async def _handle_limit(self, event, tg_user_id: int, args: str):
        """Handle /limit command - quick limit order."""
        if not args.strip():
            await event.reply("Usage: /limit <buy|sell> <token> at <price or %> for <amount>\n\nExamples:\n/limit buy BONK at -5% for 10 USDC\n/limit sell SOL at +10% for 0.5 SOL")
            return
        await self._process_agent_message(event, tg_user_id, f"[RESPOND IN ENGLISH] Set this limit order: {args.strip()}")

    async def _handle_accept(self, event, tg_user_id: int, args: str):
        """Handle /accept command - private payment requests only."""
        await self._handle_private_accept(event, tg_user_id, args)

    async def _handle_transfer(self, event, tg_user_id: int, args: str):
        """Handle /transfer command - private transfers only."""
        await self._handle_private_transfer(event, tg_user_id, args)

    async def _resolve_username_in_text(self, event, input_text: str) -> Tuple[str, Optional[str]]:
        """Resolve @username to wallet address, returning updated text and wallet if found."""
        if '@' not in input_text:
            return input_text, None

        parts = input_text.split()
        username_part = next((p for p in parts if p.startswith('@')), None)

        if not username_part:
            return input_text, None

        target_user = await self.db.get_user_by_username(username_part)

        if not target_user:
            await event.reply(f"❌ User {username_part} not found. They must have started this bot at least once.")
            return "", None

        wallet_address = target_user.get('wallet_address')

        if not wallet_address:
            await event.reply(
                f"❌ User {username_part} found, but their wallet hasn't been initialized yet. "
                "They need to run /wallet at least once to set it up."
            )
            return "", None

        input_text = input_text.replace(username_part, wallet_address)

        return input_text, wallet_address

    def _extract_wallet_address(self, text: str) -> Optional[str]:
        """Extract a likely Solana wallet address from text."""
        match = re.search(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b", text)
        return match.group(0) if match else None

    async def _get_wallet_info(self, tg_user_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Fetch stored wallet_id and wallet_address for a Telegram user."""
        user = await self.db.get_user_by_tg_id(tg_user_id)
        if not user:
            return None, None
        wallet_id = user.get("wallet_id")
        wallet_address = user.get("wallet_address")
        if wallet_id and wallet_id.startswith("did:privy:"):
            wallet_id = None
        return wallet_id, wallet_address

    async def _get_user_context(self, tg_user_id: int) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetch stored user_id (Privy DID), wallet_id, and wallet_address for a Telegram user."""
        user = await self.db.get_user_by_tg_id(tg_user_id)
        if not user:
            return None, None, None
        user_id = user.get("user_id")
        wallet_id = user.get("wallet_id")
        wallet_address = user.get("wallet_address")
        if wallet_id and wallet_id.startswith("did:privy:"):
            if not user_id:
                user_id = wallet_id
            wallet_id = None
        return user_id, wallet_id, wallet_address

    async def _handle_private_transfer(self, event, tg_user_id: int, args: str):
        """Handle /transfer command - private transfer via PrivacyCash."""
        if not args.strip():
            await event.reply(
                "Usage: /transfer <amount> <token> to <wallet or @username>\n\n"
                "Examples:\n"
                "/transfer $5 USDC to @walletbubbles\n"
                "/transfer 0.1 SOL to 6qfHeaUu1tUiEyKLRHKCPt5YzGfkkHZ34R1np3Mue81y"
            )
            return

        wallet_id, _ = await self._get_wallet_info(tg_user_id)
        if not wallet_id:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        input_text = args.strip()
        input_text, recipient_wallet = await self._resolve_username_in_text(event, input_text)
        if not input_text:
            return

        if not recipient_wallet:
            recipient_wallet = self._extract_wallet_address(input_text)

        prompt = (
            "[RESPOND_JSON_ONLY] Execute a PrivacyCash private transfer. "
            f"Use wallet_id '{wallet_id}' for the sender. "
            "Use privy_privacy_cash with action=transfer. "
            f"Instruction: '{input_text}'. "
            f"Recipient wallet address override: '{recipient_wallet or ''}'. "
            "Return ONLY JSON: {"
            "\"status\": \"success\"|\"error\", "
            "\"error\": \"\", "
            "\"recipient\": \"<wallet_address>\", "
            "\"amount\": <float>, "
            "\"token\": \"SOL\"|\"USDC\", "
            "\"usd_value\": <float>}")

        response = ""
        try:
            async with self.client.action(event.chat_id, 'typing', delay=4):
                async for chunk in self.solana_agent.process(self._get_user_id(tg_user_id), prompt):
                    response += chunk
        except Exception:
            async for chunk in self.solana_agent.process(self._get_user_id(tg_user_id), prompt):
                response += chunk

        clean_json = response.replace('```json', '').replace('```', '').strip()
        try:
            data = json.loads(clean_json)
        except Exception:
            logger.error(f"Failed to parse private transfer JSON: {clean_json}")
            await event.reply("❌ Private transfer failed. Please try again.")
            return

        if data.get("status") != "success":
            await event.reply(f"❌ Private transfer failed: {data.get('error', 'Unknown error')}")
            return

        amount = data.get("amount", 0)
        token_symbol = data.get("token", "")
        recipient_wallet = data.get("recipient") or recipient_wallet
        usd_value = data.get("usd_value", 0.0)

        amount_str = self._format_decimal(Decimal(str(amount)), 9)
        fees_line, net_line = await self._privacy_cash_fee_lines(amount, token_symbol, usd_value=usd_value)
        if recipient_wallet:
            await event.reply(
                f"✅ Private transfer sent: {amount_str} {token_symbol} to <code>{recipient_wallet}</code>\n{fees_line}\n{net_line}",
                parse_mode='html'
            )
        else:
            await event.reply(
                f"✅ Private transfer sent: {amount_str} {token_symbol}\n{fees_line}\n{net_line}",
                parse_mode='html'
            )

        if recipient_wallet:
            recipient_user = await self.db.get_user_by_wallet_address(recipient_wallet)
            if recipient_user and recipient_user.get("tg_user_id"):
                sender = await event.get_sender()
                sender_username = getattr(sender, 'username', None)
                if sender_username:
                    sender_display = f"@{sender_username}"
                else:
                    sender_user = await self.db.get_user_by_tg_id(tg_user_id)
                    sender_wallet = sender_user.get("wallet_address") if sender_user else None
                    if sender_wallet:
                        sender_display = f"<code>{sender_wallet[:8]}...{sender_wallet[-4:]}</code>"
                    else:
                        sender_display = "<b>Private Sender</b>"
                await self.send_private_payment_notification(
                    recipient_user["tg_user_id"],
                    amount,
                    token_symbol,
                    sender_display,
                    usd_value=usd_value,
                )

                # Also notify the payer that the payment was sent
                recipient_username = recipient_user.get('tg_username')
                if recipient_username:
                    recipient_display = f"@{recipient_username}"
                else:
                    recipient_display = f"<code>{recipient_wallet[:8]}...{recipient_wallet[-4:]}</code>"
                await self.send_private_payment_sent_notification(
                    tg_user_id,
                    amount,
                    token_symbol,
                    recipient_display,
                    usd_value=usd_value,
                )

    async def _handle_private_accept(self, event, tg_user_id: int, args: str, token_override: Optional[str] = None):
        """Handle /accept command - create a private payment request message."""
        if not args.strip():
            await event.reply(
                "Usage: /accept <amount> <token>\n\n"
                "Examples:\n"
                "/accept $5 SOL\n"
                "/accept 10 USDC"
            )
            return

        _, wallet_address = await self._get_wallet_info(tg_user_id)
        if not wallet_address:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        token_symbol = token_override
        if not token_symbol:
            token_match = re.search(r"\b(SOL|USDC)\b", args.strip(), re.IGNORECASE)
            token_symbol = token_match.group(1).upper() if token_match else None

        amount_match = re.search(r"(\d+(?:\.\d+)?)", args.replace(',', ''))
        amount = float(amount_match.group(1)) if amount_match else None

        if not amount or amount <= 0:
            await event.reply("❌ Couldn't understand that request. Try: /accept 5 SOL")
            return

        if token_symbol not in ("SOL", "USDC"):
            await event.reply(
                "Select a token:\n",
                buttons=[[Button.text("🪙 SOL", resize=True), Button.text("🪙 USDC", resize=True)]],
                parse_mode='html'
            )
            self._menu_context[tg_user_id] = {
                'awaiting_input': 'private_accept_token',
                'amount': amount
            }
            return

        await self._create_private_payment_request(event, tg_user_id, amount, token_symbol)

    async def _handle_private_accept_amount(self, event, tg_user_id: int, args: str):
        """Handle amount-only input for private accept and prompt token selection."""
        amount_match = re.search(r"(\d+(?:\.\d+)?)", args.replace(',', ''))
        amount = float(amount_match.group(1)) if amount_match else None
        if not amount or amount <= 0:
            await event.reply("❌ Please enter a valid amount. Example: 10")
            self._menu_context[tg_user_id] = {'awaiting_input': 'private_accept_amount'}
            return

        await event.reply(
            "Select a token:\n",
            buttons=[[Button.text("🪙 SOL", resize=True), Button.text("🪙 USDC", resize=True)]],
            parse_mode='html'
        )
        self._menu_context[tg_user_id] = {
            'awaiting_input': 'private_accept_token',
            'amount': amount
        }

    async def _handle_private_accept_token(self, event, tg_user_id: int, message_text: str, context: dict):
        """Handle token selection for private accept and create request."""
        token_symbol = message_text.replace("🪙", "").strip().upper()
        amount = context.get('amount')
        if token_symbol not in ("SOL", "USDC") or not amount:
            await event.reply("❌ Please select SOL or USDC.")
            self._menu_context[tg_user_id] = context
            return

        # Clear the token selection buttons
        await event.reply(f"Selected: {token_symbol}", buttons=Button.clear())
        await self._create_private_payment_request(event, tg_user_id, amount, token_symbol)

    async def _create_private_payment_request(self, event, tg_user_id: int, amount: float, token_symbol: str):
        """Create a private payment request with QR code and buttons."""
        _, wallet_address = await self._get_wallet_info(tg_user_id)
        if not wallet_address:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        amount_str = f"{amount:.9f}".rstrip('0').rstrip('.')
        usd_value = 0.0
        usd_str = f" (~${usd_value:.2f})" if usd_value else ""

        try:
            request_id = await self.db.create_payment_request(
                wallet_address=wallet_address,
                token_mint="",
                token_symbol=token_symbol,
                amount=amount,
                amount_usd=usd_value,
                is_private=True,
            )
        except Exception as e:
            logger.error(f"Failed to create private payment request: {e}")
            await event.reply("❌ Failed to create private payment request.")
            return

        bot_username = self.bot_username if self.bot_username else "solana_agent_bot"
        deep_link = f"https://t.me/{bot_username}?start=pay_priv_{request_id}"

        qr = segno.make(deep_link)
        buffer = BytesIO()
        qr.save(buffer, kind='png', scale=8, border=2)
        buffer.seek(0)
        buffer.name = 'qr.png'

        sender = await event.get_sender()
        username = getattr(sender, 'username', None)
        recipient_display = f"@{username}" if username else "you"

        caption = (
            "🔒 <b>Private Payment Request</b>\n\n"
            f"<b>Amount:</b> {amount_str} {token_symbol}{usd_str}\n"
            f"<b>To:</b> {recipient_display}\n\n"
            f"Scan this QR code or <a href='{deep_link}'>click here to pay privately</a>"
        )

        await event.reply(
            caption,
            file=buffer,
            parse_mode='html'
        )

    async def _handle_shield_deposit(self, event, tg_user_id: int, args: str):
        """Handle /shield_deposit command - shield (deposit) funds."""
        if not args.strip():
            await event.reply(
                "Usage: /shield_deposit <amount> <token>\n\n"
                "Examples:\n"
                "/shield_deposit 0.5 SOL\n"
                "/shield_deposit 10 USDC"
            )
            return

        wallet_id, _ = await self._get_wallet_info(tg_user_id)
        if not wallet_id:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return
        await self._process_agent_message(
            event,
            tg_user_id,
            f"[RESPOND IN ENGLISH] Shield (deposit) funds privately using wallet_id {wallet_id}: {args.strip()}. Use privy_privacy_cash action=deposit."
        )

    async def _handle_shield_withdraw(self, event, tg_user_id: int, args: str):
        """Handle /shield_withdraw command - unshield (withdraw) funds."""
        if not args.strip():
            await event.reply(
                "Usage: /shield_withdraw <amount> <token> to <wallet or @username>\n\n"
                "Examples:\n"
                "/shield_withdraw 0.1 SOL to 6qfHea...\n"
                "/shield_withdraw 5 USDC to @walletbubbles"
            )
            return

        wallet_id, _ = await self._get_wallet_info(tg_user_id)
        if not wallet_id:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        input_text = args.strip()
        input_text, _ = await self._resolve_username_in_text(event, input_text)
        if not input_text:
            return

        await self._process_agent_message(
            event,
            tg_user_id,
            f"[RESPOND IN ENGLISH] Unshield (withdraw) funds privately using wallet_id {wallet_id}: {input_text}. Use privy_privacy_cash action=withdraw."
        )

    async def _handle_shield_balance(self, event, tg_user_id: int, args: str):
        """Handle /shield_balance command - check shielded balance."""
        if not args.strip():
            await event.reply(
                "Usage: /shield_balance <token>\n\n"
                "Examples:\n"
                "/shield_balance SOL\n"
                "/shield_balance USDC"
            )
            return

        wallet_id, _ = await self._get_wallet_info(tg_user_id)
        if not wallet_id:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        await self._process_agent_message(
            event,
            tg_user_id,
            f"[RESPOND IN ENGLISH] Check my shielded balance for {args.strip()} using wallet_id {wallet_id}. Use privy_privacy_cash action=balance."
        )

    async def _execute_private_payment_request(self, event, tg_user_id: int, request: dict):
        """Execute a private payment request via Privacy Cash and confirm sender + recipient."""
        wallet_id, _ = await self._get_wallet_info(tg_user_id)
        if not wallet_id:
            await event.reply("❌ Your wallet isn't initialized yet. Run /start to create it.")
            return

        recipient_wallet = request.get("wallet_address")
        token_symbol = request.get("token_symbol")
        amount = request.get("amount")
        usd_value = request.get("amount_usd", 0.0)

        prompt = (
            "[RESPOND_JSON_ONLY] Execute a PrivacyCash private transfer. "
            f"Use wallet_id '{wallet_id}' for the sender. "
            "Use privy_privacy_cash with action=transfer. "
            f"Recipient wallet address: '{recipient_wallet}'. "
            f"Amount: {amount}. Token: {token_symbol}. "
            "Return ONLY JSON: {"
            "\"status\": \"success\"|\"error\", "
            "\"error\": \"\", "
            "\"recipient\": \"<wallet_address>\", "
            "\"amount\": <float>, "
            "\"token\": \"SOL\"|\"USDC\", "
            "\"usd_value\": <float>}"
        )

        response = ""
        try:
            async with self.client.action(event.chat_id, 'typing', delay=4):
                async for chunk in self.solana_agent.process(self._get_user_id(tg_user_id), prompt):
                    response += chunk
        except Exception:
            async for chunk in self.solana_agent.process(self._get_user_id(tg_user_id), prompt):
                response += chunk

        clean_json = response.replace('```json', '').replace('```', '').strip()
        try:
            data = json.loads(clean_json)
        except Exception:
            logger.error(f"Failed to parse private payment JSON: {clean_json}")
            await event.reply("❌ Private payment failed. Please try again.")
            return

        if data.get("status") != "success":
            await event.reply(f"❌ Private payment failed: {data.get('error', 'Unknown error')}")
            return

        amount = data.get("amount", amount)
        token_symbol = data.get("token", token_symbol)
        recipient_wallet = data.get("recipient") or recipient_wallet
        usd_value = data.get("usd_value", usd_value)

        amount_str = self._format_decimal(Decimal(str(amount)), 9)
        fees_line, net_line = await self._privacy_cash_fee_lines(amount, token_symbol, usd_value=usd_value)
        await event.reply(
            f"✅ Private payment sent: {amount_str} {token_symbol} to <code>{recipient_wallet}</code>\n{fees_line}\n{net_line}",
            parse_mode='html'
        )

        try:
            await self.db.mark_payment_request_sent(request.get("_id"))
        except Exception as e:
            logger.error(f"Failed to mark private payment request sent: {e}")

        if recipient_wallet:
            recipient_user = await self.db.get_user_by_wallet_address(recipient_wallet)
            if recipient_user and recipient_user.get("tg_user_id"):
                sender = await event.get_sender()
                sender_username = getattr(sender, 'username', None)
                if sender_username:
                    sender_display = f"@{sender_username}"
                else:
                    sender_user = await self.db.get_user_by_tg_id(tg_user_id)
                    sender_wallet = sender_user.get("wallet_address") if sender_user else None
                    if sender_wallet:
                        sender_display = f"<code>{sender_wallet[:8]}...{sender_wallet[-4:]}</code>"
                    else:
                        sender_display = "<b>Private Sender</b>"
                await self.send_private_payment_notification(
                    recipient_user["tg_user_id"],
                    amount,
                    token_symbol,
                    sender_display,
                    usd_value=usd_value,
                )

                # Also notify the payer that the payment was sent
                recipient_username = recipient_user.get('tg_username')
                if recipient_username:
                    recipient_display = f"@{recipient_username}"
                else:
                    recipient_display = f"<code>{recipient_wallet[:8]}...{recipient_wallet[-4:]}</code>"
                await self.send_private_payment_sent_notification(
                    tg_user_id,
                    amount,
                    token_symbol,
                    recipient_display,
                    usd_value=usd_value,
                )

    async def _handle_purge(self, event, tg_user_id: int):
        """Handle /purge command - clear conversation history."""
        user_id = self._get_user_id(tg_user_id)
        try:
            await self.solana_agent.delete_user_history(user_id)
            await event.reply(
                "🗑️ Conversation history cleared!\n\n"
                "Your wallet and settings are unchanged.\n"
                "Start fresh - just send me a message!",
                parse_mode='markdown'
            )
            logger.info(f"Cleared history for {tg_user_id}")
        except Exception as e:
            logger.error(f"Error clearing history for {tg_user_id}: {e}")
            await event.reply("Sorry, couldn't clear history. Try again?")
    
    def _detect_injection_attempt(self, text: str) -> Tuple[bool, str]:
        """
        Detect potential prompt injection attempts.
        Returns (is_injection, reason) tuple.
        """
        text_lower = text.lower()
        
        # === Pattern 1: Direct instruction override attempts ===
        instruction_override_patterns = [
            r"ignore\s+(all\s+)?(previous|prior|above|earlier|your)\s+(instructions?|prompts?|rules?|guidelines?)",
            r"disregard\s+(all\s+)?(previous|prior|above|your)\s+(instructions?|prompts?)",
            r"forget\s+(all\s+)?(previous|prior|your)\s+(instructions?|prompts?|context)",
            r"override\s+(all\s+)?(previous|your)\s+(instructions?|prompts?)",
            r"new\s+instructions?\s*[:=]",
            r"from\s+now\s+on\s*,?\s*(you\s+are|ignore|forget)",
            r"stop\s+being\s+(an?\s+)?ai",
            r"you\s+are\s+now\s+(in\s+)?\w+\s+mode",
        ]
        
        for pattern in instruction_override_patterns:
            if re.search(pattern, text_lower):
                return True, "instruction_override"
        
        # === Pattern 2: System prompt extraction attempts ===
        prompt_extraction_patterns = [
            r"(show|tell|reveal|display|print|output|give)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions?|rules?|guidelines?)",
            r"what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions?|rules?|initial\s+prompt)",
            r"(repeat|echo|recite)\s+(your\s+)?(system\s+)?(prompt|instructions?)",
            r"(copy|paste|dump)\s+(your\s+)?(entire\s+)?(system\s+)?(prompt|instructions?)",
            r"beginning\s+of\s+(your|the)\s+(conversation|prompt|instructions?)",
        ]
        
        for pattern in prompt_extraction_patterns:
            if re.search(pattern, text_lower):
                return True, "prompt_extraction"
        
        # === Pattern 3: Roleplay/identity manipulation ===
        roleplay_patterns = [
            r"pretend\s+(to\s+be|you\s+are|you're)\s+(a|an|the)?",
            r"act\s+as\s+(if\s+you\s+are|a|an|the)",
            r"you\s+are\s+(now\s+)?(a|an)?\s*(different|new|evil|unrestricted|jailbroken)",
            r"(enable|activate|enter)\s+(developer|debug|admin|root|sudo|god|dan|jailbreak)\s*(mode)?",
            r"\bdan\s+mode\b",
            r"\bjailbreak\b",
            r"do\s+anything\s+now",
            r"opposite\s+(mode|day)",
        ]
        
        for pattern in roleplay_patterns:
            if re.search(pattern, text_lower):
                return True, "roleplay_attempt"
        
        # === Pattern 4: Encoded/obfuscated content ===
        # Check for base64 encoded content (common injection vector)
        potential_b64 = re.findall(r'[A-Za-z0-9+/]{20,}={0,2}', text)
        for encoded in potential_b64:
            try:
                decoded = base64.b64decode(encoded).decode('utf-8', errors='ignore').lower()
                # Check if decoded content contains suspicious patterns
                if any(word in decoded for word in ['ignore', 'system', 'prompt', 'pretend', 'instructions']):
                    return True, "encoded_injection"
            except Exception:
                pass
        
        # === Pattern 5: Suspicious formatting markers ===
        # Excessive use of "IMPORTANT", "CRITICAL", "SYSTEM" might indicate injection
        emphasis_count = len(re.findall(r'\b(IMPORTANT|CRITICAL|URGENT|SYSTEM|ADMIN|ROOT|OVERRIDE)\b', text))
        if emphasis_count >= 3:
            return True, "suspicious_emphasis"
        
        # === Pattern 6: Delimiter injection attempts ===
        delimiter_patterns = [
            r"```\s*(system|instructions?|prompt)",
            r"<\s*(system|instructions?|prompt|admin)\s*>",
            r"\[\s*(system|instructions?|prompt|admin)\s*\]",
            r"###\s*(system|new\s+instructions?|override)",
        ]
        
        for pattern in delimiter_patterns:
            if re.search(pattern, text_lower):
                return True, "delimiter_injection"
        
        return False, ""
    
    def _detect_language_prefix(self, text: str) -> str:
        """Detect language and return appropriate instruction prefix."""
        # Check for Cyrillic characters (Russian, Ukrainian, etc.)
        cyrillic_count = sum(1 for c in text if '\u0400' <= c <= '\u04FF')
        # Check for CJK characters
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        # Check for Spanish/Portuguese special chars
        spanish_chars = sum(1 for c in text if c in 'áéíóúüñ¿¡ÁÉÍÓÚÜÑ')
        
        total_alpha = sum(1 for c in text if c.isalpha())
        if total_alpha == 0:
            return "[RESPOND IN ENGLISH]"
        
        cyrillic_ratio = cyrillic_count / total_alpha if total_alpha > 0 else 0
        
        if cyrillic_ratio > 0.3:
            return "[RESPOND IN RUSSIAN - this message is in Russian]"
        elif cjk_count > 5:
            return "[RESPOND IN CHINESE]"
        elif spanish_chars > 2:
            return "[RESPOND IN SPANISH]"
        else:
            return "[RESPOND IN ENGLISH]"
    
    async def _process_agent_message(self, event, tg_user_id: int, message_text: str, silent: bool = False):
        """Process message through Solana Agent."""
        # === PROMPT INJECTION DEFENSE ===
        # Check for injection attempts before processing
        # Only check user-provided text, not our internal command prompts
        if not message_text.startswith("[RESPOND IN"):
            is_injection, reason = self._detect_injection_attempt(message_text)
            if is_injection:
                logger.warning(f"Prompt injection attempt from {tg_user_id} ({reason}): {message_text[:100]}...")
                await event.reply("I'm here to help with Solana trading, wallets, and market data. How can I help?")
                return
        
        # Use telegram:user_id format for Privy
        user_id = self._get_user_id(tg_user_id)
        
        # Always prefix with language instruction to override history
        # Detect if message is already prefixed (from command handlers)
        if not message_text.startswith("[RESPOND IN"):
            lang_prefix = self._detect_language_prefix(message_text)
            message_text = f"{lang_prefix} {message_text}"

        user_id_from_db, wallet_id, wallet_address = await self._get_user_context(tg_user_id)
        if user_id_from_db or wallet_id or wallet_address:
            message_text = (
                f"{message_text}\n"
                f"[APP_CONTEXT] user_id={user_id_from_db or ''} wallet_id={wallet_id or ''} wallet_address={wallet_address or ''} wallet_public_key={wallet_address or ''}"
            )
        
        try:
            logger.info(f"Starting typing indicator for chat {event.chat_id}")
            
            # Use Telethon's action context manager for typing indicator
            # delay=4 means refresh every 4 seconds (Telegram shows typing for ~5s)
            try:
                async with self.client.action(event.chat_id, 'typing', delay=4):
                    # Collect full response from agent
                    agent_response = ""
                    async for chunk in self.solana_agent.process(user_id, message_text):
                        agent_response += chunk
            except Exception:
                agent_response = ""
                async for chunk in self.solana_agent.process(user_id, message_text):
                    agent_response += chunk
            
            if agent_response:
                if not silent:
                    # Send the response (split if needed)
                    await self._send_long_message(event, agent_response)
                    logger.info(f"Replied to {tg_user_id} ({len(agent_response)} chars)")
                else:
                    logger.info(f"Silently processed message for {tg_user_id} ({len(agent_response)} chars)")
            else:
                await event.reply("Sorry, I couldn't process that. Try again?")
                logger.warning(f"No response for {tg_user_id}")
                    
        except Exception as e:
            logger.error(f"Error processing message from {tg_user_id}: {e}", exc_info=True)
            await event.reply("Sorry, something went wrong. Please try again.")
    
    def _convert_markdown_to_html(self, text: str) -> str:
        """Convert markdown formatting to HTML for Telegram."""
        import re
        # Convert **bold** to <b>bold</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        # Convert *italic* to <i>italic</i> (but not if already converted)
        text = re.sub(r'(?<!</b>)\*(.+?)\*(?!>)', r'<i>\1</i>', text)
        # Convert `code` to <code>code</code>
        text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
        # Escape HTML special chars that aren't part of our tags
        # But be careful not to escape our own tags
        return text
    
    async def _send_long_message(self, event, text: str):
        """Send a message, splitting if too long."""
        # Convert markdown to HTML
        text = self._convert_markdown_to_html(text)
        
        # Telegram max is 4096, but leave room for issues
        max_len = 4000
        
        if len(text) <= max_len:
            try:
                await event.reply(text, parse_mode='html')
            except Exception:
                # Fallback to plain text if HTML fails
                await event.reply(text)
        else:
            # Split on double newlines or at max length
            chunks = []
            remaining = text
            while remaining:
                if len(remaining) <= max_len:
                    chunks.append(remaining)
                    break
                
                # Find a good split point
                split_at = remaining.rfind('\n\n', 0, max_len)
                if split_at == -1:
                    split_at = remaining.rfind('\n', 0, max_len)
                if split_at == -1:
                    split_at = max_len
                
                chunks.append(remaining[:split_at])
                remaining = remaining[split_at:].lstrip()
            
            for chunk in chunks:
                try:
                    await event.reply(chunk, parse_mode='html')
                except Exception:
                    await event.reply(chunk)
    
    async def start(self):
        """Start the Telegram bot."""
        await self.client.start(bot_token=app_config.TELEGRAM_BOT_TOKEN)
        
        me = await self.client.get_me()
        self.bot_username = me.username
        logger.info(f"Telegram bot started as @{self.bot_username}")
        
        # Set menu button to show default bot menu
        try:
            await self.client(SetBotMenuButtonRequest(menu_button=BotMenuButtonDefault()))
            logger.info("Menu button set to default")
        except Exception as e:
            logger.warning(f"Could not set menu button: {e}")
        
        # Keep running
        await self.client.run_until_disconnected()
    
    async def stop(self):
        """Stop the Telegram bot."""
        await self.client.disconnect()
        logger.info("Telegram bot stopped")


async def run_bot(solana_agent, db_service: DatabaseService):
    """Run the Telegram bot."""
    bot = TelegramBot(solana_agent, db_service)
    await bot.start()
