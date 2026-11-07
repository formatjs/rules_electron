"""Verify the action environment enforces the configured network restriction."""

import socket
import ssl
import unittest


class HermeticExecutionTest(unittest.TestCase):
    def test_external_network_is_unavailable(self):
        with self.assertRaises(OSError):
            with socket.create_connection(("1.1.1.1", 443), timeout=2) as connection:
                with ssl.create_default_context().wrap_socket(connection, server_hostname="one.one.one.one"):
                    self.fail("Build action unexpectedly completed an external TLS exchange")


if __name__ == "__main__":
    unittest.main()
