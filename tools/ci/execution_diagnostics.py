"""Select bounded failed executions before requesting full action results."""

import re


def failed_execution_lookups(invocation, executions):
    lookups = []
    for execution in executions:
        if not execution.get("exitCode", 0) and not execution.get("status", {}).get("code", 0):
            continue
        lookup = {"invocation_id": invocation}
        identifier = execution.get("executionId")
        digest = execution.get("actionDigest", {}).get("hash")
        if isinstance(identifier, str) and identifier:
            lookup["execution_id"] = identifier
        elif isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest):
            lookup["action_digest_hash"] = digest
        else:
            raise ValueError("Failed execution lacks lookup identity")
        lookups.append(lookup)
        if len(lookups) == 32:
            break
    return lookups
