"""本机时间和随机源，世界书与 hook 共用。

测试里把 `clock.now` 换成固定时间、把 `clock.rng` 换成 `random.Random(种子)`，
概率、分组抽签、{{random}}/{{roll}} 宏就都能复现。数据库里的时间一律是本机时间
`YYYY-MM-DD HH:MM:SS`（和 messages.created_at 同格式）。
"""
import random
from datetime import datetime

rng = random.Random()

_FORMAT = "%Y-%m-%d %H:%M:%S"
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def now() -> datetime:
    return datetime.now()


def stamp(value: datetime | None = None) -> str:
    return (value or now()).strftime(_FORMAT)


def parse(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:19], _FORMAT)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed


def today() -> str:
    return now().strftime("%Y-%m-%d")
