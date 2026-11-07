"""Verify the action environment enforces the configured network restriction."""

import socket
import unittest


class HermeticExecutionTest(unittest.TestCase):
    def test_external_network_is_unavailable(self):
        with self.assertRaises(OSError):
            with socket.create_connection(("1.1.1.1", 443), timeout=1):
                self.fail("Build action unexpectedly has external network access")


if __name__ == "__main__":
    unittest.main()
