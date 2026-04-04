"""Tests for token-sieve setup CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from token_sieve.cli.setup import (
    McpConfigFile,
    McpServerEntry,
    backup_config,
    discover_mcp_configs,
    generate_sieve_config,
    run_setup,
    unwrap_servers,
    wrap_servers,
    write_config,
)


class TestMcpServerEntry:
    """McpServerEntry data class behavior."""

    def test_server_entry_is_wrapped_when_token_sieve(self) -> None:
        entry = McpServerEntry(
            name="foo",
            command="token-sieve",
            args=["--config", "foo.yaml"],
            env={},
        )
        assert entry.is_wrapped is True

    def test_server_entry_not_wrapped_for_other_command(self) -> None:
        entry = McpServerEntry(
            name="foo",
            command="npx",
            args=["-y", "some-server"],
            env={},
        )
        assert entry.is_wrapped is False


class TestDiscoverMcpConfigs:
    """discover_mcp_configs finds project and global config files."""

    def test_discover_finds_project_mcp_json(self, tmp_path: Path) -> None:
        mcp_json = tmp_path / ".mcp.json"
        data = {
            "mcpServers": {
                "server-a": {
                    "command": "npx",
                    "args": ["-y", "server-a"],
                }
            }
        }
        mcp_json.write_text(json.dumps(data))

        # Mock home to avoid picking up real ~/.claude.json
        with patch("token_sieve.cli.setup.Path.home", return_value=tmp_path / "fakehome"):
            results = discover_mcp_configs(project_dir=tmp_path)

        assert len(results) == 1
        assert "project" in results[0].scope
        assert len(results[0].servers) == 1
        assert results[0].servers[0].name == "server-a"
        assert results[0].servers[0].command == "npx"
        assert results[0].servers[0].args == ["-y", "server-a"]

    def test_discover_finds_global_claude_json(self, tmp_path: Path) -> None:
        claude_json = tmp_path / ".claude.json"
        data = {
            "mcpServers": {
                "global-srv": {
                    "command": "node",
                    "args": ["server.js"],
                    "env": {"KEY": "val"},
                }
            }
        }
        claude_json.write_text(json.dumps(data))

        with patch("token_sieve.cli.setup.Path.home", return_value=tmp_path):
            results = discover_mcp_configs(project_dir=tmp_path / "nonexistent")

        assert len(results) == 1
        assert "global" in results[0].scope
        assert results[0].servers[0].env == {"KEY": "val"}

    def test_discover_no_configs(self, tmp_path: Path) -> None:
        with patch("token_sieve.cli.setup.Path.home", return_value=tmp_path):
            results = discover_mcp_configs(project_dir=tmp_path)

        assert results == []

    def test_discover_unknown_client_via_auto_scan(self, tmp_path: Path) -> None:
        """Auto-scan finds MCP configs in unknown dotdirs."""
        unknown_dir = tmp_path / ".warp"
        unknown_dir.mkdir()
        mcp_json = unknown_dir / "mcp.json"
        data = {
            "mcpServers": {
                "warp-srv": {"command": "warp-mcp", "args": ["--start"]}
            }
        }
        mcp_json.write_text(json.dumps(data))

        with patch("token_sieve.cli.setup.Path.home", return_value=tmp_path / "fakehome"):
            results = discover_mcp_configs(project_dir=tmp_path)

        assert len(results) == 1
        assert "warp" in results[0].scope
        assert results[0].servers[0].name == "warp-srv"
        assert results[0].servers[0].command == "warp-mcp"


class TestGenerateSieveConfig:
    """generate_sieve_config produces valid YAML config content."""

    def test_generate_sieve_config_basic(self) -> None:
        entry = McpServerEntry(
            name="my-server",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            env={},
        )
        content = generate_sieve_config(entry)
        parsed = yaml.safe_load(content)

        assert parsed["backend"]["command"] == "npx"
        assert parsed["backend"]["args"] == [
            "-y",
            "@modelcontextprotocol/server-filesystem",
        ]
        assert "env" not in parsed["backend"]

    def test_generate_sieve_config_with_env(self) -> None:
        entry = McpServerEntry(
            name="my-server",
            command="node",
            args=["server.js"],
            env={"API_KEY": "secret", "DEBUG": "1"},
        )
        content = generate_sieve_config(entry)
        parsed = yaml.safe_load(content)

        assert parsed["backend"]["env"] == {"API_KEY": "secret", "DEBUG": "1"}

    def test_generate_sieve_config_has_comment_header(self) -> None:
        entry = McpServerEntry(
            name="srv", command="cmd", args=["a"], env={}
        )
        content = generate_sieve_config(entry)
        assert "Auto-generated by token-sieve setup" in content
        assert "Original: cmd a" in content

    def test_generate_sieve_config_includes_schema_virtualization(self) -> None:
        """Generated config enables schema virtualization explicitly."""
        entry = McpServerEntry(
            name="my-server", command="npx", args=["serve"], env={}
        )
        content = generate_sieve_config(entry)
        parsed = yaml.safe_load(content)

        assert "schema_virtualization" in parsed
        assert parsed["schema_virtualization"]["enabled"] is True

    def test_generate_sieve_config_no_hardcoded_compression(self) -> None:
        """Generated config should not hardcode compression settings (inherits schema defaults)."""
        entry = McpServerEntry(
            name="my-server", command="npx", args=["serve"], env={}
        )
        content = generate_sieve_config(entry)
        parsed = yaml.safe_load(content)

        # compression section should not be present — let schema defaults apply
        assert "compression" not in parsed


class TestWrapServers:
    """wrap_servers modifies config entries and writes YAML files."""

    def test_wrap_servers_updates_entries(self, tmp_path: Path) -> None:
        servers = [
            McpServerEntry("a", "npx", ["-y", "srv-a"], {}),
            McpServerEntry("b", "node", ["b.js"], {"K": "V"}),
            McpServerEntry("c", "python", ["-m", "srv_c"], {}),
        ]
        raw = {
            "mcpServers": {
                "a": {"command": "npx", "args": ["-y", "srv-a"]},
                "b": {"command": "node", "args": ["b.js"], "env": {"K": "V"}},
                "c": {"command": "python", "args": ["-m", "srv_c"]},
            }
        }
        cf = McpConfigFile(
            path=tmp_path / ".mcp.json",
            scope="project",
            servers=servers,
            raw_data=raw,
        )
        configs_dir = str(tmp_path / "configs")

        wrapped = wrap_servers(cf, ["a", "c"], configs_dir)

        assert set(wrapped) == {"a", "c"}
        # Verify JSON structure updated
        # Command should be a full path or "token-smithers"
        assert Path(raw["mcpServers"]["a"]["command"]).name == "token-smithers"
        assert raw["mcpServers"]["a"]["args"] == [
            "--config",
            str(tmp_path / "configs" / "a.yaml"),
        ]
        # b should be unchanged
        assert raw["mcpServers"]["b"]["command"] == "node"

    def test_wrap_creates_yaml_files(self, tmp_path: Path) -> None:
        servers = [McpServerEntry("srv", "npx", ["-y", "pkg"], {})]
        raw = {
            "mcpServers": {
                "srv": {"command": "npx", "args": ["-y", "pkg"]},
            }
        }
        cf = McpConfigFile(
            path=tmp_path / ".mcp.json",
            scope="project",
            servers=servers,
            raw_data=raw,
        )
        configs_dir = str(tmp_path / "configs")

        wrap_servers(cf, ["srv"], configs_dir)

        yaml_path = tmp_path / "configs" / "srv.yaml"
        assert yaml_path.exists()
        parsed = yaml.safe_load(yaml_path.read_text())
        assert parsed["backend"]["command"] == "npx"
        assert parsed["backend"]["args"] == ["-y", "pkg"]


class TestUnwrapServers:
    """unwrap_servers restores original command/args from YAML configs."""

    def test_unwrap_servers_restores_originals(self, tmp_path: Path) -> None:
        # Set up a YAML config that wrap_servers would have created
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        yaml_content = yaml.dump(
            {"backend": {"command": "npx", "args": ["-y", "srv-a"]}}
        )
        (configs_dir / "a.yaml").write_text(yaml_content)

        yaml_path = str(configs_dir / "a.yaml")
        servers = [
            McpServerEntry("a", "token-sieve", ["--config", yaml_path], {}),
            McpServerEntry("b", "node", ["b.js"], {}),
        ]
        raw = {
            "mcpServers": {
                "a": {
                    "command": "token-sieve",
                    "args": ["--config", yaml_path],
                },
                "b": {"command": "node", "args": ["b.js"]},
            }
        }
        cf = McpConfigFile(
            path=tmp_path / ".mcp.json",
            scope="project",
            servers=servers,
            raw_data=raw,
        )

        unwrapped = unwrap_servers(cf, str(configs_dir))

        assert unwrapped == ["a"]
        assert raw["mcpServers"]["a"]["command"] == "npx"
        assert raw["mcpServers"]["a"]["args"] == ["-y", "srv-a"]

    def test_unwrap_skips_non_wrapped(self, tmp_path: Path) -> None:
        servers = [McpServerEntry("b", "node", ["b.js"], {})]
        raw = {
            "mcpServers": {
                "b": {"command": "node", "args": ["b.js"]},
            }
        }
        cf = McpConfigFile(
            path=tmp_path / ".mcp.json",
            scope="project",
            servers=servers,
            raw_data=raw,
        )

        unwrapped = unwrap_servers(cf, str(tmp_path / "configs"))

        assert unwrapped == []
        assert raw["mcpServers"]["b"]["command"] == "node"


class TestBackupConfig:
    """backup_config creates .backup copy."""

    def test_backup_config_creates_backup(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".mcp.json"
        config_path.write_text('{"mcpServers": {}}')

        backup_path = backup_config(config_path)

        assert backup_path == tmp_path / ".mcp.json.backup"
        assert backup_path.read_text() == '{"mcpServers": {}}'


class TestWriteConfig:
    """write_config writes JSON preserving non-mcpServers keys."""

    def test_write_config_preserves_other_keys(self, tmp_path: Path) -> None:
        config_path = tmp_path / ".mcp.json"
        raw = {
            "someOtherKey": "preserve-me",
            "mcpServers": {
                "a": {"command": "npx", "args": ["-y", "srv"]},
            },
        }
        cf = McpConfigFile(
            path=config_path,
            scope="project",
            servers=[McpServerEntry("a", "npx", ["-y", "srv"], {})],
            raw_data=raw,
        )

        write_config(cf)

        written = json.loads(config_path.read_text())
        assert written["someOtherKey"] == "preserve-me"
        assert "mcpServers" in written


class TestMainRouting:
    """main() routes setup subcommand correctly."""

    def test_main_routes_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from token_sieve.cli import main as main_mod

        called_with: dict = {}

        def fake_run_setup(undo: bool = False, install_hooks_flag: bool = False) -> int:
            called_with["undo"] = undo
            return 0

        monkeypatch.setattr(
            "token_sieve.cli.setup.run_setup", fake_run_setup
        )

        from token_sieve.cli.main import main

        result = main(["setup"])
        assert result == 0
        assert called_with["undo"] is False

    def test_main_routes_setup_undo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called_with: dict = {}

        def fake_run_setup(undo: bool = False, install_hooks_flag: bool = False) -> int:
            called_with["undo"] = undo
            return 0

        monkeypatch.setattr(
            "token_sieve.cli.setup.run_setup", fake_run_setup
        )

        from token_sieve.cli.main import main

        result = main(["setup", "--undo"])
        assert result == 0
        assert called_with["undo"] is True


class TestRunSetup:
    """run_setup interactive flow."""

    def test_run_setup_no_configs_returns_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with (
            patch(
                "token_sieve.cli.setup.discover_mcp_configs", return_value=[]
            ),
        ):
            result = run_setup(undo=False)

        assert result == 1
        captured = capsys.readouterr()
        assert "No MCP config" in captured.err

    def test_run_setup_undo_unwraps_all(self, tmp_path: Path) -> None:
        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        yaml_content = yaml.dump(
            {"backend": {"command": "npx", "args": ["-y", "srv"]}}
        )
        (configs_dir / "a.yaml").write_text(yaml_content)

        yaml_path = str(configs_dir / "a.yaml")
        raw = {
            "mcpServers": {
                "a": {
                    "command": "token-sieve",
                    "args": ["--config", yaml_path],
                },
            }
        }
        config_path = tmp_path / ".mcp.json"
        config_path.write_text(json.dumps(raw))
        cf = McpConfigFile(
            path=config_path,
            scope="project",
            servers=[
                McpServerEntry(
                    "a", "token-sieve", ["--config", yaml_path], {}
                )
            ],
            raw_data=raw,
        )

        with (
            patch(
                "token_sieve.cli.setup.discover_mcp_configs",
                return_value=[cf],
            ),
            patch(
                "token_sieve.cli.setup.CONFIGS_DIR", str(configs_dir)
            ),
        ):
            result = run_setup(undo=True)

        assert result == 0
        written = json.loads(config_path.read_text())
        assert written["mcpServers"]["a"]["command"] == "npx"
