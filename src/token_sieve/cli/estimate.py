"""Estimate token savings for installed MCP servers.

Scans discovered MCP configs, matches them against known server profiles,
and displays a table showing expected compression savings.
"""

from __future__ import annotations

from dataclasses import dataclass

from token_sieve.cli.setup import McpConfigFile, discover_mcp_configs

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServerProfile:
    """Compression profile for a known MCP server type."""

    name: str
    tools: int
    schema_saved_pct: int
    result_saved_pct: int
    category: str


# ---------------------------------------------------------------------------
# Known server profiles (measured benchmarks)
# ---------------------------------------------------------------------------

KNOWN_PROFILES: dict[str, ServerProfile] = {
    "context7": ServerProfile(
        name="context7", tools=2, schema_saved_pct=64, result_saved_pct=5, category="docs"
    ),
    "exa": ServerProfile(
        name="EXA", tools=3, schema_saved_pct=25, result_saved_pct=42, category="search"
    ),
    "github": ServerProfile(
        name="GitHub", tools=10, schema_saved_pct=33, result_saved_pct=25, category="api"
    ),
    "filesystem": ServerProfile(
        name="Filesystem", tools=8, schema_saved_pct=41, result_saved_pct=41, category="filesystem"
    ),
    "server-filesystem": ServerProfile(
        name="Filesystem", tools=8, schema_saved_pct=41, result_saved_pct=41, category="filesystem"
    ),
    "muninn": ServerProfile(
        name="Muninn", tools=10, schema_saved_pct=38, result_saved_pct=52, category="memory"
    ),
    "sqlite": ServerProfile(
        name="SQLite", tools=5, schema_saved_pct=35, result_saved_pct=45, category="database"
    ),
    "postgres": ServerProfile(
        name="PostgreSQL", tools=5, schema_saved_pct=35, result_saved_pct=45, category="database"
    ),
    "slack": ServerProfile(
        name="Slack", tools=8, schema_saved_pct=30, result_saved_pct=35, category="api"
    ),
    "linear": ServerProfile(
        name="Linear", tools=10, schema_saved_pct=30, result_saved_pct=40, category="api"
    ),
    "notion": ServerProfile(
        name="Notion", tools=8, schema_saved_pct=30, result_saved_pct=35, category="api"
    ),
    "playwright": ServerProfile(
        name="Playwright", tools=15, schema_saved_pct=35, result_saved_pct=20, category="browser"
    ),
    "puppeteer": ServerProfile(
        name="Puppeteer", tools=12, schema_saved_pct=35, result_saved_pct=20, category="browser"
    ),
    "memory": ServerProfile(
        name="Memory", tools=3, schema_saved_pct=40, result_saved_pct=30, category="memory"
    ),
    "brave": ServerProfile(
        name="Brave Search", tools=2, schema_saved_pct=30, result_saved_pct=40, category="search"
    ),
    "fetch": ServerProfile(
        name="Fetch", tools=2, schema_saved_pct=35, result_saved_pct=30, category="web"
    ),
}

# Already-optimized servers that should be skipped
SKIP_PATTERNS = {"jcodemunch", "jdocmunch", "context-mode"}

# Default profile for unknown servers
DEFAULT_PROFILE = ServerProfile(
    name="Unknown", tools=5, schema_saved_pct=30, result_saved_pct=30, category="unknown"
)

# Average tokens per tool schema description
_AVG_SCHEMA_TOKENS = 150
# Average tokens per tool call result
_AVG_RESULT_TOKENS = 800


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def match_profile(server_name: str, command: str) -> ServerProfile | None:
    """Match a server to a known profile by name or command substring.

    Returns None if the server matches SKIP_PATTERNS (already optimized)
    or if no known profile matches.
    """
    name_lower = server_name.lower()
    cmd_lower = command.lower()

    # Check skip patterns first
    for skip in SKIP_PATTERNS:
        if skip in name_lower or skip in cmd_lower:
            return None

    # Check known profiles
    for key, profile in KNOWN_PROFILES.items():
        if key in name_lower or key in cmd_lower:
            return profile

    return None


def estimate_session_savings(
    profiles: list[ServerProfile],
    calls_per_session: int = 10,
    refreshes: int = 5,
) -> dict:
    """Calculate estimated token savings per session.

    Args:
        profiles: Matched server profiles to include in estimate.
        calls_per_session: Average tool calls per session per server.
        refreshes: Number of times tool schemas are refreshed per session.

    Returns:
        Dict with schema_tokens_saved, result_tokens_saved, total_tokens_saved,
        server_count, and refreshes.
    """
    total_schema_saved = 0
    total_result_saved = 0

    for p in profiles:
        # Schema savings: tools * avg_schema_tokens * saved_pct * refreshes
        schema_saved = int(p.tools * _AVG_SCHEMA_TOKENS * (p.schema_saved_pct / 100) * refreshes)
        total_schema_saved += schema_saved

        # Result savings: calls * avg_result_tokens * saved_pct
        result_saved = int(calls_per_session * _AVG_RESULT_TOKENS * (p.result_saved_pct / 100))
        total_result_saved += result_saved

    return {
        "schema_tokens_saved": total_schema_saved,
        "result_tokens_saved": total_result_saved,
        "total_tokens_saved": total_schema_saved + total_result_saved,
        "server_count": len(profiles),
        "refreshes": refreshes,
    }


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

# ANSI color codes
_GREEN = "\033[32m"
_DIM = "\033[2m"
_YELLOW = "\033[33m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _format_number(n: int) -> str:
    """Format number with comma separators: 12345 -> 12,345."""
    return f"{n:,}"


def _print_table(
    rows: list[dict],
    wrappable_profiles: list[ServerProfile],
) -> None:
    """Print the savings estimate table to stdout."""
    print(f"\n{_BOLD}Token Smithers \u2014 Savings Estimate{_RESET}\n")
    print("Scanning your MCP servers...\n")

    # Header
    header = (
        f"  {'Server':<15} {'Config':<20} {'Match':<12} "
        f"{'Schema':>6}  {'Results':>7}  {'Wrap?':>5}"
    )
    print(header)
    print(
        f"  {'\u2500' * 13}  {'\u2500' * 18}  {'\u2500' * 11}  "
        f"{'\u2500' * 6}  {'\u2500' * 7}  {'\u2500' * 5}"
    )

    for row in rows:
        if row["skip"]:
            # Optimized / skip row
            print(
                f"  {_DIM}{row['name']:<15} {row['scope']:<20} "
                f"{'(optimized)':<12} {'--':>6}  {'--':>7}  "
                f"{'Skip':>5}{_RESET}"
            )
        elif row["profile"] is not None:
            p = row["profile"]
            print(
                f"  {row['name']:<15} {row['scope']:<20} "
                f"{p.name:<12} {p.schema_saved_pct:>5}%  "
                f"~{p.result_saved_pct:>5}%  "
                f"{_GREEN}{'Yes':>5}{_RESET}"
            )
        else:
            # Unknown
            print(
                f"  {row['name']:<15} {row['scope']:<20} "
                f"{'Unknown':<12} {_YELLOW}{'~30%':>6}{_RESET}  "
                f"{_YELLOW}{'~30%':>7}{_RESET}  "
                f"{_YELLOW}{'Maybe':>5}{_RESET}"
            )

    # Summary
    if wrappable_profiles:
        savings = estimate_session_savings(wrappable_profiles)
        print(f"\n  Estimated per-session savings:")
        print(
            f"    Schema compression: ~{_format_number(savings['schema_tokens_saved'])} "
            f"tokens (from {savings['refreshes']} tool refreshes)"
        )
        print(
            f"    Result compression: ~{_format_number(savings['result_tokens_saved'])} "
            f"tokens (from ~10 tool calls)"
        )
        print(
            f"    {_BOLD}Total: ~{_format_number(savings['total_tokens_saved'])} "
            f"tokens per session{_RESET}"
        )

        # Optional cost estimation via tokencost
        try:
            from token_sieve.cli.cost_utils import estimate_session_cost, format_cost, get_model

            model = get_model()
            cost = estimate_session_cost(
                tokens_saved=savings["total_tokens_saved"],
                model=model,
            )
            if cost is not None:
                print(
                    f"    {_GREEN}$/day saved: "
                    f"~{format_cost(cost['cost_per_day_saved'])} "
                    f"({model}){_RESET}"
                )
        except Exception:
            pass

    print(
        f"\n  {_DIM}\"Excellent... Run 'token-smithers setup' to start saving.\"{_RESET}\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_estimate() -> int:
    """Scan installed MCP servers and display estimated token savings.

    Returns 0 on success.
    """
    configs: list[McpConfigFile] = discover_mcp_configs()

    # Flatten all servers across config files
    all_servers: list[tuple[str, str, str]] = []  # (name, scope, command)
    for cfg in configs:
        for srv in cfg.servers:
            all_servers.append((srv.name, cfg.scope, srv.command))

    if not all_servers:
        print(
            "\nNo MCP servers found. Install some MCP servers and try again.\n"
        )
        return 0

    rows: list[dict] = []
    wrappable: list[ServerProfile] = []

    for name, scope, command in all_servers:
        name_lower = name.lower()
        cmd_lower = command.lower()

        # Check if already optimized
        is_skip = any(
            skip in name_lower or skip in cmd_lower for skip in SKIP_PATTERNS
        )

        if is_skip:
            rows.append({"name": name, "scope": scope, "profile": None, "skip": True})
            continue

        profile = match_profile(server_name=name, command=command)
        rows.append({"name": name, "scope": scope, "profile": profile, "skip": False})

        if profile is not None:
            wrappable.append(profile)
        else:
            # Unknown servers get the default profile for estimation
            wrappable.append(DEFAULT_PROFILE)

    _print_table(rows, wrappable)
    return 0
