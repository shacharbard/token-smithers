"""Tests for large-file-redirect.sh hook."""

from __future__ import annotations


class TestLargeFileRedirectHook:
    """Large unsupported files should suggest ctx_execute_file or warn."""

    def test_large_yaml_redirects(self, run_hook, tmp_path):
        """YAML > 200 lines suggests ctx_execute_file."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n" * 250)

        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": str(yaml_file)},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2
        assert "ctx_execute_file" in result.stderr

    def test_small_yaml_allows(self, run_hook, tmp_path):
        """YAML < 200 lines passes through."""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value\n" * 50)

        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": str(yaml_file)},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 0

    def test_pdf_redirects(self, run_hook, tmp_path):
        """PDF files suggest Read with pages parameter."""
        pdf_file = tmp_path / "report.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n" + b"\x00" * 100)

        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": str(pdf_file)},
        )
        assert result.exit_code == 2
        assert "pages" in result.stderr.lower()

    def test_binary_blocks(self, run_hook, tmp_path):
        """Binary files (.bin, .exe, .so) block with warning."""
        for ext in ["bin", "exe", "so"]:
            bin_file = tmp_path / f"data.{ext}"
            bin_file.write_bytes(b"\x00" * 100)

            result = run_hook(
                "large-file-redirect.sh",
                {"file_path": str(bin_file)},
            )
            assert result.exit_code == 2, f"Expected block for .{ext}"
            assert "binary" in result.stderr.lower() or "warning" in result.stderr.lower()

    def test_large_toml_redirects(self, run_hook, tmp_path):
        """TOML > 200 lines suggests ctx_execute_file."""
        toml_file = tmp_path / "config.toml"
        toml_file.write_text("[section]\nkey = 'value'\n" * 120)

        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": str(toml_file)},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2
        assert "ctx_execute_file" in result.stderr

    def test_large_xml_redirects(self, run_hook, tmp_path):
        """XML > 200 lines suggests ctx_execute_file."""
        xml_file = tmp_path / "data.xml"
        xml_file.write_text("<item>value</item>\n" * 250)

        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": str(xml_file)},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2

    def test_nonexistent_file_allows(self, run_hook):
        """Non-existent files pass through (let Read handle the error)."""
        result = run_hook(
            "large-file-redirect.sh",
            {"file_path": "/nonexistent/path/file.yaml"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 0

    def test_completes_under_50ms(self, assert_completes_under_ms, tmp_path):
        """Hook completes in < 50ms."""
        yaml_file = tmp_path / "big.yaml"
        yaml_file.write_text("key: value\n" * 250)
        assert_completes_under_ms(
            "large-file-redirect.sh",
            {"file_path": str(yaml_file)},
            max_ms=50,
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
