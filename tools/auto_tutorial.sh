#!/bin/bash
# Automated KHUx tutorial tap-through using Frida events as triggers
# Usage: bash tools/auto_tutorial.sh
#
# Requires: frida, adb
# Frida server: frida-server-16-64 with -D flag running on device

PHONE="192.168.1.181:5555"
TAP="adb -s $PHONE shell input tap"
SCRIPT="D:/Modding/Git/KHUx/tools/frida_timeline.js"
PKG="com.square_enix.android_googleplay.khuxww"
FRIDA_LOG=""

wait_for() {
    # Wait for a pattern to appear in the frida log
    local pattern="$1"
    local label="$2"
    echo "  ... waiting for: $label"
    until grep -q "$pattern" "$FRIDA_LOG" 2>/dev/null; do
        sleep 0.5
    done
    echo "  >>> $label detected!"
}

wait_for_new() {
    # Wait for a pattern that appears AFTER the current line count
    local pattern="$1"
    local label="$2"
    local baseline=$(wc -l < "$FRIDA_LOG" 2>/dev/null || echo 0)
    echo "  ... waiting for: $label (after line $baseline)"
    while true; do
        tail -n +$((baseline + 1)) "$FRIDA_LOG" 2>/dev/null | grep -q "$pattern" && break
        sleep 0.5
    done
    echo "  >>> $label detected!"
}

tap_until() {
    # Tap at coordinates every 1s until a Frida event appears
    local x=$1 y=$2 pattern="$3" label="$4"
    local baseline=$(wc -l < "$FRIDA_LOG" 2>/dev/null || echo 0)
    echo "  ... tapping ($x,$y) until: $label"
    while true; do
        tail -n +$((baseline + 1)) "$FRIDA_LOG" 2>/dev/null | grep -q "$pattern" && break
        $TAP $x $y
        sleep 1
    done
    echo "  >>> $label detected!"
}

echo "=== KHUx Auto Tutorial ==="

# Step 0: Kill game
echo "[0] Killing game..."
adb -s $PHONE shell "am force-stop $PKG"
sleep 1

# Step 1: Spawn with Frida
echo "[1] Spawning with Frida..."
FRIDA_LOG=$(mktemp)
frida -U -f $PKG -l "$SCRIPT" --eternalize > "$FRIDA_LOG" 2>&1 &
FRIDA_PID=$!

# Step 2: Wait for hooks
wait_for "hooks installed" "Frida hooks"

# Step 3: Tap until title screen
echo "[2] Tapping to title screen..."
tap_until 897 540 "SceneTitle::init" "SceneTitle"

# Step 4: Tap until EULA
echo "[3] Tapping to EULA..."
tap_until 897 540 "SceneAgreement::init" "SceneAgreement"

echo ""
echo "=== Reached EULA screen ==="
echo "=== Frida log: $FRIDA_LOG ==="
echo ""
echo "Next steps (manual or extend script):"
echo "  Accept EULA:      tap 1350 950"
echo "  Birthday Register: tap 897 648, then 1120 648"
echo "  Download:          tap 897 864"
echo "  Collect jewels:    tap 897 864"
echo "  Name OK:           tap 897 1037"
echo "  Avatar confirm:    tap 1200 1010, then 1087 1026"
echo "  Union OK:          tap 1162 815"
echo "  SKIP cutscene:     tap 1700 50"

# Keep frida alive
wait $FRIDA_PID 2>/dev/null
