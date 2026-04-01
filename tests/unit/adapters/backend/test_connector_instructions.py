"""Tests for BackendConnector.get_instructions() — initialize interception."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as types
import pytest

from token_sieve.adapters.backend.connector import BackendConnector


class TestGetInstructions:
    """BackendConnector.get_instructions() captures backend instructions."""

    @pytest.mark.asyncio
    async def test_returns_instructions_from_initialize(self) -> None:
        """get_instructions() returns the instructions field from session.initialize()."""
        session = AsyncMock()
        connector = BackendConnector(session)
        connector._instructions = "Use these tools carefully."

        result = connector.get_instructions()
        assert result == "Use these tools carefully."

    @pytest.mark.asyncio
    async def test_returns_none_when_no_instructions(self) -> None:
        """get_instructions() returns None when backend has no instructions."""
        session = AsyncMock()
        connector = BackendConnector(session)
        # No _instructions set — default should be None

        result = connector.get_instructions()
        assert result is None

    @pytest.mark.asyncio
    async def test_set_instructions_stores_value(self) -> None:
        """set_instructions() stores the instructions for later retrieval."""
        session = AsyncMock()
        connector = BackendConnector(session)
        connector.set_instructions("Backend server instructions text")

        assert connector.get_instructions() == "Backend server instructions text"
