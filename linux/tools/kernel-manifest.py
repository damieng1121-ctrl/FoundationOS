#!/usr/bin/env python3
"""Write kernel.json for Stoa's online updates: the Stoa kernel packages (image + headers) with SHA-256s.

  kernel-manifest.py BASE_URL linux-image-*.deb linux-headers-*.deb > kernel.json
"""
import hashlib
import json
import os
import re
import subprocess
import sys

base, debs = sys.argv[1].rstrip("/"), sys.argv[2:]
pkgs, release = [], ""
for d in debs:
    f = lambda k: subprocess.run(["dpkg-deb", "-f", d, k], capture_output=True, text=True, check=True).stdout.strip()  # noqa: E731
    name = f("Package")
    m = re.match(r"linux-image-(.+)", name)
    if m:
        release = m.group(1)
    pkgs.append({"package": name, "version": f("Version"), "file": os.path.basename(d),
                 "url": f"{base}/{os.path.basename(d)}", "sha256": hashlib.sha256(open(d, "rb").read()).hexdigest(),
                 "size": os.path.getsize(d)})
print(json.dumps({"release": release, "packages": pkgs}, indent=1))
