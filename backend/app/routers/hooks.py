"""事件 hook 接口（docs/LORE-AND-HOOKS.md 2.7）。主动消息的 SSE 在 routers/chat.py。"""
from __future__ import annotations

from contextlib import closing
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from ..security import same_origin
from ..services import hooks
from ..services.hooks import engine, store
from ..services.situation import VAR_NAME

router = APIRouter(prefix="/hooks", tags=["hooks"], dependencies=[Depends(same_origin)])


class FireIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: Literal["chat.open", "chat.idle"]
    persona_id: int | None = Field(None, ge=1)  # 主聊天：不带就是主人设
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def small(cls, value):
        if len(value) > 20:
            raise ValueError("payload 太大")
        clean = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 40:
                raise ValueError("payload 的键不对")
            if item is not None and not isinstance(item, (str, int, float, bool)):
                raise ValueError("payload 只收数字、文字、真假")
            clean[key] = item[:500] if isinstance(item, str) else item
        return clean


class VarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(pattern=VAR_NAME)]
    value: Annotated[str, StringConstraints(max_length=500)] | int | float | bool | None
    scope: Literal["persona", "global"] = "persona"
    persona_id: int | None = Field(None, ge=1)


def _rule(rule) -> dict:
    return rule.model_dump()


def _validation(error: ValidationError) -> HTTPException:
    issue = error.errors(include_input=False)[0]
    return HTTPException(422, f"规则有字段不对：{'.'.join(map(str, issue['loc']))} {issue['msg']}")


@router.get("/meta")
def meta():
    return hooks.meta()


@router.get("/rules")
def list_rules():
    with closing(engine.connect()) as conn:
        engine.ensure_seeded(conn)
        return {"items": [_rule(r) for r in store.list_rules(conn)]}


@router.post("/rules", status_code=201)
def create_rule(body: dict = Body(...)):
    try:
        rule = hooks.RuleBody.model_validate({k: v for k, v in body.items() if k not in ("id", "builtin")})
    except ValidationError as error:
        raise _validation(error) from None
    try:
        with closing(engine.connect()) as conn, conn:
            engine.ensure_seeded(conn)
            return _rule(store.create_rule(conn, rule))
    except store.Forbidden as error:
        raise HTTPException(409, str(error)) from None


@router.put("/rules/{rule_id}")
def update_rule(rule_id: int, patch: dict = Body(...)):
    try:
        with closing(engine.connect()) as conn, conn:
            return _rule(store.update_rule(conn, rule_id, patch))
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValidationError as error:
        raise _validation(error) from None


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int):
    try:
        with closing(engine.connect()) as conn, conn:
            store.delete_rule(conn, rule_id)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except store.Forbidden as error:
        raise HTTPException(409, str(error)) from None
    return {"ok": True}


@router.post("/fire")
def fire(body: FireIn):
    try:
        return hooks.fire(body.event, body.persona_id, body.payload)
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/pending")
def pending():
    return {"items": hooks.pending()}


@router.get("/log")
def log(limit: int = Query(50, ge=1, le=500)):
    with closing(engine.connect()) as conn:
        return {"items": store.read_log(conn, limit)}


@router.get("/vars")
def list_vars(persona_id: int | None = Query(None, ge=1)):
    with closing(engine.connect()) as conn:
        return {"items": store.list_vars(conn, persona_id)}


@router.put("/vars")
def put_var(body: VarIn):
    if body.scope == "persona" and body.persona_id is None:
        raise HTTPException(422, "联系人变量要带 persona_id")
    try:
        with closing(engine.connect()) as conn, conn:
            store.set_var(conn, body.name, body.value, body.scope, body.persona_id)
            return {"items": store.list_vars(conn, body.persona_id)}
    except store.Forbidden as error:
        raise HTTPException(409, str(error)) from None
