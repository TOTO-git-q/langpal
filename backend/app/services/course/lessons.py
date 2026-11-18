"""Strict authored course and lesson files."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...db import DATA_DIR
from ..languages import LanguageTag
from ..teaching_schema import Slug


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Practice(Strict):
    """Where the unlimited practice of one task type lives, with a short reminder of the method."""
    lesson: Slug | None = None        # the lesson whose last card holds the sets and `more`
    open: Literal['shadowing', 'voice'] | None = None
    title: str
    brief: list[str]
    points: dict[Slug, Slug] = {}     # point of a question -> the lesson that teaches it
    venue: Literal['chat'] | None = None   # 'chat': a timed writing she marks, done in the chat page

    @model_validator(mode='after')
    def destination(self):
        if (self.lesson is None) == (self.open is None):
            raise ValueError()
        return self


class Part(Strict):
    title: str
    lessons: list[Slug]
    practice: Practice | None = None


class Section(Strict):
    id: Slug
    title: str
    venue: Literal['chat', 'reading', 'listening', 'speaking']
    lessons: list[Slug]
    parts: list[Part] | None = None   # the same lessons grouped for the catalog


class Course(Strict):
    version: Literal[3]
    id: Slug
    title: str
    language: LanguageTag
    sections: list[Section]
    titles: dict[Slug, str] | None = None   # lessons of the syllabus that are not written yet


class Point(Strict):
    id: Slug
    label: str
    needs: Literal['all_bullets_done'] | None = None


class Source(Strict):
    id: Slug
    title: str
    url: str
    used: str


class Card(Strict):
    id: Slug
    title: str
    intro: str | None = None
    note: str | None = None
    src: str | None = None


class Fact(Strict):
    k: str
    v: str
    src: str


class Facts(Card):
    type: Literal['facts']
    rows: list[Fact]


class Level(Strict):
    score: int
    name: str
    summary: str
    signs: list[str]


class Explanation(Strict):
    t: str
    d: str


class Rubric(Card):
    type: Literal['rubric']
    levels: list[Level]
    takeaways: list[Explanation]


class Steps(Card):
    type: Literal['steps']
    steps: list[Explanation]


class Part(Strict):
    name: str
    what: str
    en: str


class Skeleton(Card):
    type: Literal['skeleton']
    parts: list[Part]


class Paragraph(Strict):
    p: str


class ListBody(Strict):
    list: list[str]


class BoxBody(Strict):
    box: str


class Comparison(Strict):
    thin: str
    full: str
    why: str


class CompareBody(Strict):
    compare: Comparison


class Text(Card):
    type: Literal['text']
    body: list[Paragraph | ListBody | BoxBody | CompareBody]


class Table(Card):
    type: Literal['table']
    cols: list[str]
    rows: list[list[str]]


class Post(Strict):
    who: str
    text: str


class Task(Strict):
    setting: str
    lead: str
    bullets: list[str]
    to: str | None = None
    subject: str | None = None
    posts: list[Post] | None = None


class Annotation(Strict):
    quote: str
    kind: str
    note: str


class Response(Strict):
    score: int
    text: str
    comment: str
    notes: list[Annotation]

    @model_validator(mode='after')
    def quotes(self):
        if any(note.quote not in self.text for note in self.notes):
            raise ValueError()
        return self


class Model(Card):
    type: Literal['model']
    task: Task
    responses: list[Response]


class Fix(Strict):
    from_: str = Field(alias='from')
    to: str
    rule: str


class Upgrade(Strict):
    from_: str = Field(alias='from')
    to: str
    why: str


class ExampleCoverage(Strict):
    bullet: str
    verdict: str
    quote: str
    note: str


class MarkingExample(Strict):
    about: str
    coverage: list[ExampleCoverage]
    score: int
    reason: str
    fixes: list[Fix]
    upgrade: Upgrade | None
    next: str


class Marking(Card):
    type: Literal['marking']
    format: list[Explanation]
    rules: str
    example: MarkingExample


class Item(Strict):
    q: str
    a: str


class Drill(Card):
    type: Literal['drill']
    prompt: str
    material: str | None = None
    criteria: str | None = None
    points: list[Slug]
    items: list[Item]


class WriteTask(Task):
    id: Slug
    purpose: str
    must: list[str]
    model: str | None = None

    @model_validator(mode='after')
    def requirements(self):
        if len(self.must) != len(self.bullets):
            raise ValueError()
        return self


@lru_cache(maxsize=1)
def generator_specs():
    return json.loads((CONFIG / 'generators.json').read_text('utf-8'))


class More(Strict):
    kind: str
    also: list[str] = []          # other kinds of the same practice; new sets take turns between them
    topics: list[str] = Field(min_length=5)

    @property
    def every(self):
        return [self.kind, *self.also]

    @model_validator(mode='after')
    def specification(self):
        if any(not name.strip() for name in self.every) or any(not topic.strip() for topic in self.topics):
            raise ValueError()
        return self


class Write(Card):
    type: Literal['write']
    minutes: int
    min_words: int | None = None
    points: list[Slug]
    tasks: list[WriteTask] = Field(min_length=1)
    more: More | None = None

GAPS = re.compile(r'\{([A-Za-z]+)\}')


class AudioLine(Strict):
    who: Literal['A', 'B']
    text: str


class Audio(Strict):
    intro: str | None = None
    lines: list[AudioLine]


class Question(Strict):
    stem: str
    options: list[str] = Field(min_length=2, max_length=15)
    answer: int = Field(ge=0, strict=True)
    why: str
    point: Slug

    @model_validator(mode='after')
    def option(self):
        if self.answer >= len(self.options) or len(set(self.options)) != len(self.options):
            raise ValueError()
        return self


class BlankQuestion(Strict):
    stem: str
    accept: list[str] = Field(min_length=1, max_length=6)
    why: str
    point: Slug


class OrderQuestion(Strict):
    stem: str
    lead: str | None = Field(default=None, min_length=1)
    tail: str | None = Field(default=None, min_length=1)
    chunks: list[str] = Field(min_length=3, max_length=9)
    extra: list[str] | None = Field(default=None, min_length=1, max_length=2)
    why: str
    point: Slug

    @model_validator(mode='after')
    def blocks(self):
        if (any(not chunk.strip() for chunk in self.chunks)
                or len(set(self.chunks)) != len(self.chunks)
                or any(value in self.chunks for value in self.extra or [])
                or any(getattr(self, key) is None for key in ('lead', 'tail', 'extra')
                       if key in self.model_fields_set)):
            raise ValueError()
        return self


def accepts(answer, alternatives):
    return isinstance(answer, str) and ' '.join(answer.split()).casefold() in {
        ' '.join(value.split()).casefold() for value in alternatives}


class QuestionGroup(Strict):
    label: str | None = None
    look: Literal['notice', "email", 'messages', 'post', 'passage'] | None = None
    text: str | None = None
    fill: str | None = None
    audio: Audio | None = None
    tags: list[Slug] | None = None
    notes: list[str] | None = None
    items: list[Question | BlankQuestion | OrderQuestion] | None = None

    @model_validator(mode='after')
    def gaps(self):
        count = len(GAPS.findall(self.fill or ''))
        if not count and not self.items:
            raise ValueError()
        if count and self.tags is None:
            raise ValueError()
        if any(values is not None and len(values) != count for values in (self.tags, self.notes)):
            raise ValueError()
        return self


class Check(Card):
    type: Literal['check']
    points: list[Slug]
    groups: list[QuestionGroup] = Field(min_length=1)


class QuestionSet(Strict):
    id: Slug
    groups: list[QuestionGroup] = Field(min_length=1)


class Quiz(Card):
    type: Literal['quiz']
    minutes: int
    pass_: float = Field(alias='pass', ge=0, le=1)
    points: list[Slug]
    sets: list[QuestionSet] = Field(min_length=1)
    more: More | None = None

    @model_validator(mode='after')
    def set_ids(self):
        ids = [item.id for item in self.sets]
        if len(ids) != len(set(ids)):
            raise ValueError()
        return self


LessonCard = Annotated[Facts | Rubric | Steps | Skeleton | Text | Table | Model | Marking | Drill | Check | Write | Quiz,
                       Field(discriminator='type')]


class Lesson(Strict):
    id: Slug
    title: str
    goal: str
    skill: str
    exam: str
    mastery: Literal['once'] | None = None
    points: list[Point]
    sources: list[Source]
    cards: list[LessonCard] = Field(min_length=1)

    @model_validator(mode='after')
    def references(self):
        ids = [card.id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError()
        points = {point.id for point in self.points}
        if any(set(card.points) - points for card in self.cards if card.type in ('drill', 'check', 'write', 'quiz')):
            raise ValueError()
        for card in self.cards:
            groups = (card.groups if card.type == 'check' else
                      [group for item in card.sets for group in item.groups] if card.type == 'quiz' else [])
            for group in groups:
                used = set(group.tags or []) | {item.point for item in group.items or []}
                if used - set(card.points):
                    raise ValueError()
        if (sum(card.type in ('write', 'quiz') for card in self.cards) != 1
                or self.cards[-1].type not in ('write', 'quiz')):
            raise ValueError()
        return self


DIRECTORY = Path(__file__).resolve().parents[2] / 'data' / 'lessons'   # the shipped courses, one folder each
CONFIG = DIRECTORY                    # generators.json, builder.json, exams.json
CUSTOM = DATA_DIR / 'lessons'


def _file(course_id, name):
    return next((path for directory in (DIRECTORY, CUSTOM)
                 if (path := directory / course_id / name).is_file()), None)


@lru_cache(maxsize=128)
def kinds(course_id):
    path = _file(course_id, 'kinds.json')
    return json.loads(path.read_text('utf-8')) if path is not None else {}


@lru_cache(maxsize=1)
def courses():
    result = {}
    for directory in (DIRECTORY, CUSTOM):
        for path in sorted(directory.glob('*/course.json')):
            if path.parent.name in result:
                continue
            try:
                course = Course.model_validate_json(path.read_text('utf-8'))
            except FileNotFoundError:
                continue
            if course.id != path.parent.name or (directory == CUSTOM and not course.id.startswith('my-')):
                raise ValueError()
            result[course.id] = course
    return result


@lru_cache(maxsize=128)
def load(course_id, lesson_id):
    path = _file(course_id, lesson_id + '.json')
    if path is None:
        return None
    lesson = Lesson.model_validate_json(path.read_text('utf-8'))
    if lesson.id != lesson_id:
        raise ValueError()
    for card in lesson.cards:
        if card.type in ('write', 'quiz') and card.more is not None:
            for name in card.more.every:
                definition = kinds(course_id).get(name)
                if (definition is None or definition['format'] not in generator_specs()['formats']
                        or (definition['format'] == 'essay') != (card.type == 'write')):
                    raise ValueError()
    return lesson


def reload():
    from . import content
    for cached in (generator_specs, kinds, courses, load, content.presets):
        cached.cache_clear()


def available(course):
    available = []
    for section in course.sections:
        for ident in section.lessons:
            try:
                lesson = load(course.id, ident)
            except FileNotFoundError:
                continue
            if lesson is not None:
                available.append((section, lesson))
    return available


def holders(course):
    """Lessons that only hold the questions of a practice: never offered as a lesson to take."""
    return {part.practice.lesson for section in course.sections for part in section.parts or []
            if part.practice and part.practice.lesson}


def preset(course):
    return {**course.model_dump(), 'units': [
        {'id': lesson.id, 'title': lesson.title, 'can_do': lesson.goal} for _, lesson in available(course)]}
