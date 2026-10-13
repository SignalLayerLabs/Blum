from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from app.api.public_access import public_access_error


def test_public_mode_never_invokes_mutating_get_or_post_handlers():
    app = FastAPI()
    invoked = []
    @app.get('/ipo-radar/sec-submissions/{cik}')
    def unsafe_get(cik: str):
        invoked.append(cik)
        return {'written':True}
    @app.post('/operator/run')
    def unsafe_post():
        invoked.append('post')
        return {'written':True}
    @app.get('/health')
    def health():
        return {'status':'ok'}
    @app.middleware('http')
    async def guard(request: Request, call_next):
        error = public_access_error(request, app.router.routes, enabled=True, admin_key='private-test-key')
        return error if error is not None else await call_next(request)
    client = TestClient(app)
    assert client.get('/health').status_code == 200
    assert client.get('/ipo-radar/sec-submissions/123?persist=false').status_code == 403
    assert client.post('/operator/run').status_code == 403
    for alias in ['yes','on','y','t','1','true']:
        assert client.get('/health?persist='+alias).status_code == 403
    assert invoked == []
    assert client.post('/operator/run',headers={'X-BLUM-Admin-Key':'private-test-key'}).status_code == 200
    assert invoked == ['post']


def test_static_path_cannot_escape_export_root(tmp_path, monkeypatch):
    import app.main as main
    public = tmp_path / 'static'
    public.mkdir()
    (public/'index.html').write_text('public')
    (tmp_path/'private.txt').write_text('private')
    monkeypatch.setattr(main,'STATIC_DIR',public)
    assert main.serve_frontend('../private.txt').status_code == 404
    assert main.serve_frontend('/etc/passwd').status_code == 404
