"""图片相关的共用小工具：魔数嗅探真实类型 + 不依赖 Pillow 解析宽高 + 通用文件清理。

被两处复用：routers/config.py 的人设头像上传（3MB 上限）、routers/chat.py 的聊天图片上传
（8MB 上限）。两处上限/落盘目录不同，但"这段字节是不是真的图片/是哪种格式/宽高多少"
是完全一样的逻辑，不该抄两份——这个模块就是抽出来的那一份。

宽高解析全部手写（PNG 读 IHDR、JPEG 扫 SOF、GIF 读 LSD、WebP 认 VP8/VP8L/VP8X 三种子格式），
解析失败（格式冷门/数据截断/理解有误）一律返回 None，不抛异常——上传接口的语义是
"宽高拿不到就返回 null，不影响图片本身已经存盘成功"，见 docs/history/API-v1.5-images.md。
"""

import logging
import struct
from pathlib import Path

logger = logging.getLogger(__name__)

# (魔数前缀, 扩展名)；WebP 另判（RIFF....WEBP，见 sniff_image_ext）
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

# 扩展名 -> MIME，供三个聊天引擎构造视觉 content block 时用（agent_sdk 的 base64 块 /
# deepseek.py CustomProvider 的 data URI 块 / 前端展示都用得到同一份映射）。
EXT_MEDIA_TYPE: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def sniff_image_ext(data: bytes) -> str | None:
    """按魔数判断真实图片类型，返回扩展名（png/jpg/gif/webp）或 None（不认识/不是图片）。
    不信任文件名后缀——上传的 Content-Type/文件名都可能被随意改写，这里只认字节本身。"""
    for prefix, ext in _MAGIC:
        if data.startswith(prefix):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    # 签名 8 字节 + 第一个 chunk 的 length(4) + type(4)="IHDR" 之后，紧跟 width(4) height(4)，
    # 均为大端无符号整数。IHDR 必须是文件的第一个 chunk（PNG 规范强制），偏移量是固定的。
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    # 跳过 SOI(0xFFD8)，逐个 marker 扫：多数 marker 后跟 2 字节长度 + 该长度的数据；
    # 遇到 SOFn（0xC0-0xCF，排除 DHT=C4 / JPG=C8 / DAC=CC 这几个不是"帧起始"的同段）时，
    # 数据结构是 precision(1) + height(2,大端) + width(2,大端)。
    _SOF_MARKERS = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    i = 2
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # 0xFF 填充字节/RST 标记（0xD0-0xD7）没有长度字段，直接跳过 marker 本身
        if marker in (0xFF,):
            i += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if i + 4 > n:
            return None
        seg_len = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in _SOF_MARKERS:
            if i + 9 > n:
                return None
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + seg_len
    return None


def _gif_dimensions(data: bytes) -> tuple[int, int] | None:
    # 6 字节签名（GIF87a/GIF89a）后紧跟 Logical Screen Descriptor：width(2) height(2)，小端。
    if len(data) < 10:
        return None
    width, height = struct.unpack("<HH", data[6:10])
    return width, height


def _webp_dimensions(data: bytes) -> tuple[int, int] | None:
    # RIFF 头 12 字节后是第一个 sub-chunk：4 字节 FourCC + 4 字节长度 + 数据。
    # 三种子格式的宽高编码方式互不相同（VP8/VP8L/VP8X），得分别解。
    if len(data) < 21 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    fourcc = data[12:16]
    payload = data[20:]
    try:
        if fourcc == b"VP8 ":
            # 3 字节帧标签 + 3 字节同步码(9d 01 2a) 之后：width/height 各 2 字节小端，
            # 高 2 位是缩放因子，实际尺寸取低 14 位。
            if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
                return None
            w_raw, h_raw = struct.unpack("<HH", payload[6:10])
            return w_raw & 0x3FFF, h_raw & 0x3FFF
        if fourcc == b"VP8L":
            # 1 字节签名(0x2f) 之后 4 字节里位打包：14 位 width-1 + 14 位 height-1。
            if len(payload) < 5 or payload[0] != 0x2F:
                return None
            b1, b2, b3, b4 = payload[1], payload[2], payload[3], payload[4]
            width = 1 + (((b2 & 0x3F) << 8) | b1)
            height = 1 + (((b4 & 0x0F) << 10) | (b3 << 2) | ((b2 & 0xC0) >> 6))
            return width, height
        if fourcc == b"VP8X":
            # flags(1) + reserved(3) + canvas width-1(3字节小端) + canvas height-1(3字节小端)
            if len(payload) < 10:
                return None
            w_bytes = payload[4:7] + b"\x00"
            h_bytes = payload[7:10] + b"\x00"
            width = 1 + struct.unpack("<I", w_bytes)[0]
            height = 1 + struct.unpack("<I", h_bytes)[0]
            return width, height
    except (struct.error, IndexError):
        return None
    return None


def sniff_image_dimensions(data: bytes, ext: str) -> tuple[int, int] | None:
    """按 sniff_image_ext 判出的格式解析宽高。任何解析失败（截断/冷门变体/理解有误）
    都吞掉返回 None，绝不抛异常——调用方把它当"拿不到就是 null"处理。"""
    try:
        if ext == "png":
            return _png_dimensions(data)
        if ext in ("jpg", "jpeg"):
            return _jpeg_dimensions(data)
        if ext == "gif":
            return _gif_dimensions(data)
        if ext == "webp":
            return _webp_dimensions(data)
    except Exception:
        logger.warning("图片宽高解析异常（按 null 处理）：ext=%s", ext, exc_info=True)
        return None
    return None


def remove_file(directory: Path, filename: str | None) -> None:
    """删掉 directory 下的一个文件。filename 只可能是本项目自己生成的（uuid/时间戳式），
    仍然做一次 Path(...).name 归一，杜绝任何路径穿越的可能——和原来 config.py 里
    _remove_avatar_file 的写法一致，这里提出来给头像/聊天图片两处共用。"""
    if not filename:
        return
    try:
        (directory / Path(filename).name).unlink(missing_ok=True)
    except OSError:
        logger.warning("删除文件失败：%s/%s", directory, filename, exc_info=True)
