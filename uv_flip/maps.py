"""Single-face E1 UV relief maps with optional local mask-only background removal."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import math
import warnings
import zipfile

import numpy as np
from PIL import Image, ImageChops, ImageOps, PngImagePlugin, UnidentifiedImageError

from .background import remove_background
from .studio import build_studio_project

DPI = 1440
RELIEF_MM = 0.8
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_INPUT_PIXELS = 24_000_000
MAX_OUTPUT_PIXELS = 40_000_000
ALGORITHM_VERSION = "uv-relief-1.1.0"


@dataclass(frozen=True)
class Canvas:
    width_mm: float
    height_mm: float

    def __post_init__(self):
        if any(not math.isfinite(v) or not 5 <= v <= 300 for v in (self.width_mm, self.height_mm)):
            raise ValueError("宽、高请输入 5–300 mm 之间的数字。")
        if self.width_px * self.height_px > MAX_OUTPUT_PIXELS:
            raise ValueError("这个尺寸超出了当前生成范围，请减小宽度或高度；100 × 100 mm 可以生成。")

    @property
    def width_px(self):
        return math.floor(self.width_mm / 25.4 * DPI + 0.5)

    @property
    def height_px(self):
        return math.floor(self.height_mm / 25.4 * DPI + 0.5)


@dataclass(frozen=True)
class Export:
    files: dict[str, tuple[str, bytes]]
    previews: dict[str, bytes]
    info: dict

    @property
    def byte_size(self):
        return sum(len(data) for _, data in self.files.values()) + sum(map(len, self.previews.values()))


def decode_source(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("每张图片不能为空，且不能超过 20 MB。")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("请上传 PNG、JPG 或 WebP 图片。")
                if min(original.size) < 8 or original.width * original.height > MAX_INPUT_PIXELS:
                    raise ValueError("单张图片至少为 8 × 8 像素，且不能超过 2400 万像素。")
                if getattr(original, "is_animated", False):
                    raise ValueError("请先将动图导出为静态图片，再上传。")
                image = ImageOps.exif_transpose(original).convert("RGBA")
                image.load()
        if image.getchannel("A").getextrema()[1] == 0:
            raise ValueError("有一张图片完全透明，请更换后再生成。")
        return image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("有一张图片无法读取或尺寸过大，请检查文件。") from exc


def column_recipe(width: int, count: int):
    """Keep proven two-view geometry; use the approved narrower three-view floor."""
    if count == 2:
        pitch = math.floor(RELIEF_MM * 2 / math.sqrt(3) / 25.4 * DPI + 0.5)
        run, floor_gray = pitch / 2, 0
    elif count == 3:
        # 0.917 mm period: two 0.282 mm flanks and a 0.353 mm center floor.
        # Earlier floor occlusion trades some straight-on center coverage.
        pitch, run, floor_gray = 52, 16, 26
    else:
        raise ValueError("请上传两张或三张图片。")
    complete = width // pitch
    start = (width - complete * pitch) // 2
    end = start + complete * pitch
    position = np.arange(width)
    active = (position >= start) & (position < end)
    phase = (position - start) % pitch
    if count == 2:
        # Match the existing two-frame script's incomplete-edge policy: flat frame A.
        selection = np.where(active, np.where(phase < run, 0, 1), 0).astype(np.int8)
        wave = np.where(phase < run, phase / run, 1 - (phase - run) / run)
        gray = np.where(active, np.floor(wave * 255 + 0.5), 0).astype(np.uint8)
    else:
        # Incomplete edge cells keep flat frame C, so full-bleed inputs are not cut.
        selection = np.where(active, np.where(phase < run, 0, np.where(phase < 2*run, 2, 1)), 1).astype(np.int8)
        wave = np.maximum(0, 1 - np.abs(phase - run) / run)
        gray = np.where(active, np.rint(floor_gray + (255 - floor_gray)*wave), 0).astype(np.uint8)
    return selection, gray, {"pitch_pixels": pitch, "pitch_mm": pitch / DPI * 25.4,
                             "complete_periods": complete, "active_start": start, "active_end": end,
                             "side_run_pixels": run, "floor_gray": floor_gray}


def fit_size(source_size, canvas_size):
    """Contain the complete input canvas; never trim alpha or align subjects."""
    sw, sh = source_size
    cw, ch = canvas_size
    scale = min(cw / sw, ch / sh)
    return max(1, min(cw, math.floor(sw*scale+0.5))), max(1, min(ch, math.floor(sh*scale+0.5)))


def render_maps(sources: list[Image.Image], canvas: Canvas):
    w, h = canvas.width_px, canvas.height_px
    selected, heights, recipe = column_recipe(w, len(sources))
    color = Image.new("RGBA", (w, h))
    depth = Image.new("L", (w, h))
    placements = []
    # Keep large canvases bounded: one resized input and small raster bands at a time.
    for index, source in enumerate(sources):
        fw, fh = fit_size(source.size, (w, h))
        ox, oy = (w-fw)//2, (h-fh)//2
        placements.append({"source_pixels": list(source.size), "fitted_pixels": [fw, fh], "offset_pixels": [ox, oy]})
        resized = source.resize((fw, fh), Image.Resampling.LANCZOS)
        columns = selected[ox:ox+fw] == index
        stripe_mask = (columns.astype(np.uint8) * 255)[None, :]
        for y in range(0, fh, 96):
            bh = min(96, fh-y)
            band = np.array(resized.crop((0, y, fw, y+bh)))
            # Copy alpha exactly. In particular, empty frame B must erase A in B strips.
            band[band[:, :, 3] == 0] = 0
            mask = Image.fromarray(np.repeat(stripe_mask, bh, axis=0))
            d = np.where(band[:, :, 3] > 0, heights[ox:ox+fw][None, :], 0).astype(np.uint8)
            color.paste(Image.fromarray(band), (ox, oy+y), mask)
            depth.paste(Image.fromarray(d), (ox, oy+y), mask)
        resized.close()
    return color, depth, recipe, placements


def encode_png(image, pair_id, kind):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("UVPrintPair", pair_id)
    metadata.add_text("UVPrintRole", kind)
    metadata.add_text("UVPrintAlgorithm", ALGORITHM_VERSION)
    metadata.add_text("UVPrintReliefMm", str(RELIEF_MM))
    stream = io.BytesIO()
    image.save(stream, format="PNG", dpi=(DPI, DPI), pnginfo=metadata, compress_level=6)
    data = stream.getvalue()
    # Validate exported file structure, metadata and CRC, rather than just live buffers.
    with Image.open(io.BytesIO(data)) as reopened:
        if reopened.size != image.size or reopened.info.get("UVPrintPair") != pair_id:
            raise RuntimeError("输出文件校验失败，请重新生成。")
        if abs(reopened.info["dpi"][0] - DPI) > 0.01:
            raise RuntimeError("输出分辨率校验失败，请重新生成。")
        reopened.verify()
    return data


def thumbnail(image):
    size = fit_size(image.size, (720, 720))
    stream = io.BytesIO()
    image.resize(size, Image.Resampling.LANCZOS).save(stream, format="PNG")
    return stream.getvalue()


def remove_source_background(image: Image.Image) -> dict[str, str]:
    """Compute a bounded-size mask; retain source RGB, canvas and existing alpha."""
    with image.getchannel("A") as original_alpha:
        if original_alpha.getextrema()[0] < 128:
            return {"engine": "透明通道", "note": "保留原图已有透明区域。"}
        analysis = image.copy()
        try:
            analysis.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            mask, engine, note = remove_background(analysis, "auto", 48)
            with Image.fromarray(mask) as small_mask:
                with small_mask.resize(image.size, Image.Resampling.LANCZOS) as resized:
                    with ImageChops.darker(resized, original_alpha) as alpha:
                        if alpha.getextrema()[1] == 0:
                            raise ValueError("去背景后没有可见主体，请关闭去背景或更换图片。")
                        image.putalpha(alpha)
            return {"engine": engine, "note": note}
        finally:
            analysis.close()


def generate_export(inputs: list[bytes], canvas: Canvas, pair_id: str,
                    should_remove_background: bool = False, output_mode: str = 'images') -> Export:
    if output_mode not in {'images', 'project'}:
        raise ValueError('请选择分开彩色图与高度图，或 Studio 项目文件。')
    if len(inputs) not in {2, 3}:
        raise ValueError("请上传两张或三张图片。")
    sources = []
    background_processing = []
    color = depth = None
    try:
        for data in inputs:
            sources.append(decode_source(data))
            if should_remove_background:
                try:
                    background_processing.append(remove_source_background(sources[-1]))
                except ValueError as exc:
                    raise ValueError(f"第 {len(sources)} 张图片：{exc}") from exc
        color, depth, recipe, placements = render_maps(sources, canvas)
        color_bytes = encode_png(color, pair_id, "color")
        # RGB grayscale is compatible with the previously delivered Studio depth maps.
        rgb_depth = depth.convert("RGB")
        try:
            depth_bytes = encode_png(rgb_depth, pair_id, "depth")
        finally:
            rgb_depth.close()
        previews = {"color": thumbnail(color), "depth": thumbnail(depth)}
        count = len(inputs)
        prefix = f"uv-{canvas.width_mm:g}x{canvas.height_mm:g}mm-{count}views-{pair_id[:8]}"
        color_name = prefix + "-COLOR.png"
        depth_name = prefix + "-DEPTH-0p8mm.png"
        order = ["左侧", "右侧"] if count == 2 else ["左侧", "正面", "右侧"]
        info = {"pair_id": pair_id, "algorithm": ALGORITHM_VERSION,
                "output_mode": output_mode,
                "width_mm": canvas.width_mm, "height_mm": canvas.height_mm,
                "width_px": canvas.width_px, "height_px": canvas.height_px,
                "dpi": DPI, "relief_mm": RELIEF_MM, "frame_count": count, "view_order": order,
                "experimental": count == 3, "geometry": recipe, "placements": placements,
                "remove_background": should_remove_background, "background_processing": background_processing,
                "source_sha256": [hashlib.sha256(data).hexdigest() for data in inputs],
                "studio_import_tested": False, "physical_print_tested": False,
                "files": {"color": {"name": color_name, "sha256": hashlib.sha256(color_bytes).hexdigest()},
                          "depth": {"name": depth_name, "sha256": hashlib.sha256(depth_bytes).hexdigest()}}}
        files = {"color": (color_name, color_bytes), "depth": (depth_name, depth_bytes)}
        project_note = ''
        if output_mode == 'project':
            project_name = prefix + '-STUDIO.empf'
            project_bytes = build_studio_project(color_bytes, depth_bytes, previews['color'],
                                                canvas.width_mm, canvas.height_mm, RELIEF_MM, count)
            files['project'] = (project_name, project_bytes)
            info['files']['project'] = {'name': project_name, 'sha256': hashlib.sha256(project_bytes).hexdigest()}
            project_note = (f'可直接在 Studio 打开 {project_name}，无需分别导入两张 PNG。项目内已设成品尺寸和 0.80 mm 彩色堆高。'
                            '默认标准平板画布、图案居中；请按当前平台、材料位置重新快照定位并测高。项目不会自动提交打印。\n\n')
        note = ("三画面采用小角度试印结构：周期约 0.92 mm、中间槽宽约 0.35 mm。目标是减小侧视所需倾角，正面可能更易混入左右图像；新版尚待实物验证。透明轮廓会打断凸棱，可能影响遮挡。"
                if count == 3 else "双画面采用双坡面结构；正面和过渡角度可能混图，透明轮廓交界可能出现残影。")
        background_note = ("已开启本地纯色背景移除，仅修改透明蒙版，未裁切或重绘。已有透明 PNG 使用原透明通道；请检查主体边缘与内部图案，误去除时关闭去背景或上传手工抠好的透明 PNG。"
                           if should_remove_background else "保留上传图片的背景；如需透明底，请开启去除背景或上传透明 PNG。")
        instructions = f"""UV 变画打印说明

文件编号：{pair_id}
成品尺寸：{canvas.width_mm:g} × {canvas.height_mm:g} mm
浮雕高度：0.8 mm（不等于板材厚度）
画面顺序：{' → '.join(order)}

{project_note}以下为分开导入 PNG 的备用步骤：
1. 导入 {color_name}，将宽、高分别设为 {canvas.width_mm:g} 和 {canvas.height_mm:g} mm。
2. Craft Mode → Customize Texture，导入配套的 {depth_name}。
3. Ink Mode：Color Raised；Thickness：0.80 mm；Contrast：0；Ink Saving：0%；Texture：Default。
4. 彩色图和高度图保持相同尺寸、位置和方向，不单独裁切、缩放、反相或镜像。
5. 从打印面观看，无需背印镜像。按设备流程定位、测高；条纹在文件中为竖向；需要旋转时旋转整个纹理对象，保持两图一致。
6. 透明区保持无墨、零高度。{background_note}
7. 高度图黑色表示零高度，不是黑墨。生成预览只展示输出文件，不是实物角度效果。
8. 先打印一枚小样。{note}

图片按完整原始画布等比适配，居中透明留白；没有裁去原图留白、重新排列主体或重新绘图。
修改尺寸后请重新生成，不要仅在 Studio 中拉伸旧文件。尺寸以本说明的毫米数为准，PNG 的像素/DPI 存在微小舍入。
这两张图是同一组文件，请成对使用。对应 {DPI} DPI，{canvas.width_px} × {canvas.height_px} px。
本次生成仅校验数字文件，未在 Studio 导入或进行实物打印。
"""
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
            for filename, content in files.values():
                package.writestr(filename, content)
            package.writestr("打印说明.txt", instructions)
            package.writestr("parameters.json", json.dumps(info, ensure_ascii=False, indent=2))
        files['package'] = (prefix + '.zip', archive.getvalue())
        return Export(files, previews, info)
    finally:
        for image in sources:
            image.close()
        if color is not None:
            color.close()
        if depth is not None:
            depth.close()
