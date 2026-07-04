"""Auto-tap through KHUx tutorial by polling Frida log output."""
import subprocess
import time
import sys
import os

# Fixed log path — frida_run.py always writes here
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "frida_log")
LOG_PATH = os.path.join(LOG_DIR, "latest.log")

def tap(x, y):
    subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)],
                   capture_output=True, timeout=10)

def text(s):
    subprocess.run(["adb", "shell", "input", "text", s],
                   capture_output=True, timeout=10)

def key(code):
    subprocess.run(["adb", "shell", "input", "keyevent", str(code)],
                   capture_output=True, timeout=10)

log_path = sys.argv[1] if len(sys.argv) > 1 else LOG_PATH
handled = set()
last_line = 0

def check_new_lines():
    global last_line
    if not os.path.exists(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    new = lines[last_line:]
    last_line = len(lines)
    return new

def already_handled(tag):
    if tag in handled:
        return True
    handled.add(tag)
    return False

print("=== KHUx Auto Taps ===")
print(f"Watching: {log_path}")
print("Waiting for game...")

while True:
    new_lines = check_new_lines()
    for line in new_lines:
        line = line.strip()

        if "SceneMovie" in line and not already_handled("movie"):
            print("[TAP] Intro movie — SKIP")
            tap(100, 50)

        if "SceneTitle" in line and not already_handled("title"):
            print("[TAP] Title — skip + start")
            tap(897, 540)
            time.sleep(1)
            tap(897, 540)
            time.sleep(0.5)
            tap(897, 540)

        if "SceneTutorialDownload" in line and not already_handled("download"):
            print("[TAP] Download")
            tap(897, 864)
            time.sleep(3)
            tap(897, 864)

        if "SceneNameRegister" in line and not already_handled("name"):
            print("[TAP] Name — Sora")
            tap(897, 520)
            text("Sora")
            key(66)
            time.sleep(0.2)
            tap(897, 1037)

        if "SceneAvatarEdit" in line and not already_handled("avatar"):
            print("[TAP] Avatar — Confirm + OK")
            tap(1200, 1010)
            time.sleep(0.2)
            tap(1087, 1026)

        if "SceneUnionRegister" in line and not already_handled("union"):
            print("[TAP] Union — SKIP, OK, Unicornis, Join, SKIP")
            tap(100, 50)
            time.sleep(0.2)
            tap(897, 1037)
            time.sleep(0.2)
            tap(897, 216)
            time.sleep(0.2)
            tap(1162, 815)
            time.sleep(0.2)
            tap(100, 50)

        if "SceneActionMap" in line and not already_handled("battle"):
            print("")
            print("=== TUTORIAL BATTLE STARTED ===")

        if "process-terminated" in line:
            print("Game ended. Ctrl+C to exit.")

    time.sleep(0.5)
