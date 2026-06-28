import os
from unittest import TestCase
from unittest.mock import patch

import httpx

from conduit.conduit import ConduitApp, PhabricatorConfig

# Tokens that satisfy ^(api|cli)-[A-Za-z0-9]{28}$
_TOKEN_A = "api-" + "a" * 28
_TOKEN_B = "api-" + "b" * 28
_VALID_TOKEN = "api-" + "v" * 28
_ADMIN_TOKEN = "api-" + "f" * 28
_USER_TOKEN = "cli-" + "g" * 28


class TestHTTPModeSecurity(TestCase):
    """Test HTTP mode security and user identity isolation."""

    def setUp(self):
        super().setUp()
        os.environ["PHABRICATOR_URL"] = "https://test.example.com/api/"

        self.config = PhabricatorConfig(http_mode=True)
        self.app = ConduitApp(self.config, http_mode=True)
        # Initialize shared client as the lifespan would; tests run without lifespan.
        self.app._shared_client = httpx.Client(
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )

    def tearDown(self):
        super().tearDown()
        if self.app._shared_client and not self.app._shared_client.is_closed:
            self.app._shared_client.close()
        if "PHABRICATOR_URL" in os.environ:
            del os.environ["PHABRICATOR_URL"]

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_separate_wrappers_per_request(self, mock_get_headers):
        """HTTP mode returns a new PhabricatorClient wrapper per request."""
        mock_get_headers.return_value = {"x-phabricator-token": _TOKEN_A}
        client_a = self.app.get_client()
        self.assertIsNotNone(client_a)

        mock_get_headers.return_value = {"x-phabricator-token": _TOKEN_B}
        client_b = self.app.get_client()
        self.assertIsNotNone(client_b)

        # Different wrapper instances
        self.assertNotEqual(id(client_a), id(client_b))

        # Each wrapper carries its own token
        self.assertNotEqual(client_a.maniphest.api_token, client_b.maniphest.api_token)
        self.assertEqual(client_a.maniphest.api_token, _TOKEN_A)
        self.assertEqual(client_b.maniphest.api_token, _TOKEN_B)

        self.assertNotEqual(client_a, client_b)

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_multiple_user_isolation(self, mock_get_headers):
        """Multiple users in HTTP mode each get their own token."""
        # tokens match the gate regex: api- + 28 alphanumeric chars
        tokens = ["api-" + f"user{i}" + "x" * (28 - len(f"user{i}")) for i in range(5)]
        clients = []

        for token in tokens:
            mock_get_headers.return_value = {"x-phabricator-token": token}
            client = self.app.get_client()
            clients.append(client)
            self.assertEqual(client.user.api_token, token)

        for i in range(len(clients)):
            for j in range(i + 1, len(clients)):
                self.assertNotEqual(clients[i], clients[j])
                self.assertNotEqual(
                    clients[i].user.api_token, clients[j].user.api_token
                )

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_token_validation(self, mock_get_headers):
        """Token validation in HTTP mode: missing -> ValueError; bad shape -> ValueError."""
        # Missing token
        mock_get_headers.return_value = {}

        with self.assertRaises(ValueError) as cm:
            self.app.get_client()

        self.assertIn("X-Phabricator-Token", str(cm.exception))

        # Wrong shape (not matching regex)
        mock_get_headers.return_value = {"x-phabricator-token": "short_token"}

        with self.assertRaises(ValueError) as cm:
            self.app.get_client()

        error_msg = str(cm.exception)
        self.assertTrue(
            "api-" in error_msg or "cli-" in error_msg or "28" in error_msg,
            f"Expected shape error, got: {error_msg}",
        )

        # Valid api- token
        mock_get_headers.return_value = {"x-phabricator-token": _VALID_TOKEN}
        client = self.app.get_client()
        self.assertIsNotNone(client)
        self.assertEqual(client.maniphest.api_token, _VALID_TOKEN)

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_no_persistent_state(self, mock_get_headers):
        """HTTP mode has no persistent state pollution between requests."""
        token_1 = "api-" + "c" * 28
        mock_get_headers.return_value = {"x-phabricator-token": token_1}
        client_1 = self.app.get_client()
        self.assertIsNotNone(client_1)
        self.assertEqual(client_1.maniphest.api_token, token_1)

        token_2 = "api-" + "d" * 28
        mock_get_headers.return_value = {"x-phabricator-token": token_2}
        client_2 = self.app.get_client()
        self.assertIsNotNone(client_2)
        self.assertEqual(client_2.maniphest.api_token, token_2)

        token_3 = "cli-" + "e" * 28
        mock_get_headers.return_value = {"x-phabricator-token": token_3}
        client_3 = self.app.get_client()
        self.assertIsNotNone(client_3)
        self.assertEqual(client_3.maniphest.api_token, token_3)

        # No state pollution
        self.assertEqual(client_1.user.api_token, token_1)
        self.assertEqual(client_2.user.api_token, token_2)
        self.assertEqual(client_3.user.api_token, token_3)

        self.assertNotEqual(client_1, client_2)
        self.assertNotEqual(client_2, client_3)
        self.assertNotEqual(client_1, client_3)

    def test_stdio_mode_backward_compatibility(self):
        """stdio mode maintains backward compatibility (caches a single client)."""
        stdio_token = "stdio_test_token" + "x" * 16  # 32 chars, length check only
        stdio_config = PhabricatorConfig(token=stdio_token, require_token=False)
        stdio_app = ConduitApp(stdio_config, http_mode=False)

        client_1 = stdio_app.get_client()
        self.assertIsNotNone(client_1)
        self.assertEqual(client_1.user.api_token, stdio_token)

        # Second call returns the same cached instance
        client_2 = stdio_app.get_client()
        self.assertIs(client_1, client_2)
        self.assertEqual(client_2.user.api_token, stdio_token)

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_concurrent_requests_simulation(self, mock_get_headers):
        """Rapid consecutive requests each get a separate wrapper with the correct token."""
        tokens = [f"api-{str(i).zfill(28)}" for i in range(10)]
        clients = []

        for token in tokens:
            mock_get_headers.return_value = {"x-phabricator-token": token}
            client = self.app.get_client()
            clients.append(client)

        for i, client in enumerate(clients):
            self.assertEqual(client.user.api_token, tokens[i])

        for i in range(len(clients)):
            for j in range(i + 1, len(clients)):
                self.assertNotEqual(clients[i], clients[j])

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_security_boundary(self, mock_get_headers):
        """Each request can only access its own token."""
        mock_get_headers.return_value = {"x-phabricator-token": _ADMIN_TOKEN}
        admin_client = self.app.get_client()
        self.assertEqual(admin_client.user.api_token, _ADMIN_TOKEN)

        mock_get_headers.return_value = {"x-phabricator-token": _USER_TOKEN}
        user_client = self.app.get_client()
        self.assertEqual(user_client.user.api_token, _USER_TOKEN)

        self.assertNotEqual(admin_client.user.api_token, user_client.user.api_token)
        self.assertNotEqual(admin_client, user_client)

        # Another request with the admin token creates a fresh wrapper
        mock_get_headers.return_value = {"x-phabricator-token": _ADMIN_TOKEN}
        admin_client_2 = self.app.get_client()
        self.assertEqual(admin_client_2.user.api_token, _ADMIN_TOKEN)
        self.assertNotEqual(admin_client, admin_client_2)

    @patch("conduit.conduit.get_http_headers")
    def test_http_mode_wrappers_share_http_client(self, mock_get_headers):
        """All wrappers returned by get_client() share the same underlying httpx.Client."""
        mock_get_headers.return_value = {"x-phabricator-token": _TOKEN_A}
        client_a = self.app.get_client()

        mock_get_headers.return_value = {"x-phabricator-token": _TOKEN_B}
        client_b = self.app.get_client()

        # Both wrappers reuse the shared pool
        self.assertIs(client_a.http_client, self.app._shared_client)
        self.assertIs(client_b.http_client, self.app._shared_client)

        # Closing a wrapper does NOT close the shared client
        client_a.close()
        self.assertFalse(self.app._shared_client.is_closed)


class TestHTTPModeSecurityIntegration(TestCase):
    """Integration tests for HTTP mode security."""

    def setUp(self):
        super().setUp()
        os.environ["PHABRICATOR_URL"] = "https://integration.test.com/api/"

    def tearDown(self):
        super().tearDown()
        if "PHABRICATOR_URL" in os.environ:
            del os.environ["PHABRICATOR_URL"]

    @patch("conduit.conduit.get_http_headers")
    def test_integration_with_real_phabricator_client(self, mock_get_headers):
        """get_client() in HTTP mode returns a PhabricatorClient with correct configuration."""
        from conduit.client.unified import PhabricatorClient

        config = PhabricatorConfig(http_mode=True)
        app = ConduitApp(config, http_mode=True)
        app._shared_client = httpx.Client(
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30.0,
        )

        real_token = "api-" + "r" * 28
        mock_get_headers.return_value = {"x-phabricator-token": real_token}

        client = app.get_client()

        self.assertIsInstance(client, PhabricatorClient)
        self.assertEqual(client.user.api_token, real_token)
        self.assertEqual(client.user.api_url, "https://integration.test.com/api/")

        app._shared_client.close()

    def test_app_mode_configuration(self):
        """ConduitApp exposes the correct http_mode flag."""
        http_config = PhabricatorConfig(http_mode=True)
        http_app = ConduitApp(http_config, http_mode=True)
        self.assertTrue(http_app.http_mode)

        stdio_token = "test_token_xx" + "x" * 19  # 32 chars
        stdio_config = PhabricatorConfig(token=stdio_token, require_token=False)
        stdio_app = ConduitApp(stdio_config, http_mode=False)
        self.assertFalse(stdio_app.http_mode)

    def test_http_mode_token_not_read_from_env(self):
        """PhabricatorConfig(http_mode=True) ignores PHABRICATOR_TOKEN env var."""
        os.environ["PHABRICATOR_TOKEN"] = "api-" + "z" * 28
        try:
            config = PhabricatorConfig(http_mode=True)
            self.assertIsNone(config.token)
        finally:
            del os.environ["PHABRICATOR_TOKEN"]
