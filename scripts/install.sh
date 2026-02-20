#!/bin/bash
# nBogne Transport — Raspberry Pi Setup Script
# Run as root: sudo bash scripts/install.sh

set -e

echo "========================================"
echo "  nBogne Transport — Installer"
echo "========================================"

# ── 1. System packages ───────────────────────────────────
echo "[1/6] Installing system packages..."
apt-get update -qq
apt-get install -y python python-pip python-venv git

# ── 2. Enable UART (disable Bluetooth on serial0) ───────
echo "[2/6] Configuring UART..."
if ! grep -q "enable_uart=1" /boot/firmware/config.txt 2>/dev/null; then
    # Try both paths (Bookworm vs older)
    BOOT_CFG="/boot/firmware/config.txt"
    [ ! -f "$BOOT_CFG" ] && BOOT_CFG="/boot/config.txt"

    echo "" >> "$BOOT_CFG"
    echo "# nBogne: Enable UART for SIM800C" >> "$BOOT_CFG"
    echo "enable_uart=1" >> "$BOOT_CFG"
    echo "dtoverlay=disable-bt" >> "$BOOT_CFG"

    # Disable serial console (frees /dev/serial0 for modem)
    systemctl disable serial-getty@ttyS0.service 2>/dev/null || true
    systemctl stop serial-getty@ttyS0.service 2>/dev/null || true

    # Remove console=serial from cmdline
    CMDLINE="/boot/firmware/cmdline.txt"
    [ ! -f "$CMDLINE" ] && CMDLINE="/boot/cmdline.txt"
    sed -i 's/console=serial0,[0-9]* //g' "$CMDLINE"

    echo "    UART configured (REBOOT REQUIRED)"
    NEEDS_REBOOT=1
fi

# ── 3. Create directories ───────────────────────────────
echo "[3/6] Creating directories..."
mkdir -p /opt/nbogne
mkdir -p /var/lib/nbogne
mkdir -p /var/log/nbogne

# ── 4. Copy files ────────────────────────────────────────
echo "[4/6] Installing application..."
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cp "$SCRIPT_DIR"/*.py /opt/nbogne/
chmod +x /opt/nbogne/main.py

# ── 5. Python dependencies ───────────────────────────────
echo "[5/6] Installing Python packages..."
pip3 install pyserial RPi.GPIO --break-system-packages 2>/dev/null || \
pip3 install pyserial RPi.GPIO

# ── 6. Systemd service ──────────────────────────────────
echo "[6/6] Installing systemd service..."
cp "$SCRIPT_DIR/scripts/nbogne.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable nbogne.service

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Edit /opt/nbogne/config.py with your settings"
echo "  2. Wire SIM800C to GPIO (see README.md)"
echo "  3. Insert SIM card (PIN-free, with credit)"
if [ "${NEEDS_REBOOT:-0}" = "1" ]; then
    echo "  4. REBOOT: sudo reboot"
    echo "  5. After reboot: sudo systemctl start nbogne"
else
    echo "  4. Start: sudo systemctl start nbogne"
fi
echo ""
echo "Test: python /opt/nbogne/tests/test_modem_hw.py"
echo "Logs: journalctl -u nbogne -f"
