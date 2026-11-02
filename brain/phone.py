#!/usr/bin/env python3
"""大脑侧命令行：给手机下指令。

  phone.py devices
  phone.py observe              读屏（控件+坐标，精简打印）
  phone.py shot [out.jpg]       截图存文件
  phone.py tap X Y | swipe X1 Y1 X2 Y2 [ms]
  phone.py click 文字 | type 文字 | back | home | recents
  phone.py launch 包名 | url 链接 | apps
"""
import base64
import json
import sys
import urllib.request

HUB = "http://127.0.0.1:8700"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机直连，不走代理


def call(cmd):
    req = urllib.request.Request(f"{HUB}/cmd", data=json.dumps(cmd).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def show_nodes(res):
    print(f"[{res.get('package')}] 屏幕 {res.get('screen')}  窗口 {res.get('windows')}")
    for n in res.get("nodes", []):
        flags = "".join(k for k in ("c", "e", "s") if n.get(k))
        label = n.get("t") or n.get("d") or n.get("id") or ""
        x = (n["b"][0] + n["b"][2]) // 2
        y = (n["b"][1] + n["b"][3]) // 2
        print(f"  ({x},{y}) {flags:3} {label}")


def main(a):
    if not a:
        sys.exit(__doc__)
    op, rest = a[0], a[1:]
    if op == "devices":
        print(OPENER.open(f"{HUB}/devices").read().decode())
        return
    cmd = {
        "observe": lambda: {"action": "observe"},
        "shot": lambda: {"action": "screenshot", "width": 720},
        "tap": lambda: {"action": "tap", "x": int(rest[0]), "y": int(rest[1])},
        "swipe": lambda: {"action": "swipe", "x1": int(rest[0]), "y1": int(rest[1]), "x2": int(rest[2]),
                          "y2": int(rest[3]), "ms": int(rest[4]) if len(rest) > 4 else 300},
        "click": lambda: {"action": "click_text", "text": " ".join(rest)},
        "type": lambda: {"action": "type", "text": " ".join(rest)},
        "back": lambda: {"action": "global", "name": "back"},
        "home": lambda: {"action": "global", "name": "home"},
        "recents": lambda: {"action": "global", "name": "recents"},
        "launch": lambda: {"action": "launch", "package": rest[0]},
        "url": lambda: {"action": "open_url", "url": rest[0]},
        "apps": lambda: {"action": "apps"},
    }[op]()
    res = call(cmd)
    if op == "observe" and res.get("ok"):
        show_nodes(res)
    elif op == "shot" and res.get("jpeg"):
        out = rest[0] if rest else "/tmp/aiphone-shot.jpg"
        open(out, "wb").write(base64.b64decode(res["jpeg"]))
        print("截图已存", out)
    elif op == "apps" and res.get("apps"):
        for x in res["apps"]:
            print(f"  {x['name']}  {x['package']}")
    else:
        print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
