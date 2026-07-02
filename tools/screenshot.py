"""Take a screenshot from the phone and describe it via Florence-2."""
import base64, json, urllib.request, os, subprocess, sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_env_file = os.path.join(_ROOT, ".env")
if os.path.isfile(_env_file):
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

PHONE = os.getenv("KHUX_PHONE", "127.0.0.1:5555")
FLORENCE = os.getenv("KHUX_FLORENCE_URL", "http://localhost:17778/describe_base64")
LOCAL_PATH = os.path.join(os.getenv("KHUX_REPO_DIR", _ROOT), "screen.png")

subprocess.run(["adb", "-s", PHONE, "shell", "screencap -p /sdcard/screen.png"], check=True)
subprocess.run(["adb", "-s", PHONE, "pull", "//sdcard/screen.png", LOCAL_PATH],
               capture_output=True, check=True)

with open(LOCAL_PATH, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

size = os.path.getsize(LOCAL_PATH)
print(f"Screenshot: {size:,} bytes")

tasks = sys.argv[1:] if len(sys.argv) > 1 else ["more_detailed", "ocr"]
for task in tasks:
    data = json.dumps({"image": b64, "task": task}).encode()
    req = urllib.request.Request(FLORENCE, data=data,
                                headers={"Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(req).read())["description"]
    print(f"{task}: {result}")
