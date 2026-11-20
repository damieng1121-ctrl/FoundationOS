#!/bin/sh
# Sign Stoa update descriptions (latest.json, kernel.json) with the update signing key, so Stoa PCs can check
# that an update really comes from you. Uses Ed25519 (OpenSSL).
#
#   STOA_SIGNING_KEY="$(cat key.pem)" sign-manifest.sh latest.json [kernel.json ...]   -> FILE.sig
#   sign-manifest.sh --public                                                          -> the public key
#
# The key lives in the GitHub secret STOA_SIGNING_KEY (make one with make-update-key.sh). Without it nothing is
# signed - and Stoa PCs that already know your key will then refuse the update rather than trust it.
set -e
[ -n "$STOA_SIGNING_KEY" ] || { echo "STOA_SIGNING_KEY isn't set: not signing" >&2; exit 3; }
key="$(mktemp)"; trap 'rm -f "$key"' EXIT
printf '%s\n' "$STOA_SIGNING_KEY" > "$key"
if [ "$1" = --public ]; then
  openssl pkey -in "$key" -pubout
  exit 0
fi
for f in "$@"; do
  openssl pkeyutl -sign -inkey "$key" -rawin -in "$f" -out "$f.sig"
  echo "signed $f"
done
