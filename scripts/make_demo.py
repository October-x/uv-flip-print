"""Create original geometric inputs and a complete example without external art."""
import argparse
from pathlib import Path
import secrets
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uv_flip.maps import Canvas, generate_export

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        parser.error('Output must be a new or empty directory')
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = []
    for name, color in [('left', '#e36152'), ('right', '#269c8b')]:
        with Image.new('RGBA', (512, 512)) as image:
            draw = ImageDraw.Draw(image)
            if name == 'left':
                draw.ellipse((70, 70, 442, 442), fill=color)
            else:
                draw.rounded_rectangle((70, 70, 442, 442), 30, fill=color)
            draw.ellipse((160, 170, 210, 220), fill='white')
            draw.ellipse((300, 170, 350, 220), fill='white')
            draw.arc((165, 210, 350, 360), 0, 180, fill='white', width=18)
            path = args.out / (name+'.png')
            image.save(path)
            inputs.append(path.read_bytes())
    export = generate_export(inputs, Canvas(50, 50), secrets.token_hex(12), output_mode='project')
    for name, data in export.files.values():
        (args.out / name).write_bytes(data)
    print(f'Demo ready: {args.out.resolve()}')
