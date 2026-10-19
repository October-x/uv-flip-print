"""Standalone localhost UI, independent of Spoolio and printer accounts."""
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import router

STATIC = Path(__file__).resolve().parents[1] / 'static'
app = FastAPI(title='UV Flip Print', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]'])


@app.middleware('http')
async def local_only(request: Request, call_next):
    if request.method not in {'GET', 'HEAD'}:
        origin = request.headers.get('origin')
        if (request.headers.get('x-uv-local') != '1'
                or (origin and urlsplit(origin).netloc != request.headers.get('host'))):
            return JSONResponse({'detail': '请从本地工作台操作。'}, status_code=403)
        try:
            if int(request.headers.get('content-length', '0')) > 61*1024*1024:
                return JSONResponse({'detail': '上传总大小超过 61 MB。'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': '上传长度无效。'}, status_code=400)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({'detail': '请上传两张或三张图片，检查尺寸和生成格式。'}, status_code=422)


@app.get('/')
@app.get('/uv')
def index():
    return FileResponse(STATIC / 'uv.html')


@app.get('/api/health')
def health():
    return {'uv_generator': True}


app.include_router(router)
app.mount('/static', StaticFiles(directory=STATIC), name='static')
