import unittest

from tools.ci.source_headers_diagnostics import missing_headers


class SourceHeadersDiagnosticsTest(unittest.TestCase):
    def test_only_exact_public_paths_leave_logs(self):
        log = (
            "fatal error: 'public/header.h' file not found\n"
            'fatal error: "other.h" file not found\n'
            "fatal error: 'private/header.h' file not found\n"
            "fatal error: 'secret-token/public/header.h' file not found\n"
            "Authorization: Bearer secret-token\n"
            "fatal error: 'public/header.h' file not found\n"
        )
        self.assertEqual(missing_headers(log, {"public/header.h", "other.h"}), ["other.h", "public/header.h"])

    def test_colored_compiler_diagnostics_still_require_exact_public_paths(self):
        log = "fatal error: \x1b[1m'public/header.h'\x1b[0m file not found"
        self.assertEqual(missing_headers(log, {"public/header.h"}), ["public/header.h"])
        self.assertEqual(missing_headers(log, {"other.h"}), [])

    def test_rejects_multiline_and_unbounded_output(self):
        allowed = {f"public/{index:02}.h" for index in range(20)}
        log = "\n".join(f"fatal error: '{path}' file not found" for path in sorted(allowed, reverse=True))
        log += "\nfatal error: 'public/00.h\nprivate-data' file not found"
        self.assertEqual(missing_headers(log, allowed), sorted(allowed)[:8])
        self.assertEqual(missing_headers("fatal error: 'public/00.h\rprivate-data' file not found", allowed), [])


if __name__ == "__main__":
    unittest.main()
