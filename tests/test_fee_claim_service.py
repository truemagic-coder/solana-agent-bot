"""
Tests for Jupiter fee claim service.

Critical tests for fee claiming, sweeping, and payout distribution.
"""
import pytest
import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from solders.pubkey import Pubkey
from solders.keypair import Keypair

from solana_agent_api.fee_claim_service import (
    REFERRAL_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    TOKEN_2022_PROGRAM_ID,
    ASSOCIATED_TOKEN_PROGRAM_ID,
    AGENT_TOKEN_MINT,
    WSOL_MINT,
    CLAIM_DISCRIMINATOR,
    CLAIM_V2_DISCRIMINATOR,
    ReferralType,
    ReferralConfig,
    TokenAccountInfo,
    ClaimResult,
    get_anchor_discriminator,
    derive_referral_token_account_pda,
    derive_referral_token_account_v2_pda,
    derive_project_authority_pda,
    get_associated_token_address,
    create_claim_instruction,
    create_claim_v2_instruction,
    create_ata_idempotent_instruction,
    FeeClaimService,
)


class TestConstants:
    """Test that program constants are correctly defined."""
    
    def test_referral_program_id(self):
        """Referral program ID should be correct."""
        expected = "REFER4ZgmyYx9c6He5XfaTMiGfdLwRnkV4RPp9t9iF3"
        assert str(REFERRAL_PROGRAM_ID) == expected
    
    def test_token_program_id(self):
        """Token program ID should be correct."""
        expected = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        assert str(TOKEN_PROGRAM_ID) == expected
    
    def test_token_2022_program_id(self):
        """Token-2022 program ID should be correct."""
        expected = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
        assert str(TOKEN_2022_PROGRAM_ID) == expected
    
    def test_associated_token_program_id(self):
        """Associated token program ID should be correct."""
        expected = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
        assert str(ASSOCIATED_TOKEN_PROGRAM_ID) == expected
    
    def test_agent_token_mint(self):
        """$AGENT token mint should be correct."""
        expected = "5tFRno9GXBP5gt2Kjx2MeEaFL8zGBMw4cujTLGerpump"
        assert str(AGENT_TOKEN_MINT) == expected
    
    def test_wsol_mint(self):
        """WSOL mint should be correct."""
        expected = "So11111111111111111111111111111111111111112"
        assert str(WSOL_MINT) == expected


class TestAnchorDiscriminators:
    """Test Anchor instruction discriminators."""
    
    def test_claim_discriminator_calculation(self):
        """Test claim discriminator is calculated correctly."""
        # Anchor uses first 8 bytes of SHA256("global:claim")
        preimage = "global:claim"
        expected = hashlib.sha256(preimage.encode()).digest()[:8]
        assert CLAIM_DISCRIMINATOR == expected
    
    def test_claim_v2_discriminator_calculation(self):
        """Test claimV2 discriminator is calculated correctly."""
        preimage = "global:claim_v2"
        expected = hashlib.sha256(preimage.encode()).digest()[:8]
        assert CLAIM_V2_DISCRIMINATOR == expected
    
    def test_get_anchor_discriminator_function(self):
        """Test the get_anchor_discriminator helper."""
        disc = get_anchor_discriminator("test_instruction")
        expected = hashlib.sha256(b"global:test_instruction").digest()[:8]
        assert disc == expected
    
    def test_discriminator_length(self):
        """Discriminators should be exactly 8 bytes."""
        assert len(CLAIM_DISCRIMINATOR) == 8
        assert len(CLAIM_V2_DISCRIMINATOR) == 8


class TestPDADerivation:
    """Test PDA derivation functions."""
    
    def test_derive_referral_token_account_pda(self):
        """Test referral token account PDA derivation (claim style)."""
        referral = Pubkey.from_string("11111111111111111111111111111111")
        mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        
        pda, bump = derive_referral_token_account_pda(referral, mint)
        
        # PDA should be valid (on the curve)
        assert pda is not None
        assert isinstance(bump, int)
        assert 0 <= bump <= 255
    
    def test_derive_referral_token_account_v2_pda(self):
        """Test referral ATA derivation (claimV2 style)."""
        referral = Pubkey.from_string("11111111111111111111111111111111")
        mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        
        ata = derive_referral_token_account_v2_pda(referral, mint, TOKEN_PROGRAM_ID)
        
        assert ata is not None
    
    def test_derive_project_authority_pda(self):
        """Test project authority PDA derivation."""
        project = Pubkey.from_string("11111111111111111111111111111111")
        
        pda, bump = derive_project_authority_pda(project)
        
        assert pda is not None
        assert isinstance(bump, int)
    
    def test_get_associated_token_address(self):
        """Test ATA address derivation."""
        owner = Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
        mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        
        ata = get_associated_token_address(owner, mint)
        
        assert ata is not None
        # Verify it's deterministic
        ata2 = get_associated_token_address(owner, mint)
        assert ata == ata2


class TestDataClasses:
    """Test data class definitions."""
    
    def test_referral_config(self):
        """Test ReferralConfig dataclass."""
        config = ReferralConfig(
            referral_type=ReferralType.ULTRA,
            referral_account=Pubkey.default(),
            project=Pubkey.default(),
        )
        
        assert config.referral_type == ReferralType.ULTRA
        assert config.referral_account == Pubkey.default()
    
    def test_token_account_info(self):
        """Test TokenAccountInfo dataclass."""
        info = TokenAccountInfo(
            pubkey=Pubkey.default(),
            mint=WSOL_MINT,
            balance=1_000_000_000,  # 1 SOL
            decimals=9,
            token_program=TOKEN_PROGRAM_ID,
        )
        
        assert info.balance == 1_000_000_000
        assert info.decimals == 9
        assert info.ui_amount == 1.0  # Property converts to token units
    
    def test_token_account_info_ui_amount(self):
        """Test ui_amount property calculates correctly."""
        # SOL with 9 decimals
        sol_info = TokenAccountInfo(
            pubkey=Pubkey.default(),
            mint=WSOL_MINT,
            balance=1_500_000_000,  # 1.5 SOL
            decimals=9,
            token_program=TOKEN_PROGRAM_ID,
        )
        assert sol_info.ui_amount == 1.5
        
        # USDC with 6 decimals
        usdc_mint = Pubkey.from_string("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
        usdc_info = TokenAccountInfo(
            pubkey=Pubkey.default(),
            mint=usdc_mint,
            balance=100_000_000,  # 100 USDC
            decimals=6,
            token_program=TOKEN_PROGRAM_ID,
        )
        assert usdc_info.ui_amount == 100.0
    
    def test_claim_result_success(self):
        """Test ClaimResult for successful claim."""
        result = ClaimResult(
            mint="So11111111111111111111111111111111111111112",
            amount=1.5,
            usd_value=225.0,
            signature="5abc123...",
            success=True,
        )
        
        assert result.success is True
        assert result.error is None
    
    def test_claim_result_failure(self):
        """Test ClaimResult for failed claim."""
        result = ClaimResult(
            mint="So11111111111111111111111111111111111111112",
            amount=1.5,
            usd_value=0,
            signature=None,
            success=False,
            error="Transaction failed",
        )
        
        assert result.success is False
        assert result.error == "Transaction failed"


class TestInstructionCreation:
    """Test instruction creation functions."""
    
    def test_create_claim_instruction(self):
        """Test claim instruction has correct structure."""
        payer = Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
        project = Pubkey.default()
        admin = Pubkey.default()
        project_admin_token_account = Pubkey.default()
        referral_account = Pubkey.default()
        referral_token_account = Pubkey.default()
        partner = Pubkey.default()
        partner_token_account = Pubkey.default()
        mint = WSOL_MINT
        
        ix = create_claim_instruction(
            payer=payer,
            project=project,
            admin=admin,
            project_admin_token_account=project_admin_token_account,
            referral_account=referral_account,
            referral_token_account=referral_token_account,
            partner=partner,
            partner_token_account=partner_token_account,
            mint=mint,
            token_program=TOKEN_PROGRAM_ID,
        )
        
        # Check instruction program ID
        assert ix.program_id == REFERRAL_PROGRAM_ID
        
        # Check discriminator in data
        assert ix.data[:8] == CLAIM_DISCRIMINATOR
        
        # Check account count (claim has 12 accounts)
        assert len(ix.accounts) == 12
        
        # First account should be payer (signer, writable)
        assert ix.accounts[0].pubkey == payer
        assert ix.accounts[0].is_signer is True
        assert ix.accounts[0].is_writable is True
    
    def test_create_claim_v2_instruction(self):
        """Test claimV2 instruction has correct structure."""
        payer = Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
        project = Pubkey.default()
        admin = Pubkey.default()
        project_admin_token_account = Pubkey.default()
        referral_account = Pubkey.default()
        referral_token_account = Pubkey.default()
        partner = Pubkey.default()
        partner_token_account = Pubkey.default()
        mint = WSOL_MINT
        
        ix = create_claim_v2_instruction(
            payer=payer,
            project=project,
            admin=admin,
            project_admin_token_account=project_admin_token_account,
            referral_account=referral_account,
            referral_token_account=referral_token_account,
            partner=partner,
            partner_token_account=partner_token_account,
            mint=mint,
            token_program=TOKEN_PROGRAM_ID,
        )
        
        # Check instruction program ID
        assert ix.program_id == REFERRAL_PROGRAM_ID
        
        # Check discriminator in data
        assert ix.data[:8] == CLAIM_V2_DISCRIMINATOR
        
        # Check account count (claimV2 has 12 accounts)
        assert len(ix.accounts) == 12
    
    def test_create_ata_idempotent_instruction(self):
        """Test ATA creation instruction."""
        payer = Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
        owner = Pubkey.default()
        mint = WSOL_MINT
        
        ix = create_ata_idempotent_instruction(
            payer=payer,
            owner=owner,
            mint=mint,
        )
        
        assert ix.program_id == ASSOCIATED_TOKEN_PROGRAM_ID
        assert len(ix.accounts) == 6
        # Idempotent instruction discriminator is 1
        assert ix.data == bytes([1])


class TestFeeClaimServiceInit:
    """Test FeeClaimService initialization."""
    
    @pytest.mark.asyncio
    async def test_init_without_config(self):
        """Test service initializes without config (disabled mode)."""
        with patch('solana_agent_api.fee_claim_service.config') as mock_config:
            mock_config.FEE_PAYER = None
            mock_config.JUPITER_REFERRAL_ULTRA_CODE = None
            mock_config.JUPITER_REFERRAL_TRIGGER_CODE = None
            mock_config.HELIUS_URL = "https://test.helius.xyz"
            mock_config.JUPITER_API_KEY = None
            mock_config.BIRDEYE_API_KEY = "test-key"
            
            async with FeeClaimService(None) as service:
                assert service.fee_payer is None
                assert len(service.referral_configs) == 0
    
    @pytest.mark.asyncio
    async def test_init_with_referral_codes(self):
        """Test service initializes with referral codes."""
        with patch('solana_agent_api.fee_claim_service.config') as mock_config:
            mock_config.FEE_PAYER = None
            # Use valid 32-byte base58 pubkeys (43-44 chars)
            mock_config.JUPITER_REFERRAL_ULTRA_CODE = "11111111111111111111111111111112"
            mock_config.JUPITER_REFERRAL_TRIGGER_CODE = "11111111111111111111111111111113"
            mock_config.HELIUS_URL = "https://test.helius.xyz"
            mock_config.JUPITER_API_KEY = None
            mock_config.BIRDEYE_API_KEY = "test-key"
            
            async with FeeClaimService(None) as service:
                assert len(service.referral_configs) == 2
                
                ultra_config = next(c for c in service.referral_configs if c.referral_type == ReferralType.ULTRA)
                trigger_config = next(c for c in service.referral_configs if c.referral_type == ReferralType.TRIGGER)
                
                assert ultra_config is not None
                assert trigger_config is not None


class TestFeeClaimServiceMethods:
    """Test FeeClaimService methods."""
    
    @pytest.fixture
    def mock_service(self):
        """Create a mock FeeClaimService."""
        with patch('solana_agent_api.fee_claim_service.config') as mock_config:
            mock_config.FEE_PAYER = None
            mock_config.JUPITER_REFERRAL_ULTRA_CODE = "11111111111111111111111111111111"
            mock_config.JUPITER_REFERRAL_TRIGGER_CODE = None
            mock_config.HELIUS_URL = "https://test.helius.xyz"
            mock_config.JUPITER_API_KEY = "test-key"
            mock_config.BIRDEYE_API_KEY = "test-key"
            
            service = FeeClaimService(None)
            service.http_client = AsyncMock()
            yield service
    
    @pytest.mark.asyncio
    async def test_get_token_price(self, mock_service):
        """Test fetching token price."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "success": True,
            "data": {"value": 150.0}
        }
        mock_response.raise_for_status = MagicMock()
        mock_service.http_client.get = AsyncMock(return_value=mock_response)
        
        price = await mock_service.get_token_price(WSOL_MINT)
        
        assert price == 150.0
    
    @pytest.mark.asyncio
    async def test_get_token_accounts_for_referral(self, mock_service):
        """Test fetching token accounts for a referral."""
        rpc_response = {
            "result": {
                "value": [
                    {
                        "pubkey": str(Pubkey.default()),
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "mint": str(WSOL_MINT),
                                        "tokenAmount": {
                                            "amount": "1000000000",
                                            "decimals": 9,
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            }
        }
        
        mock_response = MagicMock()
        mock_response.json.return_value = rpc_response
        mock_response.raise_for_status = MagicMock()
        mock_service.http_client.post = AsyncMock(return_value=mock_response)
        
        referral = Pubkey.from_string("11111111111111111111111111111112")
        accounts = await mock_service.get_token_accounts_for_referral(
            referral,
            ReferralType.ULTRA,
        )
        
        # Service queries both TOKEN_PROGRAM and TOKEN_2022_PROGRAM, each returns 1 account
        assert len(accounts) == 2
        assert accounts[0].balance == 1_000_000_000
        assert accounts[0].decimals == 9
    
    @pytest.mark.asyncio
    async def test_claim_without_fee_payer(self, mock_service):
        """Test claiming returns error when no fee payer."""
        ref_config = ReferralConfig(
            referral_type=ReferralType.ULTRA,
            referral_account=Pubkey.default(),
            project=Pubkey.default(),
        )
        token_account = TokenAccountInfo(
            pubkey=Pubkey.default(),
            mint=WSOL_MINT,
            balance=1_000_000_000,
            decimals=9,
            token_program=TOKEN_PROGRAM_ID,
        )
        
        result = await mock_service.claim_for_referral(ref_config, token_account)
        
        assert result.success is False
        assert "No fee payer configured" in result.error


class TestReferralTypes:
    """Test referral type enum."""
    
    def test_ultra_type(self):
        """Test Ultra referral type."""
        assert ReferralType.ULTRA.value == "ultra"
    
    def test_trigger_type(self):
        """Test Trigger referral type."""
        assert ReferralType.TRIGGER.value == "trigger"


class TestAccountParsing:
    """Test on-chain account data parsing."""
    
    @pytest.mark.asyncio
    async def test_parse_referral_account_data(self):
        """Test parsing referral account data from chain."""
        # Create mock account data in Anchor format
        # 8 bytes discriminator + 32 bytes project + 32 bytes partner + 2 bytes share_bps
        discriminator = b'\x00' * 8
        project = bytes(Pubkey.default())
        partner = bytes(Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"))
        share_bps = (1000).to_bytes(2, 'little')  # 10% = 1000 bps
        
        account_data = discriminator + project + partner + share_bps
        
        # Mock the RPC response
        with patch('solana_agent_api.fee_claim_service.config') as mock_config:
            mock_config.FEE_PAYER = None
            mock_config.JUPITER_REFERRAL_ULTRA_CODE = None
            mock_config.JUPITER_REFERRAL_TRIGGER_CODE = None
            mock_config.HELIUS_URL = "https://test.helius.xyz"
            mock_config.JUPITER_API_KEY = None
            mock_config.BIRDEYE_API_KEY = "test-key"
            
            service = FeeClaimService(None)
            service.http_client = AsyncMock()
            
            rpc_response = {
                "result": {
                    "value": {
                        "data": [base64.b64encode(account_data).decode(), "base64"]
                    }
                }
            }
            
            mock_response = MagicMock()
            mock_response.json.return_value = rpc_response
            mock_response.raise_for_status = MagicMock()
            service.http_client.post = AsyncMock(return_value=mock_response)
            
            referral = Pubkey.default()
            info = await service.get_referral_account_info(referral)
            
            assert info["project"] == Pubkey.default()
            assert info["partner"] == Pubkey.from_string("7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU")
            assert info["share_bps"] == 1000
