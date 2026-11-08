"""Fixed network categories; never return arbitrary log text or URLs."""

import re


def network_diagnostics(log):
    patterns = {
        "READ_TIMEOUT": r"read timed out|ReadTimeout",
        "CONNECT_TIMEOUT": r"connect(?:ion)? timed out|ConnectTimeout",
        "TLS_FAILURE": r"SSLHandshakeException|SSLException|PKIX",
        "DNS_FAILURE": r"UnknownHostException|Temporary failure in name resolution|Could not resolve host",
        "CONNECTION_RESET": r"connection reset|reset by peer",
        "CONNECTION_REFUSED": r"connection refused",
    }
    repositories = ["bazel-contrib/rules_python", "bazel-contrib/bazel-lib",
                    "bazelbuild/rules_cc", "bazelbuild/bazel-skylib"]
    codes = re.findall(r"(?:GET returned|returned error|(?:HTTP(?: response)?|response|status)(?: code)?)\s*:?\s*([45][0-9]{2})", log, re.I)
    return {
        "categories": sorted(name for name, pattern in patterns.items() if re.search(pattern, log, re.I)),
        "http_status_codes": sorted({int(code) for code in codes}),
        "public_dependencies": [name for name in repositories if "github.com/" + name + "/" in log],
    }
