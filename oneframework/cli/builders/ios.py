"""iOS builder: production web build -> Capacitor sync -> xcodebuild -> .app.

The Android sibling produces a debug APK; the closest honest equivalent here is
a **simulator** build. A device build or an .ipa needs a signing identity and a
provisioning profile, which are an Apple account concern, not a build concern --
so this target stops at the artifact anyone with Xcode can produce and run.

The toolchain is checked in the order the build needs it, and every missing
piece names the command that installs it: the failure mode this target has to
avoid is a wall of Xcode output that never says "install Xcode".
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..assets import project_root
from . import web as web_builder

#: Capacitor always names the iOS target -- and therefore the scheme -- "App".
SCHEME = "App"
PROJECT_RELATIVE = Path("ios/App/App.xcodeproj")
WORKSPACE_RELATIVE = Path("ios/App/App.xcworkspace")
#: the name Capacitor's own ios/.gitignore already excludes
DERIVED_DATA = Path("ios/DerivedData")
PRODUCTS_RELATIVE = DERIVED_DATA / "Build/Products/Debug-iphonesimulator"

_INSTALL_XCODE = (
    "Install Xcode from the App Store (or https://developer.apple.com/xcode/),\n"
    "then point the command line tools at it:\n"
    "    sudo xcode-select -s /Applications/Xcode.app/Contents/Developer\n"
    "    sudo xcodebuild -license accept"
)

#: shown whenever a Capacitor step that may shell out to CocoaPods fails
_INSTALL_COCOAPODS = (
    "If the failure above mentions pods, CocoaPods is missing:\n"
    "    brew install cocoapods    (or: sudo gem install cocoapods)"
)

#: the two things that go wrong in a freshly installed Xcode
_XCODEBUILD_HINT = (
    "If the log says no destination matches 'iOS Simulator', Xcode has no\n"
    "simulator runtime yet: Xcode > Settings > Components > iOS Simulator.\n"
    "The project itself is ready either way: open ios/App/App.xcodeproj"
)


def _run(command, cwd, env=None, label=None, hint=None):
    print(f"$ {' '.join(str(c) for c in command)}")
    result = subprocess.run(
        [str(c) for c in command], cwd=cwd, env={**os.environ, **(env or {})}
    )
    if result.returncode != 0:
        message = f"{label or 'command'} failed (exit {result.returncode})"
        raise SystemExit(f"{message}\n{hint}" if hint else message)


def require_macos() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "iOS builds require macOS: Xcode runs nowhere else. "
            "Use 'build web' for a PWA that iPhones can install from Safari."
        )


def require_capacitor_ios(root: Path) -> None:
    """The platform package Capacitor needs before it can create ios/."""
    if (root / "node_modules" / "@capacitor" / "ios").exists():
        return
    raise SystemExit(
        "@capacitor/ios is not installed. From the project root:\n"
        "    npm install --save-dev @capacitor/ios"
    )


def require_cocoapods(root: Path) -> None:
    """Demand CocoaPods only when this project actually uses it.

    Capacitor 8 wires plugins through Swift Package Manager whenever every
    plugin ships a ``Package.swift``, and then no pod is ever installed. A
    Podfile in ``ios/App`` is the signal that a plugin forced the CocoaPods
    path -- and only then is a missing ``pod`` fatal.
    """
    if not (root / "ios" / "App" / "Podfile").exists() or shutil.which("pod"):
        return
    raise SystemExit(
        "This project's iOS plugins need CocoaPods, which is not installed:\n"
        "    brew install cocoapods    (or: sudo gem install cocoapods)"
    )


def require_xcode() -> str:
    """Return the Xcode version line, or explain exactly what is missing.

    ``xcodebuild`` exists at /usr/bin even with only the Command Line Tools
    installed -- it is a shim that fails at run time -- so its presence proves
    nothing and it has to be asked for its version.
    """
    if shutil.which("xcodebuild") is None:
        raise SystemExit(f"xcodebuild not found.\n\n{_INSTALL_XCODE}")

    probe = subprocess.run(
        ["xcodebuild", "-version"], capture_output=True, text=True
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip()
        raise SystemExit(
            f"Xcode is required to compile the iOS app.\n{detail}\n\n{_INSTALL_XCODE}"
        )
    return probe.stdout.strip().splitlines()[0]


def ensure_platform(root: Path) -> None:
    if (root / "ios").exists():
        return
    print("Adding the Capacitor iOS platform...")
    # 'cap add' is where a CocoaPods project would be created, so this is the
    # one step whose failure may really mean "no pod on this machine".
    hint = None if shutil.which("pod") else _INSTALL_COCOAPODS
    _run(["npx", "--no-install", "cap", "add", "ios"], root, None, "cap add ios", hint)


def xcode_target(root: Path):
    """``-workspace`` when CocoaPods made one, ``-project`` otherwise."""
    if (root / WORKSPACE_RELATIVE).exists():
        return "-workspace", root / WORKSPACE_RELATIVE
    return "-project", root / PROJECT_RELATIVE


def build(app_file: Path, app, install: bool = False) -> Path:
    root = project_root()
    require_macos()

    # 1. production web build (this is what ships inside the app bundle)
    web_builder.build(app_file, app)

    # 2. Capacitor project + sync. Generated before Xcode is demanded, so that a
    #    machine without Xcode still ends up with a project to open.
    require_capacitor_ios(root)
    ensure_platform(root)
    require_cocoapods(root)  # a Podfile means 'cap sync' will run 'pod install'
    _run(["npx", "--no-install", "cap", "sync", "ios"], root, None, "cap sync")

    # 3. Xcode
    print(f"Xcode: {require_xcode()}")
    flag, target = xcode_target(root)
    _run(
        [
            "xcodebuild",
            flag, target,
            # Capacitor generates no shared scheme and relies on Xcode creating
            # one on demand -- 'cap run ios' passes -scheme App the same way.
            "-scheme", SCHEME,
            "-configuration", "Debug",
            # A generic simulator destination needs no device to be booted and
            # no signing identity to exist -- the one build anybody can run.
            "-destination", "generic/platform=iOS Simulator",
            "-derivedDataPath", root / DERIVED_DATA,
            "CODE_SIGNING_ALLOWED=NO",
            "build",
        ],
        root / "ios" / "App",
        None,
        "xcodebuild",
        _XCODEBUILD_HINT,
    )

    bundle = _find_app_bundle(root)
    size_mb = sum(f.stat().st_size for f in bundle.rglob("*") if f.is_file()) / 1e6
    print(f"\niOS app (simulator):\n{bundle}  ({size_mb:.1f} MB)")

    if install:
        install_on_simulator(root, bundle)
    return bundle


def _find_app_bundle(root: Path) -> Path:
    products = root / PRODUCTS_RELATIVE
    bundles = sorted(products.glob("*.app")) if products.exists() else []
    if not bundles:
        raise SystemExit(f"xcodebuild finished but no .app under {products}")
    return bundles[0]


def install_on_simulator(root: Path, bundle: Path) -> None:
    booted = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "booted"],
        capture_output=True, text=True,
    ).stdout
    if "(Booted)" not in booted:
        raise SystemExit(
            "No booted simulator to install into. Start one first:\n"
            "    open -a Simulator"
        )
    _run(["xcrun", "simctl", "install", "booted", bundle], root, None, "simctl install")
    _run(
        ["xcrun", "simctl", "launch", "booted", _app_id(root)],
        root, None, "simctl launch",
    )


def _app_id(root: Path) -> str:
    config = root / "capacitor.config.json"
    if config.exists():
        return json.loads(config.read_text()).get("appId", "com.example.app")
    return "com.example.app"
