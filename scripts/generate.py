"""Generate paired print files without starting a server."""
import argparse
import json
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from uv_flip.maps import Canvas, MAX_FILE_BYTES, generate_export


def main():
    parser = argparse.ArgumentParser(description='UV relief flip print: PNG pairs and optional Studio EMPF')
    parser.add_argument('--left', type=Path, required=True, help='Image seen from the left')
    parser.add_argument('--right', type=Path, required=True, help='Image seen from the right')
    parser.add_argument('--center', type=Path, help='Experimental third image seen from the front')
    parser.add_argument('--width-mm', type=float, default=50)
    parser.add_argument('--height-mm', type=float, default=50)
    parser.add_argument('--remove-background', action='store_true', help='Remove edge-connected solid background')
    parser.add_argument('--project', action='store_true', help='Also export self-contained Studio .empf')
    parser.add_argument('--out', type=Path, required=True, help='New or empty output folder')
    args = parser.parse_args()
    try:
        canvas = Canvas(args.width_mm, args.height_mm)
        if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
            raise ValueError('输出目录须为新的或空的目录，避免覆盖原有文件。')
        sources = [args.left, args.center, args.right] if args.center else [args.left, args.right]
        inputs = []
        for path in sources:
            with path.open('rb') as f:
                inputs.append(f.read(MAX_FILE_BYTES+1))
        export = generate_export(inputs, canvas, secrets.token_hex(12), args.remove_background,
                                 'project' if args.project else 'images')
        args.out.mkdir(parents=True, exist_ok=True)
        files = {}
        for role, (name, data) in export.files.items():
            target = args.out / name
            target.write_bytes(data)
            files[role] = str(target.resolve())
        (args.out / 'parameters.json').write_text(json.dumps(export.info, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'success': True, 'files': files, 'parameters': export.info}, ensure_ascii=True))
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Generation failed: {exc}\n')


if __name__ == '__main__':
    main()
