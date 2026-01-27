import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # MongoDB
    MONGO_URL = os.getenv("MONGO_URL")
    MONGO_DB = os.getenv("MONGO_DB")
    
    # AI Providers
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    GROK_API_KEY = os.getenv("GROK_API_KEY")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    LOGFIRE_API_KEY = os.getenv("LOGFIRE_API_KEY")
    
    # External APIs
    BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY")
    JUPITER_API_KEY = os.getenv("JUPITER_API_KEY")
    JUPITER_REFERRAL_ULTRA_CODE = os.getenv("JUPITER_REFERRAL_ULTRA_CODE")  # Referral account for Ultra swaps
    JUPITER_REFERRAL_TRIGGER_CODE = os.getenv("JUPITER_REFERRAL_TRIGGER_CODE")  # Referral account for Trigger/Swap
    
    # Privy
    PRIVY_APP_ID = os.getenv("PRIVY_APP_ID")
    PRIVY_APP_SECRET = os.getenv("PRIVY_APP_SECRET")
    PRIVY_SIGNING_KEY = os.getenv("PRIVY_SIGNING_KEY")
    PRIVY_OWNER_ID = os.getenv("PRIVY_OWNER_ID")

    # Privacy Cash
    PRIVY_PRIVACY_CASH_API_KEY = os.getenv("PRIVY_PRIVACY_CASH_API_KEY")
    
    # Auth (Privy JWT verification)
    AUTH_AUDIENCE = os.getenv("AUTH_AUDIENCE")
    AUTH_ISSUER = os.getenv("AUTH_ISSUER")
    AUTH_RSA = os.getenv("AUTH_RSA")
    
    # Solana / Helius
    HELIUS_URL = os.getenv("HELIUS_URL")
    FEE_PAYER = os.getenv("FEE_PAYER")  # Private key (base58)
    
    # Telegram
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    # Trading Agent
    TRADING_AGENT_INTERVAL_SECONDS = int(os.getenv("TRADING_AGENT_INTERVAL_SECONDS", "14400"))

config = Config()
