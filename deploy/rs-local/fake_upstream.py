#!/usr/bin/env python3
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


MODEL = os.environ.get("RS_UPSTREAM_MODEL", "gpt-3.5-turbo")
UPSTREAM_KEY = os.environ["RS_UPSTREAM_KEY"]


class Handler(BaseHTTPRequestHandler):
    server_version = "RSLocalFakeUpstream/1.0"

    def log_message(self, format_string, *args):
        print(f"fake-upstream {self.command} {self.path} {format_string % args}", flush=True)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        return self.headers.get("Authorization") == f"Bearer {UPSTREAM_KEY}"

    def do_GET(self):
        if self.path == "/healthz":
            self.send_json(200, {"ok": True})
            return
        if self.path == "/v1/models":
            if not self.authorized():
                self.send_json(401, {"error": {"message": "invalid upstream key"}})
                return
            self.send_json(
                200,
                {"object": "list", "data": [{"id": MODEL, "object": "model"}]},
            )
            return
        self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_json(404, {"error": {"message": "not found"}})
            return
        if not self.authorized():
            self.send_json(401, {"error": {"message": "invalid upstream key"}})
            return

        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length) or b"{}")
        if request.get("model") != MODEL:
            self.send_json(400, {"error": {"message": "unexpected model"}})
            return

        prompt = ""
        messages = request.get("messages") or []
        if messages:
            prompt = str(messages[-1].get("content", ""))
        created = int(time.time())
        response_text = f"RS fake upstream response: {prompt}"

        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            chunks = [
                {
                    "id": "chatcmpl-rs-local-stream",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "RS fake upstream "},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-rs-local-stream",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "stream response"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-rs-local-stream",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 6,
                        "total_tokens": 18,
                    },
                },
            ]
            for chunk in chunks:
                event = f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                self.wfile.write(event)
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self.send_json(
            200,
            {
                "id": "chatcmpl-rs-local",
                "object": "chat.completion",
                "created": created,
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 6,
                    "total_tokens": 18,
                },
            },
        )


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
