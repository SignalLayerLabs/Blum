from app.core import release


def test_baked_revision_takes_priority_over_a_new_runtime_variable(tmp_path, monkeypatch):
    path = tmp_path / 'revision.json'
    path.write_text('{"source_revision":"' + 'a'*40 + '"}')
    monkeypatch.setattr(release, 'BUILD_REVISION', path)
    monkeypatch.setenv('BLUM_SOURCE_REVISION', 'b'*40)
    assert release.source_revision() == 'a'*40


def test_invalid_baked_revision_does_not_relabel_the_image_from_environment(tmp_path, monkeypatch):
    path = tmp_path / 'revision.json'
    path.write_text('{"source_revision":"invalid"}')
    monkeypatch.setattr(release, 'BUILD_REVISION', path)
    monkeypatch.setenv('BLUM_SOURCE_REVISION', 'b'*40)
    assert release.source_revision() == 'unavailable'
