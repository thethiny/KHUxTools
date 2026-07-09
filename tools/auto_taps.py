"""Auto-tap through KHUx tutorial by polling Frida log output.

Usage:
    python tools/auto_taps.py                    # full run including battle
    python tools/auto_taps.py --skip-battle      # stop at battle's first OK
"""
import argparse
import subprocess
import time
import os

# Fixed log path — frida_run.py always writes here
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "frida_log")
LOG_PATH = os.path.join(LOG_DIR, "latest.log")

parser = argparse.ArgumentParser()
parser.add_argument("log", nargs="?", default=None, help="Log file path")
parser.add_argument("--skip-battle", action="store_true", help="Stop at battle's first OK popup")
cli_args = parser.parse_args()

def tap(x, y):
    subprocess.run(["adb", "shell", "input", "tap", str(x), str(y)],
                   capture_output=True, timeout=5)

def text(s):
    subprocess.run(["adb", "shell", "input", "text", s],
                   capture_output=True, timeout=5)

def swipe(x1, y1, x2, y2, ms=300):
    subprocess.run(["adb", "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms)],
                   capture_output=True, timeout=5)

def key(code):
    subprocess.run(["adb", "shell", "input", "keyevent", str(code)],
                   capture_output=True, timeout=5)

log_path = cli_args.log or LOG_PATH
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

        if "SceneAgreement" in line and not already_handled("eula"):
            print("[TAP] EULA — accept")
            time.sleep(1)
            tap(1226, 1026)

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
            time.sleep(0.5)
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
            print("[BATTLE] popup")
            time.sleep(5.0)
            tap(897, 1026)
            if cli_args.skip_battle:
                print("=== SKIP BATTLE — stopped at first OK ===")
                continue
            print("[BATTLE] move to enemy 1")
            time.sleep(0.5)
            tap(1286, 402)
            time.sleep(0.5)
            swipe(1300, 540, 1300, 540, 600)
            print("[BATTLE] popup")
            time.sleep(2.0)
            tap(897, 1026)
            print("[BATTLE] attack x3")
            time.sleep(0.5)
            swipe(1440, 540, 480, 540)
            time.sleep(0.6)
            swipe(1440, 540, 480, 540)
            time.sleep(0.6)
            swipe(1440, 540, 480, 540)
            print("[BATTLE] walk to enemy 2")
            time.sleep(0.5)
            swipe(1440, 540, 1440, 540, 2000)
            print("[BATTLE] attack x3")
            time.sleep(0.5)
            swipe(1440, 540, 480, 540)
            time.sleep(0.6)
            swipe(1440, 540, 480, 540)
            time.sleep(0.6)
            swipe(1440, 540, 480, 540)
            print("[BATTLE] move to phase 2")
            time.sleep(0.5)
            swipe(1440, 540, 1440, 540, 2000)
            print("[BATTLE] popup")
            time.sleep(1.0)
            tap(897, 1026)
            print("[BATTLE] open chest")
            time.sleep(1.0)
            tap(975, 208)
            print("[BATTLE] popup")
            time.sleep(1.0)
            tap(897, 1026)
            print("[BATTLE] walk to boss")
            time.sleep(1.0)
            tap(1388, 234)
            time.sleep(0.5)
            swipe(1440, 540, 1440, 540, 2000)
            print("[BATTLE] boss animation")
            time.sleep(5.0)
            tap(897, 1026)
            print("[BATTLE] medal swipe")
            time.sleep(0.5)
            swipe(145, 794, 960, 540, 500)
            print("[BATTLE] attack x2")
            time.sleep(5.0)
            swipe(1440, 540, 480, 540)
            time.sleep(0.6)
            swipe(1440, 540, 480, 540)
            print("[BATTLE] popup")
            time.sleep(0.5)
            tap(897, 1026)
            print("[BATTLE] victory")
            time.sleep(18.0)
            tap(897, 540)
            print("[BATTLE] claim rewards")
            time.sleep(5.0)
            tap(897, 1026)
            print("[BATTLE] skip cutscene")
            time.sleep(5.0)
            tap(100, 50)
            print("")
            print("=== BATTLE DONE ===")

        if "process-terminated" in line:
            print("Game ended. Ctrl+C to exit.")

    time.sleep(0.5)
