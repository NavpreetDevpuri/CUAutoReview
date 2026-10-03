#!/usr/bin/env python3
"""Verify Gemini CLI 0.61.0 image/schema transport against a loopback fake API.

Run this inside the pinned CLI image with networking disabled, for example:

    docker run --rm --network none --read-only \
      --tmpfs /tmp:rw,noexec,nosuid,nodev,size=128m \
      --mount type=bind,src="$PWD/platform/scripts/check_cli_image_transport.py",dst=/check.py,readonly \
      --mount type=bind,src="$PWD/platform/backend/app/worker/cli_backends.py",\
dst=/workspace/platform/backend/app/worker/cli_backends.py,readonly \
      --user 10001:10001 -w /workspace/platform/backend cuautoreview-local:dev python /check.py

The dummy key and local base URL are scoped to this subprocess. No provider call
or external network connection is possible in the suggested container command.
"""

from __future__ import annotations

import base64
import json
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, "/workspace/platform/backend")
from app.worker.cli_backends import _clean_env, _gemini_command


def png_1x1() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x20\x40\x60\xff"))
        + chunk(b"IEND", b"")
    )


def descend(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from descend(child)
    elif isinstance(value, list):
        for child in value:
            yield from descend(child)


class FakeGeminiHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict]] = []

    def log_message(self, *_args):
        pass

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(size))
        self.requests.append((self.path, body))
        if self.path.endswith(":countTokens"):
            encoded = json.dumps({"totalTokens": 17}).encode()
            content_type = "application/json"
        else:
            response = {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": '{"ok":true}'}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 17,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 21,
                },
            }
            encoded = ("data: " + json.dumps(response) + "\n\n").encode()
            content_type = "text/event-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    png = png_1x1()
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    server = HTTPServer(("127.0.0.1", 0), FakeGeminiHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gemini-image-transport-") as temp:
            root = Path(temp)
            cwd = root / "scratch"
            home = root / "home"
            cwd.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            image_path = cwd / "frame.png"
            image_path.write_bytes(png)
            image_path.chmod(0o400)

            command = _gemini_command(
                model="gemini-3.8-flash",
                reasoning="low",
                cwd=cwd,
                home=home,
                output_tokens=256,
                schema=schema,
            )
            settings_path = home / "gemini-home" / ".gemini" / "settings.json"
            settings = json.loads(settings_path.read_text())
            assert settings.get("security", {}).get("auth", {}).get("selectedType") == "gemini-api-key", (
                "isolated Gemini settings do not select API-key auth"
            )
            assert "--admin-policy" in command, "deny-all policy flag missing"
            policy_path = Path(command[command.index("--admin-policy") + 1])
            assert 'toolName = "*"' in policy_path.read_text()
            assert 'decision = "deny"' in policy_path.read_text()

            env = _clean_env(cwd=cwd, home=home, provider="gemini_cli", key="fake-local-key")
            env["GOOGLE_GEMINI_BASE_URL"] = f"http://127.0.0.1:{server.server_port}"
            prompt = 'Inspect the attached synthetic image and return exactly {"ok":true}.\n@./frame.png'
            completed = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )

        if completed.returncode != 0:
            raise AssertionError(f"Gemini CLI exited {completed.returncode}; stderr: {completed.stderr[-4000:]}")
        output = json.loads(completed.stdout)
        assert isinstance(output, dict) and not output.get("error"), output
        assert json.loads(output["response"]) == {"ok": True}, output.get("response")
        paths = [path for path, _ in FakeGeminiHandler.requests]
        assert len(paths) == 2 and paths[0].endswith(":countTokens") and ":streamGenerateContent?alt=sse" in paths[1], (
            f"unexpected Gemini API request sequence: {paths}"
        )
        request_path, request = FakeGeminiHandler.requests[1]
        nodes = list(descend(request))
        inline_parts = [node["inlineData"] for node in nodes if isinstance(node.get("inlineData"), dict)]
        assert any(
            part.get("mimeType") == "image/png" and part.get("data") == base64.b64encode(png).decode("ascii")
            for part in inline_parts
        ), "exact synthetic PNG bytes missing from inlineData"
        generation = [node for node in nodes if "responseMimeType" in node]
        assert any(
            node.get("responseMimeType") == "application/json" and node.get("responseJsonSchema") == schema
            for node in generation
        ), "JSON MIME type and response schema were not forwarded together"

        print(
            json.dumps(
                {
                    "status": "passed",
                    "cli_version": subprocess.run(
                        ["gemini", "--version"], text=True, capture_output=True, timeout=10, check=True
                    ).stdout.strip(),
                    "transport": "loopback fake Gemini API; network disabled by caller",
                    "request_sequence": paths,
                    "request_path": request_path,
                    "image_mime": "image/png",
                    "image_bytes_match": True,
                    "response_mime_type": "application/json",
                    "response_schema_forwarded": True,
                    "structured_response": output["response"],
                    "deny_all_policy": str(policy_path),
                },
                indent=2,
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    main()
