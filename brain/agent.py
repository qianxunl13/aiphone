#!/usr/bin/env python3
"""自主大脑：给一个目标，自己循环「读屏 → 模型决策 → 操作」直到完成。

复用开源手机 Agent 同一套 read→decide→act 循环，但决策喂的是「手」读到的
控件清单（文字+坐标），比纯截图更准、更省。模型走 Ray 网关的 qwen3-14b。

用法：agent.py "打开设置里的关于手机，告诉我安卓版本" [--max 12] [--shots 目录]
"""
import argparse
import base64
import json
import re
import sys
import time
import urllib.error
import urllib.request

HUB = "http://127.0.0.1:8700"
LLM = "http://218.84.70.83:57311/v1/chat/completions"
MODEL = "qwen3-14b"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 本机/内网直连


def hub(cmd, timeout=60):
    req = urllib.request.Request(f"{HUB}/cmd", data=json.dumps(cmd).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def llm(prompt):
    body = {"model": MODEL, "temperature": 0.1,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 600, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(LLM, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with OPENER.open(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def parse_action(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    return {"action": "fail", "arg": "模型没给出合法 JSON：" + text[:120]}


def _center(b):
    return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2


def screen():
    """读屏 → (package, 干净的元素列表)。去状态栏、合并标签、去重，可操作项在前。"""
    for _try in range(3):           # 界面切换瞬间可能读到空，重试
        d = hub({"action": "observe"})
        raw = d.get("nodes", [])
        if len(raw) > 3:
            break
        time.sleep(1.2)
    texts = [n for n in raw if (n.get("t") or n.get("d"))]
    items, consumed, seen = [], set(), set()
    # 1) 可操作项（可点/可输入/可滚动），把落在里面的文字借来当标签
    for n in raw:
        if not (n.get("c") or n.get("e") or n.get("s")):
            continue
        cx, cy = _center(n["b"])
        if cy < 66:            # 状态栏跳过
            continue
        label = n.get("t") or n.get("d") or ""
        if not label:
            l, t, r, b = n["b"]
            for m in texts:
                mx, my = _center(m["b"])
                if l <= mx <= r and t <= my <= b:
                    label = m.get("t") or m.get("d")
                    consumed.add(id(m))
                    break
        label = label or n.get("id", "")
        if not label:
            continue
        flags = "".join(k for k in ("c", "e", "s") if n.get(k))
        items.append((label, flags, cx, cy))
    # 2) 补未被用作标签的纯文字（供阅读），去重
    for m in texts:
        if id(m) in consumed or m.get("c") or m.get("e") or m.get("s"):
            continue
        cx, cy = _center(m["b"])
        if cy < 66:
            continue
        lab = m.get("t") or m.get("d")
        if lab in seen or any(lab == it[0] for it in items):
            continue
        seen.add(lab)
        items.append((lab, "", cx, cy))
    return d.get("package", "?"), items


PROMPT = """你在操作一台安卓手机完成任务。每一步我给你当前屏幕上的元素，你只回一个 JSON 决定下一步。

任务：{goal}
当前 App：{pkg}
屏幕元素（编号 | 文字 | 类型 c=可点 e=可输入 s=可滚动）：
{elems}

已做过的步骤：
{hist}

只输出一个 JSON，别的都不要：
{{"thought":"一句话判断","action":"动作","arg":"参数"}}
动作可选：
- "tap" arg=元素编号（点它）
- "type" arg=要输入的文字
- "swipe_up"（向下滚，看列表更下面的内容）/ "swipe_down"（向上滚，回到上面）
- "launch" arg=App包名（直接开 App，比在桌面找图标稳；已知：设置=com.android.settings）
- "back" / "home"
- "done" arg=给用户的结论（任务完成/已读到答案时）
- "fail" arg=卡住的原因
规则：先在元素列表里找和目标相关、带 c(可点) 的项，有就直接 tap 它的编号；确实没有再 swipe_up 向下翻找；到达目标或读到答案就 done。编号必须来自上面列表。"""


def run(goal, max_steps, shots_dir=None):
    history = []
    for step in range(1, max_steps + 1):
        pkg, items = screen()
        if shots_dir:
            save_shot(f"{shots_dir}/step{step:02d}.jpg")
        elems = "\n".join(f"{i}. {lbl} [{fl}]" for i, (lbl, fl, _, _) in enumerate(items)) or "(空)"
        prompt = PROMPT.format(goal=goal, pkg=pkg, elems=elems,
                               hist="\n".join(history[-8:]) or "(还没开始)")
        act = parse_action(llm(prompt))
        a, arg = act.get("action"), act.get("arg", "")
        print(f"[{step}] {pkg} | 想法：{act.get('thought','')[:60]} | 动作：{a} {str(arg)[:40]}")
        if a == "done":
            print(f"\n✅ 完成：{arg}")
            return {"ok": True, "result": arg, "steps": step}
        if a == "fail":
            print(f"\n❌ 放弃：{arg}")
            return {"ok": False, "result": arg, "steps": step}
        try:
            do(a, arg, items)
        except Exception as e:
            history.append(f"第{step}步 {a} 出错：{e}")
            continue
        history.append(f"第{step}步：{a} {arg}")
        time.sleep(1.5)
    return {"ok": False, "result": "步数用完还没完成", "steps": max_steps}


def do(a, arg, items):
    if a == "tap":
        _, _, cx, cy = items[int(arg)]
        hub({"action": "tap", "x": cx, "y": cy})
    elif a == "type":
        hub({"action": "type", "text": str(arg)})
    elif a == "swipe_up":
        hub({"action": "swipe", "x1": 540, "y1": 1600, "x2": 540, "y2": 600, "ms": 300})
    elif a == "swipe_down":
        hub({"action": "swipe", "x1": 540, "y1": 600, "x2": 540, "y2": 1600, "ms": 300})
    elif a == "launch":
        hub({"action": "launch", "package": str(arg)})
    elif a in ("back", "home"):
        hub({"action": "global", "name": a})
    else:
        raise ValueError(f"未知动作 {a}")


def save_shot(path):
    d = hub({"action": "screenshot", "width": 720})
    if d.get("jpeg"):
        open(path, "wb").write(base64.b64decode(d["jpeg"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("goal")
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--shots", default=None)
    a = ap.parse_args()
    r = run(a.goal, a.max, a.shots)
    print(json.dumps(r, ensure_ascii=False))
