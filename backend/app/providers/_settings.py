"""settings 表的小工具读取，给各 provider 共用（避免每个文件各写一遍 SELECT）。

只负责读；写入统一走 routers/config.py 的通用 PUT /api/settings（含密钥掩码规则，
见 docs/history/API-v1.3-engines.md）。这里绝不打印/返回密钥类 value 之外的额外处理——调用方
自己决定要不要把读到的值当密钥对待（这个模块不知道哪些 key 是密钥）。
"""
from ..db import get_conn


def get_setting(key: str, default: str = "") -> str:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or row["value"] is None:
        return default
    return row["value"]
