"""Report only allowlisted public headers from compiler diagnostics."""

import re


def missing_headers(log, allowed):
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
    matches = re.findall(r"fatal error: ['\"]([^'\"\r\n]+)['\"] file not found", log)
    return sorted({header for header in matches if header in allowed})[:8]
