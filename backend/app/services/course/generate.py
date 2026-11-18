"""Generate, validate and store spare lesson practice items."""
import asyncio
import copy
import json
import logging
import re
import threading
import unicodedata
from contextlib import closing

from ...db import get_conn
from .. import clock
from . import lessons, planner

log = logging.getLogger(__name__)
_guard = threading.Lock()
_locks = {}
_pending = set()
_WORDS = re.compile(r"[A-Za-z0-9]+(?:[-'’][A-Za-z0-9]+)*")
_LETTERS = 'ABCDEFGHIJKLMNO'
_OPTION = re.compile(r'(?<![A-Za-z0-9])[A-O](?![A-Za-z0-9])(?!\s*[A-Za-z])')


def ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS course_generated (
        id INTEGER PRIMARY KEY,
        language TEXT NOT NULL, course_id TEXT NOT NULL, lesson_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        topic TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
        UNIQUE (language, course_id, lesson_id, item_id))""")


def _lock(language, lesson_id):
    with _guard:
        return _locks.setdefault((language, lesson_id), threading.Lock())


def items(conn, language, course_id, lesson_id, card):
    """Return authored items first, followed by generated items in creation order."""
    ensure(conn)
    model = lessons.WriteTask if card.type == 'write' else lessons.QuestionSet
    authored = card.tasks if card.type == 'write' else card.sets
    rows = conn.execute('''SELECT payload_json FROM course_generated
        WHERE language=? AND course_id=? AND lesson_id=? ORDER BY id''',
                        (language, course_id, lesson_id))
    return [*authored, *(model.model_validate_json(row['payload_json']) for row in rows)]


def used(conn, language, course_id, lesson_id):
    from . import lesson
    lesson.ensure(conn)
    result = {}
    for row in conn.execute('''SELECT id, ended_at, log_json FROM course_lessons
            WHERE language=? AND course_id=? AND lesson_id=? AND outcome='finished'
            ORDER BY ended_at,id''', (language, course_id, lesson_id)):
        saved = json.loads(row['log_json'])
        ident = saved.get('task') or saved.get('set')
        if ident is not None:
            result[ident] = (row['ended_at'], row['id'])
    return result


def unused(conn, language, course_id, lesson_id, card):
    history = used(conn, language, course_id, lesson_id)
    return [item for item in items(conn, language, course_id, lesson_id, card) if item.id not in history]


def gaps(paragraph):
    """Apply the official alternating half-word cut, or reject an unsafe cut."""
    paragraph = ' '.join(paragraph.split())
    first = re.search(r'[.!?]["\u201d\u2019\)]*\s+', paragraph)
    if first is None:
        raise ValueError()
    functions = set(lessons.generator_specs()['function_words'].split())
    cuts, tags = [], []
    cut_next = False
    for match in _WORDS.finditer(paragraph, first.end()):
        word = match[0]
        if not re.search('[A-Za-z]', word):
            continue
        if not cut_next:
            cut_next = True
            continue
        if len(word) == 1:
            continue
        sentence_start = re.search(r'[.!?]["\u201d\u2019\)]*\s*$', paragraph[:match.start()]) is not None
        if not word.isascii() or not word.isalpha() or (word[0].isupper() and not sentence_start):
            raise ValueError()
        half = len(word) // 2
        cuts.append((match.start(), match.end(), word[:half] + '{' + word[half:] + '}'))
        tags.append('function' if word.casefold() in functions else 'content')
        cut_next = False
        if len(cuts) == 10:
            break
    if len(cuts) != 10:
        raise ValueError()
    for start, end, replacement in reversed(cuts):
        paragraph = paragraph[:start] + replacement + paragraph[end:]
    return paragraph, tags


class Rejected(ValueError):
    pass


def _reject(reason, **values):
    raise Rejected(lessons.generator_specs()['reasons'][reason].format(**values))


def _bounds(value):
    return (value, value) if type(value) is int else tuple(value)


def _measure(text, language):
    """Characters for text written mostly in CJK (whatever the course language: a translation task quotes Chinese), else words."""
    letters = [char for char in text if not char.isspace() and not unicodedata.category(char).startswith('P')]
    cjk = sum('぀' <= char <= 'ヿ' or '㐀' <= char <= '鿿' or '가' <= char <= '힯' for char in letters)
    if letters and cjk * 2 > len(letters):
        return len(letters)
    return len(text.split())


def _range(key, got, expected, reason='count'):
    low, high = _bounds(expected)
    if not low <= got <= high:
        _reject(reason, key=key, got=got, low=low, high=high)


def _schema(value, item):
    if isinstance(value, dict):
        if value.get('$ref') == '#/$defs/item':
            return copy.deepcopy(item)
        return {key: _schema(part, item) for key, part in value.items()}
    if isinstance(value, list):
        return [_schema(part, item) for part in value]
    return value


def _banked(checks):
    """One list of options for all the questions of a group (word bank, paragraph letters): given once, copied by code."""
    return bool(checks.get('bank')) and checks.get('answer', 'choice') == 'choice'


def _unbank(raw):
    for group in raw['groups']:
        bank = group.pop('bank')
        for question in group['items']:
            question['options'] = list(bank)


def _output_schema(definition, specs):
    banked = _banked(definition['checks'])
    schema = _schema(specs['formats'][definition['format']]['schema'],
                     specs['item']['bank' if banked else definition['checks'].get('answer', 'choice')])
    if banked:
        group = schema['properties']['groups']['items']
        group['properties']['bank'] = {'type': 'array', 'items': {'type': 'string'}}
        group['required'] = [*group['required'], 'bank']
    if definition['format'] == 'essay':
        checks = definition['checks']
        for key in ('to', 'subject', 'posts'):
            enabled = checks.get('to') if key in ('to', 'subject') else 'posts' in checks
            if enabled:
                if key not in schema['required']:
                    schema['required'].append(key)
            else:
                schema['properties'].pop(key, None)
        for key in definition.get('fixed', {}):
            schema['properties'].pop(key, None)
            if key in schema['required']:
                schema['required'].remove(key)
    return schema


def _shape(value, schema, key='JSON'):
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'array': isinstance(value, list),
             'string': isinstance(value, str), 'integer': type(value) is int}
    if kind in valid and not valid[kind]:
        _reject('type', key=key)
    if kind == 'object':
        for name in schema.get('required', []):
            if name not in value:
                _reject('missing', key=name)
        for name in list(value):
            if name not in schema.get('properties', {}):    # a field of its own (type, note) is dropped, not worth a retry
                del value[name]
        for name, part in schema.get('properties', {}).items():
            if name in value:
                _shape(value[name], part, name)
    elif kind == 'array':
        for part in value:
            _shape(part, schema['items'], key)


async def _call(prompt, payload, schema, feedback=''):
    from ...providers.registry import get_utility_provider
    text = prompt + json.dumps(payload, ensure_ascii=False) + '\n' + json.dumps(schema, ensure_ascii=False) + feedback
    return await asyncio.wait_for(get_utility_provider().generate_json(text, schema), timeout=150)


def _material(group):
    if group.get('audio') is not None:
        lines = group['audio']['lines']
        if len({line['who'] for line in lines}) == 1:
            return '\n'.join(line['text'] for line in lines)
        return '\n'.join(line['who'] + ': ' + line['text'] for line in lines)
    return group.get('text') or group.get('fill') or ''


SPEAKER_LABEL = re.compile(r"^\s*(?:[A-Z][A-Za-z.'-]*(?: [A-Z][A-Za-z.'-]*){0,2}|[\u3040-\u30ff\u4e00-\u9fff]{1,8})\s*[:：]\s")


def _checks(raw, definition, language, points):
    checks = definition['checks']
    fixed = definition.get('fixed', {})
    groups = raw.get('groups', [])
    questions = [item for group in groups for item in group['items']]
    if 'groups' in checks:
        _range('groups', len(groups), checks['groups'])
    if 'text' in checks:
        for group in groups:
            text = group['text'] if definition['format'] == 'reading' else ' '.join(
                line['text'] for line in group['lines'])
            _range('text', _measure(text, language), checks['text'], 'length')
    if definition['format'] == 'listening':
        for group in groups:
            if any(SPEAKER_LABEL.match(line['text']) for line in group['lines']):
                _reject('label')
    if 'lines' in checks:
        for group in groups:
            _range('lines', len(group['lines']), checks['lines'])
    if checks.get('alternate'):
        for group in groups:
            if any(line['who'] != ('A' if index % 2 == 0 else 'B') for index, line in enumerate(group['lines'])):
                _reject('format', key='alternate')
    if 'items' in checks:
        for group in groups:
            _range('items', len(group['items']), checks['items'])
    if 'total' in checks:
        _range('total', len(questions), checks['total'])
    if checks.get('answer', 'choice') == 'choice':
        expected = checks.get('options', 4)
        low, high = _bounds(expected)
        for item in questions:
            options = item['options']
            if not (2 <= len(options) <= 15 and low <= len(options) <= high and len(set(options)) == len(options)):
                _reject('options', n=expected if type(expected) is int else f'{low}–{high}')
            if not 0 <= item['answer'] < len(options):
                _reject('format', key='answer')
    elif checks.get('answer') == 'order':
        if 'chunks' in checks:
            for item in questions:
                _range('chunks', len(item['chunks']), checks['chunks'])
    else:
        for item in questions:
            if not 1 <= len(item['accept']) <= 6:
                _reject('format', key='accept')
    if 'looks' in checks and any(group['look'] not in checks['looks'] for group in groups):
        _reject('format', key='looks')
    if 'intro' in checks and any(not group['intro'].startswith(checks['intro']) for group in groups):
        _reject('format', key='intro')
    if 'stem' in checks and any(item['stem'] != checks['stem'] for item in questions):
        _reject('format', key='stem')
    for key in ('bullets', 'must'):
        if key in checks and not (key == 'bullets' and key in fixed):
            _range(key, len(raw[key]), checks[key])
    if checks.get('to') and ('@' not in raw['to'] or not raw['subject']):
        _reject('format', key='to')
    if 'posts' in checks:
        _range('posts', len(raw['posts']), checks['posts'])
    if 'post' in checks:
        for post in raw['posts']:
            _range('post', _measure(post['text'], language), checks['post'], 'length')
    if checks.get('question') and (not raw.get('posts') or not raw['posts'][0]['text'].rstrip().endswith(('?', '？'))):
        _reject('format', key='question')
    if 'setting' in checks:
        _range('setting', _measure(raw['setting'], language), checks['setting'], 'length')
    if 'lead' in checks:
        start, end = checks['lead']
        if not raw['lead'].startswith(start) or not raw['lead'].endswith(end):
            _reject('format', key='lead')
    if 'paragraphs' in checks:
        _range('paragraphs', len(raw['paragraphs']), checks['paragraphs'])
    if 'paragraph' in checks:
        for paragraph in raw['paragraphs']:
            _range('paragraph', _measure(paragraph, language), checks['paragraph'], 'length')
    if any(item['point'] not in points for item in questions):
        _reject('point')


def _assemble(definition, raw, card):
    if definition['checks'].get('answer') == 'order':
        raw = copy.deepcopy(raw)
        for group in raw['groups']:
            for item in group['items']:
                for key in ('lead', 'tail', 'extra'):
                    if not item.get(key):
                        item.pop(key, None)
    shape = definition['format']
    if shape == 'essay':
        return {**copy.deepcopy(raw), **copy.deepcopy(definition.get('fixed', {}))}
    if shape == 'ctw':
        groups = []
        sources = card.sets[0].groups
        for index, paragraph in enumerate(raw['paragraphs']):
            try:
                fill, tags = gaps(paragraph)
            except ValueError:
                _reject('cut', n=index + 1)
            group = {'fill': fill, 'tags': tags}
            source = sources[min(index, len(sources) - 1)]
            if source.label is not None:
                group['label'] = source.label
            groups.append(group)
        return {'groups': groups}
    if shape == 'listening':
        return {'groups': [{'audio': {key: group[key] for key in ('intro', 'lines')},
                            'items': group['items']} for group in raw['groups']]}
    groups = copy.deepcopy(raw['groups'])
    for group in groups:
        if group.get('text') == '':
            del group['text']
    return {'groups': groups}


def _validate(authored, item):
    data = authored.model_dump(exclude_unset=True, by_alias=True)
    card = data['cards'][-1]
    card['tasks' if card['type'] == 'write' else 'sets'] = [item]
    try:
        validated = lessons.Lesson.model_validate(data).cards[-1]
    except ValueError:
        _reject('fixed')
    return (validated.tasks if validated.type == 'write' else validated.sets)[0]


def _shuffle(item, checks):
    if checks.get('answer', 'choice') != 'choice' or not checks.get('shuffle', True) or _banked(checks):
        return
    for group in item.get('groups', []):
        for question in group.get('items') or []:
            options, answer = question['options'], question['answer']
            order = list(range(len(options)))
            clock.rng.shuffle(order)
            question['options'] = [options[index] for index in order]
            question['answer'] = order.index(answer)
            letters = {letter: _LETTERS[order.index(index)] for index, letter in enumerate(_LETTERS[:len(options)])}
            question['why'] = _OPTION.sub(lambda match: letters.get(match[0], match[0]), question['why'])


def _alphabetize(item):
    """A word bank the model wrote in part-of-speech blocks (easier for it to count) is shown A-Z, like the exam."""
    for group in item.get('groups', []):
        questions = group.get('items') or []
        if not questions:
            continue
        bank = questions[0]['options']
        order = sorted(range(len(bank)), key=lambda index: bank[index].casefold())
        for question in questions:
            question['answer'] = order.index(question['answer'])
            question['options'] = [bank[index] for index in order]


async def _blind(item, specs, answer_type, keep=None):
    groups = item.get('groups', [])
    questions = [question for group in groups for question in group.get('items') or []]
    if questions:
        keys = ('stem',) if answer_type in ('blank', 'order') else ('stem', 'options')
        payload = [{'material': _material(group),
                    'questions': [{key: question[key] for key in keys}
                                  for question in group.get('items') or []]} for group in groups]
        if answer_type == 'order':
            for question, sent in zip(questions, [q for group in payload for q in group['questions']]):
                pool = question['chunks'] + question.get('extra', [])
                clock.rng.shuffle(pool)
                sent.update(lead=question.get('lead', ''), tail=question.get('tail', ''), pool=pool)
        answer_schema = ({'type': 'array', 'items': {'type': 'string'}} if answer_type == 'order' else
                         {'type': 'string' if answer_type == 'blank' else 'integer'})
        schema = {'type': 'object', 'required': ['answers'],
                  'properties': {'answers': {'type': 'array', 'items': answer_schema}}}
        blind_key = 'blind' if answer_type == 'choice' else 'blind_' + answer_type
        result = await _call(specs[blind_key], payload, schema)
        answers = result['answers']
        if not isinstance(answers, list):
            _reject('blind', n=1)
        failed = []
        for index, question in enumerate(questions):
            answer = answers[index] if index < len(answers) else None
            if answer_type == 'order':
                correct = isinstance(answer, list) and answer == question['chunks']
            else:
                correct = (lessons.accepts(answer, question['accept']) if answer_type == 'blank' else
                           type(answer) is int and answer == question['answer'])
            if not correct:
                failed.append(index)
        if failed and (keep is None or len(questions) - len(failed) < keep):
            _reject('blind', n=failed[0] + 1)
        if len(answers) != len(questions) and keep is None:
            _reject('blind', n=len(questions) + 1)
        if keep is not None:                 # independent questions: drop the ones that did not survive, keep the first `keep`
            dropped, left = {id(questions[index]) for index in failed}, keep
            for group in groups:
                group['items'] = [question for question in group['items'] if id(question) not in dropped][:left]
                left -= len(group['items'])
    for index, group in enumerate(groups):
        if not group.get('fill'):
            continue
        fill = group['fill']
        schema = {'type': 'object', 'required': ['words'],
                  'properties': {'words': {'type': 'array', 'items': {'type': 'string'}}}}
        paragraph = lessons.GAPS.sub(lambda match: '_' * len(match[1]), fill)
        from ...providers.registry import get_utility_provider
        prompt = specs['fill'] + paragraph + '\n' + json.dumps(schema, ensure_ascii=False)
        result = await asyncio.wait_for(get_utility_provider().generate_json(prompt, schema), timeout=150)
        words = result['words']
        expected = [match[1] + match[2] for match in re.finditer(r'([A-Za-z]+)\{([A-Za-z]+)\}', fill)]
        if not isinstance(words, list) or len(words) != len(expected) or len(words) != 10:
            _reject('ambiguous', n=index + 1)
        if any(not isinstance(word, str) or (word.casefold() != answer.casefold() and len(word) == len(answer))
               for word, answer in zip(words, expected)):
            _reject('ambiguous', n=index + 1)


async def item(language, specification, example, topic, points, ident, *, avoid=None, authored=None, card=None, trace=None):
    """Make one checked item from an explicit specification, without database access.
    `trace`, when given, collects why each attempt was rejected (the builder reports the last one)."""
    specs = lessons.generator_specs()
    def validate(item):
        if authored is not None:
            return _validate(authored, item).model_dump(exclude_unset=True, by_alias=True)
        model = lessons.WriteTask if specification['format'] == 'essay' else lessons.QuestionSet
        try:
            return model.model_validate(item).model_dump(exclude_unset=True, by_alias=True)
        except ValueError:
            _reject('fixed')
    schema = _output_schema(specification, specs)
    checks = specification['checks']
    answer_type = checks.get('answer', 'choice')
    payload = {'points': points, 'example': example, 'topic': topic, 'avoid': avoid or []}
    prompt = specs['head'] + specification['spec']
    if specification['format'] in ('reading', 'listening'):
        prompt += specs['items_bank' if _banked(checks) else 'items' if answer_type == 'choice' else 'items_' + answer_type]
    feedback = ''
    for attempt in range(3):
        try:
            raw = await _call(prompt + '\n', payload, schema, feedback)
            _shape(raw, schema)
            if _banked(checks):
                _unbank(raw)
            _checks({**raw, **specification.get('fixed', {})}, specification, language, [point['id'] for point in points])
            item = {**_assemble(specification, raw, card), 'id': ident}
            item = validate(item)
            _shuffle(item, checks)
            await _blind(item, specs, answer_type, checks.get('keep'))
            if checks.get('alphabetical') and _banked(checks):
                _alphabetize(item)
            validate(item)
            return item
        except Rejected as error:
            feedback = '\n' + specs['retry'].format(reason=str(error))
            log.warning('Lesson generation attempt %s rejected (%s)', attempt + 1, error)
            if trace is not None:
                trace.append(str(error))
        except Exception as error:
            feedback = ''
            log.warning('Lesson generation attempt %s failed (%s: %s)', attempt + 1, type(error).__name__, str(error)[:200])
    return None


async def make(language, lesson_id):
    lock = _lock(language, lesson_id)
    if not lock.acquire(blocking=False):
        return None
    try:
        with closing(get_conn()) as conn:
            course, active = planner.selected(conn, language)
            if not active:
                return None
            authored = next((item for _, item in lessons.available(course) if item.id == lesson_id), None)
            if authored is None or authored.cards[-1].more is None:
                return None
            card = authored.cards[-1]
            choices = items(conn, language, course.id, lesson_id, card)
            rows = conn.execute('''SELECT item_id,topic FROM course_generated
                WHERE language=? AND course_id=? AND lesson_id=? ORDER BY id''',
                                (language, course.id, lesson_id)).fetchall()
            topics = card.more.topics
            seen = {row['topic'] for row in rows}
            topic = next((value for value in topics if value not in seen), topics[len(rows) % len(topics)])
            avoid = [item.purpose if card.type == 'write' else
                     _material(item.groups[0].model_dump(exclude_none=True))[:60] for item in choices][-12:]
            number = max((int(row['item_id'][1:]) for row in rows), default=0) + 1
            ident = 'g' + str(number)
        # Model calls can take a minute; hold no database handles while waiting.
        names = card.more.every
        specification = lessons.kinds(course.id).get(names[(number - 1) % len(names)])
        if specification is None:
            return None
        used = {question.get('point') for group in specification['example'].get('groups', [])
                for question in group.get('items') or []} - {None}
        made = await item(language, specification, specification['example'], topic,
                          [{'id': point.id, 'label': point.label} for point in authored.points
                           if point.id in card.points and (not used or point.id in used)],
                          ident, avoid=avoid, authored=authored, card=card)
        if made is None:
            return None
        with closing(get_conn()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            if course.id not in lessons.courses():
                return None
            ensure(conn)
            conn.execute('INSERT INTO course_generated (language,course_id,lesson_id,item_id,topic,payload_json,created_at) VALUES (?,?,?,?,?,?,?)',
                         (language, course.id, lesson_id, ident, topic,
                          json.dumps(made, ensure_ascii=False), clock.stamp()))
        from . import lesson
        recordings = lesson.recordings(made.get('groups', []))
        if recordings:
            lesson.warm(language, recordings)
        return made
    finally:
        lock.release()


async def spare(language, lesson_id):
    """For "one more": true once an unused item exists. Waits for a generation already in flight instead of failing."""
    lock = _lock(language, lesson_id)
    while lock.locked():
        await asyncio.sleep(0.2)
    return not _needs_refill(language, lesson_id) or await make(language, lesson_id) is not None


def _needs_refill(language, lesson_id):
    with closing(get_conn()) as conn:
        course, active = planner.selected(conn, language)
        if not active:
            return False
        authored = next((item for _, item in lessons.available(course) if item.id == lesson_id), None)
        return (authored is not None and authored.cards[-1].more is not None
                and not unused(conn, language, course.id, lesson_id, authored.cards[-1]))


async def refill(language, lesson_id):
    try:
        if _needs_refill(language, lesson_id):
            await make(language, lesson_id)
    except Exception as error:
        log.warning('Lesson refill failed (%s)', type(error).__name__)


def top_up(language, lesson_id):
    try:
        if not _needs_refill(language, lesson_id):
            return
    except Exception as error:
        log.warning('Lesson top-up check failed (%s)', type(error).__name__)
        return
    key = (language, lesson_id)
    lock = _lock(*key)
    with _guard:
        if key in _pending or lock.locked():
            return
        _pending.add(key)

    def run():
        try:
            asyncio.run(refill(language, lesson_id))
        except Exception as error:
            log.warning('Lesson top-up failed (%s)', type(error).__name__)
        finally:
            with _guard:
                _pending.discard(key)

    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception as error:
        with _guard:
            _pending.discard(key)
        log.warning('Lesson top-up could not start (%s)', type(error).__name__)
