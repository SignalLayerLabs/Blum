"""Exercise real nested archives; a physical recovery cannot mix snapshot generations."""
import hashlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[2]


def recovery_module():
    spec = importlib.util.spec_from_file_location("postgres_recovery", ROOT / "scripts/postgres_recovery.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compressed_archive(path, files):
    with tarfile.open(path, "w:gz") as archive:
        for name, value in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))


def snapshot(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    compressed_archive(source / "base.tar.gz", {"PG_VERSION": b"15\n", "base/1/data": b"generation-one"})
    compressed_archive(source / "pg_wal.tar.gz", {"0000000100000023000000F6": b"same-generation-wal"})
    return source


def rewrite_bundle(path, mutate):
    with tarfile.open(path) as archive:
        files = [(member.name, archive.extractfile(member).read()) for member in archive]
    files = mutate(files)
    with tarfile.open(path, "w") as archive:
        for name, value in files:
            info = tarfile.TarInfo(name)
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))


def test_real_bundle_round_trip_keeps_base_and_wal_together(tmp_path):
    module = recovery_module()
    source = snapshot(tmp_path)
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    with tarfile.open(bundle) as archive:
        assert archive.getnames() == ["manifest.json", "pg_wal.tar.gz", "base.tar.gz"]
        manifest = json.load(archive.extractfile("manifest.json"))
        for name in ["base.tar.gz", "pg_wal.tar.gz"]:
            assert manifest["files"][name]["sha256"] == hashlib.sha256((source / name).read_bytes()).hexdigest()
    target = tmp_path / "local"
    target.mkdir()
    module.restore(bundle, target)
    assert (target / "base/1/data").read_bytes() == b"generation-one"
    assert (target / "pg_wal/0000000100000023000000F6").read_bytes() == b"same-generation-wal"


@pytest.mark.parametrize("layout", ["empty-leading", "split-header", "empty-and-split"])
def test_postgres_wal_concatenated_gzip_members_restore_the_whole_tar(tmp_path, layout):
    module = recovery_module()
    source = snapshot(tmp_path)
    wal = source / "pg_wal.tar.gz"
    raw = gzip.decompress(wal.read_bytes())
    parts = [raw] if layout == "empty-leading" else [raw[:512], raw[512:]]
    if layout != "split-header":
        parts.insert(0, b"")
    wal.write_bytes(b"".join(gzip.compress(part) for part in parts))
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    target = tmp_path / "local"
    module.restore(bundle, target)
    assert (target / "pg_wal/0000000100000023000000F6").read_bytes() == b"same-generation-wal"
    assert (target / "base/1/data").read_bytes() == b"generation-one"


@pytest.mark.parametrize("damage", ["truncated", "crc"])
def test_gzip_trailer_is_validated_even_after_the_tar_end_marker(tmp_path, damage):
    module = recovery_module()
    source = snapshot(tmp_path)
    wal = source / "pg_wal.tar.gz"
    raw = gzip.decompress(wal.read_bytes())
    trailing = bytearray(gzip.compress(b""))
    if damage == "truncated":
        trailing = trailing[:-4]
    else:
        trailing[-8] ^= 1
    wal.write_bytes(gzip.compress(raw) + trailing)
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    with pytest.raises((OSError, EOFError, tarfile.TarError)):
        module.restore(bundle, tmp_path / "local")


def test_other_generation_wal_is_rejected_even_when_it_is_valid_gzip(tmp_path):
    module = recovery_module()
    source = snapshot(tmp_path)
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    newer = tmp_path / "new-wal.gz"
    compressed_archive(newer, {"000000010000002400000000": b"wrong-generation"})
    rewrite_bundle(bundle, lambda files: [(name, newer.read_bytes() if name == "pg_wal.tar.gz" else value) for name, value in files])
    target = tmp_path / "local"
    target.mkdir()
    with pytest.raises(ValueError, match="checksum|size"):
        module.restore(bundle, target)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "truncated"])
def test_incomplete_or_ambiguous_bundle_is_rejected(tmp_path, mutation):
    module = recovery_module()
    source = snapshot(tmp_path)
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    if mutation == "truncated":
        bundle.write_bytes(bundle.read_bytes()[:1300])
    else:
        rewrite_bundle(bundle, lambda files: files[:-1] if mutation == "missing" else files + ([files[-1]] if mutation == "duplicate" else [("extra", b"unexpected")]))
    target = tmp_path / "local"
    target.mkdir()
    with pytest.raises((ValueError, tarfile.TarError, EOFError)):
        module.restore(bundle, target)


def test_additional_tablespaces_are_not_published_as_complete_recovery(tmp_path):
    module = recovery_module()
    source = snapshot(tmp_path)
    (source / "12345.tar.gz").write_bytes(b"external-tablespace")
    with pytest.raises(ValueError, match="tablespace"):
        module.pack(source, tmp_path / "recovery.tar")


def test_archive_cannot_extract_outside_the_local_cluster(tmp_path):
    module = recovery_module()
    source = snapshot(tmp_path)
    compressed_archive(source / "base.tar.gz", {"../outside": b"unsafe"})
    bundle = tmp_path / "recovery.tar"
    module.pack(source, bundle)
    target = tmp_path / "local"
    target.mkdir()
    with pytest.raises(tarfile.FilterError):
        module.restore(bundle, target)
    assert not (tmp_path / "outside").exists()


def run_start_functions(tmp_path, commands):
    fake = tmp_path / "bin"
    fake.mkdir()
    for name in ["service", "chown"]:
        tool = fake / name
        tool.write_text("#!/bin/sh\nexit 0\n")
        tool.chmod(0o700)
    (fake / "python3").symlink_to(sys.executable)
    script = (ROOT / "scripts/start.sh").read_text().split('if [[ -z "${DATABASE_URL:-}" ]]; then')[0]
    script = script.replace("/app/scripts/postgres_recovery.py", str(ROOT / "scripts/postgres_recovery.py"))
    target = tmp_path / "local"
    target.mkdir()
    env = {**os.environ, "PATH": str(fake) + ":/usr/bin:/bin", "BLUM_PERSIST_DIR": str(tmp_path / "data"),
           "BLUM_LOCAL_POSTGRES_DATA_DIR": str(target)}
    return subprocess.run(["/bin/bash", "-c", script + "\n" + commands], env=env, capture_output=True, text=True, timeout=15)


def test_actual_publisher_and_restore_use_one_object_ignoring_legacy_wal(tmp_path):
    source = snapshot(tmp_path)
    command = 'publish_embedded_postgres_physical_backup ' + shlex.quote(str(source)) + '\n'
    command += 'printf invalid > "${BLUM_PHYSICAL_POSTGRES_WAL_BACKUP}"\nrestore_embedded_postgres_physical_backup\n'
    result = run_start_functions(tmp_path, command)
    assert result.returncode == 0, result.stderr
    physical = tmp_path / "data/embedded_postgres_physical"
    assert (physical / "recovery.tar").is_file()
    assert (tmp_path / "local/base/1/data").read_bytes() == b"generation-one"
    assert (tmp_path / "local/pg_wal/0000000100000023000000F6").read_bytes() == b"same-generation-wal"


def test_failed_new_publication_keeps_the_previous_recovery(tmp_path):
    source = snapshot(tmp_path)
    physical = tmp_path / "data/embedded_postgres_physical"
    physical.mkdir(parents=True)
    (physical / "ready").touch()
    (physical / "recovery.tar").write_bytes(b"previous-good-object")
    (source / "pg_wal.tar.gz").unlink()
    result = run_start_functions(tmp_path, 'publish_embedded_postgres_physical_backup ' + shlex.quote(str(source)))
    assert result.returncode != 0
    assert (physical / "ready").exists()
    assert (physical / "recovery.tar").read_bytes() == b"previous-good-object"
