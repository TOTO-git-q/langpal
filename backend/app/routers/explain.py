"""解析路由：词卡与句子结构。
接 services/explain.py：cache 查询 → provider.generate_json（Haiku 档）→ 写 cache。
返回 JSON 形状见 docs/history/API.md，前端依赖，勿改。

registry 未初始化（WP-A 未完成接线）时，缓存未命中的请求会从 services 层
收到 RuntimeError，这里统一转成 503 {"detail": "engine not ready"}。
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import explain as explain_service
from ..services import word_glosses
from ..services.languages import LanguageTag

router = APIRouter(prefix="/explain", tags=["explain"])


class WordIn(BaseModel):
    language: LanguageTag
    lemma: str
    surface: str
    sentence: str          # token 所在整句，上下文解释的依据
    occurrence: int | None = Field(default=None, ge=0, le=6000)


class SentenceIn(BaseModel):
    language: LanguageTag
    sentence: str


class WordsIn(BaseModel):
    language: LanguageTag
    sentence: str = Field(min_length=1, max_length=word_glosses.MAX_TEXT)


@router.post("/words")
async def explain_words(body: WordsIn):
    try:
        return await word_glosses.explain_words(body.sentence, body.language)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from None
    except RuntimeError:
        raise HTTPException(503, detail="word glosses unavailable") from None


@router.post("/word")
async def explain_word(body: WordIn):
    try:
        return await explain_service.explain_word(
            language=body.language,
            lemma=body.lemma,
            surface=body.surface,
            sentence=body.sentence,
            occurrence=body.occurrence,
        )
    except RuntimeError:
        raise HTTPException(503, detail="engine not ready")


@router.post("/sentence")
async def explain_sentence(body: SentenceIn):
    try:
        return await explain_service.explain_sentence(
            language=body.language,
            sentence=body.sentence,
        )
    except RuntimeError:
        raise HTTPException(503, detail="engine not ready")
