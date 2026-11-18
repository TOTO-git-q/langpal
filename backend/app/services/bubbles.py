"""气泡拆分 + 投递节奏：把一段回复拆成多条聊天气泡，并给出人类打字节奏用的停顿时长/分片。

纯函数、零 IO——可打断的 sleep（用 asyncio.Event 做检查点）由调用方 services/chat.py 自己
实现，这里只负责"拆成什么"和"该停多久"两件事。贴纸清单本身的文件读取（真正的 IO）留在
prompts.py 里，这里的贴纸相关函数只接收调用方传进来的"合法 id 集合"，本身仍然是纯函数。

拆分优先吃模型在 system prompt（见 prompts.py）里学会的单独一行 `---` 分隔；模型没拆、或
拆出来某一段仍然过长时，在这里兜底按段落/句末标点贪心切短——语义照抄 TG 线
tgbot/tg_send.py 的 `split_bubbles`/`_soft_split`，不做改动。

## WP-G 新增：mood 标记剥离 + 贴纸标记拆分（API v1.2）

- `strip_mood`：回复最末尾单独一行的 `⟦mood:xxx⟧` 标记，在语言守门之前、拆气泡之前由
  services/chat.py 调用剥离，永远不进气泡文本/分词/落库。
- `strip_sticker_lines_for_guard`：语言守门前的"去噪"视图——把所有 `⟦sticker:...⟧` 标记行
  整行抹掉（不管 id 是否合法），避免这些 ASCII 标记干扰语言检测；不影响真正的贴纸拆分
  （那边用原始文本重新识别一遍，标记行的识别本身是幂等的）。
- `split_bubbles_with_stickers`：在 `split_bubbles` 基础上识别单独一行的 `⟦sticker:<id>⟧`
  标记，合法 id → 独立成一条贴纸气泡；非法 id / 贴纸功能关闭（valid_sticker_ids 为空）→
  整行直接丢弃，不留痕迹。
"""

from __future__ import annotations

import random
import re

# 一次回复最多拆几条气泡（硬上限，兜底防失控；模型每次只调一次，不会因为拆条多花钱）。
MAX_BUBBLES = 4

# 模型自己拆条时用的分隔符：单独一行的 `---`（至少三个 `-`，允许前后空白）。
_BUBBLE_SEP = re.compile(r"(?m)^\s*-{3,}\s*$")

# 单条气泡软上限（字符）：模型没按指令拆短时，代码层兜底切开。
_SOFT_LIMIT = 90

_PARA_SEP = re.compile(r"\n\s*\n")  # 空行 = 段落边界
# 句末标点（含日语常见语气符号 ♪ ~ 〜）后 / 换行处切句，标点保留在句尾。
_SENT_SEP = re.compile(r"(?<=[。！？!?…♪~〜])\s*|\n+")

# 每条气泡内 delta 分片粒度（字符数）——不是节奏考量，只是把整段文字切成小块逐个 yield。
DELTA_CHUNK_SIZE = 6
# 分片之间的小间隔（秒）：营造"正在一个字一个字打"的观感，同时也是打断检查点。
DELTA_PAUSE_SEC = 0.03

# 第一条气泡之前的"读完对方的话、在想怎么回"停顿区间（秒）。
THINK_PAUSE_RANGE = (0.8, 1.8)
# 气泡间停顿的封顶（秒）；实际停顿 = min(cap, 0.6 + 字数*0.045) * rand(0.85, 1.15)。
BUBBLE_PAUSE_CAP = 3.5

# ---------------------------------------------------------------------------
# mood（十词表，冻结见 docs/history/API-v1.2-additions.md）
# ---------------------------------------------------------------------------

# 冻结顺序（供 prompts.py 拼进 system prompt 展示用），MOOD_WORDS 由它派生，
# 两处不会各写一份词表、也不会漂移。
MOOD_WORDS_ORDERED = (
    "normal",
    "happy",
    "excited",
    "shy",
    "smug",
    "pout",
    "sad",
    "tired",
    "surprised",
    "thinking",
)
MOOD_WORDS = frozenset(MOOD_WORDS_ORDERED)

# 只在"回复最末尾单独一行"识别，不满足这个位置/格式一律当没有 mood 标记处理。
_MOOD_LINE_RE = re.compile(r"^⟦mood:([A-Za-z]+)⟧$")

# ---------------------------------------------------------------------------
# 贴纸（API v1.2）
# ---------------------------------------------------------------------------

# 贴纸标记必须单独占一行（同 `---` 分隔符的识别方式：整行、允许前后空白）。
_STICKER_LINE_RE = re.compile(r"(?m)^[ \t]*⟦sticker:([^⟧\s]+)⟧[ \t]*$")

# 贴纸气泡的投递停顿：不按文字长度算（贴纸没有"打字时间"这回事），固定给一个短停顿。
STICKER_PAUSE_SEC = 1.0


def _soft_split(text: str) -> list[str]:
    """把过长的一段按段落/句子贪心打包成多条短气泡；本来就短的原样保留。

    模型（尤其小档位）不一定严格遵守"拆短"的指令，这里在代码层兜底，避免一整段糊脸。
    """
    text = (text or "").strip()
    if not text:
        return []
    out: list[str] = []
    for para in _PARA_SEP.split(text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= _SOFT_LIMIT:
            out.append(para)
            continue
        buf = ""
        for sent in _SENT_SEP.split(para):
            sent = (sent or "").strip()
            if not sent:
                continue
            if buf and len(buf) + len(sent) > _SOFT_LIMIT:
                out.append(buf)
                buf = sent
            else:
                buf += sent
        if buf:
            out.append(buf)
    return out


def _split_bubbles_raw(reply: str) -> list[str]:
    """`split_bubbles` 的主体，不做 MAX_BUBBLES 裁剪——供 `split_bubbles` 和
    `split_bubbles_with_stickers`（按贴纸标记先切段、每段分别拆条）共用，裁剪统一在
    调用方按"全轮一共几条气泡"的口径做一次，不能在这里按段裁剪。
    """
    parts = _BUBBLE_SEP.split(reply or "")
    raw = [p.strip() for p in parts if p.strip()]
    if not raw:
        raw = [(reply or "").strip()] if (reply or "").strip() else []
    chunks: list[str] = []
    for c in raw:
        chunks.extend(_soft_split(c))
    return chunks


def split_bubbles(reply: str) -> list[str]:
    """先按单独一行的 `---` 切；模型没拆或某条仍过长时，再按段落/句子兜底拆成短气泡。

    永远至少返回一条（除非 reply 整个是空白），硬上限 MAX_BUBBLES 条。
    """
    return _split_bubbles_raw(reply)[:MAX_BUBBLES]


def strip_mood(text: str) -> tuple[str, str | None]:
    """剥离回复里**所有**单独成行的 `⟦mood:xxx⟧` 标记，mood 取最后一个标记的值。

    返回 (去掉全部标记行之后的文本, mood 或 None)；最后那个标记的值不在十词表里（非法）
    或压根没有标记（缺失）都返回 None，调用方（guard 事件）据此填 null。

    早先只剥"最后一行"的那个标记，实测漏过（线上 129 条消息里漏了 2 条，标记原样变成一条
    气泡发出去、还落了库——她等于当着人面念出 `⟦mood:shy⟧`）：模型偶尔会把这行footer重复
    一次，或在它后面再补一行别的标记，末行判定就落空了。这类标记行永远不是聊天内容，
    出现在哪一行都该整行丢掉，不做"只看末行"的假设。
    """
    kept: list[str] = []
    last_raw: str | None = None
    for line in (text or "").splitlines():
        m = _MOOD_LINE_RE.match(line.strip())
        if m:
            last_raw = m.group(1).lower()
            continue
        kept.append(line)
    mood = last_raw if last_raw in MOOD_WORDS else None
    return "\n".join(kept).rstrip(), mood


def strip_sticker_lines_for_guard(text: str) -> str:
    """语言守门前的"去噪"视图：把所有 `⟦sticker:...⟧` 标记行整行抹掉（不管 id 合不合法），
    避免这些 ASCII 标记干扰语言检测。不是真正的贴纸拆分——那边（split_bubbles_with_stickers）
    用原始文本重新识别一遍，标记行识别本身幂等，结果一致。
    """
    return _STICKER_LINE_RE.sub("", text or "")


def split_bubbles_with_stickers(
    reply: str, valid_sticker_ids: "set[str] | frozenset[str] | None" = None
) -> list[dict]:
    """在 `split_bubbles` 基础上识别单独一行的 `⟦sticker:<id>⟧` 标记，拆成
    `[{"text": ..., "sticker": id 或 None}, ...]`：

    - id 在 valid_sticker_ids 里 → 独立成一条贴纸气泡：text 是给 DB/落库用的占位
      `"[sticker:<id>]"`，sticker 字段=id。
    - id 不在里面（含 valid_sticker_ids 为空/None，即贴纸功能关闭）→ 整行直接丢弃，
      不留任何痕迹，也不会跟前后的文字糊在一起。

    先按贴纸标记行切段，再对每个纯文字段落分别跑 `_split_bubbles_raw`，最后统一按
    MAX_BUBBLES 裁剪——这样贴纸永远独立成一条气泡，不会被 `_soft_split` 按段落规则
    跟相邻文字粘连进同一条气泡里。永远至少返回一条。
    """
    valid = valid_sticker_ids or set()
    text = reply or ""
    matches = list(_STICKER_LINE_RE.finditer(text))

    segments: list[tuple[str, str | None]] = []
    last_end = 0
    for m in matches:
        before = text[last_end:m.start()]
        if before.strip():
            segments.append(("text", before))
        sid = m.group(1)
        if sid in valid:
            segments.append(("sticker", sid))
        # 非法 id / 贴纸关闭：整行丢弃，什么都不追加
        last_end = m.end()
    tail = text[last_end:]
    if tail.strip():
        segments.append(("text", tail))

    out: list[dict] = []
    for kind, payload in segments:
        if kind == "sticker":
            out.append({"text": f"[sticker:{payload}]", "sticker": payload})
        else:
            out.extend({"text": c, "sticker": None} for c in _split_bubbles_raw(payload))

    if not out:
        if matches:
            # 全部内容都是被丢弃的贴纸标记行（非法/关闭），不能把原始标记文本漏出去
            out = [{"text": "", "sticker": None}]
        else:
            stripped = text.strip()
            out = [{"text": stripped if stripped else "", "sticker": None}]
    return out[:MAX_BUBBLES]


def bubble_pause_seconds(bubble_text: str) -> float:
    """下一条气泡发送前该停多久：按这条气泡的可见长度估打字时间，封顶 BUBBLE_PAUSE_CAP。"""
    base_len = len(bubble_text or "")
    return min(BUBBLE_PAUSE_CAP, 0.6 + base_len * 0.045) * random.uniform(0.85, 1.15)


def think_pause_seconds() -> float:
    """第一条气泡之前的思考停顿。"""
    return random.uniform(*THINK_PAUSE_RANGE)


def delta_chunks(text: str, size: int = DELTA_CHUNK_SIZE) -> list[str]:
    """把一条气泡的文本切成小块，供逐块 yield 成 delta 事件。"""
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]
