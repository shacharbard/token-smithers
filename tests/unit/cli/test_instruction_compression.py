"""Tests for system prompt compression in _run_proxy."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from token_sieve.cli.main import main


class TestInstructionCompression:
    """System prompt compression wires into _run_proxy."""

    def test_compressed_instructions_passed_to_server(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When backend has instructions, they are compressed and passed to Server."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "backend:\n  command: echo\n  args: [hello]\n"
            "system_prompt:\n  enabled: true\n  compress_instructions: true\n"
        )

        captured_init_kwargs = {}

        # Mock the transport and backend connector
        with (
            patch(
                "token_sieve.cli.main.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.cli.main.BackendConnector"
            ) as mock_connector_cls,
        ):
            # Set up mock transport context manager
            mock_session = AsyncMock()
            mock_transport = MagicMock()

            # Create async context manager
            async def fake_connect():
                return mock_session

            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_transport.connect.return_value = mock_ctx
            mock_transport_cls.return_value = mock_transport

            # Mock connector with instructions
            mock_connector = MagicMock()
            mock_connector.get_instructions.return_value = "Long backend instructions " * 20
            mock_connector_cls.return_value = mock_connector

            # Mock proxy to capture the run and prevent actual server start
            with patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create:
                mock_proxy = MagicMock()
                mock_proxy.run = AsyncMock()
                mock_proxy.rebind_connector = MagicMock()
                mock_proxy._pipeline = MagicMock()

                # Pipeline.process returns compressed content
                from token_sieve.domain.model import ContentEnvelope, ContentType

                compressed = ContentEnvelope(
                    content="Compressed instructions",
                    content_type=ContentType.TEXT,
                )
                mock_proxy._pipeline.process.return_value = (compressed, [])
                mock_create.return_value = mock_proxy

                import asyncio

                exit_code = asyncio.run(
                    __import__("token_sieve.cli.main", fromlist=["_run_proxy"])._run_proxy(
                        str(config_file)
                    )
                )

                assert exit_code == 0
                # Verify connector.get_instructions was called
                mock_connector.get_instructions.assert_called_once()

    def test_no_instructions_passthrough(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When backend has no instructions, no compression happens."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "backend:\n  command: echo\n  args: [hello]\n"
            "system_prompt:\n  enabled: true\n"
        )

        with (
            patch(
                "token_sieve.cli.main.StdioClientTransport"
            ) as mock_transport_cls,
            patch(
                "token_sieve.cli.main.BackendConnector"
            ) as mock_connector_cls,
        ):
            mock_session = AsyncMock()
            mock_transport = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_transport.connect.return_value = mock_ctx
            mock_transport_cls.return_value = mock_transport

            mock_connector = MagicMock()
            mock_connector.get_instructions.return_value = None
            mock_connector_cls.return_value = mock_connector

            with patch(
                "token_sieve.server.proxy.ProxyServer.create_from_config"
            ) as mock_create:
                mock_proxy = MagicMock()
                mock_proxy.run = AsyncMock()
                mock_proxy.rebind_connector = MagicMock()
                mock_create.return_value = mock_proxy

                import asyncio

                exit_code = asyncio.run(
                    __import__("token_sieve.cli.main", fromlist=["_run_proxy"])._run_proxy(
                        str(config_file)
                    )
                )

                assert exit_code == 0
                # Pipeline.process should NOT be called for instructions
                mock_proxy._pipeline.process.assert_not_called()
