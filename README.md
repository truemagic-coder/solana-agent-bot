# Solana Agent Bot

**Solana Privacy Hack (Privacy Payment Track) submission**

This project is built for the Solana Privacy Hack hackathon (https://solana.com/privacyhack) and focuses on private payments (track) using Privacy Cash, Helius, and Telegram. It uses these technologies to support private transfers for Telegram users that include payment links and QR codes. For non-private payments, it also integrates Helius webhooks for transfer notifications. A demo video is below.

It meets all the criteria for the hackathon:

* All code must be open source -> my code is open source (MIT licensed) and built on all open source.
* Projects must integrate with Solana and use privacy-preserving technologies -> Solana Agent Bot fully integrates with Solana, Helius, and Privacy Cash.
* All programs must be deployed to Solana devnet or mainnet -> Solana Agent Bot is deployed on mainnet and on Telegram at https://t.me/solana_agent_bot.
* Submit a demo video (maximum 3 minutes) showcasing your project -> see below.
* Include documentation on how to run and use your project -> this README is the documentation

## How to Use

* Create a Telegram account
* Visit https://t.me/solana_agent_bot and run command start - you will be assigned a self-custody wallet
* Transfer either SOL or USDC into your wallet from another wallet or by buying and swapping $AGENT
* Bring up the menu by clicking it or saying `/menu`
* Click `wallet` and then `privacy` and then `private transfer` and specify the token (SOL or USDC) the token amount and payee (must have a wallet on Solana Agent Bot)
* The transfer should succeed and you (the payer) and the payee will be notified by the bot

## Demo Video


https://github.com/user-attachments/assets/9afc7c52-c1aa-4a6d-a9be-c14d17d28ed3




This Telegram bot is also a Solana AI trading copilot with private transfers, private shielding, market data, social sentiment on X, Jupiter swaps, and Jupiter limit orders using self-custody Privy wallets.

The code is a FastAPI backend and Telegram bot for Solana Agent. The production Telegram bot is deployed at https://t.me/solana_agent_bot.

### What this repo includes

- FastAPI API server
- Telegram bot (Telethon) that runs alongside the API
- MongoDB persistence
- Helius webhook endpoint for transfer notifications

---

## Requirements

- Python 3.13.11
- MongoDB (required)
- API keys for the providers you intend to use

---

## Setup

1. `uv sync`

2. Create a `.env` file in the repo root (same level as `pyproject.toml`).

3. Setup a running version of Solana Agent Cash -> https://github.com/truemagic-coder/solana-agent-cash

3. Configure environment variables (see below).

4. Run the API server (this also starts the Telegram bot).

---

## Environment variables

Create a `.env` file with the following values. Only the fields you use need to be set, but most production features require the full set.

### MongoDB

- `MONGO_URL` (required) — Mongo connection string
- `MONGO_DB` (required) — Database name

### AI Providers

- `OPENAI_API_KEY` — OpenAI key (used by solana-agent)
- `GROK_API_KEY` — Grok key for search
- `LOGFIRE_API_KEY` — Optional logging key

### Market / Swap APIs

- `BIRDEYE_API_KEY` — Birdeye market data
- `JUPITER_API_KEY` — Jupiter API key
- `JUPITER_REFERRAL_ULTRA_CODE` — Referral account for Ultra swaps
- `JUPITER_REFERRAL_TRIGGER_CODE` — Referral account for Trigger/Swap

### Privy

- `PRIVY_APP_ID` — Privy application ID
- `PRIVY_APP_SECRET` — Privy application secret
- `PRIVY_SIGNING_KEY` — Privy wallet authorization signing key
- `PRIVY_OWNER_ID` — Privy key authorization key for wallet creation (required)
- `PRIVY_PRIVACY_CASH_API_KEY` — Privy Privacy Cash API key (see https://github.com/truemagic-coder/solana-agent-cash)

### Auth (Privy JWT verification)

- `AUTH_AUDIENCE`
- `AUTH_ISSUER`
- `AUTH_RSA`

### Solana / Helius

- `HELIUS_URL` — RPC URL (Helius)
- `HELIUS_WEBHOOK_SECRET` — Secret used to authenticate webhooks
- `FEE_PAYER` — Base58 private key (fee payer)

### Telegram

- `TELEGRAM_API_ID` — Telegram API ID (integer)
- `TELEGRAM_API_HASH` — Telegram API hash
- `TELEGRAM_BOT_TOKEN` — Bot token

---

## Running locally

The API server starts the Telegram bot during app startup (see `lifespan` in [solana_agent_api/main.py](solana_agent_api/main.py)).

### Dev server

- Use the provided script in [dev.sh](dev.sh). `bash ./dev.sh`. It runs Uvicorn with autoreload on port 8080.

### Production

- Use the command in [Procfile](Procfile) (Gunicorn + Uvicorn worker).

---

## Webhooks

Helius transfer notifications are handled at:

- `POST /webhooks/helius`

Set `HELIUS_WEBHOOK_SECRET` and configure Helius to send that value in the `Authorization` header.

These notfications are for non-private payments - private payment notifications use internal logic.

---

## Tests

Install test dependencies with the `uv sync --extra test` and then run with `uv run pytest`.

---

## Telegram bot

The production bot is live at https://t.me/solana_agent_bot.

The bot runs inside the API process and uses your `TELEGRAM_*` credentials. Private chats only; group messages are ignored by design.
