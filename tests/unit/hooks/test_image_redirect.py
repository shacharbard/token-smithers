"""Tests for image-redirect.sh hook."""

from __future__ import annotations

import os
import tempfile

import pytest


class TestImageRedirectHook:
    """Read on large images should suggest resize via sips."""

    def test_large_image_blocks(self, run_hook, tmp_path):
        """Read on a .png > 500KB suggests sips resize."""
        # Create a file larger than 500KB
        img = tmp_path / "large.png"
        img.write_bytes(b"\x00" * (600 * 1024))

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(img)},
        )
        assert result.exit_code == 2
        assert "sips" in result.stderr or "resize" in result.stderr.lower()

    def test_small_image_allows(self, run_hook, tmp_path):
        """Read on small images passes through."""
        img = tmp_path / "small.png"
        img.write_bytes(b"\x00" * (100 * 1024))  # 100KB

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(img)},
        )
        assert result.exit_code == 0

    def test_svg_allows(self, run_hook, tmp_path):
        """SVG files pass through (text-based)."""
        svg = tmp_path / "icon.svg"
        svg.write_text("<svg></svg>")

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(svg)},
        )
        assert result.exit_code == 0

    def test_screenshot_suggests_resize(self, run_hook, tmp_path):
        """Files matching screenshot* always suggest resize regardless of size."""
        img = tmp_path / "screenshot_2024.png"
        img.write_bytes(b"\x00" * (200 * 1024))  # Even under 500KB

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(img)},
        )
        assert result.exit_code == 2
        assert "resize" in result.stderr.lower() or "sips" in result.stderr

    def test_screen_shot_suggests_resize(self, run_hook, tmp_path):
        """Files matching 'Screen Shot*' always suggest resize."""
        img = tmp_path / "Screen Shot 2024-01-01.png"
        img.write_bytes(b"\x00" * (200 * 1024))

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(img)},
        )
        assert result.exit_code == 2

    def test_non_image_allows(self, run_hook, tmp_path):
        """Non-image files pass through."""
        txt = tmp_path / "readme.txt"
        txt.write_text("hello" * 200000)

        result = run_hook(
            "image-redirect.sh",
            {"file_path": str(txt)},
        )
        assert result.exit_code == 0

    def test_completes_under_50ms(self, assert_completes_under_ms, tmp_path):
        """Hook completes in < 50ms."""
        img = tmp_path / "test.png"
        img.write_bytes(b"\x00" * (600 * 1024))
        assert_completes_under_ms(
            "image-redirect.sh",
            {"file_path": str(img)},
            max_ms=50,
        )
