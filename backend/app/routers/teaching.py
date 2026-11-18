"""Course settings, lesson runs and builds."""
import asyncio
from contextlib import closing
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..db import get_conn
from ..services import clock, course, languages
from ..security import same_origin

router = APIRouter(prefix="/teaching", tags=["teaching"], dependencies=[Depends(same_origin)])


@router.get("/presets")
def list_presets():
    return {"items": [course.lessons.preset(item) for item in course.presets().values()]}


@router.get('/plan/{language}')
def learning_plan(language: languages.LanguageTag):
    return {'active': False, 'targets': []}


@router.post('/observe')
def observe():
    return {'status': 'inactive'}


def _language_bundle(conn, language: str) -> dict:
    if language not in languages.registered(conn):
        raise HTTPException(404, "请先添加这门语言")
    settings = course.language_settings(conn, language)
    return {"language": language, "teaching": {"mode": settings.mode, "preset_id": settings.preset}, "progress": course.planner.overview(conn, language, clock.now())}


@router.get("/settings/{language}")
def language_settings(language: languages.LanguageTag):
    with closing(get_conn()) as conn, conn:
        return _language_bundle(conn, language)


@router.put("/settings/{language}")
def save_language_settings(language: languages.LanguageTag, body: course.Teaching):
    try:
        with closing(get_conn()) as conn, conn:
            course.save_language_settings(conn, language, body)
            return _language_bundle(conn, language)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


class LessonStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: languages.LanguageTag
    lesson_id: str | None = None
    practice: bool = False


class LessonRun(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: int = Field(strict=True)

    @model_validator(mode='before')
    @classmethod
    def require_run_id(cls, values):
        if not isinstance(values, dict) or type(values.get('run_id')) is not int:
            raise HTTPException(409, course.lesson.RUN_CHANGED)
        return values


class LessonAnswer(LessonRun):
    card: str
    item: int = Field(ge=0, strict=True)
    text: str


class LessonSubmit(LessonRun):
    text: str
    seconds: int = Field(ge=0, strict=True)


class LessonQuiz(LessonRun):
    answers: list[list[Any]]
    seconds: int = Field(ge=0, strict=True)


class LessonStop(LessonRun):
    dismiss: bool = False


@router.get('/lesson')
def lesson_view():
    with closing(get_conn()) as conn, conn:
        return {'lesson': course.lesson.current(conn, clock.now())}


@router.get('/lesson/audio')
def lesson_audio(card: str, group: int):
    with closing(get_conn()) as conn, conn:
        recording = course.lesson.audio(conn, card, group)
    return Response(recording, media_type='audio/wav', headers={'Cache-Control': 'no-store'})


@router.post('/lesson/start', status_code=201)
async def lesson_start(body: LessonStart):
    with closing(get_conn()) as conn, conn:
        lesson_id = body.lesson_id
        if body.practice:
            selected, authored = course.lesson.start_target(conn, body.language, lesson_id)
            lesson_id = authored.id
            if not course.generate.unused(conn, body.language, selected.id, lesson_id, authored.cards[-1]):
                try:
                    made = await asyncio.wait_for(course.generate.spare(body.language, lesson_id), timeout=90)
                except asyncio.TimeoutError:
                    made = False
                if not made:
                    raise HTTPException(503, '新题没出成，再点一次')
        return {'lesson': course.lesson.start(conn, body.language, lesson_id, practice=body.practice)}


@router.post('/lesson/answer')
async def lesson_answer(body: LessonAnswer | None = None):
    if body is None:
        raise HTTPException(409, course.lesson.RUN_CHANGED)
    with closing(get_conn()) as conn, conn:
        return await course.lesson.answer(conn, body.card, body.item, body.text, body.run_id)


@router.post('/lesson/submit')
async def lesson_submit(body: LessonSubmit | None = None):
    if body is None:
        raise HTTPException(409, course.lesson.RUN_CHANGED)
    with closing(get_conn()) as conn, conn:
        return {'lesson': await course.lesson.submit(conn, body.text, body.seconds, body.run_id)}


@router.post('/lesson/quiz')
def lesson_quiz(body: LessonQuiz | None = None):
    if body is None:
        raise HTTPException(409, course.lesson.RUN_CHANGED)
    with closing(get_conn()) as conn, conn:
        return {'lesson': course.lesson.quiz(conn, body.answers, body.seconds, body.run_id)}


@router.post('/lesson/stop')
def lesson_stop(body: LessonStop | None = None):
    if body is None:
        raise HTTPException(409, course.lesson.RUN_CHANGED)
    with closing(get_conn()) as conn, conn:
        course.lesson.stop(conn, body.run_id, dismiss=body.dismiss)
    return {'lesson': None}




class CourseBuild(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: languages.LanguageTag
    exam: str
    notes: str | None = Field(default=None, max_length=2000)
    material: str | None = Field(default=None, max_length=12000)


@router.post('/build', status_code=202)
def build_start(body: CourseBuild):
    try:
        return {'course_id': course.builder.start(**body.model_dump())}
    except course.builder.Busy:
        raise HTTPException(409, '有一门课正在做') from None


@router.get('/build')
def build_list():
    return {'builds': course.builder.list_builds()}


@router.post('/build/{course_id}/stop')
def build_stop(course_id: str):
    try:
        course.builder.stop(course_id)
    except FileNotFoundError:
        raise HTTPException(404) from None
    return {}


@router.post('/build/{course_id}/resume', status_code=202)
def build_resume(course_id: str):
    try:
        course.builder.resume(course_id)
    except FileNotFoundError:
        raise HTTPException(404) from None
    except course.builder.Busy:
        raise HTTPException(409, '有一门课正在做') from None
    return {'course_id': course_id}


@router.delete('/build/{course_id}')
def build_delete(course_id: str):
    try:
        with closing(get_conn()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            course.lesson.ensure(conn)
            course.ledger.ensure(conn)
            conn.execute("""UPDATE course_lessons SET ended_at=?, outcome='stopped'
                            WHERE course_id=? AND ended_at IS NULL""", (clock.stamp(), course_id))
            conn.execute("""DELETE FROM study_events WHERE kind IN ('reading', 'listening') AND ref IN
                            (SELECT 'lesson:run' || id FROM course_lessons WHERE course_id=?)""", (course_id,))
            for table in ('course_events', 'course_generated', 'course_lessons'):
                conn.execute(f'DELETE FROM {table} WHERE course_id=?', (course_id,))
            for language in languages.registered(conn):
                settings = course.language_settings(conn, language)
                if settings.preset == course_id:
                    course.save_language_settings(conn, language, course.Teaching(mode='off'))
            course.builder.delete(course_id)
    except FileNotFoundError:
        raise HTTPException(404) from None
    return {}
