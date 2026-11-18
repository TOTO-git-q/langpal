"""Offline: what the chat persona is told about speaking-coach lessons (backend/app/services/coach_bridge.py).

Runs against a temp bridge file (COACH_BRIDGE_FILE) and an in-memory settings table; never touches data/.
    .venv\\Scripts\\python.exe -m pytest tests/test_coach_bridge.py   (or run the file directly)
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import coach_bridge  # noqa: E402

PERSONA = {"id": 5, "language": "ja"}


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def _bridge(lesson_hours_ago: float = 2, lesson_id: str = "2026-11-05_ja_1") -> dict:
    return {"version": 1, "updatedAt": _iso(0), "langs": {"ja": {
        "lessonsDone": 1,
        "lastLesson": {"id": lesson_id, "date": _iso(lesson_hours_ago), "unit": "場面別の自己紹介",
                       "comment": "敬語の切り替えが遅い", "next": "n", "homework": "自己紹介を録音",
                       "errors": [{"said": "分で交流", "correct": "文で交流", "reason": "同音异义"}]},
        "debts": [{"id": "ja-x", "name": "汉字词意思偏差", "name_zh": "", "rule": "中日同形词意思不同",
                   "impact": "unnatural", "recent30d": 2, "total": 2, "lastSeen": _iso(2),
                   "examples": [{"said": "分で交流", "correct": "文で交流"}]}],
    }}}


def _write(data) -> None:
    path = Path(os.environ["COACH_BRIDGE_FILE"])
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    st = path.stat()  # force a new mtime even inside the same second, so the module cache re-reads
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))


def test_all():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["COACH_BRIDGE_FILE"] = str(Path(tmp) / "langpal.json")
        conn = _conn()

        # no coach at all: nothing injected
        assert coach_bridge.system_block(conn, "ja") == ""
        assert coach_bridge.lesson_note(conn, PERSONA) == ("", None)

        # standing block: recurring problem with the learner's own words, plus the last lesson's comment
        _write(_bridge())
        block = coach_bridge.system_block(conn, "ja")
        assert "汉字词意思偏差" in block and "把「文で交流」说成「分で交流」" in block
        assert "敬語の切り替えが遅い" in block
        assert coach_bridge.system_block(conn, "en") == ""  # Emma gets nothing from the Japanese lessons

        # fresh lesson: one note, then silence once it has been delivered
        note, lid = coach_bridge.lesson_note(conn, PERSONA)
        assert lid == "2026-11-05_ja_1" and "说成了「分で交流」，应该是「文で交流」" in note and "自己紹介を録音" in note
        assert coach_bridge.lesson_note(conn, PERSONA)[1] == lid  # not marked yet: generation might have failed
        coach_bridge.mark_seen(conn, PERSONA["id"], lid)
        assert coach_bridge.lesson_note(conn, PERSONA) == ("", None)
        assert coach_bridge.lesson_note(conn, {"id": 6, "language": "ja"})[1] == lid  # each persona hears it once

        # a lesson first seen long after it happened is not news: silently marked as read
        _write(_bridge(lesson_hours_ago=100, lesson_id="2026-11-01_ja_1"))
        assert coach_bridge.lesson_note(conn, {"id": 7, "language": "ja"}) == ("", None)
        assert conn.execute("SELECT value FROM settings WHERE key='coach_lesson_seen_p7'").fetchone()["value"] == "2026-11-01_ja_1"

        # switched off in 設定
        _write(_bridge(lesson_id="2026-11-06_ja_1"))
        conn.execute("INSERT INTO settings VALUES ('coach_bridge', '0')")
        assert coach_bridge.system_block(conn, "ja") == ""
        assert coach_bridge.lesson_note(conn, PERSONA) == ("", None)

        # broken file: treated as no coach, never raises
        conn.execute("DELETE FROM settings WHERE key='coach_bridge'")
        Path(os.environ["COACH_BRIDGE_FILE"]).write_text("{not json", encoding="utf-8")
        os.utime(os.environ["COACH_BRIDGE_FILE"], ns=(0, 10**18))
        assert coach_bridge.system_block(conn, "ja") == ""
    print("coach_bridge: all checks passed")


def test_chat_corrections_to_inbox():
    import asyncio
    import types

    import app.db  # only to swap get_conn for an in-memory settings table below; never opens data/

    # markers: own line, inline, other arrows; lines left empty disappear
    clean, fixes = coach_bridge.extract_fixes(
        "それ「手伝ってくれた」でしょ\n⟦fix:手伝いました=>手伝ってくれました⟧\n本当に ⟦fix:私も行きます→行く行く⟧\n⟦mood:smug⟧"
    )
    assert clean == "それ「手伝ってくれた」でしょ\n本当に\n⟦mood:smug⟧"
    assert fixes == [("手伝いました", "手伝ってくれました"), ("私も行きます", "行く行く")]
    assert coach_bridge.extract_fixes("普通の返事") == ("普通の返事", [])

    # only phrases the user really wrote (spaces / punctuation ignored), and only real changes
    user = "昨日、先輩が データの整理を手伝いました。はい、私も行きます！"
    assert coach_bridge.match_fixes(
        [("手伝いました", "手伝ってくれました"), ("私も 行きます", "行く行く"), ("勉強しました", "勉強した"), ("はい", "はい。")],
        user,
    ) == [("手伝いました", "手伝ってくれました"), ("私も 行きます", "行く行く")]

    with tempfile.TemporaryDirectory() as tmp:
        bridge = Path(tmp) / "data" / "bridge" / "langpal.json"
        bridge.parent.mkdir(parents=True)
        os.environ["COACH_BRIDGE_FILE"] = str(bridge)
        os.environ.pop("COACH_INBOX_FILE", None)
        conn = _conn()
        assert coach_bridge.fix_instruction(conn, "ja") == ""  # coach never exported: no marker rule

        data = _bridge()
        data["langs"]["ja"]["catalog"] = [{"id": "ja-juju", "name": "授受表現", "name_zh": "授受表现",
                                          "category": "grammar", "rule": "てくれる", "impact": "impolite"}]
        _write(data)
        assert "⟦fix:" in coach_bridge.fix_instruction(conn, "ja")
        assert coach_bridge.fix_instruction(conn, "de") == ""  # the coach teaches ja / en only

        # fake DB (settings only) and fake helper model
        sys.modules["app.db"].get_conn = _conn
        answer = {"items": [
            {"index": 0, "keep": True, "reason": "别人为我做事", "category": "grammar", "impact": "impolite",
             "debt_id": "ja-juju", "new_debt_name": "", "new_debt_name_zh": "", "new_rule": ""},
            {"index": 1, "keep": True, "reason": "对朋友太生硬", "category": "register", "impact": "unnatural",
             "debt_id": "ja-unknown", "new_debt_name": "親しい相手に硬い", "new_debt_name_zh": "对平辈生硬", "new_rule": "朋友用普通体"},
            {"index": 1, "keep": True, "reason": "dup", "category": "grammar", "impact": "unnatural",
             "debt_id": "", "new_debt_name": "x", "new_debt_name_zh": "", "new_rule": ""},
        ]}

        class FakeProvider:
            prompts = []

            async def generate_json(self, prompt, schema):
                FakeProvider.prompts.append(prompt)
                return answer

        sys.modules["app.providers.registry"] = types.SimpleNamespace(get_utility_provider=FakeProvider)
        n = asyncio.run(coach_bridge.record_fixes(5, "糖糖（あめ）", "ja",
                                                  [("手伝いました", "手伝ってくれました"), ("私も 行きます", "行く行く"),
                                                   ("編造", "x")], user))
        assert n == 2, n
        assert "ja-juju：授受表現" in FakeProvider.prompts[0]
        inbox = Path(tmp) / "data" / "inbox" / "langpal.jsonl"
        lines = [json.loads(x) for x in inbox.read_text(encoding="utf-8").splitlines()]
        assert [x["debt_id"] for x in lines] == ["ja-juju", None]
        assert lines[0]["debt_name"] == "授受表現" and lines[0]["impact"] == "impolite"
        assert lines[1]["debt_name"] == "親しい相手に硬い" and lines[1]["rule"] == "朋友用普通体"
        assert all(x["v"] == 1 and x["lang"] == "ja" and x["persona"] == "糖糖（あめ）" and len(x["id"]) == 32 for x in lines)

        # switched off: nothing written
        def off():
            c = _conn()
            c.execute("INSERT INTO settings VALUES ('coach_bridge', '0')")
            return c
        sys.modules["app.db"].get_conn = off
        assert asyncio.run(coach_bridge.record_fixes(5, "糖糖", "ja", [("手伝いました", "手伝ってくれました")], user)) == 0
        assert len(inbox.read_text(encoding="utf-8").splitlines()) == 2
    print("coach_bridge: chat corrections → inbox passed")


if __name__ == "__main__":
    test_all()
    test_chat_corrections_to_inbox()
