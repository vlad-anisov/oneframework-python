"""Android builder: production web build -> Capacitor sync -> Gradle -> APK.

Deliberately end-to-end. ``oneframework build android app.py`` must produce an
installable artifact, not a set of instructions.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..assets import project_root
from . import web as web_builder

APK_RELATIVE = Path("android/app/build/outputs/apk/debug/app-debug.apk")


def _find_android_sdk() -> Path:
    for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(env)
        if value and Path(value).exists():
            return Path(value)
    default = Path.home() / "Library" / "Android" / "sdk"
    if default.exists():
        return default
    linux = Path.home() / "Android" / "Sdk"
    if linux.exists():
        return linux
    raise SystemExit(
        "Android SDK not found. Set ANDROID_HOME or install it via Android Studio."
    )


def _find_jdk(minimum=21) -> Path | None:
    """Capacitor 8 needs JDK 21+; prefer an explicit JAVA_HOME when adequate."""
    candidates = []
    java_home = os.environ.get("JAVA_HOME")
    if java_home and Path(java_home).exists():
        candidates.append(Path(java_home))

    try:
        out = subprocess.run(
            ["/usr/libexec/java_home", "-V"], capture_output=True, text=True
        ).stderr
        for line in out.splitlines():
            if "/" not in line:
                continue
            path = Path(line.split(" ", 1)[-1].strip().split('" ')[-1].strip())
            if path.exists():
                candidates.append(path)
    except FileNotFoundError:
        pass

    for base in (Path("/opt/homebrew/opt"), Path("/usr/lib/jvm")):
        if base.exists():
            for entry in sorted(base.glob("*jdk*")):
                for suffix in ("libexec/openjdk.jdk/Contents/Home", "", "Contents/Home"):
                    path = entry / suffix if suffix else entry
                    if (path / "bin" / "javac").exists():
                        candidates.append(path)

    best = None
    for path in candidates:
        version = _java_major(path)
        if version is None or version < minimum:
            continue
        if best is None or version < best[0]:  # smallest version that qualifies
            best = (version, path)
    return best[1] if best else None


def _java_major(java_home: Path):
    binary = java_home / "bin" / "java"
    if not binary.exists():
        return None
    try:
        out = subprocess.run(
            [str(binary), "-version"], capture_output=True, text=True
        ).stderr
        token = out.split('"')[1]
        parts = token.split(".")
        return int(parts[1]) if parts[0] == "1" else int(parts[0])
    except Exception:
        return None


def _run(command, cwd, env=None, label=None):
    print(f"$ {' '.join(str(c) for c in command)}")
    result = subprocess.run(
        [str(c) for c in command], cwd=cwd, env={**os.environ, **(env or {})}
    )
    if result.returncode != 0:
        raise SystemExit(f"{label or 'command'} failed (exit {result.returncode})")


def ensure_platform(root: Path, env: dict) -> None:
    if (root / "android").exists():
        return
    print("Adding the Capacitor Android platform...")
    _run(["npx", "--no-install", "cap", "add", "android"], root, env, "cap add android")


def write_local_properties(root: Path, sdk: Path) -> None:
    target = root / "android" / "local.properties"
    text = f"sdk.dir={sdk}\n"
    if not target.exists() or target.read_text() != text:
        target.write_text(text)


def build(app_file: Path, app, install: bool = False) -> Path:
    root = project_root()

    # 1. production web build (this is what ships inside the APK)
    web_builder.build(app_file, app)

    sdk = _find_android_sdk()
    jdk = _find_jdk()
    if jdk is None:
        raise SystemExit(
            "No JDK 21+ found. Capacitor 8 requires it "
            "(e.g. 'brew install openjdk@21')."
        )
    print(f"Android SDK: {sdk}\nJDK: {jdk}")
    env = {"JAVA_HOME": str(jdk), "ANDROID_HOME": str(sdk), "ANDROID_SDK_ROOT": str(sdk)}

    # 2. Capacitor project + sync
    ensure_platform(root, env)
    write_local_properties(root, sdk)
    _run(["npx", "--no-install", "cap", "sync", "android"], root, env, "cap sync")

    # 3. Gradle
    gradlew = root / "android" / "gradlew"
    gradlew.chmod(0o755)
    _run([gradlew, "assembleDebug", "--console=plain"], root / "android", env, "gradle")

    apk = root / APK_RELATIVE
    if not apk.exists():
        raise SystemExit(f"Gradle finished but no APK at {apk}")

    size_mb = apk.stat().st_size / 1e6
    print(f"\nAndroid APK:\n{apk}  ({size_mb:.1f} MB)")

    if install:
        adb = sdk / "platform-tools" / "adb"
        _run([adb, "install", "-r", apk], root, env, "adb install")
        package = _package_name(root)
        _run(
            [adb, "shell", "monkey", "-p", package, "-c",
             "android.intent.category.LAUNCHER", "1"],
            root, env, "launch",
        )
    return apk


def _package_name(root: Path) -> str:
    config = root / "capacitor.config.json"
    if config.exists():
        return json.loads(config.read_text()).get("appId", "com.example.app")
    return "com.example.app"
