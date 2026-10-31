#!/bin/sh
# Local-only certificate. Not suitable for a client-facing internet site.
set -eu
cd "$(dirname "$0")/.."
if [ -e deploy/tls/privkey.pem ] || [ -e deploy/tls/fullchain.pem ]; then
    echo "Certificate exists; not overwritten." >&2
    exit 1
fi
umask 077
mkdir -p deploy/tls
openssl req -x509 -newkey rsa:3072 -nodes -days 30 \
    -keyout deploy/tls/privkey.pem -out deploy/tls/fullchain.pem \
    -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
echo "Local localhost certificate created. Nothing deployed."
