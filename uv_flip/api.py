"""Local UV generator endpoints and a small expiring in-memory download store."""
from collections import OrderedDict
from dataclasses import dataclass
import secrets
import threading
import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from typing import Literal
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .maps import Canvas, Export, MAX_FILE_BYTES, generate_export

router = APIRouter(prefix="/api/uv")
STORE = OrderedDict()
STORE_LOCK = threading.RLock()
GENERATION_LOCK = threading.Lock()
TTL = 3600
MAX_RESULTS = 6
MAX_STORED_BYTES = 160 * 1024 * 1024


@dataclass
class Saved:
    export: Export
    touched: float


def cleanup():
    now = time.monotonic()
    for key in [key for key, value in STORE.items() if now-value.touched > TTL]:
        del STORE[key]


def generate(data, canvas, remove_background=False, output_mode='images'):
    if not GENERATION_LOCK.acquire(blocking=False):
        raise HTTPException(429, "正在生成另一组图片，请稍后再试。")
    try:
        key = secrets.token_urlsafe(18)
        result = generate_export(data, canvas, key, remove_background, output_mode)
        if result.byte_size > MAX_STORED_BYTES:
            raise ValueError("输出文件过大，请减小成品尺寸后重试。")
        with STORE_LOCK:
            cleanup()
            while STORE and (len(STORE) >= MAX_RESULTS or
                             sum(item.export.byte_size for item in STORE.values()) + result.byte_size > MAX_STORED_BYTES):
                STORE.popitem(last=False)
            STORE[key] = Saved(result, time.monotonic())
        return {"id": key, **result.info,
                "downloads": {role: f"/api/uv/results/{key}/{role}" for role in result.files},
                "previews": {role: f"/api/uv/results/{key}/{role}-preview" for role in result.previews},
                "expires_in_seconds": TTL}
    finally:
        GENERATION_LOCK.release()


@router.post("/generate")
async def create(files: list[UploadFile] = File(...), width_mm: float = Form(...), height_mm: float = Form(...),
                 remove_background: bool = Form(False),
                 output_mode: Literal['images', 'project'] = Form('images')):
    try:
        canvas = Canvas(width_mm, height_mm)
        if len(files) not in {2, 3}:
            raise ValueError("请上传两张或三张图片。")
        data = []
        for file in files:
            item = await file.read(MAX_FILE_BYTES+1)
            if not item or len(item) > MAX_FILE_BYTES:
                raise ValueError("每张图片不能为空，且不能超过 20 MB。")
            data.append(item)
        return await run_in_threadpool(generate, data, canvas, remove_background, output_mode)
    finally:
        for file in files:
            await file.close()


@router.get("/results/{key}/{role}")
def download(key: str, role: str):
    with STORE_LOCK:
        cleanup()
        saved = STORE.get(key)
        if saved is None:
            raise HTTPException(404, "这组文件已过期，请用原图重新生成。")
        result = saved.export
        if role.endswith("-preview") and role[:-8] in result.previews:
            saved.touched = time.monotonic()
            STORE.move_to_end(key)
            return Response(result.previews[role[:-8]], media_type="image/png")
        if role not in result.files:
            raise HTTPException(404, "没有这个下载文件。")
        saved.touched = time.monotonic()
        STORE.move_to_end(key)
        filename, data = result.files[role]
    return Response(data, media_type="application/zip" if role == "package" else "application/octet-stream" if role == "project" else "image/png",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})
