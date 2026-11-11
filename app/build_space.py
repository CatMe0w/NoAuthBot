import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
MODULES = ("__init__.py", "decode.py", "peaks.py", "runtime.py")

HEADER = """---
title: NoAuthBot
emoji: 🪃
colorFrom: gray
colorTo: red
sdk: gradio
sdk_version: 6.31.0
python_version: "3.12"
app_file: app/app.py
pinned: false
---
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    args = parser.parse_args()

    out = args.out
    for name in ("app", "noauthbot"):
        shutil.rmtree(out / name, ignore_errors=True)
    shutil.copytree(
        APP, out / "app", ignore=shutil.ignore_patterns("__pycache__", ".venv", "build_space.py", "requirements.txt")
    )
    (out / "noauthbot").mkdir(parents=True)
    for module in MODULES:
        shutil.copy2(ROOT / "noauthbot" / module, out / "noauthbot" / module)
    shutil.copy2(APP / "requirements.txt", out / "requirements.txt")
    (out / "README.md").write_text(HEADER, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
