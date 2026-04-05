"""Contract tests for VisibilityControllerPort protocol."""

from __future__ import annotations

from token_sieve.domain.ports_visibility import VisibilityControllerPort


class FakeVisibilityController:
    """Minimal implementation satisfying the VisibilityControllerPort protocol."""

    def __init__(self) -> None:
        self._hidden: dict[str, object] = {}

    def apply(
        self,
        tools: list,
        usage_stats: list,
        *,
        session_count: int,
    ) -> tuple[list, list]:
        return tools, []

    def hidden_stats(self) -> dict:
        return {"total_hidden": 0, "visible": 0}

    def get_hidden_tools(self) -> list:
        return []

    def get_hidden_tool_names(self) -> frozenset[str]:
        return frozenset()

    def unhide_for_session(self, tool_name: str) -> None:
        pass


class TestVisibilityControllerPortProtocol:
    """VisibilityControllerPort is a runtime-checkable Protocol."""

    def test_protocol_structural_subtyping(self) -> None:
        """FakeVisibilityController satisfies the protocol via structural subtyping."""
        fake = FakeVisibilityController()
        assert isinstance(fake, VisibilityControllerPort)

    def test_apply_returns_tuple(self) -> None:
        """apply() returns a (visible, hidden) tuple."""
        fake = FakeVisibilityController()
        result = fake.apply([], [], session_count=1)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_protocol_is_runtime_checkable(self) -> None:
        """VisibilityControllerPort has Protocol runtime-check attributes."""
        assert hasattr(VisibilityControllerPort, "__protocol_attrs__") or hasattr(
            VisibilityControllerPort, "_is_protocol"
        )


class TestVisibilityControllerSatisfiesPort:
    """Real VisibilityController satisfies the port protocol."""

    def test_controller_satisfies_protocol(self) -> None:
        """VisibilityController is a structural subtype of VisibilityControllerPort."""
        from token_sieve.adapters.visibility.visibility_controller import (
            VisibilityController,
        )

        ctrl = VisibilityController()
        assert isinstance(ctrl, VisibilityControllerPort)
