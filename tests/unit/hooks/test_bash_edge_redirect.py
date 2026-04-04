"""Tests for bash-edge-redirect.sh hook."""

from __future__ import annotations


class TestBashEdgeRedirectHook:
    """Verbose CLI commands should suggest ctx_execute."""

    def test_docker_logs_redirects(self, run_hook):
        """docker logs suggests ctx_execute."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "docker logs my-container --tail 500"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2
        assert "ctx_execute" in result.stderr

    def test_kubectl_logs_redirects(self, run_hook):
        """kubectl logs suggests ctx_execute."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "kubectl logs pod/my-pod -n default"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2
        assert "ctx_execute" in result.stderr

    def test_terraform_plan_redirects(self, run_hook):
        """terraform plan suggests ctx_execute."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "terraform plan -out=tfplan"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2
        assert "ctx_execute" in result.stderr

    def test_kubectl_describe_redirects(self, run_hook):
        """kubectl describe suggests ctx_execute."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "kubectl describe pod my-pod"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2

    def test_helm_template_redirects(self, run_hook):
        """helm template suggests ctx_execute."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "helm template my-chart ./charts"},
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
        assert result.exit_code == 2

    def test_simple_commands_allow(self, run_hook):
        """ls, git status, mkdir pass through."""
        for cmd in ["ls -la", "git status", "mkdir -p /tmp/test"]:
            result = run_hook(
                "bash-edge-redirect.sh",
                {"command": cmd},
                env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
            )
            assert result.exit_code == 0, f"Expected allow for: {cmd}"

    def test_without_context_mode_allows(self, run_hook):
        """Without context-mode, verbose commands pass through."""
        result = run_hook(
            "bash-edge-redirect.sh",
            {"command": "docker logs container"},
        )
        assert result.exit_code == 0

    def test_completes_under_50ms(self, assert_completes_under_ms):
        """Hook completes in < 50ms."""
        assert_completes_under_ms(
            "bash-edge-redirect.sh",
            {"command": "docker logs container"},
            max_ms=50,
            env={"TOKEN_SIEVE_CONTEXT_MODE": "1"},
        )
