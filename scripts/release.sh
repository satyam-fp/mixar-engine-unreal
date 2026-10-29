#!/usr/bin/env bash
# Package MixarLink/ as dist/MixarLink.zip (the zip holds MixarLink/…, ready to
# unpack into a project's Plugins/) and publish it as a GitHub release named
# after the plugin's VersionName. The Mixar app downloads
#   https://github.com/<owner>/mixar-engine-unreal/releases/latest/download/MixarLink.zip
#   scripts/release.sh            # build + publish
#   scripts/release.sh --dry-run  # build only
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION="$(python3 -c 'import json; print(json.load(open("MixarLink/MixarLink.uplugin"))["VersionName"])')"
ADAPTER="$(sed -n 's/^ADAPTER_VERSION = "\(.*\)"/\1/p' MixarLink/Content/Python/mixar_link/__init__.py)"
[ "$VERSION" = "$ADAPTER" ] || { echo "MixarLink.uplugin ($VERSION) and ADAPTER_VERSION ($ADAPTER) differ"; exit 1; }
rm -rf dist && mkdir -p dist
zip -qr -X dist/MixarLink.zip MixarLink -x '*/__pycache__/*' -x '*/.DS_Store'
echo "built dist/MixarLink.zip (v$VERSION, $(wc -c < dist/MixarLink.zip) bytes)"
[ "${1:-}" = "--dry-run" ] && exit 0
gh release create "v$VERSION" dist/MixarLink.zip --title "Mixar Link for Unreal $VERSION" \
  --notes "Unzip into your Unreal project's Plugins/ folder (the Mixar app does this for you). Needs Unreal Engine 5.8+."
