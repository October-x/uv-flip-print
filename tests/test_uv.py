"""UV map geometry, alpha replacement, physical sizes and HTTP downloads."""
import hashlib
import io
import json
import math
import zipfile

from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from uv_flip.app import app
from uv_flip import api as uv_api, maps as uv_maps
from uv_flip.maps import Canvas, decode_source, generate_export, render_maps


def png(image):
    data = io.BytesIO()
    image.save(data, format="PNG")
    return data.getvalue()


def images(count, canvas):
    h, w = canvas.height_px, canvas.width_px
    result = []
    for i in range(count):
        pixels = np.zeros((h, w, 4), dtype=np.uint8)
        pixels[:, :] = [(210, 40, 70, 255), (20, 150, 90, 255), (60, 80, 230, 255)][i]
        pixels[30:100, 60:160] = [255, 255, 230, 255]  # Opaque eye-white-like detail.
        pixels[130:200, 70+i*20:150+i*20] = [90, 120, 150, 0]  # Hidden RGB must not leak.
        result.append(Image.fromarray(pixels))
    return result


@pytest.mark.parametrize("count", [2, 3])
def test_maps_follow_independent_geometry_and_selected_alpha(count):
    canvas = Canvas(10, 8)
    inputs = images(count, canvas)
    color, depth, recipe, _ = render_maps(inputs, canvas)
    c, d = np.array(color), np.array(depth)
    pitch = 52
    start = (canvas.width_px-(canvas.width_px//pitch)*pitch)//2
    end = start+(canvas.width_px//pitch)*pitch
    source_arrays = [np.array(s) for s in inputs]
    for x in range(canvas.width_px):
        if not start <= x < end:
            frame, gray = (0 if count == 2 else 1), 0
        else:
            q = (x-start)%pitch
            if count == 2:
                frame = 0 if q < 26 else 1
                gray = math.floor((1-abs(q-26)/26)*255+0.5)
            else:
                frame = 0 if q < 16 else 2 if q < 32 else 1
                gray = round(26+229*max(0,1-abs(q-16)/16))
        expected = source_arrays[frame][:, x].copy()
        expected[expected[:, 3] == 0] = 0
        assert np.array_equal(c[:, x], expected)
        assert np.array_equal(d[:, x], np.where(expected[:, 3] > 0, gray, 0))
    assert d.max() == 255
    assert not np.any(d[c[:, :, 3] == 0])
    assert np.count_nonzero((c[:, :, 0] == 255)&(c[:, :, 1] == 255)&(c[:, :, 3] == 255)) > 1000
    assert recipe["pitch_pixels"] == pitch


def test_dimensions_regenerate_count_instead_of_scaling_the_prism():
    canvas50, canvas80 = Canvas(50, 50), Canvas(80, 80)
    _, _, first = uv_maps.column_recipe(canvas50.width_px, 2)
    _, _, second = uv_maps.column_recipe(canvas80.width_px, 2)
    assert first["pitch_pixels"] == second["pitch_pixels"] == 52
    assert first["complete_periods"] == 54
    assert second["complete_periods"] == 87
    assert canvas50.width_px == 2835 and canvas80.width_px == 4535
    assert Canvas(100, 100).width_px == 5669


def test_complete_canvas_contain_keeps_white_background_and_proportion():
    canvas = Canvas(10, 10)
    source = Image.new("RGBA", (200, 100), "white")
    source.putpixel((0, 0), (220, 0, 0, 255))
    color, _, _, places = render_maps([source, source.copy()], canvas)
    pixels = np.array(color)
    assert places[0]["fitted_pixels"] == [567, 284]
    assert places[0]["offset_pixels"] == [0, 141]
    assert pixels[0, 200, 3] == 0
    assert pixels[200, 200].tolist() == [255, 255, 255, 255]
    assert pixels[424, 200, 3] == 255 and pixels[425, 200, 3] == 0


@pytest.mark.parametrize("size", [(0, 50), (float("nan"), 50), (50, float("inf")), (301, 5), (300, 300)])
def test_bad_or_excessive_output_sizes_are_rejected(size):
    with pytest.raises(ValueError):
        Canvas(*size)


def test_decode_keeps_original_resolution_and_uses_exif_orientation():
    large = Image.new("RGBA", (2200, 12), (1, 2, 3, 255))
    assert decode_source(png(large)).size == (2200, 12)
    jpeg = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (16, 8), "red").save(jpeg, format="JPEG", exif=exif)
    assert decode_source(jpeg.getvalue()).size == (8, 16)
    for data in (b"invalid image", png(Image.new("RGBA", (16, 16))), png(Image.new("RGB", (2, 2)))):
        with pytest.raises(ValueError):
            decode_source(data)


def test_png_pair_metadata_crc_and_zip_manifest():
    export = generate_export([png(Image.new("RGBA", (16, 16), color)) for color in ("red", "blue")], Canvas(8, 8), "pair-test123")
    for role in ("color", "depth"):
        image = Image.open(io.BytesIO(export.files[role][1]))
        assert image.size == (454, 454)
        assert image.info["UVPrintPair"] == "pair-test123"
        assert image.info["UVPrintRole"] == role
        assert image.info["dpi"][0] == pytest.approx(1440, abs=.01)
    with zipfile.ZipFile(io.BytesIO(export.files["package"][1])) as z:
        assert z.testzip() is None and len(z.namelist()) == 4
        manifest = json.loads(z.read("parameters.json"))
        for role in ("color", "depth"):
            entry = manifest["files"][role]
            assert entry["sha256"] == hashlib.sha256(z.read(entry["name"])).hexdigest()
        assert "0.80 mm" in z.read("打印说明.txt").decode()


@pytest.fixture
def client():
    uv_api.STORE.clear()
    with TestClient(app, base_url="http://127.0.0.1", headers={"X-UV-Local": "1"}) as c:
        yield c
    uv_api.STORE.clear()


def submit(client, count=2, **values):
    files = [("files", (f"frame-{i}.png", png(Image.new("RGB", (20, 20), color)), "image/png"))
             for i, color in enumerate(["red", "green", "blue", "yellow"][:count])]
    return client.post("/api/uv/generate", files=files,
                       data={"width_mm": "8", "height_mm": "10", **values})


@pytest.mark.parametrize("count", [2, 3])
def test_http_generate_previews_and_both_downloads(client, count):
    response = submit(client, count)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["experimental"] is (count == 3)
    assert len(data["source_sha256"]) == count
    assert data["relief_mm"] == .8
    for role in ("color", "depth", "package"):
        output = client.get(data["downloads"][role])
        assert output.status_code == 200
        assert output.headers["Cache-Control"] == "no-store"
        assert "attachment" in output.headers["Content-Disposition"]
        if role != "package":
            assert Image.open(io.BytesIO(output.content)).size == (454, 567)
        else:
            assert zipfile.ZipFile(io.BytesIO(output.content)).testzip() is None
    for url in data["previews"].values():
        assert client.get(url).headers["Content-Type"] == "image/png"
    assert client.get(f'/api/uv/results/{data["id"]}/not-a-file').status_code == 404


def test_http_validation_and_wrong_site_calls(client):
    assert submit(client, 1).status_code == 422
    assert submit(client, 4).status_code == 422
    assert submit(client, width_mm="nan").status_code == 422
    assert submit(client, width_mm="300", height_mm="300").status_code == 422
    assert submit(client, width_mm="not-a-number").status_code == 422
    assert client.post("/api/uv/generate", headers={"Origin": "https://example.com"}).status_code == 403
    invalid = client.post("/api/uv/generate", data={"width_mm": 10, "height_mm": 10},
                          files=[("files", ("x.png", b"bad", "image/png")), ("files", ("y.png", b"bad", "image/png"))])
    assert invalid.status_code == 422 and "无法读取" in invalid.json()["detail"]


def test_result_expiry_and_limit_do_not_return_someone_elses_file(client, monkeypatch):
    monkeypatch.setattr(uv_api, "MAX_RESULTS", 2)
    first = submit(client).json()
    second = submit(client).json()
    third = submit(client).json()
    assert client.get(first["downloads"]["color"]).status_code == 404
    assert client.get(second["downloads"]["color"]).status_code == 200
    uv_api.STORE[third["id"]].touched -= uv_api.TTL+1
    assert client.get(third["downloads"]["package"]).status_code == 404


def test_concurrent_generation_has_clear_retry_response(client):
    with uv_api.GENERATION_LOCK:
        response = submit(client)
        assert response.status_code == 429 and "稍后" in response.json()["detail"]
    assert submit(client).status_code == 200


def test_uv_page_and_existing_tool_are_available(client):
    page = client.get("/uv")
    assert page.status_code == 200 and "变画工坊" in page.text
    assert "变画工坊" in client.get("/").text
    assert client.get("/static/uv.js").status_code == 200
    assert client.get("/api/health").json()["uv_generator"] is True
