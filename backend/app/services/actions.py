"""Private action lines carried by a chat reply."""
import re

_LINE = re.compile(r"^\[do:([a-z]+)(?:\s+(.+?))?\]$")
_PAGES = {"talk", "today", "reading", "listening", "coach", "drill", "review", "notebook",
          "workspace-agent", "settings", "course"}


_PAGE_NAMES = {"聊天": "talk", "今天": "today", "阅读": "reading", "听力": "listening", "口语": "coach", "复习": "drill",
               "错题本": "review", "单词本": "notebook", "课程管家": "workspace-agent", "设置": "settings", "课程": "course"}


def _lenient(name: str, arg: str | None, languages, formats) -> str | None:
    """She sometimes writes a page or a type by the name she sees instead of its id. Take the obvious ones;
    a listening type she made up means "whatever is set" rather than nothing at all."""
    if arg is None:
        return None
    arg = arg.strip().strip("「」『』\"'")
    if name == "open":
        return _PAGE_NAMES.get(arg, arg)
    if name == "listen" and arg not in formats:
        labels = {label: ident for ident, label in formats.items()} if isinstance(formats, dict) else {}
        return labels.get(arg)
    if name == "language" and arg not in languages and isinstance(languages, dict):
        return next((tag for tag, label in languages.items() if label == arg), arg)
    return arg


def extract(reply: str, *, languages, formats) -> tuple[str, list[dict]]:
    """`languages` and `formats` may be plain sets of ids, or dicts id -> label (then labels are accepted too)."""
    kept, actions = [], []
    for line in reply.splitlines(keepends=True):
        match = _LINE.fullmatch(line.strip())
        if match is None:
            kept.append(line)
            continue
        name, arg = match.groups()
        arg = _lenient(name, arg, languages, formats)
        valid = ((name == "open" and arg in _PAGES)
                 or (name == "listen" and (arg is None or arg in formats))
                 or (name in {"review", "lesson"} and arg is None)
                 or (name == "language" and arg in languages)
                 or (name in {"fun", "voice"} and arg in {"on", "off"})
                 or (name == "save" and arg is not None and 1 <= len(arg) <= 60)
                 or (name == "manage" and arg is not None and 2 <= len(arg) <= 300))
        if valid and len(actions) < 2:
            actions.append({"name": name, "arg": arg})
    return "".join(kept), actions


def prompt_block(language: str, languages: dict[str, str], formats: dict[str, str], course_line="") -> str:
    return (
        (course_line.rstrip('\n') + '\n' if course_line else '') +
        "【你可以替他动手】这个软件你也能操作。要动手就在回复里单独写一行（这一行他看不到）：\n"
        "[do:open 页面] 打开一页：talk 聊天、today 今天、reading 阅读、listening 听力、coach 口语、drill 复习、review 错题本、notebook 单词本、settings 设置\n"
        "[do:listen 题型] 马上开一组听力，题型可以不写；现在能选：" + "、".join(f"{k} {v}" for k, v in formats.items()) + "\n"
        "[do:review] 开始复习\n"
        "[do:lesson] 开始上下一课（他说「上课吧」「来一课」这类才用）\n"
        "[do:open course] 打开课程页\n"
        "[do:language 语言代码] 把聊天语言拨过去；现在有：" + "、".join(f"{k} {v}" for k, v in languages.items()) + "\n"
        "[do:fun on] / [do:fun off] 趣味模式\n"
        "[do:voice on] / [do:voice off] 开关你的声音\n"
        "[do:save 单词] 把这个词收进他的单词本\n"
        "[do:manage 一句话说清要改什么] 改设置：课程、世界书、阅读来源、题型、听力安排、角色卡\n"
        "绝大多数时候不用动手。只有他明明白白让你做（「打开…」「帮我…」「…して」「…にして」）才写，一次最多两行；"
        "拿不准就不写，问他一句。他只是问你话、跟你聊天的时候，绝不替他换页面。动手的同时照常跟他说话，别把这些写法念出来。\n"
    )
