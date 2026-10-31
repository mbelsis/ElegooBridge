#!/bin/sh
# Builds "Stamp for Bambuddy.app", a drag-and-drop Mac app around
# stamp_for_bambuddy.py. Needs only macOS (osacompile and codesign are built in).
#
#   ./stamp/build-mac-app.sh        -> stamp/dist/Stamp for Bambuddy.app
set -e
here="$(cd "$(dirname "$0")" && pwd)"
dist="$here/dist"
app="$dist/Stamp for Bambuddy.app"

# Build outside the project folder: iCloud-synced folders add file attributes
# that make code signing fail.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
built="$work/Stamp for Bambuddy.app"
osacompile -o "$built" "$here/mac/Stamp for Bambuddy.applescript"
cp "$here/stamp_for_bambuddy.py" "$built/Contents/Resources/"
plist="$built/Contents/Info.plist"

/usr/libexec/PlistBuddy -c "Set :CFBundleName Stamp for Bambuddy" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string org.elegoobridge.stamp" "$plist" 2>/dev/null ||
    /usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier org.elegoobridge.stamp" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 1.0" "$plist" 2>/dev/null || true
# Accept dropped files and folders.
/usr/libexec/PlistBuddy -c "Delete :CFBundleDocumentTypes" "$plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes array" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0 dict" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string Print file or folder" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string public.data" "$plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:1 string public.folder" "$plist"

codesign --force --deep --sign - "$built"

rm -rf "$app"
mkdir -p "$dist"
ditto "$built" "$app"
# iCloud may re-add attributes after the copy; clear them and re-sign until clean.
for attempt in 1 2 3 4 5; do
    xattr -cr "$app"
    if codesign --force --deep --sign - "$app" 2>/dev/null && codesign --verify --deep "$app" 2>/dev/null; then
        echo "Built: $app"
        exit 0
    fi
    sleep 1
done
echo "Built, but signing failed (iCloud attributes). The unsigned app is at: $app" >&2
exit 1
