#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
UVICORN="$BACKEND_DIR/venv/bin/uvicorn"
CERT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/trackme/certs"
CA_CERT="$CERT_DIR/trackme-root-ca.crt"
CA_KEY="$CERT_DIR/trackme-root-ca.key"
SERVER_CERT="$CERT_DIR/trackme-server.crt"
SERVER_KEY="$CERT_DIR/trackme-server.key"
CERT_SHARE_DIR="$CERT_DIR/share"

if [[ ! -f "$BACKEND_DIR/.env" ]]; then
    printf 'Missing %s/backend/.env. Configure it before launching TRACKME.\n' "$PROJECT_DIR" >&2
    exit 1
fi

if [[ ! -x "$UVICORN" ]]; then
    printf 'Could not find the backend environment at %s.\n' "$BACKEND_DIR/venv" >&2
    exit 1
fi

if ! command -v openssl >/dev/null 2>&1 || ! command -v ip >/dev/null 2>&1; then
    printf 'Phone testing requires the openssl and ip commands.\n' >&2
    exit 1
fi

LAN_IP="${TRACKME_LAN_IP:-$(ip -4 route show default 2>/dev/null | awk 'NR == 1 { for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit } }')}"
if [[ -z "$LAN_IP" ]]; then
    LAN_IP="$(hostname -I 2>/dev/null | awk '{ print $1 }')"
fi
if [[ -z "$LAN_IP" ]] || ! python3 -c 'import ipaddress, sys; ipaddress.IPv4Address(sys.argv[1])' "$LAN_IP" 2>/dev/null; then
    printf 'Could not determine this PC’s Wi-Fi/LAN IPv4 address.\n' >&2
    printf 'Find it with `hostname -I`, then run: TRACKME_LAN_IP=PC_IP ./run_trackme_phone.sh\n' >&2
    exit 1
fi

mkdir -p "$CERT_DIR"
mkdir -p "$CERT_SHARE_DIR"
chmod 700 "$CERT_DIR"
chmod 755 "$CERT_SHARE_DIR"
umask 077

if [[ -e "$CA_CERT" && ! -e "$CA_KEY" ]] || [[ ! -e "$CA_CERT" && -e "$CA_KEY" ]]; then
    printf 'The local certificate authority is incomplete in %s. Do not delete its key; inspect the files first.\n' "$CERT_DIR" >&2
    exit 1
fi

if [[ ! -e "$CA_CERT" ]]; then
    openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
        -keyout "$CA_KEY" \
        -out "$CA_CERT" \
        -subj "/CN=TRACKME Local Test CA" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign"
    chmod 600 "$CA_KEY"
    chmod 644 "$CA_CERT"
fi
cp "$CA_CERT" "$CERT_SHARE_DIR/trackme-root-ca.crt"
chmod 644 "$CERT_SHARE_DIR/trackme-root-ca.crt"

openssl req -new -newkey rsa:2048 -nodes \
    -keyout "$SERVER_KEY" \
    -out "$CERT_DIR/trackme-server.csr" \
    -subj "/CN=$LAN_IP"

printf 'subjectAltName=IP:%s\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$LAN_IP" \
    > "$CERT_DIR/trackme-server.ext"

openssl x509 -req -sha256 -days 825 \
    -in "$CERT_DIR/trackme-server.csr" \
    -CA "$CA_CERT" \
    -CAkey "$CA_KEY" \
    -CAserial "$CERT_DIR/trackme-root-ca.srl" \
    -CAcreateserial \
    -out "$SERVER_CERT" \
    -extfile "$CERT_DIR/trackme-server.ext"
rm -f "$CERT_DIR/trackme-server.csr" "$CERT_DIR/trackme-server.ext"
chmod 600 "$SERVER_KEY"

api_pid=
frontend_pid=
certificate_pid=

cleanup() {
    if [[ -n "$api_pid" ]]; then
        kill "$api_pid" 2>/dev/null || true
        wait "$api_pid" 2>/dev/null || true
    fi
    if [[ -n "$frontend_pid" ]]; then
        kill "$frontend_pid" 2>/dev/null || true
        wait "$frontend_pid" 2>/dev/null || true
    fi
    if [[ -n "$certificate_pid" ]]; then
        kill "$certificate_pid" 2>/dev/null || true
        wait "$certificate_pid" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export FRONTEND_ORIGINS="https://${LAN_IP}:5500,http://localhost:5500,http://127.0.0.1:5500"

(
    cd "$BACKEND_DIR"
    exec "$UVICORN" app.main:app \
        --host "$LAN_IP" \
        --port 8000 \
        --ssl-certfile "$SERVER_CERT" \
        --ssl-keyfile "$SERVER_KEY"
) &
api_pid=$!

python3 "$PROJECT_DIR/frontend/https_server.py" \
    --host "$LAN_IP" \
    --port 5500 \
    --directory "$PROJECT_DIR/frontend" \
    --cert "$SERVER_CERT" \
    --key "$SERVER_KEY" &
frontend_pid=$!

python3 -m http.server 5501 \
    --bind "$LAN_IP" \
    --directory "$CERT_SHARE_DIR" &
certificate_pid=$!

sleep 2
if ! kill -0 "$api_pid" 2>/dev/null; then
    printf 'The API failed to start. Check MySQL, backend/.env, and the message above.\n' >&2
    wait "$api_pid" || true
    exit 1
fi
if ! kill -0 "$frontend_pid" 2>/dev/null; then
    printf 'The frontend server failed to start. Check whether port 5500 is already in use.\n' >&2
    wait "$frontend_pid" || true
    exit 1
fi
if ! kill -0 "$certificate_pid" 2>/dev/null; then
    printf 'The certificate download server failed to start. Check whether port 5501 is already in use.\n' >&2
    wait "$certificate_pid" || true
    exit 1
fi

printf '\nTRACKME phone test is running on this Wi-Fi:\n'
printf '  https://%s:5500/\n' "$LAN_IP"
printf 'Download this certificate on each phone before opening the app:\n'
printf '  http://%s:5501/trackme-root-ca.crt\n' "$LAN_IP"
printf 'The certificate is also saved at %s\n' "$CA_CERT"
printf 'Keep this terminal open. Press Ctrl+C to stop the servers.\n\n'

wait "$api_pid"
