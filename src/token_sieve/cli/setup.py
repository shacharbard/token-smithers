"""Interactive CLI setup to wrap/unwrap MCP servers with token-sieve compression."""

from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIGS_DIR = "~/.token-sieve/configs"


@dataclass
class McpServerEntry:
    """A single MCP server entry parsed from a config file."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    @property
    def is_wrapped(self) -> bool:
        """True if this server is already wrapped by token-sieve."""
        cmd = Path(self.command).name if self.command else ""
        return cmd in ("token-sieve", "token-smithers")


@dataclass
class McpConfigFile:
    """An MCP configuration file with its parsed server entries."""

    path: Path
    scope: str  # "project" or "global"
    servers: list[McpServerEntry] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


def _parse_servers(data: dict) -> list[McpServerEntry]:
    """Parse mcpServers dict into McpServerEntry list."""
    entries: list[McpServerEntry] = []
    mcp_servers = data.get("mcpServers", {})
    for name, cfg in mcp_servers.items():
        entries.append(
            McpServerEntry(
                name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
                env=cfg.get("env", {}),
            )
        )
    return entries


def _try_load_config(
    path: Path, scope: str, configs: list["McpConfigFile"]
) -> None:
    """Try to load an MCP config file if it exists and has servers."""
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if data.get("mcpServers"):
        configs.append(
            McpConfigFile(
                path=path,
                scope=scope,
                servers=_parse_servers(data),
                raw_data=data,
            )
        )


# Known MCP client config locations (label → relative path from root/home).
_KNOWN_PROJECT_CONFIGS: list[tuple[str, str]] = [
    ("Claude Code", ".mcp.json"),
    ("Cursor", ".cursor/mcp.json"),
    ("Windsurf", ".windsurf/mcp.json"),
    ("VS Code/Cline", ".vscode/mcp.json"),
]

_KNOWN_GLOBAL_CONFIGS: list[tuple[str, str]] = [
    ("Claude Code", ".claude.json"),
    ("Cursor", ".cursor/mcp.json"),
    ("Windsurf", ".windsurf/mcp.json"),
    ("Continue", ".continue/config.json"),
    ("Codex", ".codex/mcp.json"),
]


def _scan_dotdirs_for_mcp(
    root: Path, scope_prefix: str, known_paths: set[Path], configs: list["McpConfigFile"]
) -> None:
    """Auto-discover MCP configs in dotdirs not covered by known paths.

    Scans {root}/.*/mcp.json and {root}/.*/mcp*.json for any JSON file
    containing an "mcpServers" key. This catches new/unknown MCP clients
    that follow the standard convention.
    """
    if not root.is_dir():
        return
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith(".") or not entry.is_dir():
            continue
        # Skip common non-MCP dotdirs to avoid slow scanning
        if entry.name in {".git", ".venv", ".env", ".cache", ".npm", ".cargo",
                          ".local", ".ssh", ".gnupg", ".Trash", ".DS_Store",
                          ".token-sieve", ".vbw-planning", ".planning", ".muninn"}:
            continue
        try:
            candidates = sorted(entry.iterdir())
        except OSError:
            continue
        for f in candidates:
            if not f.is_file():
                continue
            if not (f.name == "mcp.json" or ("mcp" in f.name and f.suffix == ".json")):
                continue
            resolved = f.resolve()
            if resolved in known_paths:
                continue
            # Derive a label from the dotdir name
            label = entry.name.lstrip(".")
            _try_load_config(f, f"{scope_prefix} ({label})", configs)
            if configs and configs[-1].path == f:
                known_paths.add(resolved)


def discover_mcp_configs(
    project_dir: Path | None = None,
) -> list[McpConfigFile]:
    """Find MCP config files across all MCP clients.

    Two-pass discovery:
    1. Check known paths for major clients (Claude Code, Cursor, Windsurf, etc.)
    2. Auto-scan dotdirs for any unknown MCP client that uses *mcp*.json

    Args:
        project_dir: Directory to search for project-level configs. Defaults to cwd.

    Returns:
        List of discovered config files with parsed server entries.
    """
    configs: list[McpConfigFile] = []
    proj_root = project_dir or Path.cwd()
    home = Path.home()

    # Track resolved paths to avoid duplicates between known + scan
    known_paths: set[Path] = set()

    # -- Pass 1: Known project-level configs --
    for label, rel_path in _KNOWN_PROJECT_CONFIGS:
        p = proj_root / rel_path
        _try_load_config(p, f"project ({label})", configs)
        if p.exists():
            known_paths.add(p.resolve())

    # -- Pass 1: Known global configs --
    for label, rel_path in _KNOWN_GLOBAL_CONFIGS:
        p = home / rel_path
        _try_load_config(p, f"global ({label})", configs)
        if p.exists():
            known_paths.add(p.resolve())

    # -- Pass 2: Auto-scan for unknown MCP clients --
    _scan_dotdirs_for_mcp(proj_root, "project", known_paths, configs)
    _scan_dotdirs_for_mcp(home, "global", known_paths, configs)

    return configs


def generate_sieve_config(server: McpServerEntry) -> str:
    """Generate YAML config content for a token-sieve wrapper.

    Args:
        server: The original server entry to wrap.

    Returns:
        YAML string with backend config referencing the original server.
    """
    args_str = " ".join(server.args)
    header = (
        f"# Auto-generated by token-sieve setup\n"
        f"# Original: {server.command} {args_str}\n"
    )

    backend: dict = {
        "command": server.command,
        "args": server.args,
    }
    if server.env:
        backend["env"] = server.env

    config: dict = {
        "backend": backend,
        "schema_virtualization": {"enabled": True},
    }
    return header + yaml.dump(config, default_flow_style=False)


def wrap_servers(
    config_file: McpConfigFile,
    server_names: list[str],
    configs_dir: str,
) -> list[str]:
    """Wrap selected servers with token-sieve in the config.

    Creates YAML config files in configs_dir and modifies raw_data in-place.
    Does NOT write the config file to disk.

    Args:
        config_file: The MCP config file to modify.
        server_names: Names of servers to wrap.
        configs_dir: Directory to write per-server YAML configs.

    Returns:
        List of server names that were wrapped.
    """
    configs_path = Path(configs_dir)
    configs_path.mkdir(parents=True, exist_ok=True)

    wrapped: list[str] = []
    server_map = {s.name: s for s in config_file.servers}

    # Resolve full path to token-smithers binary (avoids pyenv/venv shim issues)
    import shutil

    ts_bin = shutil.which("token-smithers") or "token-smithers"

    for name in server_names:
        server = server_map.get(name)
        if server is None or server.is_wrapped:
            continue

        # Write YAML config
        yaml_path = configs_path / f"{name}.yaml"
        yaml_path.write_text(generate_sieve_config(server))

        # Update raw_data — use full binary path for cross-project compatibility
        yaml_abs = str(yaml_path.resolve())
        config_file.raw_data["mcpServers"][name] = {
            "command": ts_bin,
            "args": ["--config", yaml_abs],
        }

        # Update server entry
        server.command = ts_bin
        server.args = ["--config", yaml_abs]

        wrapped.append(name)

    return wrapped


def unwrap_servers(
    config_file: McpConfigFile,
    configs_dir: str,
) -> list[str]:
    """Unwrap token-sieve wrapped servers back to their originals.

    Reads YAML configs to restore original command/args/env.

    Args:
        config_file: The MCP config file to modify.
        configs_dir: Directory where per-server YAML configs are stored.

    Returns:
        List of server names that were unwrapped.
    """
    unwrapped: list[str] = []

    for server in config_file.servers:
        if not server.is_wrapped:
            continue

        # Find the --config path from args
        config_path = None
        for i, arg in enumerate(server.args):
            if arg == "--config" and i + 1 < len(server.args):
                config_path = Path(server.args[i + 1])
                break

        if config_path is None or not config_path.exists():
            continue

        # Read original backend from YAML
        data = yaml.safe_load(config_path.read_text())
        backend = data.get("backend", {})

        original_cmd = backend.get("command", "")
        original_args = backend.get("args", [])
        original_env = backend.get("env", {})

        # Restore raw_data
        restored: dict = {
            "command": original_cmd,
            "args": original_args,
        }
        if original_env:
            restored["env"] = original_env
        config_file.raw_data["mcpServers"][server.name] = restored

        # Update server entry
        server.command = original_cmd
        server.args = original_args
        server.env = original_env

        unwrapped.append(server.name)

    return unwrapped


def backup_config(path: Path) -> Path:
    """Create a backup of the config file.

    Args:
        path: Path to the config file.

    Returns:
        Path to the backup file.
    """
    backup_path = path.with_suffix(path.suffix + ".backup")
    # H3: preserve oldest backup -- only write if no backup exists yet
    if not backup_path.exists():
        shutil.copy2(path, backup_path)
    return backup_path


def write_config(config_file: McpConfigFile) -> None:
    """Write the modified config back to disk.

    H1 fix: uses atomic write (write to .tmp, then os.rename) so a crash
    mid-write cannot leave a truncated config file.

    Preserves all non-mcpServers keys from raw_data.

    Args:
        config_file: The config file with updated raw_data.
    """
    import os

    tmp_path = config_file.path.with_suffix(config_file.path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(config_file.raw_data, indent=2) + "\n")
    os.rename(str(tmp_path), str(config_file.path))


# --- Hook installation ---

# Token-sieve PreToolUse hook entries to install in settings.json.
_HOOK_MARKER = "token-sieve"

_HOOK_ENTRIES: list[dict] = [
    {
        "matcher": "Grep",
        "hooks": [
            {
                "type": "command",
                "command": f"echo 'token-sieve: consider jCodeMunch search_symbols for code definitions'",
            }
        ],
    },
    {
        "matcher": "Glob",
        "hooks": [
            {
                "type": "command",
                "command": f"echo 'token-sieve: consider jCodeMunch get_file_tree for broad patterns'",
            }
        ],
    },
    {
        "matcher": "Read",
        "hooks": [
            {
                "type": "command",
                "command": f"echo 'token-sieve: consider jCodeMunch get_symbol for targeted code reads'",
            }
        ],
    },
    {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": f"echo 'token-sieve: consider ctx_execute for large output commands'",
            }
        ],
    },
]


def install_hooks(
    settings_path: Path, undo: bool = False
) -> list[str]:
    """Install or remove token-sieve PreToolUse hook entries in settings.json.

    Args:
        settings_path: Path to Claude Code settings.json.
        undo: If True, remove token-sieve entries instead of adding.

    Returns:
        List of installed (or removed) hook matcher names.
    """
    import os

    # Read existing settings
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}

    if "hooks" not in data:
        data["hooks"] = {}
    if "PreToolUse" not in data["hooks"]:
        data["hooks"]["PreToolUse"] = []

    existing: list[dict] = data["hooks"]["PreToolUse"]

    if undo:
        # Remove token-sieve entries
        removed = []
        filtered = []
        for entry in existing:
            is_ts = any(
                _HOOK_MARKER in str(h.get("command", ""))
                for h in entry.get("hooks", [])
            )
            if is_ts:
                removed.append(entry.get("matcher", "unknown"))
            else:
                filtered.append(entry)
        data["hooks"]["PreToolUse"] = filtered
        _atomic_write(settings_path, data)
        return removed

    # Install: add entries that don't already exist
    installed = []
    for hook_entry in _HOOK_ENTRIES:
        # Check if already present (by matcher + token-sieve marker)
        already = any(
            e.get("matcher") == hook_entry["matcher"]
            and any(
                _HOOK_MARKER in str(h.get("command", ""))
                for h in e.get("hooks", [])
            )
            for e in existing
        )
        if not already:
            existing.append(hook_entry)
            installed.append(hook_entry["matcher"])

    _atomic_write(settings_path, data)
    return installed


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON data atomically using tmp+rename pattern."""
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2) + "\n")
    os.rename(str(tmp_path), str(path))


def run_setup(undo: bool = False, install_hooks_flag: bool = False) -> int:
    """Interactive setup runner.

    Args:
        undo: If True, unwrap all token-sieve wrapped servers.
        install_hooks_flag: If True, install PreToolUse hooks.

    Returns:
        0 on success, 1 on error.
    """
    import os

    if install_hooks_flag:
        settings_path_str = os.environ.get(
            "TOKEN_SIEVE_SETTINGS_PATH",
            os.path.expanduser("~/.claude/settings.json"),
        )
        settings_path = Path(settings_path_str)
        installed = install_hooks(settings_path)
        if installed:
            print(f"Installed {len(installed)} hook(s): {', '.join(installed)}")
        else:
            print("All hooks already installed.")
        return 0

    configs = discover_mcp_configs()
    if not configs:
        print(
            "No MCP config files found (.mcp.json or ~/.claude.json).",
            file=sys.stderr,
        )
        return 1

    configs_dir = str(Path(CONFIGS_DIR).expanduser())

    if undo:
        return _run_undo(configs, configs_dir)
    return _run_wrap(configs, configs_dir)


def _run_undo(configs: list[McpConfigFile], configs_dir: str) -> int:
    """Unwrap all wrapped servers."""
    total_unwrapped: list[str] = []

    for cf in configs:
        unwrapped = unwrap_servers(cf, configs_dir)
        if unwrapped:
            backup_config(cf.path)
            write_config(cf)
            total_unwrapped.extend(unwrapped)

    if not total_unwrapped:
        print("No wrapped servers found to undo.")
        return 0

    print(f"Unwrapped {len(total_unwrapped)} server(s): {', '.join(total_unwrapped)}")
    print()
    print('  "Smithers, you\'re fired." — Token compression disabled.')
    print("  Your MCP servers are back to their original configuration.")
    return 0


def _run_wrap(configs: list[McpConfigFile], configs_dir: str) -> int:
    """Interactive server wrapping."""
    # Collect all unwrapped servers
    available: list[tuple[McpConfigFile, McpServerEntry]] = []
    already_wrapped: list[str] = []

    for cf in configs:
        for srv in cf.servers:
            if srv.is_wrapped:
                already_wrapped.append(srv.name)
            else:
                available.append((cf, srv))

    if not available:
        if already_wrapped:
            print(
                f"All servers already wrapped: {', '.join(already_wrapped)}"
            )
        else:
            print("No servers found in config files.")
        return 0

    # Guidance
    print("Available MCP servers:\n")
    print("  TIPS:")
    print("  - Wrap servers that return raw/verbose data (filesystem, APIs, databases)")
    print("  - Skip servers that already optimize their output (e.g., jCodeMunch, jDocMunch, context-mode)")
    print("  - If a server appears at both global and project level, wrap the global one")
    print("    (global = compressed everywhere, project = only that project)")
    print("  - Duplicate servers across configs only need wrapping once at the highest level")
    print()

    for i, (cf, srv) in enumerate(available, 1):
        print(f"  {i}. [{cf.scope}] {srv.name} ({srv.command} {' '.join(srv.args)})")

    if already_wrapped:
        print(f"\n  Already wrapped: {', '.join(already_wrapped)}")

    print("\nEnter server numbers (comma-separated) or 'all': ", end="")
    sys.stdout.flush()
    user_input = input().strip()

    if not user_input:
        print("No servers selected.")
        return 0

    # Parse selection
    if user_input.lower() == "all":
        selected = list(range(len(available)))
    else:
        try:
            selected = [int(x.strip()) - 1 for x in user_input.split(",")]
            for idx in selected:
                if idx < 0 or idx >= len(available):
                    print(f"Invalid selection: {idx + 1}", file=sys.stderr)
                    return 1
        except ValueError:
            print("Invalid input. Enter numbers or 'all'.", file=sys.stderr)
            return 1

    # Group by config file
    by_config: dict[Path, tuple[McpConfigFile, list[str]]] = {}
    for idx in selected:
        cf, srv = available[idx]
        if cf.path not in by_config:
            by_config[cf.path] = (cf, [])
        by_config[cf.path][1].append(srv.name)

    # Wrap servers
    total_wrapped: list[str] = []
    for cf, names in by_config.values():
        backup_config(cf.path)
        wrapped = wrap_servers(cf, names, configs_dir)
        write_config(cf)
        total_wrapped.extend(wrapped)

    print(f"\nWrapped {len(total_wrapped)} server(s): {', '.join(total_wrapped)}")
    print(f"Configs written to: {configs_dir}")
    print()
    print('  "Release the hounds!" — Token compression is now active.')
    print("  Use Claude Code normally. Check savings with: token-smithers stats")
    return 0
