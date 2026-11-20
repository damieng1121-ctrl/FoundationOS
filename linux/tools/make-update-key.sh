#!/bin/sh
# One-time: create Stoa's update signing key.
#
#   ./make-update-key.sh
#
# Then in GitHub: your repository > Settings > Secrets and variables > Actions > New repository secret,
# name STOA_SIGNING_KEY, and paste the whole of stoa-update-key.pem (including the BEGIN/END lines).
# Keep stoa-update-key.pem somewhere safe and offline (a USB stick in a drawer) - and don't commit it.
set -e
umask 077
[ -e stoa-update-key.pem ] && { echo "stoa-update-key.pem already exists - not overwriting it." >&2; exit 1; }
openssl genpkey -algorithm ed25519 -out stoa-update-key.pem
echo "Created stoa-update-key.pem. Public key (Stoa PCs will trust updates signed by this):"
openssl pkey -in stoa-update-key.pem -pubout
