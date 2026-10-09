#!/usr/bin/env python3
"""Fail-closed policy validation for EmuFusion's one-app Phase 3 research set."""
import json, re, sys
from pathlib import Path

EXPECTED = {"3do","psvita","wiiu","switch","ps3","xbox","xbox360","windows"}
GATES = {"source","license","dependencies","androidArm64","firmware","legalContent","renderer","state","performance","device"}

def validate(data):
    errors=[]
    if data.get("schemaVersion") != 1: errors.append("schemaVersion must be 1")
    if data.get("oneAppContract") is not True: errors.append("oneAppContract must be true")
    if set(data.get("expectedSystems",[])) != EXPECTED: errors.append("expectedSystems differs from Phase 3")
    seen_ids=set(); seen_systems=set()
    for row in data.get("engines",[]):
        engine=row.get("id","")
        if engine in seen_ids: errors.append(f"duplicate engine {engine}")
        seen_ids.add(engine)
        if row.get("status") != "research" or row.get("shipped") is not False:
            errors.append(f"{engine}: Phase 3 must remain research/unshipped")
        if row.get("route") not in {"libretro-core","native-adapter","container-adapter"}:
            errors.append(f"{engine}: route must remain inside Lucent")
        source=row.get("source") or {}
        if not str(source.get("repository","")).startswith("https://") or not re.fullmatch(r"[0-9a-f]{40}",str(source.get("commit",""))):
            errors.append(f"{engine}: current upstream identity is missing")
        archive, archive_hash = source.get("archive"), source.get("archiveSha256")
        if bool(archive) != bool(archive_hash) or (archive and
                (not str(archive).startswith("https://") or
                 not re.fullmatch(r"[0-9a-f]{64}", str(archive_hash)))):
            errors.append(f"{engine}: source archive identity is incomplete")
        gates=row.get("gates") or {}
        if set(gates) != GATES or any(value is not False for value in gates.values()):
            errors.append(f"{engine}: research gates must fail closed")
        for system in row.get("systems",[]):
            if system in seen_systems: errors.append(f"duplicate system owner {system}")
            seen_systems.add(system)
    if seen_systems != EXPECTED: errors.append("engine coverage differs from expectedSystems")
    return errors

def main():
    path=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).parents[1]/"engines/phase3-registry.json"
    errors=validate(json.loads(path.read_text()))
    if errors:
        print("\n".join(errors)); return 1
    print(f"Phase 3 registry valid: {path}"); return 0
if __name__ == "__main__": raise SystemExit(main())
