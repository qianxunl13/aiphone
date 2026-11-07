#!/usr/bin/env python3
"""懂上下文的输入:读当前屏幕(聊天上下文)→ 你给一句意图 → 云端 LLM 按你的口吻写成整句 → 填进输入框。

不自动发送,填好让你确认。复用「手」的读屏+打字 + Ray 网关的 qwen3-14b。
用法:compose.py "回复：参加，但要晚点到，大概8点"
"""
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from agent import hub, llm  # 复用:hub 下指令、llm 调模型  # noqa: E402

STATUS_Y = 66  # 状态栏高度,忽略


def read_screen():
    """读屏 → (上下文文字列表, 输入框坐标 or None)。"""
    d = hub({"action": "observe"})
    ctx, box = [], None
    for n in d.get("nodes", []):
        b = n["b"]
        cy = (b[1] + b[3]) // 2
        if cy < STATUS_Y:
            continue
        if n.get("e"):                       # 可输入 = 输入框
            box = ((b[0] + b[2]) // 2, cy)
        t = n.get("t") or n.get("d")
        if t:
            ctx.append(t)
    return ctx, box


PROMPT = """下面是我手机当前聊天屏幕上的内容(可能含对方发来的消息、按钮文字等,请只关注对话):
---
{ctx}
---
我想表达的意思:{intent}

请以我的口吻,写一条自然、得体、可以直接发出去的回复。只输出回复正文本身,不要引号、不要解释、不要"回复："之类的前缀。"""


def main(intent):
    ctx, box = read_screen()
    if box is None:
        sys.exit("当前屏幕没找到输入框(先打开一个聊天/输入框再试)")
    draft = llm(PROMPT.format(ctx="\n".join(ctx[-30:]), intent=intent)).strip()
    draft = re.sub(r'^["“]|["”]$', "", draft).strip()   # 去掉模型可能加的引号
    print("AI 拟的回复：", draft)
    hub({"action": "tap", "x": box[0], "y": box[1]})     # 点一下输入框,聚焦
    hub({"action": "type", "text": draft})               # 填进去(不发送)
    print("已填进输入框,等你确认再发。")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('用法: compose.py "你的意图,如 回复：参加但晚点到"')
    main(" ".join(sys.argv[1:]))
