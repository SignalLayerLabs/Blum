from pathlib import Path


def test_release_hash_detects_protected_code_changes_and_ignores_generated_revision(tmp_path):
    from app.core.release import content_hash_for_root
    source=tmp_path/'backend/app/core'
    source.mkdir(parents=True)
    file=source/'example.py'
    file.write_text('value = 1\n')
    scripts=tmp_path/'scripts'
    scripts.mkdir()
    script=scripts/'start.sh'
    script.write_text('exit 0\n')
    original=content_hash_for_root(tmp_path)
    (source/'build_revision.json').write_text('{"source_revision":"changed"}')
    assert content_hash_for_root(tmp_path)==original
    file.write_text('value = 2\n')
    changed=content_hash_for_root(tmp_path)
    assert changed!=original
    script.write_text('exit 1\n')
    assert content_hash_for_root(tmp_path)!=changed


def test_identical_release_code_has_same_hash_across_checkout_paths(tmp_path):
    from app.core.release import content_hash_for_root
    for name in ['first','second']:
        file=tmp_path/name/'backend/app/example.py'
        file.parent.mkdir(parents=True)
        file.write_text('identical protected source\n')
    assert content_hash_for_root(tmp_path/'first')==content_hash_for_root(tmp_path/'second')
