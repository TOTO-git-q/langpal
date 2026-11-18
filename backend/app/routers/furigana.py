"""Local dictionary readings for Japanese text; no LLM provider is used."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from ..services.furigana import annotate
from ..security import same_origin

router = APIRouter(prefix='/reader/furigana', tags=['reading'])


class TextInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(max_length=12000)


@router.post('', dependencies=[Depends(same_origin)])
def readings(body: TextInput):
    return {'tokens': annotate(body.text)}
