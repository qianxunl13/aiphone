#!/usr/bin/env python3
"""大脑和手之间的中转站（只用标准库）。

手（手机上的 App）长轮询 GET /hand/poll 取指令、POST /hand/result 回结果；
大脑（现在是 Claude，以后是 agent_world）POST /cmd 下指令并同步等结果。
GET /devices 看哪些手在线；GET /apk 下载手机端安装包。

配对码：环境变量 AIPHONE_CODE，或 ~/.config/aiphone/code（没有就自动生成 6 位）。
"""
import json
import os
import queue
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("AIPHONE_PORT", "8700"))
APK = Path(__file__).resolve().parent.parent / "hand-android/app/build/outputs/apk/debug/app-debug.apk"
CODE_FILE = Path.home() / ".config/aiphone/code"


def load_code():
    if os.environ.get("AIPHONE_CODE"):
        return os.environ["AIPHONE_CODE"]
    if not CODE_FILE.exists():
        CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CODE_FILE.write_text("".join(secrets.choice("23456789") for _ in range(6)))
        CODE_FILE.chmod(0o600)
    return CODE_FILE.read_text().strip()


CODE = load_code()
QUEUES: dict[str, queue.Queue] = {}   # 设备 → 待执行指令
WAITERS: dict[str, dict] = {}         # 指令 id → {"ev": Event, "res": 结果}
SEEN: dict[str, float] = {}           # 设备 → 最后一次来取指令的时间
LOCK = threading.Lock()


def q_of(device):
    with LOCK:
        return QUEUES.setdefault(device, queue.Queue())


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _qs(self):
        return {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}

    def do_GET(self):
        path, qs = urlparse(self.path).path, self._qs()
        if path == "/hand/poll":
            if qs.get("code") != CODE:
                return self._json(401, {"error": "bad code"})
            dev = qs.get("device", "unknown")
            SEEN[dev] = time.time()
            try:
                cmd = q_of(dev).get(timeout=25)
            except queue.Empty:
                self.send_response(204)
                self.end_headers()
                return
            return self._json(200, cmd)
        if path == "/devices":
            now = time.time()
            return self._json(200, {d: round(now - t, 1) for d, t in SEEN.items()})
        if path == "/apk" and APK.exists():
            data = APK.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.android.package-archive")
            self.send_header("Content-Disposition", 'attachment; filename="ai-hand.apk"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        path, qs = urlparse(self.path).path, self._qs()
        if path == "/hand/result":
            if qs.get("code") != CODE:
                return self._json(401, {"error": "bad code"})
            res = self._body()
            w = WAITERS.get(res.get("id", ""))
            if w:
                w["res"] = res
                w["ev"].set()
            return self._json(200, {"ok": True})
        if path == "/cmd":
            # 只允许本机（大脑在本机）下指令，防止同网段别人遥控手机
            if self.client_address[0] not in ("127.0.0.1", "::1"):
                return self._json(403, {"error": "local only"})
            cmd = self._body()
            dev = cmd.pop("device", None) or (max(SEEN, key=SEEN.get) if SEEN else None)
            if not dev:
                return self._json(503, {"error": "没有在线的手机"})
            cmd["id"] = uuid.uuid4().hex
            w = WAITERS[cmd["id"]] = {"ev": threading.Event(), "res": None}
            q_of(dev).put(cmd)
            ok = w["ev"].wait(float(cmd.get("timeout", 45)))
            WAITERS.pop(cmd["id"], None)
            if not ok:
                return self._json(504, {"error": "手机没在规定时间内回应", "device": dev})
            return self._json(200, {"device": dev, **w["res"]})
        self._json(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"hub on :{PORT}  配对码 {CODE}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
