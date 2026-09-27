#!/usr/bin/env python3
"""Serve only documentation and POC artifacts on loopback."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROJECT=Path(__file__).resolve().parent.parent
class ViewerHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path=unquote(urlsplit(self.path).path)
        if path=='/':
            self.send_response(302);self.send_header('Location','/poc/viewer/');self.end_headers();return
        target=(PROJECT/path.lstrip('/')).resolve()
        if target.is_dir(): target=target/'index.html'
        relative=target.relative_to(PROJECT) if target.is_relative_to(PROJECT) else None
        allowed=relative is not None and not any(part.startswith('.') for part in relative.parts)
        allowed=allowed and (str(relative) in ('README.md','poc/README.md','poc/RESULTS.md','poc/RESULTS-SOL.md','poc/VIEWER-FEEDBACK.md') or str(relative).startswith(('specs/','poc/viewer/','poc/data/','poc/runs/','poc/screenshots/')))
        allowed=allowed and target.suffix.lower() in ('.html','.css','.js','.json','.jsonl','.yaml','.md','.png','.jpg','.jpeg','.webp','.txt')
        if not allowed or not target.is_file(): self.send_error(404);return
        super().do_GET()
    def end_headers(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'")
        super().end_headers()
    def list_directory(self,path): self.send_error(404)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);a=p.parse_args()
    print(f'CUAutoReview POC: http://127.0.0.1:{a.port}/poc/viewer/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',a.port),partial(ViewerHandler,directory=str(PROJECT))).serve_forever()
