"""Today, difficulty advice, question-type diagnosis and statistics. docs/LEARNING.md sections 3-4.

Everything here is read-only and computed from study_events and review_log.
"""
import json
from datetime import timedelta

from .. import clock
from . import cards, store

READING_TYPES = {
    "detail": "事实细节", "inference": "推断", "vocabulary": "词义", "reference": "指代",
    "insertion": "句子插入", "summary": "主旨与总结", "attitude": "作者态度",
    # JLPT N1 reading: one tag per exam section (大题). A JLPT set is tagged by its section.
    "jlpt_short": "内容理解（短文）", "jlpt_mid": "内容理解（中文）", "jlpt_long": "内容理解（长文）",
    "jlpt_claim": "主张理解", "jlpt_integrated": "统合理解", "jlpt_search": "信息检索",
}
LISTENING_TYPES = {"gist": "主旨", "detail": "细节", "function": "功能与态度", "organization": "组织结构",
                   "inference": "推断",
                   # JLPT N1 listening sections
                   "jlpt_task": "课题理解", "jlpt_points": "要点理解", "jlpt_gist": "概要理解",
                   "jlpt_response": "即时应答", "jlpt_integrated": "统合理解"}
# Practice format -> the JLPT section it reproduces (the tag every question of that set gets).
JLPT_READING = {"jlpt_short": "jlpt_short", "jlpt_mid": "jlpt_mid", "jlpt_long": "jlpt_long", "jlpt_theme": "jlpt_claim"}
JLPT_LISTENING = {"ja_task": "jlpt_task", "ja_points": "jlpt_points", "ja_gist": "jlpt_gist",
                  "ja_response": "jlpt_response", "ja_integrated": "jlpt_integrated"}
TYPES = {"reading": READING_TYPES, "listening": LISTENING_TYPES}
CAUSES = {"not_heard": "没听清", "not_understood": "听清了没听懂", "misjudged": "听懂了答错"}
ADVICE_WINDOW = 5
ADVICE_MIN = 3
TYPE_MIN_SAMPLES = 8
TYPE_WINDOW_DAYS = 90


def _events(conn, language, kind, since=None, limit=None):
    sql = "SELECT * FROM study_events WHERE language = ? AND kind = ?"
    args = [language, kind]
    if since:
        sql += " AND at >= ?"
        args.append(since)
    sql += " ORDER BY at DESC, id DESC"
    if limit:
        sql += " LIMIT ?"
        args.append(limit)
    rows = conn.execute(sql, args).fetchall()
    return [{**dict(r), "data": json.loads(r["data_json"] or "{}")} for r in rows]


def _day_start(offset_days=0) -> str:
    return (clock.now() - timedelta(days=offset_days)).strftime("%Y-%m-%d") + " 00:00:00"


# ---------------------------------------------------------------- advice


def _advice(events, skill):
    if len(events) < ADVICE_MIN:
        return {"level": None, "suggestion": None, "basis": f"做满 {ADVICE_MIN} 次后再给建议", "n": len(events)}
    correct = sum(e["data"].get("correct", 0) for e in events)
    total = sum(e["data"].get("total", 0) for e in events) or 1
    accuracy = correct / total
    per = total / len(events)
    basis = f"最近 {len(events)} 次平均答对 {correct / len(events):.1f}/{per:.0f}"
    rate = None
    if skill == "reading":
        rated = [e for e in events if e["data"].get("words")]
        if rated:
            rate = sum(e["data"].get("lookups", 0) / e["data"]["words"] for e in rated) / len(rated)
            basis += f"，查词 {rate * 100:.1f}%"
    if accuracy > 0.90 and (skill != "reading" or (rate is not None and rate < 0.02)):
        level, text = "up", "可以升一档"
    elif accuracy < 0.65 or (skill == "reading" and rate is not None and rate > 0.08):
        level, text = "down", "降一档会学得更快"
    else:
        level, text = "keep", "难度正合适"
    return {"level": level, "suggestion": text, "basis": basis, "n": len(events),
            "accuracy": round(accuracy, 3), "lookup_rate": None if rate is None else round(rate, 4)}


def type_accuracy(conn, language, skill):
    since = clock.stamp(clock.now() - timedelta(days=TYPE_WINDOW_DAYS))
    counts: dict[str, list[int]] = {}
    for event in _events(conn, language, skill, since):
        for item in event["data"].get("items") or []:
            kind = item.get("type")
            if kind in TYPES[skill]:
                bucket = counts.setdefault(kind, [0, 0])
                bucket[0] += int(bool(item.get("correct")))
                bucket[1] += 1
    return {kind: {"accuracy": round(c / n, 3), "n": n} for kind, (c, n) in counts.items()}


def weak_types(conn, language):
    rows = []
    for skill in TYPES:
        for kind, value in type_accuracy(conn, language, skill).items():
            if value["n"] >= TYPE_MIN_SAMPLES:
                rows.append({"skill": skill, "type": kind, "label": TYPES[skill][kind], **value})
    return sorted(rows, key=lambda r: (r["accuracy"], -r["n"]))


def weakest_type(conn, language, skill) -> str | None:
    """The type to ask one more question about next time (needs >= 8 answered of that type)."""
    rows = [r for r in weak_types(conn, language) if r["skill"] == skill]
    return rows[0]["type"] if rows and rows[0]["accuracy"] < 1 else None


def advice(conn, language) -> dict:
    return {"language": language,
            "reading": _advice(_events(conn, language, "reading", limit=ADVICE_WINDOW), "reading"),
            "listening": _advice(_events(conn, language, "listening", limit=ADVICE_WINDOW), "listening"),
            "weak_types": weak_types(conn, language)}


# ---------------------------------------------------------------- stats


def stats(conn, language, days=30) -> dict:
    since = clock.stamp(clock.now() - timedelta(days=days))
    result = {"language": language, "days": days}
    for skill in ("reading", "listening"):
        events = _events(conn, language, skill, since)
        if not events:
            result[skill] = None
            continue
        correct = sum(e["data"].get("correct", 0) for e in events)
        total = sum(e["data"].get("total", 0) for e in events)
        types = {}
        for event in events:
            for item in event["data"].get("items") or []:
                if item.get("type") in TYPES[skill]:
                    bucket = types.setdefault(item["type"], {"n": 0, "correct": 0})
                    bucket["n"] += 1
                    bucket["correct"] += int(bool(item.get("correct")))
        result[skill] = {"count": len(events), "accuracy": round(correct / total, 3) if total else None,
                         "types": {k: {**v, "accuracy": round(v["correct"] / v["n"], 3), "label": TYPES[skill][k]}
                                   for k, v in types.items()} or None}
    if result["listening"] is not None:
        causes = {}
        for event in _events(conn, language, "listening_cause", since):
            for item in event["data"].get("items") or []:
                if item.get("cause") in CAUSES:
                    causes[item["cause"]] = causes.get(item["cause"], 0) + 1
        result["listening"]["causes"] = causes or None
        dictation = [e["data"].get("score") for e in _events(conn, language, "dictation", since)
                     if isinstance(e["data"].get("score"), (int, float))]
        result["listening"]["dictation"] = round(sum(dictation) / len(dictation), 3) if dictation else None
        plays = _events(conn, language, "listening_play", since)
        result["listening"]["replays"] = max(0, len(plays) - len({p["ref"] for p in plays})) if plays else None
    reviews = conn.execute(
        """SELECT count(*), sum(l.rating = 1 OR l.peeked = 1) FROM review_log l JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.at >= ? AND l.weak = 0""", (language, since)).fetchone()
    result["review"] = None if not reviews[0] else {
        "count": reviews[0], "forgot": reviews[1] or 0,
        "retention_7d": cards.retention(conn, language, 7), "retention_30d": cards.retention(conn, language, 30)}
    met = conn.execute("SELECT count(*) FROM vocab_entries WHERE language = ? AND encounters > 0",
                       (language,)).fetchone()[0]
    result["words_encountered"] = met or None
    return result


# ---------------------------------------------------------------- today


def _course_overview(conn, language):
    from .. import course
    return course.planner.overview(conn, language, clock.now())


def _speaking(conn, language):
    try:
        from .. import coach_bridge
        lesson = coach_bridge.latest_lessons(conn).get(language)
        debts = coach_bridge.open_debts(conn, language)
    except Exception:
        return None, 0
    return lesson, debts


def today(conn, language) -> dict:
    start = _day_start()
    week = _day_start(6)
    summary = cards.summary(conn, language)
    reviewed_today = conn.execute(
        """SELECT count(*) FROM review_log l JOIN review_cards c ON c.id = l.card_id
           WHERE c.language = ? AND l.at >= ? AND l.weak = 0""", (language, start)).fetchone()[0]
    pending = summary["due_now"] + summary["new_available"]
    steps = [{"kind": "review", "count": pending, "done": reviewed_today > 0 and pending == 0,
              "reviewed_today": reviewed_today}]
    tips = advice(conn, language)
    inputs = []
    for skill in ("reading", "listening"):
        week_count = len(_events(conn, language, skill, week))
        done_today = len(_events(conn, language, skill, start))
        inputs.append((week_count, skill, {"kind": skill, "count": done_today, "done": done_today > 0,
                                           "week": week_count, "suggestion": tips[skill]["suggestion"],
                                           "basis": tips[skill]["basis"]}))
    steps.extend(step for _, _, step in sorted(inputs, key=lambda x: (x[0], x[1] != "reading")))
    overview = _course_overview(conn, language)
    words = [{"lemma": r["lemma"], "meaning": r["meaning"]} for r in cards.due_vocab(conn, language, 3)]
    lesson, debts = _speaking(conn, language)
    chatted = conn.execute(
        """SELECT count(*) FROM messages m JOIN sessions s ON s.id = m.session_id
           WHERE m.role = 'user' AND COALESCE(m.language, s.language) = ? AND m.created_at >= ?""",
        (language, start)).fetchone()[0]
    lesson_today = bool(lesson) and (clock.parse(lesson.get("date")) or clock.now() - timedelta(days=2)).date() == clock.now().date()
    steps.append({"kind": "output", "done": bool(chatted) or lesson_today,
                  "target": {"lesson": overview["next"], "words": words, "speaking_debts": debts,
                             "last_lesson": {"id": lesson.get("id"), "date": lesson.get("date")} if lesson else None}})
    return {"language": language, "date": clock.today(), "steps": steps}
