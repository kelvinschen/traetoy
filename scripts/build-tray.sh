#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/macos-app/build/Passport.app"
mkdir -p "$APP/Contents/MacOS"
xcrun swiftc -O -swift-version 5 -framework AppKit -framework ServiceManagement "$ROOT/macos-app/Sources/Socket.swift" "$ROOT/macos-app/Sources/main.swift" -o "$APP/Contents/MacOS/Passport"
/usr/bin/python3 - "$APP" "$ROOT" <<'PY'
import plistlib,sys
from pathlib import Path
app,root=sys.argv[1:]
p={'CFBundleIdentifier':'cn.traetoy.passport','CFBundleName':'Passport','CFBundleDisplayName':'Passport','CFBundleExecutable':'Passport','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.5.0','CFBundleVersion':'5','LSUIElement':True,'LSMinimumSystemVersion':'13.0','PassportWorkspace':root,'NSHighResolutionCapable':True}
Path(app,'Contents/Info.plist').write_bytes(plistlib.dumps(p))
PY
codesign --force --sign - "$APP"
echo "Built $APP"
