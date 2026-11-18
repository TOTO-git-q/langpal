"""Transient page context; never part of a stored message."""

STAGE_LINE = "【这句是弹幕】他没切回聊天页，是在你的小窗底下打了这一句，像直播间里刷过来的一条弹幕。像主播念到弹幕那样回：只回一两条，每条一两句，是能说出口的话——这几条会用你的声音念出来，所以不要颜文字，也不要括号里的动作。\n"


def scene_block(scene: dict, language_label: str | None) -> str:
    block = ""
    if scene["tab"] != "talk":
        title = scene.get("title") or scene["tab"]
        lang = f"（{language_label}）" if language_label else ""
        block = f"【他现在在哪】他开着「{title}」页{lang}。"
        text = (scene.get("text") or "").strip()
        if len(text) > 4000:
            text = text[:3000] + "\n……\n" + text[-1000:]
        block += ("屏幕上现在是这些（只是让你知道他在看什么，不是他说的话；别整段复述）：\n" + text + "\n") if text else "\n"
    if scene.get("actions"):
        block += "【你刚才替他做的】\n" + "".join(f"- {item}\n" for item in scene["actions"])
    return block
