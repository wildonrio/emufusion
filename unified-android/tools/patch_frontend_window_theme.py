#!/usr/bin/env python3
"""Give the Qt activity an explicit no-action-bar theme before decor inflation.

The upstream APK spells its theme attribute ``android.theme`` (no namespace).
Android ignores that attribute and supplies its default action-bar theme. On
Android 16 a deferred menu invalidation can then construct WindowDecorActionBar
while Qt's immersive flags already request hiding it, crashing in doHide().
Qt owns the whole window and does not need a framework action bar.

The Qt 5 loader also replaces custom app themes with its framework fallback and
requests FEATURE_ACTION_BAR at runtime. Repairing resources alone is therefore
insufficient: keep the manifest theme and omit that unused feature request.
"""

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

ANDROID = "http://schemas.android.com/apk/res/android"
NAME = "{" + ANDROID + "}name"
THEME = "{" + ANDROID + "}theme"
ACTIVITY = "org.pegasus_frontend.android.MainActivity"
STYLE = "PegasusMain"
PARENT = "@android:style/Theme.DeviceDefault.NoActionBar.Fullscreen"
ITEMS = {"android:windowActionBar": "false", "android:windowNoTitle": "true"}
LOADER = Path("smali/org/qtproject/qt5/android/bindings/QtActivityLoader.smali")
LOADER_METHOD = ".method public onCreate(Landroid/os/Bundle;)V"
LOADER_EDITS = (
    ("    invoke-virtual {v1, v0}, Lorg/qtproject/qt5/android/bindings/QtActivity;->setTheme(I)V",
     "    # EmuFusion: retain the manifest's custom no-action-bar window theme.\n    nop"),
    ("    const/16 v1, 0x8\n\n"
     "    invoke-virtual {v0, v1}, Lorg/qtproject/qt5/android/bindings/QtActivity;->requestWindowFeature(I)Z",
     "    # EmuFusion: Qt owns the window; do not request FEATURE_ACTION_BAR.\n    nop"),
)


def patched_loader(decoded: Path):
    """Validate the pinned loader before any file changes; preserve other code."""
    source = (decoded / LOADER).read_text(encoding="utf-8")
    if source.count(LOADER_METHOD) != 1:
        raise ValueError("Unexpected Qt loader onCreate method")
    start = source.index(LOADER_METHOD)
    end = source.index(".end method", start)
    method = source[start:end]
    for old, new in LOADER_EDITS:
        if method.count(old) == 1 and new not in method:
            method = method.replace(old, new, 1)
        elif method.count(new) != 1 or old in method:
            raise ValueError("Unexpected Qt loader theme/action-bar instructions")
    if "->setTheme(I)V" in method or "->requestWindowFeature(I)Z" in method:
        raise ValueError("Qt loader retains a window-theme override")
    return source, source[:start] + method + source[end:]


def read_targets(decoded: Path):
    manifest = ET.parse(decoded / "AndroidManifest.xml")
    styles = ET.parse(decoded / "res/values/styles.xml")
    activities = [item for item in manifest.findall("./application/activity")
                  if item.get(NAME) == ACTIVITY]
    themes = [item for item in styles.getroot().findall("style")
              if item.get("name") == STYLE]
    if len(activities) != 1 or len(themes) != 1:
        raise ValueError("Expected exactly one Qt MainActivity and PegasusMain style")
    return manifest, styles, activities[0], themes[0]


def check(decoded: Path):
    _, _, activity, style = read_targets(decoded)
    if activity.get(THEME) != "@style/" + STYLE or "android.theme" in activity.attrib:
        raise ValueError("Qt activity must use the namespaced android:theme attribute")
    if style.get("parent") != PARENT:
        raise ValueError("Qt activity must inherit the no-action-bar fullscreen theme")
    for name, value in ITEMS.items():
        found = [item.text for item in style.findall("item") if item.get("name") == name]
        if found != [value]:
            raise ValueError("Qt window theme must set " + name + "=" + value + " exactly once")
    source, repaired = patched_loader(decoded)
    if source != repaired:
        raise ValueError("Qt loader must preserve the manifest window theme")


def patch(decoded: Path):
    # Resolve all inputs before writing any: never silently patch another
    # activity or manufacture a missing upstream resource.
    manifest, styles, activity, style = read_targets(decoded)
    _, loader = patched_loader(decoded)
    activity.attrib.pop("android.theme", None)
    activity.set(THEME, "@style/" + STYLE)
    style.set("parent", PARENT)
    for name, value in ITEMS.items():
        for old in list(style.findall("item")):
            if old.get("name") == name:
                style.remove(old)
        ET.SubElement(style, "item", {"name": name}).text = value
    ET.register_namespace("android", ANDROID)
    manifest.write(decoded / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True)
    styles.write(decoded / "res/values/styles.xml", encoding="utf-8", xml_declaration=True)
    (decoded / LOADER).write_text(loader, encoding="utf-8")
    check(decoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decoded", type=Path)
    parser.add_argument("--check", action="store_true", help="Validate without editing")
    args = parser.parse_args()
    (check if args.check else patch)(args.decoded)
    print("Qt frontend window theme: no action bar, fullscreen, namespaced attribute, loader preserves theme")


if __name__ == "__main__":
    main()
