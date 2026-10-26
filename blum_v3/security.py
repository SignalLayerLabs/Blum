"""Bound request buffering before application parsing or financial side effects."""
from starlette.responses import JSONResponse


class RequestBodyLimit:
    def __init__(self,app,*,limit=25_000_000):self.app=app;self.limit=limit

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('method') not in {'POST','PUT','PATCH'}:
            return await self.app(scope,receive,send)
        messages=[];size=0
        while True:
            message=await receive()
            if message['type']=='http.disconnect':return
            size+=len(message.get('body',b''))
            if size>self.limit:
                response=JSONResponse({'detail':'request_too_large'},status_code=413,headers={'Connection':'close','Cache-Control':'no-store'})
                return await response(scope,receive,send)
            messages.append(message)
            if not message.get('more_body',False):break
        index=0
        async def replay():
            nonlocal index
            if index<len(messages):
                message=messages[index];index+=1;return message
            return await receive()
        return await self.app(scope,replay,send)
