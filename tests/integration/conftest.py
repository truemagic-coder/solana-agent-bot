"""
Pytest configuration for integration tests.

These tests run against real services and require:
- Valid API keys in environment
- A funded test wallet
- Network connectivity to Solana mainnet
"""

import pytest


def pytest_configure(config):
    """Configure pytest for integration tests."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (runs against real services)"
    )


def pytest_collection_modifyitems(config, items):
    """Add integration marker to all tests in this directory."""
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
