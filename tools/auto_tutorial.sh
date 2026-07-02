#!/bin/bash
# Automated KHUx tutorial — event-driven via Frida hooks
# Usage: bash tools/auto_tutorial.sh
#
# Requires: frida 16.1.4, adb, frida-server-16-64 with -D on device

# Load env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

PHONE="${KHUX_PHONE:?KHUX_PHONE not set in .env}"
SCRIPT="$SCRIPT_DIR/frida_timeline.js"
PKG="com.square_enix.android_googleplay.khuxww"
FRIDA_LOG=$(mktemp)
HANDLED=""

tap() {
    adb -s $PHONE shell input tap "$1" "$2"
}

type_text() {
    adb -s $PHONE shell input tap 897 520   # focus name field
    sleep 1
    adb -s $PHONE shell input text "$1"
    sleep 1
    adb -s $PHONE shell input keyevent 66   # Enter
}

already_handled() {
    echo "$HANDLED" | grep -q "$1" && return 0
    HANDLED="$HANDLED $1"
    return 1
}

echo "=== KHUx Auto Tutorial ==="

# Kill game
echo "[0] Killing game..."
adb -s $PHONE shell "am force-stop $PKG"
sleep 1

# Spawn with Frida
echo "[1] Spawning with Frida..."
frida -U -f $PKG -l "$SCRIPT" > "$FRIDA_LOG" 2>&1 &
FRIDA_PID=$!

# Wait for hooks
echo "  ... waiting for hooks"
until grep -q "hooks installed" "$FRIDA_LOG" 2>/dev/null; do sleep 1; done
echo "  >>> hooks ready"

# Event loop — poll file instead of tail pipe (Windows compatibility)
echo "[2] Event loop started"
LAST_LINE=0
while true; do
    TOTAL=$(wc -l < "$FRIDA_LOG" 2>/dev/null || echo 0)
    if [ "$TOTAL" -gt "$LAST_LINE" ]; then
        tail -n +$((LAST_LINE + 1)) "$FRIDA_LOG" | head -n $((TOTAL - LAST_LINE)) | while read -r line; do

            if echo "$line" | grep -q "SceneMovie::init"; then
                already_handled "movie1" && continue
                echo "[TAP] Intro movie — SKIP"
                tap 100 50
            fi

            if echo "$line" | grep -q "SceneTitle::init"; then
                already_handled "title" && continue
                echo "[TAP] Title — skip transition + start"
                sleep 1
                tap 897 540
                sleep 1
                tap 897 540
            fi

            if echo "$line" | grep -q "SceneAgreement::init"; then
                already_handled "eula" && continue
                echo "[TAP] EULA — Accept"
                sleep 2
                tap 1350 950
            fi

            if echo "$line" | grep -q "openBirthRegisterPopup"; then
                already_handled "birth" && continue
                echo "[TAP] Birthday — Register + Confirm"
                sleep 1
                tap 897 648
                sleep 2
                tap 1120 648
            fi

            if echo "$line" | grep -q "SceneTutorialDownload::init"; then
                already_handled "download" && continue
                echo "[TAP] Download — tap download button"
                sleep 1
                tap 897 864
            fi

            if echo "$line" | grep -q "openJewelPopup"; then
                already_handled "jewel" && continue
                echo "[TAP] Jewels — Collect"
                sleep 1
                tap 897 864
            fi

            if echo "$line" | grep -q "openNameRegisterPopup"; then
                already_handled "name" && continue
                echo "[TAP] Name — type Sora + OK"
                sleep 1
                type_text "Sora"
                sleep 1
                tap 897 1037
            fi

            if echo "$line" | grep -q "SceneAvatarEdit::init"; then
                already_handled "avatar" && continue
                echo "[TAP] Avatar — Confirm + OK"
                sleep 2
                tap 1200 1010
                sleep 2
                tap 1087 1026
            fi

            if echo "$line" | grep -q "SceneUnionRegister::init"; then
                already_handled "union_reg" && continue
                echo "[TAP] Union cutscene — SKIP, I understand, select Unicornis"
                sleep 3
                tap 100 50
                sleep 3
                tap 897 1037
                sleep 2
                tap 897 216
            fi

            if echo "$line" | grep -q "openPopUpbeLongToUnion"; then
                already_handled "join_union" && continue
                echo "[TAP] Join Unicornis — OK"
                sleep 1
                tap 1162 815
                sleep 3
                tap 100 50
            fi

            if echo "$line" | grep -q "startTutorialStage"; then
                already_handled "battle" && continue
                echo ""
                echo "=== TUTORIAL BATTLE STARTING ==="
                echo "=== Frida log: $FRIDA_LOG ==="
            fi

        done
        LAST_LINE=$TOTAL
    fi

    # Check if battle started
    grep -q "startTutorialStage" "$FRIDA_LOG" 2>/dev/null && break

    sleep 0.5
done

echo ""
echo "=== Auto tutorial complete ==="
echo "Frida log: $FRIDA_LOG"
wait $FRIDA_PID 2>/dev/null
