#!/usr/bin/env python3
"""Write latest.json for Stoa's online updates: version, download address, SHA-256, size and what's new.

  update-manifest.py PACKAGE.deb BASE_URL > latest.json
"""
import hashlib
import json
import os
import re
import subprocess
import sys

deb, base = sys.argv[1], sys.argv[2].rstrip("/")
version = subprocess.run(["dpkg-deb", "-f", deb, "Version"], capture_output=True, text=True, check=True).stdout.strip()
h = hashlib.sha256(open(deb, "rb").read()).hexdigest()
log = subprocess.run(["git", "log", "-25", "--no-merges", "--format=%s"], capture_output=True, text=True).stdout
notes = [n for n in log.splitlines() if not re.match(r"(?i)(ci|build|wip|merge|fixup|test)[:( ]", n)][:15]
print(json.dumps({"version": version, "file": os.path.basename(deb), "url": f"{base}/{os.path.basename(deb)}",
                  "sha256": h, "size": os.path.getsize(deb), "notes": notes}, indent=1))
