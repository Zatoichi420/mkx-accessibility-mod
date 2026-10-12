#!/usr/bin/env python3
"""Build the Windows program, the read-me page, Setup.exe and a portable zip.

    pip install -r requirements.txt -r requirements-dev.txt
    python packaging/build.py

Windows only (PyInstaller builds for the OS it runs on, and the reader is
Windows-only). Needs Inno Setup 6 for the installer step; CI installs it -
see .github/workflows/build.yml. Pass --skip-installer to stop after the
program and zip.

Output, all under dist/:
  mkx-access/                     the program folder (PyInstaller one-dir)
  docs/README.html                      the read me, as shipped in the installer
  MKX-Access-Setup-<version>.exe
  MKX-Access-Portable-<version>.zip
  SHA256SUMS.txt

One-dir rather than one-file on purpose: a one-file build unpacks itself
to a temp folder on every start, which is slower and is the pattern
antivirus heuristics flag most often.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
READER = ROOT / "ocr_reader"
DIST = ROOT / "dist"
APP_NAME = "mkx-access"
NVDA_DIR = READER / "game_a11y_core" / "nvda_controller_client"

ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def read_version() -> str:
    text = (READER / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        sys.exit("Couldn't find __version__ in ocr_reader/version.py")
    return match.group(1)


def check_tag(version: str) -> None:
    ref = os.environ.get("GITHUB_REF", "")
    if ref.startswith("refs/tags/v") and ref[len("refs/tags/v"):] != version:
        sys.exit(f"Tag {ref} doesn't match ocr_reader/version.py ({version}). Bump the version first.")


def run(cmd: list[str]) -> None:
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], cwd=ROOT, check=True)


def build_program() -> Path:
    sep = os.pathsep
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onedir",
        "--windowed",  # no console window, ever - output goes to the log file
        "--name", APP_NAME,
        "--distpath", DIST,
        "--workpath", ROOT / "build" / "pyinstaller",
        "--specpath", ROOT / "build",
        "--paths", READER,
        "--add-data", f"{READER / 'known_screens'}{sep}known_screens",
        "--add-data", f"{READER / 'vocabulary.txt'}{sep}.",
        "--hidden-import", "menu_ocr",
        "--add-data", f"{NVDA_DIR / 'x64' / 'nvdaControllerClient.dll'}{sep}game_a11y_core/nvda_controller_client/x64",
        "--add-data", f"{NVDA_DIR / 'license.txt'}{sep}game_a11y_core/nvda_controller_client",
        # winsdk loads each WinRT namespace from one native module at import
        # time; name the four the reader uses so they're always bundled.
        "--hidden-import", "winsdk.windows.media.ocr",
        "--hidden-import", "winsdk.windows.graphics.imaging",
        "--hidden-import", "winsdk.windows.storage.streams",
        "--hidden-import", "winsdk.windows.globalization",
        "--hidden-import", "win32com.client",
        "--exclude-module", "tkinter",
        READER / "main.py",
    ])
    program_dir = DIST / APP_NAME
    if not (program_dir / f"{APP_NAME}.exe").is_file():
        sys.exit(f"PyInstaller finished but {APP_NAME}.exe is missing")
    return program_dir


def build_readme_html(version: str) -> Path:
    import markdown

    source = (ROOT / "README.md").read_text(encoding="utf-8")
    body = markdown.markdown(source, extensions=["extra", "sane_lists", "toc"])
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mortal Kombat X accessibility reader {version} - read me</title>
<style>
body {{ font-family: Segoe UI, system-ui, sans-serif; font-size: 1.1rem; line-height: 1.6;
       max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #111; background: #fff; }}
code, kbd {{ font-family: Consolas, monospace; background: #f2f2f2; padding: 0 .2em; }}
pre {{ background: #f2f2f2; padding: .8rem; overflow-x: auto; }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""
    out = DIST / "docs" / "README.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def find_iscc() -> Path | None:
    found = shutil.which("iscc") or shutil.which("ISCC")
    if found:
        return Path(found)
    for candidate in ISCC_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def build_installer(version: str) -> Path:
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup 6 (ISCC.exe) not found. Install it, or pass --skip-installer.")
    run([iscc, f"/DAppVersion={version}", ROOT / "packaging" / "installer.iss"])
    setup = DIST / f"MKX-Access-Setup-{version}.exe"
    if not setup.is_file():
        sys.exit(f"Inno Setup finished but {setup.name} is missing")
    return setup


def build_portable_zip(version: str, program_dir: Path, readme_html: Path) -> Path:
    staging = ROOT / "build" / "portable" / f"MKX-Access-{version}"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(program_dir, staging)
    shutil.copy2(readme_html, staging / "README.html")
    shutil.copy2(ROOT / "LICENSE", staging / "LICENSE.txt")
    shutil.copy2(ROOT / "NOTICE", staging / "NOTICE.txt")
    base = DIST / f"MKX-Access-Portable-{version}"
    return Path(shutil.make_archive(str(base), "zip", staging.parent, staging.name))


def write_checksums(files: list[Path]) -> Path:
    out = DIST / "SHA256SUMS.txt"
    lines = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}" for f in files]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-installer", action="store_true", help="don't run Inno Setup")
    args = parser.parse_args()

    if sys.platform != "win32":
        sys.exit("The reader is Windows-only; build it on Windows (CI does this on windows-latest).")

    version = read_version()
    check_tag(version)
    print(f"Building version {version}", flush=True)

    if DIST.exists():
        shutil.rmtree(DIST)
    program_dir = build_program()
    readme_html = build_readme_html(version)
    artifacts = [build_portable_zip(version, program_dir, readme_html)]
    if not args.skip_installer:
        artifacts.insert(0, build_installer(version))
    sums = write_checksums(artifacts)
    print("Built:", *[a.name for a in artifacts], sums.name, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
