"""Keep a streamed PostgreSQL base backup and its WAL in one checked object.

The outer tar is uncompressed: its members are already gzip archives. Restore
streams both members from one open object without staging another full backup.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


MEMBERS = ("pg_wal.tar.gz", "base.tar.gz")
CHUNK = 1024 * 1024


def pack(source: Path, destination: Path) -> None:
    if set(path.name for path in source.glob("*.tar.gz")) != set(MEMBERS):
        raise ValueError("Expected base and WAL archives only; additional tablespaces are unsupported")
    files = {}
    for name in MEMBERS:
        digest = hashlib.sha256()
        size = 0
        with (source / name).open("rb") as handle:
            while chunk := handle.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
        if not size:
            raise ValueError("Empty recovery member: " + name)
        files[name] = {"size": size, "sha256": digest.hexdigest()}
    manifest = json.dumps({"version": 1, "files": files}, sort_keys=True).encode()
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        archive.addfile(info, io.BytesIO(manifest))
        for name in MEMBERS:
            info = tarfile.TarInfo(name)
            info.size = files[name]["size"]
            with (source / name).open("rb") as handle:
                archive.addfile(info, handle)


class CheckedReader:
    def __init__(self, handle):
        self.handle = handle
        self.digest = hashlib.sha256()
        self.size = 0

    def read(self, size=-1):
        value = self.handle.read(size)
        self.digest.update(value)
        self.size += len(value)
        return value


def restore(bundle: Path, target: Path) -> None:
    with tarfile.open(bundle, "r|") as archive:
        first = archive.next()
        if first is None or first.name != "manifest.json" or not first.isfile() or first.size > 65536:
            raise ValueError("Missing or oversized recovery manifest")
        manifest = json.load(archive.extractfile(first))
        if manifest.get("version") != 1 or set(manifest.get("files", {})) != set(MEMBERS):
            raise ValueError("Invalid recovery manifest")
        seen = set()
        for member in archive:
            if member is first:
                continue
            if member.name not in MEMBERS or member.name in seen or not member.isfile():
                raise ValueError("Unexpected or duplicate recovery member")
            expected = manifest["files"][member.name]
            if member.size != expected.get("size"):
                raise ValueError("Recovery member size mismatch")
            reader = CheckedReader(archive.extractfile(member))
            directory = target / "pg_wal" if member.name == "pg_wal.tar.gz" else target
            directory.mkdir(parents=True, exist_ok=True)
            with tarfile.open(fileobj=reader, mode="r|gz") as nested:
                nested.extractall(directory, filter="data")
            while reader.read(CHUNK):
                pass
            if reader.size != member.size or reader.digest.hexdigest() != expected.get("sha256"):
                raise ValueError("Recovery member checksum mismatch")
            seen.add(member.name)
        if seen != set(MEMBERS):
            raise ValueError("Incomplete recovery bundle")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    {"pack": pack, "restore": restore}[arguments.operation](arguments.source, arguments.destination)
