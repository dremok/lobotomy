#!/bin/bash
# setup-laptop-bridge.sh — Run this on the laptop with sudo to set up the lobotomy user.
# Usage: sudo bash setup-laptop-bridge.sh

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this with sudo: sudo bash setup-laptop-bridge.sh"
    exit 1
fi

PUBKEY='command="/Users/lobotomy/read-only-gate.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP8Xiyz3v6MSLxQOHukSqphob4r6Z41e0mjaePOFnDNl lobotomy-daemon'

echo "=== Creating lobotomy user ==="
dscl . -create /Users/lobotomy
dscl . -create /Users/lobotomy UserShell /bin/bash
dscl . -create /Users/lobotomy NFSHomeDirectory /Users/lobotomy
dscl . -create /Users/lobotomy UniqueID 502
dscl . -create /Users/lobotomy PrimaryGroupID 20
dscl . -create /Users/lobotomy RealName "Lobotomy Daemon"
createhomedir -c -u lobotomy 2>/dev/null || mkdir -p /Users/lobotomy
echo "  User created (UID 502, group staff)"

echo "=== Setting up SSH ==="
mkdir -p /Users/lobotomy/.ssh
echo "$PUBKEY" > /Users/lobotomy/.ssh/authorized_keys
chmod 700 /Users/lobotomy/.ssh
chmod 600 /Users/lobotomy/.ssh/authorized_keys
echo "  authorized_keys written with forced command"

echo "=== Installing read-only gate ==="
cp "$(dirname "$0")/read-only-gate.sh" /Users/lobotomy/read-only-gate.sh
chmod +x /Users/lobotomy/read-only-gate.sh
echo "  Gate script installed"

echo "=== Creating sandbox directories ==="
mkdir -p /Users/lobotomy/{sandbox,test-runs,snapshots}
echo "  Sandbox dirs created"

echo "=== Setting ownership ==="
chown -R lobotomy:staff /Users/lobotomy/
echo "  Ownership set to lobotomy:staff"

echo "=== Making Max's dirs group-readable ==="
chmod -R g+rX /Users/maxleander/code 2>/dev/null || true
chmod -R g+rX /Users/maxleander/projects 2>/dev/null || true
chmod -R g+rX /Users/maxleander/notes 2>/dev/null || true
echo "  Added group read to ~/code, ~/projects, ~/notes"

echo "=== Hiding sensitive dirs ==="
chmod 700 /Users/maxleander/.ssh 2>/dev/null || true
chmod 700 /Users/maxleander/.gnupg 2>/dev/null || true
chmod 700 /Users/maxleander/.aws 2>/dev/null || true
chmod 700 /Users/maxleander/.config/anthropic 2>/dev/null || true
echo "  Sensitive dirs locked to owner-only"

echo "=== Hiding lobotomy from login screen ==="
dscl . -create /Users/lobotomy IsHidden 1
echo "  User hidden from login screen"

echo ""
echo "Done. Make sure Remote Login is enabled:"
echo "  System Settings > General > Sharing > Remote Login > ON"
echo "  Add lobotomy to allowed users (or allow all users)"
echo ""
echo "Then test from VPS:"
echo '  ssh -i ~/.ssh/laptop_key lobotomy@<tailscale-hostname> "ls /Users/maxleander/code/"'
