"""Portable local EMPF export; self-contained ZIP format supported by Studio 4.3.6cn.

The schema follows a native Customize Texture / Color Raised project. No user
template, installed Studio, cloud account, camera image or encryption key is used.
"""
import base64
import io
import json
import math
from uuid import uuid4
import zipfile

from PIL import Image

MM_TO_STUDIO = 1.9685
BED_WIDTH_MM = 335
BED_HEIGHT_MM = 420


def _data_uri(data: bytes) -> str:
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')


def build_studio_project(color: bytes, depth: bytes, preview: bytes,
                         width_mm: float, height_mm: float, relief_mm: float,
                         frame_count: int) -> bytes:
    if (any(not math.isfinite(n) or n <= 0 for n in [width_mm, height_mm, relief_mm])
            or width_mm > BED_WIDTH_MM or height_mm > BED_HEIGHT_MM or frame_count not in {2, 3}):
        raise ValueError('Studio 项目尺寸或画面数量不合法。')
    with Image.open(io.BytesIO(color)) as image:
        pixels_w, pixels_h = image.size
    with Image.open(io.BytesIO(depth)) as image:
        if image.size != (pixels_w, pixels_h):
            raise ValueError('彩色图与高度图尺寸不一致，无法合并项目。')
    project_id, canvas_id, object_id = uuid4().hex, uuid4().hex, str(uuid4())
    name = f'UV变画 {width_mm:g}×{height_mm:g}mm {frame_count}画面'
    bed_w, bed_h = round(BED_WIDTH_MM*MM_TO_STUDIO), round(BED_HEIGHT_MM*MM_TO_STUDIO)
    texture = {
        'type': 'image', 'version': '5.3.0', 'id': object_id,
        'originX': 'center', 'originY': 'center', 'left': bed_w/2, 'top': bed_h/2,
        'width': pixels_w, 'height': pixels_h, 'pixelWidth': pixels_w, 'pixelHeight': pixels_h,
        'scaleX': width_mm*MM_TO_STUDIO/pixels_w, 'scaleY': height_mm*MM_TO_STUDIO/pixels_h,
        'angle': 0, 'flipX': False, 'flipY': False, 'opacity': 1, 'visible': True,
        'selectable': True, 'hasControls': True, 'hasBorders': True, 'evented': True,
        'lockMovementX': False, 'lockMovementY': False, '_isLock': False,
        'fill': 'rgb(0,0,0)', 'stroke': None, 'strokeWidth': 0,
        'skewX': 0, 'skewY': 0, 'cropX': 0, 'cropY': 0,
        'paintFirst': 'fill', 'globalCompositeOperation': 'source-over',
        '_layerName': name, '_layerNameCus': name, '_customType': 'customImage',
        'src': _data_uri(color), 'grayscale': _data_uri(depth),
        'textureType': 'pattern', '_isCustomizeTexture': True, 'isCanvasTexture': True,
        'isRaised': False, 'inkMode': 'cmyk', 'subPrintModel': '',
        'thickness': relief_mm, 'contrastNew': 0, 'invert': False,
        'grayPercentSave': 0, 'maxGrayValue': 255,
        'whiteLayerNum': 3, 'colorLayerNum': 1, 'crossOrigin': None, 'filters': [],
    }
    params = {
        'printModel': 120, 'imgQuality': 720,
        'printLayerData': [{'printType': 1, 'subPrintModel': 120, 'printTypeFileStr': 'PicColorInk',
                            'layerNum': 1, 'printLayerObjIds': []}],
        'format_size_w': BED_WIDTH_MM, 'format_size_h': BED_HEIGHT_MM,
        'format_size_w_non': BED_WIDTH_MM, 'format_size_h_non': BED_HEIGHT_MM,
        'selectedInkMode': 120, 'subPrintType': 1, 'is3dPrint': True, 'inkModeEnabled': False,
        'maskList': [], 'maxThickness': relief_mm, 'max_thickness': relief_mm,
        'gloss_thickness': 0, 'max_gray_value': 255, 'useColorAsBg': False,
    }
    # Blank editor backdrop only; it is never added to the printable objects.
    backdrop = io.BytesIO()
    with Image.new('RGBA', (bed_w, bed_h), 'white') as image:
        image.save(backdrop, format='PNG')
    metadata = {
        'project_info': {'project_name': name, 'category': 101, 'sub_category': 101,
                         'is_standard_product': 1, 'project_id': project_id, 'project_type': 1,
                         'is_local_project': True, 'isSavedLocal': True},
        'canvasesIndex': 0,
        'canvases': [{'canvas_id': canvas_id, 'canvas_name': name, 'is_standard_product': 1,
                      'category': 101, 'sub_category': 101, 'scenes': '[]',
                      'base_map': _data_uri(backdrop.getvalue()), 'base_map_width': bed_w, 'base_map_height': bed_h,
                      'model_link': '', 'print_param': json.dumps(params, separators=(',', ':')),
                      'extra': json.dumps({'cutData': '', 'appCavas': '', 'pcCavas': '', 'canvasShape': None,
                                           'bleedingLine': None, 'isPhotograph': False}),
                      'thumb_file': None, 'effect_file': None}],
    }
    canvas = {'version': '5.3.0', 'objects': [texture], 'id': 'canvas', 'selection': True}
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('Metadata/project_info.json', json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))
        archive.writestr(f'Asset/project_file/canvas_{canvas_id}.json', json.dumps(canvas, ensure_ascii=False, separators=(',', ':')))
        archive.writestr('Asset/font/font_mapping.json', '{}')
        archive.writestr('Asset/images/thumbnail.png', preview)
    return result.getvalue()
