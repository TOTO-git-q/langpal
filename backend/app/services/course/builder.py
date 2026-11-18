"""Build custom lesson courses one validated, cached step at a time.

A course is made the way the shipped ones are: sections -> parts (one question type each) -> whole lessons.
Each part has a practice: a holder lesson whose only card is the timed card, with a question kind that draws
unlimited new sets. Every lesson is written by one model call and checked like a hand-written one (lint, blind check).
"""
import asyncio
import copy
import json
import logging
import random
import re
import shutil
import threading
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, ValidationError

from .. import clock
from . import generate, lessons, lint

log = logging.getLogger(__name__)
_guard = threading.RLock()
_workers = set()
SHAPES = {'writing': 'essay', 'reading': 'reading', 'listening': 'listening'}
VENUES = {'writing': 'chat', 'reading': 'reading', 'listening': 'listening'}
PICTURES = lessons.re.compile(r'照片|图片|看图|photo|picture', lessons.re.I)


class Busy(Exception):
    pass


class Stopped(Exception):
    pass


class Shipped(HTTPException):
    """The exam already has a course that ships with the app: nothing is built, the user is told where it is."""
    def __init__(self, title):
        super().__init__(409, _data()['titles']['shipped'].format(title=title))


class BriefFact(lessons.Strict):
    label: str
    value: str
    src: str = 'material'


class Brief(lessons.Strict):
    item: str
    what: str
    facts: list[BriefFact]
    stimulus: str
    questions: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    practice: str
    unverified: list[str]


class PracticePoint(lessons.Strict):
    id: lessons.Slug
    label: str
    lesson: lessons.Slug


class PlannedPractice(lessons.Strict):
    brief: list[str] = Field(min_length=3, max_length=4)
    points: list[PracticePoint] = Field(min_length=2, max_length=3)


class PlannedLesson(lessons.Strict):
    id: lessons.Slug
    title: str
    goal: str
    points: list[lessons.Point] = Field(min_length=2, max_length=3)


class PlannedPart(lessons.Strict):
    id: lessons.Slug
    title: str
    minutes: int = Field(ge=1, le=90)
    min_words: int | None = Field(default=None, ge=1)
    brief: Brief
    practice: PlannedPractice
    lessons: list[PlannedLesson] = Field(min_length=2, max_length=5)


class PlannedSection(lessons.Strict):
    id: Literal['writing', 'reading', 'listening']
    title: str
    parts: list[PlannedPart] = Field(min_length=1)


class Skipped(lessons.Strict):
    item: str
    why: str


class Blueprint(lessons.Strict):
    title: str
    sections: list[PlannedSection] = Field(min_length=1)
    skipped: list[Skipped]


class Kind(lessons.Strict):
    spec: str
    checks: dict
    topics: list[str] = Field(min_length=8, max_length=60)


class Written(lessons.Strict):
    """What the model hands in for one lesson: the cards. Everything else comes from the blueprint."""
    cards: list[Annotated[lessons.Text | lessons.Steps | lessons.Table | lessons.Check | lessons.Quiz,
                          Field(discriminator='type')]] = Field(min_length=1)


def _data():
    return json.loads((lessons.CONFIG / 'builder.json').read_text('utf-8'))


def _read(path):
    return json.loads(path.read_text('utf-8'))


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf-8')
    temporary.replace(path)


def _directory(ident):
    if not ident.startswith('my-') or not lessons.re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', ident):
        raise FileNotFoundError(ident)
    return lessons.CUSTOM / ident


def _state(ident):
    path = _directory(ident) / 'build.json'
    state = _read(path)
    # A run that has not written for longer than any one step can take (three tries of a model call and its checks) died.
    if state['status'] == 'running' and datetime.fromisoformat(state['updated_at']) < clock.now() - timedelta(minutes=20):
        state['status'] = 'stopped'
        _write(path, state)
    return state


def _save(ident, state):
    state['updated_at'] = clock.stamp()
    _write(_directory(ident) / 'build.json', state)


def list_builds():
    with _guard:
        found = []
        for path in sorted(lessons.CUSTOM.glob('my-*/build.json')):
            state = _state(path.parent.name)
            course = path.parent / 'course.json'                # a folder left half-made must not break the list
            found.append({'course_id': path.parent.name, 'title': _read(course)['title'] if course.exists() else state.get('exam', ''), **state})
        return found


def _idle():
    if any(row['status'] == 'running' for row in list_builds()):
        raise Busy()


def _holder(part):
    return part['id'] + '-practice'


def _shipped(exam):
    """The title of the shipped course for this exam, if there is one."""
    normalize = lambda text: ''.join(text.split()).casefold()
    for course_id, entry in _read(lessons.CONFIG / 'exams.json').items():
        path = lessons.CONFIG / course_id / 'course.json'
        title = _read(path)['title'] if path.is_file() else None
        if normalize(exam) in {normalize(name) for name in [*entry['names'], *([title] if title else [])]}:
            return title or course_id
    return None


def _course(ident, plan, state):
    data = _data()
    sections = []
    for section in plan['sections']:
        parts = []
        for part in section['parts']:
            practice = {'lesson': _holder(part), 'title': data['titles']['waiting'].format(minutes=part['minutes']),
                        'brief': part['practice']['brief'],
                        'points': {point['id']: point['lesson'] for point in part['practice']['points']}}
            if section['id'] == 'writing':
                practice['venue'] = 'chat'
            parts.append({'title': part['title'], 'lessons': [row['id'] for row in part['lessons']], 'practice': practice})
        sections.append({'id': section['id'], 'title': section['title'], 'venue': VENUES[section['id']],
                         'lessons': [_holder(part) for part in section['parts']]
                                    + [row['id'] for part in section['parts'] for row in part['lessons']],
                         'parts': parts})
    return {'version': 3, 'id': ident, 'title': plan['title'], 'language': state['language'], 'sections': sections}


def _install(ident, plan, state):
    course = _course(ident, plan, state)
    lessons.Course.model_validate(course)
    _write(_directory(ident) / 'course.json', course)
    _write(_directory(ident) / '_build' / 'plan.json', plan)
    title = _data()['titles']['holder']
    state['lessons'] = [row for section in plan['sections'] for part in section['parts'] for row in
                        [{'id': _holder(part), 'title': title.format(part=part['title']), 'status': 'waiting'}]
                        + [{'id': lesson['id'], 'title': lesson['title'], 'status': 'waiting'} for lesson in part['lessons']]]
    state['skipped'] = plan['skipped']
    _save(ident, state)
    lessons.reload()


def start(language, exam, notes=None, material=None):
    with _guard:
        title = _shipped(exam)
        if title is not None:
            raise Shipped(title)
        _idle()
        ident = 'my-course-' + uuid4().hex
        while _directory(ident).exists() or ident in lessons.courses():
            ident = 'my-course-' + uuid4().hex
        state = {'status': 'running', 'exam': exam, 'language': language,
                 'started_at': clock.stamp(), 'updated_at': clock.stamp(), 'lessons': [], 'skipped': []}
        _save(ident, state)
        _write(_directory(ident) / 'course.json', {'version': 3, 'id': ident, 'title': exam, 'language': language, 'sections': []})
        _write(_directory(ident) / '_build' / 'request.json',
               {'exam': exam, 'language': language, 'notes': notes or '', 'material': (material or '')[:12000]})
        lessons.reload()
        launch(ident)
        return ident


def launch(ident):
    threading.Thread(target=lambda: asyncio.run(run(ident)), daemon=True).start()


def stop(ident):
    with _guard:
        state = _state(ident)
        state['status'] = 'stopped'
        _save(ident, state)


def resume(ident):
    with _guard:
        state = _state(ident)
        _idle()
        for row in state['lessons']:
            if row['status'] != 'done':
                row.update(status='waiting')
                for key in ('error', 'step', 'steps'):
                    row.pop(key, None)
        state['status'] = 'running'
        _save(ident, state)
        launch(ident)


def delete(ident):
    with _guard:
        directory = _directory(ident)
        if not (directory / 'build.json').is_file():
            raise FileNotFoundError(ident)
        stop(ident)
        # Resolve before recursive removal; only a custom course directory is eligible.
        if directory.resolve().parent != lessons.CUSTOM.resolve():
            raise FileNotFoundError(ident)
        shutil.rmtree(directory)
        lessons.reload()


def _running(ident):
    if _state(ident)['status'] != 'running':
        raise Stopped()


async def _ask(ident, prompt, payload, schema, validate):
    specs, feedback = lessons.generator_specs(), ''
    reason = specs['reasons']['fixed']
    for _ in range(3):
        _running(ident)
        try:
            raw = await generate._call(prompt, payload, schema, feedback)
        except Exception:
            feedback = ''
            continue
        try:
            return await validate(raw)
        except generate.Rejected as error:
            reason = str(error)
            log.warning('Build step rejected (%s)', reason)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            reason = specs['reasons']['fixed']
            log.warning('Build step rejected (%s: %s)', type(error).__name__, ' '.join(str(error).split())[:400])
        feedback = '\n' + specs['retry'].format(reason=reason)
    raise generate.Rejected(reason)


def _kind(raw, shape):
    value = Kind.model_validate(raw).model_dump()
    # A model that was asked for twenty topics often hands in nineteen or twenty-two: keep what is usable.
    value['topics'] = list(dict.fromkeys(text.strip() for text in value['topics'] if text.strip()))[:20]
    if len(value['topics']) < 8:
        generate._reject('fixed')
    asked = copy.deepcopy(value['checks'])               # the model's own numbers, before code widens them
    numeric = {'groups', 'text', 'lines', 'items', 'total', 'chunks', 'options', 'bullets', 'must', 'posts', 'post', 'setting', 'paragraphs', 'paragraph', 'keep'}
    booleans = {'alternate', 'shuffle', 'to', 'question', 'bank'}
    for key, part in value['checks'].items():
        if key in numeric:
            bounds = generate._bounds(part)
            if len(bounds) != 2 or any(type(n) is not int or n < 0 for n in bounds) or bounds[0] > bounds[1]:
                generate._reject('fixed')
            if key in ('text', 'paragraph', 'setting', 'post'):     # a length a model sets for itself is narrower than it writes
                value['checks'][key] = [0 if bounds[0] <= 10 else bounds[0] // 2, max(bounds[1] * 3, 60)]   # single sentences: no text
            elif key in ('items', 'total', 'lines', 'groups'):    # the same for how many passages, questions or lines it writes
                value['checks'][key] = [1, max(bounds[1] * 2, bounds[1] + 2)]
        elif key in booleans:
            if type(part) is not bool:
                generate._reject('fixed')
        elif key == 'answer':
            if part not in ('choice', 'blank', 'order'):
                generate._reject('fixed')
        elif key in ('intro', 'stem'):
            if not isinstance(part, str):
                generate._reject('fixed')
        elif key in ('looks', 'lead'):
            if not isinstance(part, list) or not all(isinstance(p, str) for p in part) or (key == 'lead' and len(part) != 2):
                generate._reject('fixed')
        else:
            generate._reject('fixed')
    checks = value['checks']
    if shape == 'reading' and 'keep' not in checks and 'text' in asked and generate._bounds(asked['text'])[1] <= 20 \
            and 'items' in asked:
        # single sentences, each its own question: one that the blind check cannot answer is dropped, not the whole set;
        # the set keeps as many as the model was asked for
        checks['keep'] = max(1, generate._bounds(asked['items'])[0])
    if shape == 'essay':
        low, high = generate._bounds(value['checks']['bullets'])
        if not 2 <= low <= high <= 4:
            generate._reject('fixed')
    return value


def _example(definition, item):
    raw = copy.deepcopy(item)
    raw.pop('id', None)
    if definition['checks'].get('answer') == 'order':
        for group in raw['groups']:
            for question in group['items']:
                for key, empty in (('lead', ''), ('tail', ''), ('extra', [])):
                    question.setdefault(key, empty)
    if generate._banked(definition['checks']):               # back to the way a model hands it in: the options once per group
        for group in raw['groups']:
            group['bank'] = list(group['items'][0]['options'])
            for question in group['items']:
                del question['options']
    if definition['format'] == 'listening':
        for group in raw['groups']:
            audio = group.pop('audio')
            group.update(audio)
    if definition['format'] == 'reading':
        for group in raw['groups']:
            group.setdefault('text', '')
    return raw


class _Steps:
    """The progress row of one build target and its cached steps under _build/<id>/."""
    def __init__(self, ident, state, name, steps):
        self.ident, self.state, self.home = ident, state, _directory(ident) / '_build' / name
        self.row = next(item for item in state['lessons'] if item['id'] == name)
        self.row.update(status='building', step=0, steps=steps)
        _save(ident, state)

    async def __call__(self, step, action):
        _running(self.ident)
        path = self.home / (step + '.json')
        if path.exists():
            result = _read(path)
        else:
            result = await action()
            # A stop preserves the completed step, but prevents any later steps or writes.
            if not _directory(self.ident).exists():
                raise Stopped()
            _write(path, result)
        _running(self.ident)
        self.row['step'] += 1
        _save(self.ident, self.state)
        return result

    def done(self, title):
        _running(self.ident)
        name = self.row['id']
        self.row.clear()
        self.row.update(id=name, title=title, status='done')
        _save(self.ident, self.state)
        lessons.reload()


async def _practice(ident, state, section, part, data):
    """The holder of a part's practice: a question kind and its first two sets (or tasks), on one timed card."""
    name, shape = _holder(part), SHAPES[section['id']]
    exemplar = lessons.kinds('toefl-2026')[data['kinds'][shape]]
    points = [{'id': point['id'], 'label': point['label']} for point in part['practice']['points']]
    brief = {'title': part['title'], 'brief': part['brief'], 'points': points}
    steps = _Steps(ident, state, name, 4 if shape == 'essay' else 3)
    allowed = data['checks'][shape]              # the checks a model may set for this shape; the rest are for hand-written kinds

    async def kind():
        async def validate(raw):
            raw = {**raw, 'checks': {key: value for key, value in raw.get('checks', {}).items() if key in allowed}}
            return _kind(raw, shape)
        return await _ask(ident, data['kind'] + data['fields'][shape] + '\n',
                          {'exam': state['exam'], 'lesson': brief,
                           'example': {'spec': exemplar['spec'],
                                       'checks': {key: value for key, value in exemplar['checks'].items() if key in allowed}}},
                          Kind.model_json_schema(), validate)
    definition = {'format': shape, **await steps('kind', kind)}
    schema = generate._output_schema(definition, lessons.generator_specs())
    example = copy.deepcopy({key: value for key, value in exemplar['example'].items() if key in schema['properties']})

    def reshape(groups):
        """The TOEFL examples are multiple choice: show them the way this kind's questions are handed in."""
        for group in groups:
            if not all('options' in q for q in group.get('items') or []):
                continue
            if definition['checks'].get('answer') == 'blank':
                group['items'] = [{'stem': q['stem'], 'accept': [q['options'][q['answer']]], 'why': q['why'], 'point': q['point']}
                                  for q in group['items']]
            elif generate._banked(definition['checks']):
                bank = list(dict.fromkeys(option for q in group['items'] for option in q['options']))
                group['items'] = [{'stem': q['stem'], 'answer': bank.index(q['options'][q['answer']]), 'why': q['why'], 'point': q['point']}
                                  for q in group['items']]
                group['bank'] = bank
    if shape == 'reading' and definition['checks'].get('keep') and 'text' not in definition['checks']:
        example = copy.deepcopy(data['examples']['items'])      # independent one-sentence questions have their own example
        for number, question in enumerate(example['groups'][0]['items']):
            question['point'] = points[number % len(points)]['id']
    if shape != 'essay':
        reshape(example['groups'])
    tasks = []
    for index, letter in enumerate(('a', 'b')):
        async def task():
            trace, made = [], None
            for _ in range(2):                               # the hand-in-hand items of a lesson are worth a second round
                _running(ident)
                made = await generate.item(state['language'], definition, example, definition['topics'][index],
                                           points, ('task-' if shape == 'essay' else 'set-') + letter, trace=trace)
                if made is not None:
                    break
            if made is None:
                if index == 0:                               # a specification nothing can be made from is written again next time
                    (steps.home / 'kind.json').unlink(missing_ok=True)
                if trace:
                    raise generate.Rejected(trace[-1])
                generate._reject('fixed')
            return made
        made = await steps('task-' + letter, task)
        tasks.append(made)
        if index == 0:
            definition['example'] = _example(definition, made)
            example = definition['example']
    cards = []
    if shape == 'essay':                             # marking reads the levels of the holder's rubric card
        cards.append(await steps('rubric', lambda: _rubric(ident, state, part, tasks[0], data)))
    final = {'id': 'timed', 'type': 'write' if shape == 'essay' else 'quiz',
             'title': '限时写作' if shape == 'essay' else '限时练习',
             'minutes': part['minutes'], 'points': [p['id'] for p in points],
             'more': {'kind': part['id'], 'topics': definition.pop('topics')},
             'tasks' if shape == 'essay' else 'sets': tasks}
    if shape == 'essay':
        if part.get('min_words'):
            final['min_words'] = part['min_words']
    else:
        final['pass'] = data['pass'][section['id']]
    title = data['titles']['holder'].format(part=part['title'])
    result = {'id': name, 'title': title, 'goal': part['brief']['what'], 'skill': section['id'],
              'exam': state['exam'], 'points': points, 'sources': [], 'cards': [*cards, final]}
    lessons.Lesson.model_validate(result)
    _running(ident)
    kinds_path = _directory(ident) / 'kinds.json'
    kinds = _read(kinds_path) if kinds_path.exists() else {}
    kinds[part['id']] = definition
    _write(kinds_path, kinds)
    _write(_directory(ident) / (name + '.json'), result)
    # Now that a real set exists, the catalog can say how big one is.
    course_path = _directory(ident) / 'course.json'
    course = _read(course_path)
    first = tasks[0]
    label = data['titles'][shape].format(minutes=part['minutes'], groups=len(first.get('groups') or []),
                                         items=sum(len(group.get('items') or []) for group in first.get('groups') or []))
    for row in course['sections']:
        for catalog in row.get('parts') or []:
            if (catalog.get('practice') or {}).get('lesson') == name:
                catalog['practice']['title'] = label
    lessons.Course.model_validate(course)
    _write(course_path, course)
    steps.done(title)


async def _rubric(ident, state, part, task, data):
    """The six levels a writing practice is marked by (0-5, as the marking sheet scores), written for this exam."""
    source, name = data['rubric_example']
    example = next(card for card in _read(lessons.CONFIG / source / (name + '.json'))['cards'] if card['type'] == 'rubric')

    async def validate(raw):
        if not isinstance(raw, dict):
            generate._reject('type', key='JSON')
        try:
            card = lessons.Rubric.model_validate({**raw, 'id': 'rubric', 'type': 'rubric', 'title': '评分标准'}).model_dump(
                exclude_unset=True, by_alias=True)
        except ValidationError as error:
            raise _invalid(error) from None
        if [level['score'] for level in card['levels']] != [5, 4, 3, 2, 1, 0]:
            generate._reject('format', key='levels.score')
        return card
    return await _ask(ident, data['rubric'],
                      {'exam': state['exam'], 'part': {'title': part['title'], 'brief': part['brief']},
                       'task': {key: task[key] for key in ('setting', 'lead', 'bullets')}, 'example': example},
                      lessons.Rubric.model_json_schema(by_alias=True), validate)


def _example_lesson(data, language, skill):
    table = data['lessons']
    found = (table.get(language.split('-')[0]) or {}).get(skill) or table['en'][skill]
    return _read(lessons.CONFIG / found[0] / (found[1] + '.json'))


def _answer_type(question):
    return 'blank' if 'accept' in question else 'order' if 'chunks' in question else 'choice'


async def _blind(card, specs):
    """The blind check of generate, per kind of answer: a model that sees only the material must find the same answers."""
    groups = [group for group in card['groups'] if group.get('items')]
    for answer_type in ('choice', 'blank', 'order'):
        picked = [{**{key: value for key, value in group.items() if key not in ('items', 'fill')},
                   'items': [question for question in group['items'] if _answer_type(question) == answer_type]}
                  for group in groups]
        picked = [group for group in picked if group['items']]
        if picked:
            await generate._blind({'groups': picked}, specs, answer_type)


ORDINALS = '一二三四五六七八'
QUESTION_KEYS = {'stem', 'options', 'answer', 'accept', 'lead', 'chunks', 'tail', 'extra', 'why', 'point'}


def _spread(card, seed):
    """Models put the right answer first far too often. Move answers round the positions by swapping two options,
    and swap the 「第一项」 words of the explanation with them; shared option lists (one list per group) stay as they are."""
    groups = [group for one in card.get('sets') or [card] for group in one.get('groups') or []]
    questions = [question for group in groups
                 if len({json.dumps(q.get('options')) for q in group.get('items') or []}) > 1 or len(group.get('items') or []) == 1
                 for question in group.get('items') or []
                 if isinstance(question.get('options'), list) and type(question.get('answer')) is int
                 and 0 <= question['answer'] < len(question['options']) <= len(ORDINALS)]
    rng = random.Random(seed)
    targets = []
    for question in questions:
        if not targets:
            targets = list(range(len(question['options'])))
            rng.shuffle(targets)
        target = targets.pop() % len(question['options'])
        answer = question['answer']
        if target == answer:
            continue
        options = question['options']
        options[answer], options[target] = options[target], options[answer]
        question['answer'] = target
        names = {f'第{ORDINALS[answer]}项': f'第{ORDINALS[target]}项', f'第{ORDINALS[target]}项': f'第{ORDINALS[answer]}项'}
        if isinstance(question.get('why'), str):
            question['why'] = re.sub('|'.join(names), lambda match: names[match[0]], question['why'])


def _invalid(error):
    """A short reason a model can act on, from a pydantic error."""
    where = ['.'.join(str(part) for part in item['loc']) for item in error.errors()[:3]]
    return generate.Rejected(lessons.generator_specs()['reasons']['fixed'] + '：' + '；'.join(where))


async def _lesson(ident, state, section, part, row, data):
    """One whole lesson, written in one go and checked like a hand-written one."""
    name = row['id']
    kinds_path = _directory(ident) / 'kinds.json'
    definition = (_read(kinds_path) if kinds_path.exists() else {}).get(part['id'])
    steps = _Steps(ident, state, name, 1)
    points = [lessons.Point.model_validate(point).model_dump(exclude_none=True) for point in row['points']]
    base = {'id': name, 'title': row['title'], 'goal': row['goal'], 'skill': section['id'], 'exam': state['exam'],
            'mastery': 'once', 'points': points, 'sources': []}
    course = _read(_directory(ident) / 'course.json')
    specs = lessons.generator_specs()

    async def write():
        async def validate(raw):
            raw = copy.deepcopy(raw)
            cards = raw.get('cards') if isinstance(raw, dict) else None
            if not isinstance(cards, list) or not cards or not all(isinstance(card, dict) for card in cards):
                generate._reject('missing', key='cards')
            for number, card in enumerate(cards):            # what code can settle by itself is not worth a retry
                if card.get('type') in ('check', 'quiz'):
                    card.pop('intro', None)                  # the page shows the amount and the time itself
                    for group in [g for one in card.get('sets') or [card] for g in one.get('groups') or []]:
                        for question in group.get('items') or []:
                            if isinstance(question, dict):  # a field of its own (options_note, hint) is dropped, not retried
                                for key in set(question) - QUESTION_KEYS:
                                    del question[key]
                    _spread(card, f'{name}:{number}')
            if cards[-1].get('type') == 'quiz':
                cards[-1].update(id='timed', title='小测', points=[point['id'] for point in points],
                                 **{'pass': data['pass'][section['id']]})
                cards[-1].setdefault('minutes', 6)
                cards[-1].pop('more', None)
            try:
                lesson = {**base, **Written.model_validate(raw).model_dump(exclude_unset=True, by_alias=True)}
                lessons.Lesson.model_validate(lesson)
            except ValidationError as error:
                raise _invalid(error) from None
            # The Japanese course's check that a `why` is not written in Japanese applies to any Japanese course.
            errors, _ = lint.check(lesson, course, name, 'n1' if state['language'].split('-')[0] == 'ja' else ident,
                                   choices=(3, 4))       # some exams give three options (TOEIC question-response)
            if errors:
                raise generate.Rejected('；'.join(errors[:6]))
            for card in lesson['cards']:
                if card['type'] == 'check':
                    await _blind(card, specs)
            return lesson
        payload = {'exam': state['exam'], 'language': state['language'],
                   'part': {'title': part['title'], 'skill': section['id'], 'brief': part['brief']},
                   'lesson': {key: row[key] for key in ('id', 'title', 'goal', 'points')},
                   'others': [{'title': other['title'], 'goal': other['goal']} for other in part['lessons'] if other['id'] != name],
                   'practice': None if definition is None else {'spec': definition['spec'], 'example': definition.get('example')},
                   'example': {'cards': _example_lesson(data, state['language'], section['id'])['cards']}}
        return await _ask(ident, data['lesson'], payload, Written.model_json_schema(by_alias=True), validate)
    lesson = await steps('lesson', write)
    _running(ident)
    _write(_directory(ident) / (name + '.json'), lesson)
    steps.done(row['title'])


def _tidy(raw):
    """What code can settle in a blueprint is not worth a retry: a part that needs a photo goes to skipped
    (a page of text cannot show it), skipped written inside a section moves up, a practice brief keeps four lines."""
    if not isinstance(raw, dict) or not isinstance(raw.get('sections'), list):
        return raw
    skipped = raw['skipped'] if isinstance(raw.get('skipped'), list) else []
    for section in raw['sections']:
        if not isinstance(section, dict):
            continue
        extra = section.pop('skipped', None)
        skipped += extra if isinstance(extra, list) else [extra] if isinstance(extra, dict) else []
        kept = []
        for part in section.get('parts') if isinstance(section.get('parts'), list) else []:
            if isinstance(part, dict):
                brief = part.get('brief') if isinstance(part.get('brief'), dict) else {}
                if PICTURES.search(' '.join(str(text) for text in (part.get('title'), brief.get('item')))):   # the name, not the material
                    skipped.append({'item': str(part.get('title') or brief.get('item') or ''), 'why': '要看照片或图片才能答，这里放不了图。'})
                    continue
                practice = part.get('practice')
                if isinstance(practice, dict) and isinstance(practice.get('brief'), list):
                    practice['brief'] = practice['brief'][:4]
            kept.append(part)
        section['parts'] = kept
    raw['sections'] = [s for s in raw['sections'] if not isinstance(s, dict) or s.get('parts')]
    seen = set()      # the same item named in a section and again at the top is listed once
    raw['skipped'] = [entry for entry in skipped if not isinstance(entry, dict) or not (
        str(entry.get('item', '')).strip() in seen or seen.add(str(entry.get('item', '')).strip()))]
    return raw


def _plan(raw):
    """Checks a blueprint beyond its shape: ids, counts, titles, and where the practice points are taught."""
    raw = _tidy(raw)
    Blueprint.model_validate(raw)
    rows = [lesson for section in raw['sections'] for part in section['parts'] for lesson in part['lessons']]
    ids = [lesson['id'] for lesson in rows] + [_holder(part) for section in raw['sections'] for part in section['parts']]
    if len(rows) > 30:
        generate._reject('count', key='lessons', got=len(rows), low=1, high=30)
    if len(set(ids)) != len(ids):
        generate._reject('format', key='lessons.id')
    for section in raw['sections']:
        for part in section['parts']:
            taught = {lesson['id'] for lesson in part['lessons']}
            practice = [point['id'] for point in part['practice']['points']]
            if len(set(practice)) != len(practice) or any(point['lesson'] not in taught for point in part['practice']['points']):
                generate._reject('format', key='practice.points')
            for lesson in part['lessons']:
                if not lesson['id'].startswith(section['id'] + '-') or lint.QUESTION_TITLE.search(lesson['title']):
                    generate._reject('format', key='lessons.id / lessons.title')
            for fact in part['brief']['facts']:
                fact['src'] = 'material'
            if section['id'] != 'writing':
                part.pop('min_words', None)
    return raw


async def run(ident):
    key = str(_directory(ident).resolve())
    with _guard:
        if key in _workers or _state(ident)['status'] != 'running':
            return
        _workers.add(key)
    try:
        state, data = _state(ident), _data()
        plan_path = _directory(ident) / '_build' / 'plan.json'
        if not plan_path.exists():
            async def validate(raw):
                return _plan(raw)
            plan = await _ask(ident, data['blueprint'], _read(_directory(ident) / '_build' / 'request.json'),
                              Blueprint.model_json_schema(), validate)
            _running(ident)
            _install(ident, plan, state)
        plan = _read(plan_path)
        for section in plan['sections']:
            for part in section['parts']:
                targets = [(_holder(part), lambda: _practice(ident, state, section, part, data))]
                targets += [(row['id'], lambda row=row: _lesson(ident, state, section, part, row, data)) for row in part['lessons']]
                for name, build in targets:
                    _running(ident)
                    progress = next(r for r in state['lessons'] if r['id'] == name)
                    if progress['status'] not in ('waiting', 'building'):
                        continue
                    try:
                        await build()
                    except Stopped:
                        raise
                    except Exception as error:
                        title = progress.get('title', name)
                        progress.clear()
                        progress.update(id=name, title=title, status='failed', error=str(error))
                        _running(ident)
                        _save(ident, state)
        _running(ident)
        state['status'] = 'done'
        _save(ident, state)
    except (Stopped, FileNotFoundError):
        pass
    except Exception:
        if _directory(ident).exists():
            stop(ident)
    finally:
        with _guard:
            _workers.discard(key)
