"""Start the web interface on localhost only."""
import argparse
import threading
import webbrowser

import uvicorn

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be 1–65535')
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}/uv')).start()
    uvicorn.run('uv_flip.app:app', host='127.0.0.1', port=args.port)
