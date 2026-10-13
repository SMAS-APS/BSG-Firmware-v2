"""Costruisce un contenitore .ammsfw riproducibile per BSG ESP32."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import zipfile
import os
import sys


ROOT = Path(__file__).resolve().parents[1]


def source_files(root):
    from tools.build_web_assets import build_assets
    values = [(root / "main.py", "main.py")]
    values += [(asset, asset.name) for asset in build_assets(root)]
    values += [(path, "modules/" + path.name) for path in sorted((root / "modules").glob("*.py"))
               if not path.name.startswith("ota_")]
    library = root / "external" / "AMMSUtils"
    values += [(path, "lib/" + path.relative_to(library).as_posix())
               for path in sorted((library / "amms").rglob("*.py"))]
    return values


def build_release(root=ROOT, output=None, version=None):
    root = Path(root).resolve()
    runtime = runpy.run_path(str(root / "modules" / "bsg_runtime.py"))
    version = version or runtime["FIRMWARE_VERSION"]
    files = []
    payload = []
    for source, relative in source_files(root):
        body = source.read_bytes()
        if source.suffix == ".py":
            compile(body.decode("utf-8"), str(source), "exec")
        files.append({"path": relative, "size": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        payload.append((relative, body))
    manifest = {
        "schema": 2, "target": "bsg-esp32", "version": version, "format": "files",
        "compatibility": {
            "board": runtime["FIRMWARE_BOARD"],
            "firmware_schema": runtime["FIRMWARE_SCHEMA"],
            "native_api": runtime["NATIVE_API"],
            "rf_driver_revision": runtime["RF_DRIVER_REVISION"],
        },
        "files": files,
    }
    destination = Path(output or root / ("amms-bsg-%s.ammsfw" % version)).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".bsg-ota-", suffix=".ammsfw")
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            entries = [("manifest.json", json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode())]
            entries += [("payload/" + relative, body) for relative, body in payload]
            for name, body in entries:
                info = zipfile.ZipInfo(name)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.external_attr = 0o100644 << 16
                archive.writestr(info, body)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return destination, manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Crea release OTA BSG .ammsfw")
    parser.add_argument("--output")
    parser.add_argument("--version")
    args = parser.parse_args(argv)
    path, manifest = build_release(output=args.output, version=args.version)
    print(json.dumps({"path": str(path), "target": manifest["target"],
                      "version": manifest["version"], "files": len(manifest["files"])}, indent=2))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
