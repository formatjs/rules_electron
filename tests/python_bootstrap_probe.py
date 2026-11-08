"""Report the declared runtime reached through the executable bootstrap."""

import json
import sys

print(json.dumps({"version": list(sys.version_info[:2]), "executable": sys.executable}))
