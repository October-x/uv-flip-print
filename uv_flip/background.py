"""Optional edge-connected solid-background removal; no AI or model download."""
import numpy as np
from PIL import Image, ImageDraw


def remove_background(image, mode='auto', tolerance=48):
    rgb = np.asarray(image.convert('RGB'), dtype=np.int16)
    corner = min(8, image.width // 4, image.height // 4)
    samples = np.concatenate([rgb[:corner, :corner].reshape(-1, 3),
                              rgb[:corner, -corner:].reshape(-1, 3),
                              rgb[-corner:, :corner].reshape(-1, 3),
                              rgb[-corner:, -corner:].reshape(-1, 3)])
    background = np.median(samples, axis=0)
    if np.percentile(np.max(np.abs(samples-background), axis=1), 95) > 12:
        raise ValueError('背景不是均匀纯色，请关闭去背景，或先上传处理好的透明 PNG。')
    candidate = (np.max(np.abs(rgb-background), axis=2) <= tolerance).astype('uint8') * 255
    # fromarray can expose a read-only NumPy buffer; floodfill needs writable pixels.
    with Image.fromarray(candidate).copy() as connected:
        # Fill all border-connected regions, never enclosed eye-white or markings.
        border = ([(x, 0) for x in range(image.width)] +
                  [(x, image.height-1) for x in range(image.width)] +
                  [(0, y) for y in range(image.height)] +
                  [(image.width-1, y) for y in range(image.height)])
        for point in border:
            if connected.getpixel(point) == 255:
                ImageDraw.floodfill(connected, point, 128)
        mask = np.where(np.asarray(connected) == 128, 0, 255).astype('uint8')
    return mask, '边缘连通纯色去背景', '仅去掉与边缘连通的相近底色，请检查浅色边缘。'
