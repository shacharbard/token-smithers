"""Zero-dependency enforcement: domain/ must have no external imports.

These tests verify the domain core is pure Python with stdlib-only dependencies.
If any test fails, an accidental third-party dependency leaked into domain/.
"""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys


class TestDomainZeroDependencies:
    """Verify domain/ has no external (third-party) dependencies."""

    def test_domain_has_no_external_dependencies(self):
        """Import domain in a subprocess with stripped sys.path (only stdlib + src/).

        If domain accidentally imports a third-party package, the subprocess
        will raise ImportError and this test fails.
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys;"
                    "sys.path = [p for p in sys.path if 'site-packages' not in p];"
                    "sys.path.insert(0, 'src');"
                    "import token_sieve.domain;"
                    "import token_sieve.domain.model;"
                    "import token_sieve.domain.ports;"
                    "print('OK')"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, (
            f"Domain import failed without site-packages:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        assert "OK" in result.stdout

    def test_domain_modules_import_only_stdlib(self):
        """Walk all domain module imports and assert none are third-party.

        Uses sys.stdlib_module_names (Python 3.10+) to classify imports.
        """
        stdlib_names = sys.stdlib_module_names

        # Import domain modules
        import token_sieve.domain.model as model_mod
        import token_sieve.domain.ports as ports_mod

        # Collect all imports from domain modules
        domain_modules = [model_mod, ports_mod]

        # Also try pipeline if it exists
        try:
            import token_sieve.domain.pipeline as pipeline_mod
            domain_modules.append(pipeline_mod)
        except ImportError:
            pass

        # Also try counters, session, metrics if they exist
        for mod_name in ("counters", "session", "metrics"):
            try:
                mod = importlib.import_module(f"token_sieve.domain.{mod_name}")
                domain_modules.append(mod)
            except ImportError:
                pass

        for mod in domain_modules:
            # Get all names that look like module-level imports
            source_file = getattr(mod, "__file__", None)
            if source_file is None:
                continue

            with open(source_file) as f:
                source = f.read()

            # Parse import statements from source
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    # Extract the top-level module name
                    if stripped.startswith("from "):
                        parts = stripped.split()
                        if len(parts) >= 2:
                            top_module = parts[1].split(".")[0]
                    else:
                        parts = stripped.split()
                        if len(parts) >= 2:
                            top_module = parts[1].split(".")[0]
                        else:
                            continue

                    # Skip relative imports and self-imports
                    if top_module.startswith(".") or top_module == "token_sieve":
                        continue
                    # Skip __future__
                    if top_module == "__future__":
                        continue

                    assert top_module in stdlib_names, (
                        f"Module {mod.__name__} imports '{top_module}' "
                        f"which is not in stdlib"
                    )
