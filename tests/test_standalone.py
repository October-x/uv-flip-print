import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import numpy as np
from PIL import Image, ImageDraw
import pytest

from uv_flip.maps import Canvas, generate_export
from test_uv import png, client, submit

ROOT = Path(__file__).resolve().parents[1]


def test_background_removes_exterior_preserves_enclosed_white_and_rgb():
    image = Image.new('RGBA', (80, 80), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 60, 60), fill='black')
    draw.rectangle((30, 30, 40, 40), fill='white')
    raw = png(image)
    export = generate_export([raw, raw], Canvas(8, 8), 'bg', True)
    result = Image.open(io.BytesIO(export.files['color'][1]))
    values = np.array(result)
    assert values[0, 0, 3] == 0
    # Full opaque enclosed white detail remains after background removal.
    assert values[200, 200].tolist() == [255, 255, 255, 255]
    depth = np.array(Image.open(io.BytesIO(export.files['depth'][1])))
    assert not np.any(depth[values[:, :, 3] == 0])


def test_existing_transparency_skips_processing_and_complex_background_is_explicit():
    image = Image.new('RGBA', (32, 32), 'white')
    image.putpixel((0, 0), (1, 2, 3, 0))
    a = generate_export([png(image)]*2, Canvas(8, 8), 'same')
    b = generate_export([png(image)]*2, Canvas(8, 8), 'same', True)
    assert a.files['color'] == b.files['color']
    complex_image = Image.new('RGB', (32, 32), 'red')
    ImageDraw.Draw(complex_image).rectangle((16, 0, 31, 31), fill='blue')
    with pytest.raises(ValueError, match='背景不是均匀纯色'):
        generate_export([png(complex_image)]*2, Canvas(8, 8), 'bad', True)


def test_project_api_download_and_mode_validation(client):
    data = submit(client, count=3, output_mode='project').json()
    assert data['output_mode'] == 'project'
    response = client.get(data['downloads']['project'])
    assert response.status_code == 200
    assert response.headers['content-type'] == 'application/octet-stream'
    assert '.empf' in response.headers['content-disposition']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert 'Metadata/project_info.json' in archive.namelist()
    assert submit(client, output_mode='bad').status_code == 422
    assert client.post('/api/uv/generate').status_code == 422
    assert client.post('/api/uv/generate', headers={'X-UV-Local': ''}).status_code == 403


def test_cli_generates_downloadable_files_and_refuses_overwrite(tmp_path):
    for name, color in [('left', 'red'), ('right', 'blue')]:
        Image.new('RGB', (32, 32), color).save(tmp_path / (name+'.png'))
    out = tmp_path / 'result'
    command = [sys.executable, str(ROOT / 'scripts/generate.py'), '--left', str(tmp_path/'left.png'),
               '--right', str(tmp_path/'right.png'), '--width-mm', '8', '--height-mm', '10',
               '--project', '--out', str(out)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)
    assert info['success'] is True
    assert set(info['files']) == {'color', 'depth', 'project', 'package'}
    for target in info['files'].values():
        assert Path(target).is_file()
    original = {p.name: p.read_bytes() for p in out.iterdir()}
    retry = subprocess.run(command, capture_output=True)
    assert retry.returncode == 2
    assert original == {p.name: p.read_bytes() for p in out.iterdir()}
