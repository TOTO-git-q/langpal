"""hook_rules / hook_vars / hook_log / hook_rule_state 的读写。都收调用方开好的连接。"""
from __future__ import annotations

import json
import logging

from pydantic import ValidationError

from .. import clock
from .builtin import BUILTINS
from .model import MAX_RULES, Rule, RuleBody

logger = logging.getLogger(__name__)

LOG_KEEP = 500


class Forbidden(ValueError):
    pass


def _dump(body: RuleBody) -> str:
    return body.model_dump_json(exclude={"name", "enabled"})


def _to_rule(row) -> Rule | None:
    try:
        data = json.loads(row["rule_json"])
        return Rule.model_validate({**data, "id": row["id"], "name": row["name"], "enabled": bool(row["enabled"]),
                                    "builtin": row["builtin"]})
    except (ValidationError, ValueError, TypeError):
        logger.warning("hook 规则 %s 解析失败，先不生效", row["id"], exc_info=True)
        return None


def ensure_builtins(conn) -> None:
    for spec in BUILTINS:
        body = RuleBody.model_validate({k: v for k, v in spec.items() if k != "builtin"})
        row = conn.execute("SELECT id, name, enabled, rule_json, created_at, updated_at FROM hook_rules "
                           "WHERE builtin = ?", (spec["builtin"],)).fetchone()
        stamp = clock.stamp()
        if row is None:
            conn.execute("INSERT INTO hook_rules (name, enabled, rule_json, builtin, created_at, updated_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (body.name, int(body.enabled), _dump(body), spec["builtin"], stamp, stamp))
        elif row["created_at"] == row["updated_at"] and \
                (row["name"], bool(row["enabled"]), row["rule_json"]) != (body.name, body.enabled, _dump(body)):
            # 用户没改过：跟着新版的默认定义走
            conn.execute("UPDATE hook_rules SET name = ?, enabled = ?, rule_json = ?, created_at = ?, updated_at = ? "
                         "WHERE id = ?", (body.name, int(body.enabled), _dump(body), stamp, stamp, row["id"]))


def list_rules(conn) -> list[Rule]:
    rows = conn.execute("SELECT id, name, enabled, rule_json, builtin FROM hook_rules ORDER BY id").fetchall()
    return [rule for rule in map(_to_rule, rows) if rule is not None]


def get_rule(conn, rule_id: int) -> Rule | None:
    row = conn.execute("SELECT id, name, enabled, rule_json, builtin FROM hook_rules WHERE id = ?",
                       (rule_id,)).fetchone()
    return _to_rule(row) if row else None


def create_rule(conn, body: RuleBody) -> Rule:
    if conn.execute("SELECT count(*) FROM hook_rules").fetchone()[0] >= MAX_RULES:
        raise Forbidden(f"规则最多 {MAX_RULES} 条")
    stamp = clock.stamp()
    rule_id = conn.execute(
        "INSERT INTO hook_rules (name, enabled, rule_json, builtin, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
        (body.name, int(body.enabled), _dump(body), stamp, stamp)).lastrowid
    return get_rule(conn, rule_id)


def update_rule(conn, rule_id: int, patch: dict) -> Rule:
    current = get_rule(conn, rule_id)
    if current is None:
        raise LookupError("没有这条规则")
    merged = {**current.model_dump(exclude={"id", "builtin"}), **{k: v for k, v in patch.items()
                                                                  if k not in ("id", "builtin")}}
    body = RuleBody.model_validate(merged)
    # 带微秒，和写入时的 created_at（到秒）一定不同：自带规则据此判断"用户改过"
    stamp = clock.now().isoformat(sep=" ", timespec="microseconds")
    conn.execute("UPDATE hook_rules SET name = ?, enabled = ?, rule_json = ?, updated_at = ? WHERE id = ?",
                 (body.name, int(body.enabled), _dump(body), stamp, rule_id))
    return get_rule(conn, rule_id)


def delete_rule(conn, rule_id: int) -> None:
    row = conn.execute("SELECT builtin FROM hook_rules WHERE id = ?", (rule_id,)).fetchone()
    if row is None:
        raise LookupError("没有这条规则")
    if row[0]:
        raise Forbidden("自带规则不能删，只能关")
    conn.execute("DELETE FROM hook_rules WHERE id = ?", (rule_id,))
    conn.execute("DELETE FROM hook_rule_state WHERE rule_id = ?", (rule_id,))


# ---------------------------------------------------------------- 变量

def list_vars(conn, persona_id: int | None = None) -> list[dict]:
    if persona_id is None:
        rows = conn.execute("SELECT scope, persona_id, name, value FROM hook_vars ORDER BY scope, persona_id, name")
    else:
        rows = conn.execute("SELECT scope, persona_id, name, value FROM hook_vars WHERE scope = 'global' OR "
                            "(scope = 'persona' AND persona_id = ?) ORDER BY scope, name", (persona_id,))
    items = []
    for row in rows:
        try:
            value = json.loads(row[3])
        except (TypeError, ValueError):
            value = row[3]
        items.append({"name": row[2], "value": value, "scope": row[0],
                      "persona_id": row[1] if row[0] == "persona" else None})
    return items


def set_var(conn, name: str, value, scope: str, persona_id: int | None) -> None:
    owner = (persona_id or 0) if scope == "persona" else 0
    if value is None:
        conn.execute("DELETE FROM hook_vars WHERE scope = ? AND persona_id = ? AND name = ?", (scope, owner, name))
        return
    if conn.execute("SELECT count(*) FROM hook_vars").fetchone()[0] >= 2000 and not conn.execute(
            "SELECT 1 FROM hook_vars WHERE scope = ? AND persona_id = ? AND name = ?", (scope, owner, name)).fetchone():
        raise Forbidden("变量太多了（上限 2000 个）")
    conn.execute("INSERT OR REPLACE INTO hook_vars (scope, persona_id, name, value) VALUES (?, ?, ?, ?)",
                 (scope, owner, name, json.dumps(value, ensure_ascii=False)))


def inc_var(conn, name: str, by: float, scope: str, persona_id: int | None):
    owner = (persona_id or 0) if scope == "persona" else 0
    row = conn.execute("SELECT value FROM hook_vars WHERE scope = ? AND persona_id = ? AND name = ?",
                       (scope, owner, name)).fetchone()
    try:
        current = float(json.loads(row[0])) if row else 0.0
    except (TypeError, ValueError):
        current = 0.0
    result = current + by
    result = int(result) if float(result).is_integer() else result
    set_var(conn, name, result, scope, persona_id)
    return result


# ---------------------------------------------------------------- 日志 / 规则状态

def log(conn, event: str, rule_id: int | None, persona_id: int | None, detail: dict) -> None:
    conn.execute("INSERT INTO hook_log (at, rule_id, event, persona_id, detail_json) VALUES (?, ?, ?, ?, ?)",
                 (clock.stamp(), rule_id, event, persona_id, json.dumps(detail, ensure_ascii=False, default=str)))
    conn.execute("DELETE FROM hook_log WHERE id <= (SELECT id FROM hook_log ORDER BY id DESC LIMIT 1 OFFSET ?)",
                 (LOG_KEEP,))


def read_log(conn, limit: int) -> list[dict]:
    names = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM hook_rules")}
    items = []
    for row in conn.execute("SELECT at, rule_id, event, persona_id, detail_json FROM hook_log ORDER BY id DESC LIMIT ?",
                            (limit,)):
        try:
            detail = json.loads(row[4])
        except (TypeError, ValueError):
            detail = {}
        items.append({"at": row[0], "rule_id": row[1], "rule_name": detail.get("rule_name") or names.get(row[1]),
                      "event": row[2], "persona_id": row[3], "actions": detail.get("actions", []),
                      "skipped_reason": detail.get("skipped_reason")})
    return items


def rule_state(conn, rule_id: int, persona_id: int) -> dict:
    row = conn.execute("SELECT last_at, last_turn, last_day, last_session FROM hook_rule_state "
                       "WHERE rule_id = ? AND persona_id = ?", (rule_id, persona_id)).fetchone()
    return dict(zip(("last_at", "last_turn", "last_day", "last_session"), row)) if row else {}


def mark_fired(conn, rule_id: int, persona_id: int, turn: int | None, session: str) -> None:
    conn.execute(
        """INSERT INTO hook_rule_state (rule_id, persona_id, last_at, last_turn, last_day, last_session)
           VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(rule_id, persona_id) DO UPDATE SET last_at = excluded.last_at,
           last_turn = excluded.last_turn, last_day = excluded.last_day, last_session = excluded.last_session""",
        (rule_id, persona_id, clock.stamp(), turn, clock.today(), session))
