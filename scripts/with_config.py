"""Load installer-generated EnvironmentFile values without interpreting shell code."""

import os
from pathlib import Path
import sys

for line in Path("/etc/aster/config.env").read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ[key] = value
os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
