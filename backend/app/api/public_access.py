"""One shared, reviewed public API boundary; legacy operations stay private."""
from hmac import compare_digest
import json
from pathlib import Path

from fastapi.routing import APIRoute
from starlette.responses import JSONResponse
from starlette.routing import Match

PUBLIC_ROUTES = frozenset(json.loads((Path(__file__).parents[1] / 'data/public_api_routes.json').read_text()))


def public_access_error(request, routes, *, enabled: bool, admin_key: str):
    if not enabled:
        return None
    supplied = request.headers.get('X-BLUM-Admin-Key', '')
    if admin_key and compare_digest(supplied.encode(), admin_key.encode()):
        return None
    if request.method not in {'GET', 'HEAD'}:
        return JSONResponse({'detail':'Administrative authorization required'}, status_code=403)
    for key, value in request.query_params.multi_items():
        if key.lower() in {'persist', 'refresh', 'rebuild', 'force'} and value.strip().lower() not in {'false', '0'}:
            return JSONResponse({'detail':'Mutating query is not public'}, status_code=403)
    for route in routes:
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            if isinstance(route, APIRoute) and route.path not in PUBLIC_ROUTES and route.path != '/{full_path:path}':
                return JSONResponse({'detail':'This API operation requires administrative authorization'}, status_code=403)
            return None
    return None
