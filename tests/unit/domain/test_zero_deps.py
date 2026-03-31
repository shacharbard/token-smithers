"""Zero-dependency enforcement: domain/ must have no external imports.

These tests verify the domain core is pure Python with stdlib-only dependencies.
If any test fails, an accidental third-party dependency leaked into domain/.
"""

from __future__ import annotations

import ast
import importlib
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
            source_file = getattr(mod, "__file__", None)
            if source_file is None:
                continue

            with open(source_file, encoding="utf-8") as f:
                source = f.read()

            # Use ast.parse for robust import extraction
            tree = ast.parse(source, filename=source_file)
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top_module = alias.name.split(".")[0]
                        if top_module == "token_sieve":
                            continue
                        assert top_module in stdlib_names, (
                            f"Module {mod.__name__} imports '{top_module}' "
                            f"which is not in stdlib"
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.level > 0:  # relative import
                        continue
                    if node.module is None:
                        continue
                    top_module = node.module.split(".")[0]
                    if top_module in ("token_sieve", "__future__"):
                        continue
                    assert top_module in stdlib_names, (
                        f"Module {mod.__name__} imports '{top_module}' "
                        f"which is not in stdlib"
                    )
