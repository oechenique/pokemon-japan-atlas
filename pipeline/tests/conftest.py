import dataclasses
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pipeline.sources.registry import load_registry


@pytest.fixture(autouse=True)
def _clean_source_env(monkeypatch):
    # El contenedor trae el .env del usuario (por ejemplo OVERPASS_MODE=reuse): los tests
    # parten siempre del default y fijan lo que necesiten.
    monkeypatch.delenv("OVERPASS_MODE", raising=False)


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path_factory):
    # Ningún test escribe en el data/ real (en CI, además, no es escribible para el
    # usuario del contenedor): DuckDB vuelca a disco en un directorio temporal.
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path_factory.mktemp("data")))


@pytest.fixture(scope="session")
def registry():
    return load_registry()


@pytest.fixture
def make_source(registry):
    def _make(source_id="natural_earth", **changes):
        return dataclasses.replace(registry.get(source_id), **changes)

    return _make


class FileServer:
    """Servidor HTTP local con ETag y respuestas 304, para probar descargas condicionales."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.requests: list[tuple[str, int]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = self.path.split("?", 1)[0]
                body = server.files.get(path)
                if body is None:
                    status = 404
                    self.send_response(status)
                    self.end_headers()
                else:
                    etag = '"' + hashlib.md5(body).hexdigest() + '"'
                    if self.headers.get("If-None-Match") == etag:
                        status = 304
                        self.send_response(status)
                        self.send_header("ETag", etag)
                        self.end_headers()
                    else:
                        status = 200
                        self.send_response(status)
                        self.send_header("ETag", etag)
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                server.requests.append((path, status))

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path):
        return f"http://127.0.0.1:{self.httpd.server_port}{path}"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def file_server():
    server = FileServer()
    yield server
    server.close()
