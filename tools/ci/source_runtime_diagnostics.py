"""Bound public runtime failures, keeping fatal checks ahead of startup noise."""

import re


def runtime_failures(log, public_basenames, public_identifiers):
    log = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", log)
    severe = re.compile(r"\bFATAL\b|Check failed|(?:Assertion|assertion) failed|\b(?:ReferenceError|TypeError|SyntaxError|RangeError|Error):")
    diagnostic = re.compile(r"FATAL|ERROR|Check failed|Assertion|assertion|\b(?:ReferenceError|TypeError|SyntaxError|RangeError|Error):")
    lines = sorted(log.splitlines(), key=lambda line: 0 if severe.search(line) else 1 if diagnostic.search(line) else 2)
    sites, failures = [], []
    stack = []
    for line in log.splitlines():
        if re.match(r"^\s*#[0-9]{1,3}\s+0x[0-9a-fA-F]+\s", line):
            words = [word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", re.sub(r"0x[0-9a-fA-F]+", "", line))
                     if word in public_identifiers][:16]
            if words and len(stack) < 32:
                stack.append(words)
    for line in lines:
        for name, number in re.findall(r"([A-Za-z_0-9.-]+\.(?:h|c|cc|cpp))[:(]([0-9]{1,5})", line):
            site = {"file": name, "line": int(number)}
            if name in public_basenames and 0 < int(number) < 10000 and site not in sites and len(sites) < 8:
                sites.append(site)
        if diagnostic.search(line) and len(failures) < 6:
            words = list(dict.fromkeys(word for word in re.findall(r"[A-Za-z_][A-Za-z_0-9]*", line)
                                       if word in public_identifiers))[:20]
            if words and words not in failures:
                failures.append(words)
    return {"public_check_sites": sites, "public_fatal_identifiers": failures, "public_stack_identifiers": stack}
