"""Native EMPF asset, scale, relief and portable ZIP contracts."""
import base64
import io
import json
import zipfile

import pytest
from PIL import Image

from uv_flip.maps import Canvas, generate_export
from uv_flip.studio import build_studio_project
from test_uv import png


def unpack(payload):
    archive = zipfile.ZipFile(io.BytesIO(payload))
    assert archive.testzip() is None
    metadata = json.loads(archive.read('Metadata/project_info.json'))
    path = next(n for n in archive.namelist() if n.startswith('Asset/project_file/') and n.endswith('.json'))
    return archive, metadata, json.loads(archive.read(path))


@pytest.mark.parametrize('width,height', [(50, 50), (80, 50), (100, 100), (300, 5)])
def test_project_has_exact_assets_and_mm_scale_without_templates_or_paths(width, height):
    color = png(Image.new('RGBA', (64, 32), (12, 34, 56, 127)))
    depth = png(Image.new('RGB', (64, 32), (55, 55, 55)))
    payload = build_studio_project(color, depth, color, width, height, .8, 3)
    with unpack(payload)[0] as archive:
        _, meta, canvas = unpack(payload)
        assert len(canvas['objects']) == 1
        obj = canvas['objects'][0]
        assert base64.b64decode(obj['src'].split(',', 1)[1]) == color
        assert base64.b64decode(obj['grayscale'].split(',', 1)[1]) == depth
        assert obj['width']*obj['scaleX']/1.9685 == pytest.approx(width)
        assert obj['height']*obj['scaleY']/1.9685 == pytest.approx(height)
        assert obj['textureType'] == 'pattern' and obj['_isCustomizeTexture'] is True
        assert obj['inkMode'] == 'cmyk' and obj['thickness'] == .8
        assert obj['contrastNew'] == 0 and obj['grayPercentSave'] == 0 and not obj['invert']
        assert meta['project_info']['is_local_project'] is True
        params = json.loads(meta['canvases'][0]['print_param'])
        assert params['max_thickness'] == .8 and params['selectedInkMode'] == 120
        assert archive.read('Asset/images/thumbnail.png') == color
        assert json.loads(archive.read('Asset/font/font_mapping.json')) == {}
        serialized = json.dumps([meta, canvas])
        for forbidden in ['http://', 'https://', 'C:/', 'D:/', 'AppData', 'user_id', 'device_sn', 'auth_token']:
            assert forbidden not in serialized


@pytest.mark.parametrize('count', [2, 3])
def test_project_mode_keeps_png_pixels_and_package_contains_the_same_empf(count):
    images = [png(Image.new('RGBA', (32, 32), c)) for c in ['red', 'blue', 'green'][:count]]
    maps = generate_export(images, Canvas(8, 10), 'same-pair')
    project = generate_export(images, Canvas(8, 10), 'same-pair', output_mode='project')
    assert 'project' not in maps.files
    for role in ['color', 'depth']:
        assert project.files[role] == maps.files[role]
    _, _, canvas = unpack(project.files['project'][1])
    obj = canvas['objects'][0]
    for field, role in [('src', 'color'), ('grayscale', 'depth')]:
        assert base64.b64decode(obj[field].split(',', 1)[1]) == project.files[role][1]
    with zipfile.ZipFile(io.BytesIO(project.files['package'][1])) as archive:
        assert len(archive.namelist()) == 5
        assert archive.read(project.files['project'][0]) == project.files['project'][1]
        assert json.loads(archive.read('parameters.json'))['output_mode'] == 'project'
        assert '重新快照定位并测高' in archive.read('打印说明.txt').decode()
    assert project.byte_size > maps.byte_size


def test_project_rejects_bad_modes_geometry_and_mismatched_images():
    image = png(Image.new('RGBA', (32, 32), 'red'))
    with pytest.raises(ValueError, match='请选择'):
        generate_export([image]*2, Canvas(8, 8), 'bad', output_mode='invalid')
    small = png(Image.new('RGB', (16, 16)))
    with pytest.raises(ValueError, match='尺寸不一致'):
        build_studio_project(image, small, image, 50, 50, .8, 2)
    for width, height in [(0, 50), (float('nan'), 50), (400, 50)]:
        with pytest.raises(ValueError):
            build_studio_project(image, image, image, width, height, .8, 2)
