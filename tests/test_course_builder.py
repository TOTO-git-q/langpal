"""The course concierge builds a course for another exam in the shape of the shipped ones: sections, parts (one question type
each, with an unlimited practice) and whole lessons, each lesson written in one go and checked like a hand-written one.

The fake model "copies the homework": a lesson comes back as the shipped lesson it was shown as the example, with the
points renamed; the practice questions come back as the TOEFL example of the same shape.
"""
import asyncio
import copy
import json
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

try:
    from .test_course_lessons import ESSAY, Base, SHIPPED, authored, sheet
    from .test_course_generate import KINDS, SPECS
except ImportError:
    from test_course_lessons import ESSAY, Base, SHIPPED, authored, sheet
    from test_course_generate import KINDS, SPECS
from app import db
from app.services import course
from app.services.course import lessons, lint

DATA = SHIPPED
BUILDER = json.loads((DATA / 'builder.json').read_text('utf-8'))
EXAMS = json.loads((DATA / 'exams.json').read_text('utf-8'))
NAMES = ['writing-email', 'writing-discussion', 'reading-complete-words', 'reading-daily-life', 'reading-academic',
         'listening-response', 'listening-conversation', 'listening-announcement', 'listening-talk']
RIGHT = {}
for _name in NAMES:
    for _card in authored(_name)['cards']:
        for _group in _card.get('groups', []) + [g for s in _card.get('sets', []) for g in s['groups']]:
            for _item in _group.get('items') or []:
                RIGHT[frozenset(_item['options'])] = _item['options'][_item['answer']]


def brief(what, **more):
    return {'item': what, 'what': what + '，做后面的题', 'facts': [{'label': '题量', 'value': '1', 'src': 'official'}],
            'stimulus': '一段材料', 'questions': ['细节'], 'practice': '一套 = 一段材料', 'unverified': [], **more}


def practice(name, *teaching):
    """The points of the TOEFL lesson whose example the practice questions copy, so copied questions stay valid."""
    found = [{'id': p['id'], 'label': p['label']} for p in authored(name)['points']][:3]
    return {'brief': ['先读题目要求。', '再找材料里的依据。', '最后核对选项。'],
            'points': [{**point, 'lesson': teaching[n % len(teaching)]} for n, point in enumerate(found)]}


def lesson(ident, title):
    return {'id': ident, 'title': title, 'goal': '学完能' + title,
            'points': [{'id': 'first', 'label': '找出依据'}, {'id': 'second', 'label': '排除干扰项'}]}


PLAN = {'title': '演示考试分项课', 'skipped': [{'item': '口语', 'why': '要对着人说'}], 'sections': [
    {'id': 'writing', 'title': '写作', 'parts': [
        {'id': 'writing-note', 'title': '便条', 'minutes': 20, 'min_words': 80,
         'brief': brief('便条', criteria=['内容', '语言'], unverified=['满分 15 分']),
         'practice': practice('writing-email', 'writing-note-method', 'writing-note-support'),
         'lessons': [lesson('writing-note-method', '便条的结构'), lesson('writing-note-support', '理由与例子')]}]},
    {'id': 'reading', 'title': '阅读', 'parts': [
        {'id': 'reading-short', 'title': '短文阅读', 'minutes': 8, 'brief': brief('短文'),
         'practice': practice('reading-academic', 'reading-short-method', 'reading-short-main'),
         'lessons': [lesson('reading-short-method', '短文阅读的解题步骤'), lesson('reading-short-main', '主旨题')]}]},
    {'id': 'listening', 'title': '听力', 'parts': [
        {'id': 'listening-talks', 'title': '长对话', 'minutes': 6, 'brief': brief('对话'),
         'practice': practice('listening-conversation', 'listening-talks-method', 'listening-talks-main'),
         'lessons': [lesson('listening-talks-method', '长对话的结构'), lesson('listening-talks-main', '对话目的题')]}]}]}
SHAPES = {'writing': 'essay', 'reading': 'reading', 'listening': 'listening'}
PARTS = {part['id']: (section['id'], part) for section in PLAN['sections'] for part in section['parts']}
LESSONS = [row['id'] for section in PLAN['sections'] for part in section['parts'] for row in part['lessons']]
ROWS = [name for section in PLAN['sections'] for part in section['parts'] for name in [part['id'] + '-practice'] + [r['id'] for r in part['lessons']]]


def shaped(kind):
    """The TOEFL example of a kind, cut down to the fields a new kind of the same shape returns (no `to`, `subject`)."""
    example = copy.deepcopy(KINDS[kind]['example'])
    return {k: v for k, v in example.items() if k not in ('to', 'subject')}


def sent(prompt, prefix):
    return json.loads(prompt[len(prefix):].split('\n', 1)[0])


class Teacher:
    """Fake utility model. `spoil` maps a lesson id to how many times its lesson breaks a rule of the lint."""
    def __init__(self, plan=None, spoil=None):
        self.plan, self.spoil, self.prompts, self.right = plan, dict(spoil or {}), [], dict(RIGHT)

    def of(self, prefix):
        return [p for p in self.prompts if p.startswith(prefix)]

    def lessons(self, ident):
        return [p for p in self.of(BUILDER['lesson']) if sent(p, BUILDER['lesson'])['lesson']['id'] == ident]

    async def generate_json(self, prompt, schema):
        self.prompts.append(prompt)
        if prompt.startswith(BUILDER['blueprint']):
            return copy.deepcopy(self.plan)
        if prompt.startswith(BUILDER['kind']):
            given = json.loads(prompt.split('\n')[-2])
            checks = {**given['example']['checks'], 'lead': ['a', 'b']}        # a key the model may not set: it is dropped
            return {'spec': 'SPEC ' + given['lesson']['title'], 'checks': checks, 'topics': ['话题' + str(n) for n in range(20)]}
        if prompt.startswith(SPECS['blind_blank']):
            return {'answers': [self.right[q['stem']] for part in sent(prompt, SPECS['blind_blank']) for q in part['questions']]}
        if prompt.startswith(SPECS['blind_order']):
            return {'answers': [self.right[q['stem']] for part in sent(prompt, SPECS['blind_order']) for q in part['questions']]}
        if prompt.startswith(SPECS['blind']):
            return {'answers': [q['options'].index(self.right[frozenset(q['options'])])
                                for part in sent(prompt, SPECS['blind']) for q in part['questions']]}
        if prompt.startswith(SPECS['head']):
            title = prompt[len(SPECS['head']) + len('SPEC '):].split('\n', 1)[0]
            skill = next(skill for skill, part in PARTS.values() if title.startswith(part['title']))
            return shaped(BUILDER['kinds'][SHAPES[skill]])
        if prompt.startswith(BUILDER['rubric']):
            card = sent(prompt, BUILDER['rubric'])['example']
            return {key: value for key, value in card.items() if key not in ('id', 'title')}   # code names the card itself
        assert prompt.startswith(BUILDER['lesson']), prompt[:80]
        given = sent(prompt, BUILDER['lesson'])
        cards = copy.deepcopy(given['example']['cards'])
        rename = dict(zip(cards[-1]['points'], [p['id'] for p in given['lesson']['points']]))
        for card in cards:
            if 'points' in card:
                card['points'] = [rename[p] for p in card['points']]
            for group in card.get('groups', []) + [g for s in card.get('sets', []) for g in s['groups']]:
                for item in group.get('items') or []:
                    item['point'] = rename[item['point']]
                    if 'options' in item:
                        self.right[frozenset(item['options'])] = item['options'][item['answer']]
                    else:
                        self.right[item['stem']] = item['accept'][0] if 'accept' in item else item['chunks']
        cards[-1].update(id='last', title='测验', more={'kind': 'x', 'topics': ['a'] * 5})    # code settles these itself
        if self.spoil.get(given['lesson']['id'], 0) > 0:
            self.spoil[given['lesson']['id']] -= 1
            text = next(card for card in cards if card['type'] == 'text')
            text['body'].append({'p': '你记住这一条。'})
        return {'cards': cards}


class Building(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp.name) / 'lessons'
        self.launched = []
        for target, name, value in ((lessons, 'CUSTOM', self.home), (course.builder, 'launch', self.launched.append)):
            guard = patch.object(target, name, value)
            guard.start()
            self.addCleanup(guard.stop)
        self.addCleanup(lessons.reload)
        lessons.reload()

    def use(self, model):
        guard = patch('app.providers.registry.get_utility_provider', return_value=model)
        guard.start()
        self.addCleanup(guard.stop)
        return model

    def state(self, ident):
        return json.loads((self.home / ident / 'build.json').read_text('utf-8'))

    def lesson(self, ident, name):
        return json.loads((self.home / ident / (name + '.json')).read_text('utf-8'))

    def build(self, model, exam='演示考试', **more):
        self.use(model)
        ident = course.builder.start('en', exam, **more)
        asyncio.run(course.builder.run(ident))
        return ident


class Whole(Building):
    def test_an_unknown_exam_is_planned_by_the_model_and_built_like_the_shipped_courses(self):
        model = self.use(Teacher(PLAN))
        ident = course.builder.start('en', '演示考试', notes='只要读写听', material='官方说明：……')
        self.assertRegex(ident, r'^my-course-[0-9a-f]{32}$')
        self.assertEqual(self.launched, [ident])
        self.assertEqual({k: self.state(ident)[k] for k in ('status', 'exam', 'language', 'lessons')},
                         {'status': 'running', 'exam': '演示考试', 'language': 'en', 'lessons': []})
        asyncio.run(course.builder.run(ident))
        plan = model.of(BUILDER['blueprint'])
        self.assertEqual(len(plan), 1)
        self.assertEqual(sent(plan[0], BUILDER['blueprint']),
                         {'exam': '演示考试', 'language': 'en', 'notes': '只要读写听', 'material': '官方说明：……'})
        state = self.state(ident)
        self.assertEqual((state['status'], state['skipped']), ('done', PLAN['skipped']))
        self.assertEqual([(row['id'], row['status']) for row in state['lessons']], [(name, 'done') for name in ROWS])
        self.assertEqual(state['lessons'][0]['title'], '便条 · 练习')

        made = lessons.courses()[ident]                                        # course.json validates and loads
        self.assertEqual((made.version, made.title, made.language), (3, PLAN['title'], 'en'))
        self.assertEqual([(s.id, s.venue) for s in made.sections], [('writing', 'chat'), ('reading', 'reading'), ('listening', 'listening')])
        for section in made.sections:
            (part,) = section.parts
            ident_part = part.practice.lesson[:-len('-practice')]
            planned = PARTS[ident_part][1]
            self.assertEqual(section.lessons, [planned['id'] + '-practice'] + [r['id'] for r in planned['lessons']])
            self.assertEqual((part.title, part.lessons), (planned['title'], [r['id'] for r in planned['lessons']]))
            self.assertEqual((part.practice.brief, part.practice.points),
                             (planned['practice']['brief'], {p['id']: p['lesson'] for p in planned['practice']['points']}))
            self.assertEqual(part.practice.venue, 'chat' if section.id == 'writing' else None)
        self.assertEqual([p.practice.title for s in made.sections for p in s.parts],
                         ['1 篇 · 20 分钟', '1 篇 5 题 · 8 分钟', '3 段 6 题 · 6 分钟'])  # the size of the first set
        self.assertEqual(lessons.holders(made), {part + '-practice' for part in PARTS})

        kinds = json.loads((self.home / ident / 'kinds.json').read_text('utf-8'))
        self.assertEqual({name: kinds[name]['format'] for name in kinds}, {name: SHAPES[skill] for name, (skill, _) in PARTS.items()})
        for name, (skill, part) in PARTS.items():
            holder = self.lesson(ident, name + '-practice')
            self.assertIsNotNone(lessons.load(ident, name + '-practice'))
            essay = skill == 'writing'
            *before, final = holder['cards']                                   # the holder shows only its timed card
            self.assertEqual([(c['id'], c['type'], c['title']) for c in before], [('rubric', 'rubric', '评分标准')] if essay else [])
            if essay:                                                          # the levels marking reads, written for this exam
                example = next(c for c in json.loads((DATA / 'cet6' / 'writing-essay.json').read_text('utf-8'))['cards'] if c['type'] == 'rubric')
                self.assertEqual(before[0]['levels'], example['levels'])
            self.assertEqual((final['id'], final['type'], final['title']),
                             ('timed', 'write' if essay else 'quiz', '限时写作' if essay else '限时练习'))
            self.assertEqual(final['more'], {'kind': name, 'topics': ['话题' + str(n) for n in range(20)]})
            self.assertEqual([i['id'] for i in final.get('tasks') or final['sets']], ['task-a', 'task-b'] if essay else ['set-a', 'set-b'])
            self.assertEqual((final['minutes'], final['points']), (part['minutes'], [p['id'] for p in part['practice']['points']]))
            self.assertEqual(final.get('min_words') if essay else final['pass'], 80 if essay else BUILDER['pass'][skill])
            self.assertEqual((holder['skill'], holder['exam'], holder['goal']), (skill, '演示考试', part['brief']['what']))
            self.assertEqual((kinds[name]['spec'], len(kinds[name]['example']) > 0), ('SPEC ' + part['title'], True))
            self.assertTrue(set(kinds[name]['checks']) <= set(BUILDER['checks'][SHAPES[skill]]))

        for name in LESSONS:
            built = self.lesson(ident, name)
            self.assertIsNotNone(lessons.load(ident, name))
            self.assertEqual(lint.check(built, json.loads((self.home / ident / 'course.json').read_text('utf-8')), name, ident)[0], [])
            final = built['cards'][-1]
            self.assertEqual((final['id'], final['title'], [s['id'] for s in final['sets']], 'more' in final), ('timed', '小测', ['set-a'], False))
            self.assertEqual((built['mastery'], built['skill'], built['exam'], built['sources']), ('once', name.split('-')[0], '演示考试', []))

        blind = sum(len(model.of(SPECS[key])) for key in ('blind', 'blind_blank', 'blind_order'))
        self.assertTrue(model.of(SPECS['blind_order']) and model.of(SPECS['blind_blank']))   # every kind of answer in a check card is checked blind
        writing = sum(skill == 'writing' for skill, _ in PARTS.values())
        self.assertEqual(len(model.prompts) - blind, 1 + 3 * len(PARTS) + writing + len(LESSONS))   # the plan; a kind and two sets a part, a rubric a writing part; one call a lesson
        self.assertEqual(len(model.of(BUILDER['rubric'])), writing)

    def test_the_prompts_are_built_from_the_data_files(self):
        model = Teacher(PLAN)
        ident = self.build(model)
        kind = next(p for p in model.of(BUILDER['kind']) if '短文阅读' in p)
        self.assertTrue(kind.startswith(BUILDER['kind'] + BUILDER['fields']['reading'] + '\n'))
        part = copy.deepcopy(PARTS['reading-short'][1])
        part['brief']['facts'][0]['src'] = 'material'                          # facts a model wrote come from the material
        example = KINDS[BUILDER['kinds']['reading']]
        self.assertEqual(json.loads(kind.split('\n')[-2]),
                         {'exam': '演示考试',
                          'lesson': {'title': part['title'], 'brief': part['brief'],
                                     'points': [{'id': p['id'], 'label': p['label']} for p in part['practice']['points']]},
                          'example': {'spec': example['spec'],
                                      'checks': {k: v for k, v in example['checks'].items() if k in BUILDER['checks']['reading']}}})
        first = [p for p in model.of(SPECS['head']) if p.startswith(SPECS['head'] + 'SPEC 短文阅读')]
        payloads = [json.loads(p[len(SPECS['head'] + 'SPEC 短文阅读' + SPECS['items']) + 1:].split('\n', 1)[0]) for p in first]
        self.assertEqual([p['topic'] for p in payloads], ['话题0', '话题1'])
        self.assertEqual(payloads[0]['example'], example['example'])                     # the first one copies the TOEFL example
        kinds = json.loads((self.home / ident / 'kinds.json').read_text('utf-8'))
        self.assertEqual(payloads[1]['example'], kinds['reading-short']['example'])

        (prompt,) = model.lessons('reading-short-main')
        given = sent(prompt, BUILDER['lesson'])
        self.assertEqual(given['part'], {'title': part['title'], 'skill': 'reading', 'brief': part['brief']})
        self.assertEqual(given['lesson'], part['lessons'][1])
        self.assertEqual(given['others'], [{'title': '短文阅读的解题步骤', 'goal': '学完能短文阅读的解题步骤'}])
        self.assertEqual(given['practice'], {'spec': kinds['reading-short']['spec'], 'example': kinds['reading-short']['example']})
        shipped = json.loads((DATA / 'cet4' / 'reading-careful-main.json').read_text('utf-8'))
        self.assertEqual(given['example'], {'cards': shipped['cards']})
        self.assertEqual(json.loads(prompt[len(BUILDER['lesson']):].split('\n')[1]), course.builder.Written.model_json_schema(by_alias=True))

    def test_the_course_that_was_built_can_be_taken(self):
        ident = self.build(Teacher(PLAN))
        with closing(db.get_conn()) as conn, conn:
            course.save_language_settings(conn, 'en', course.Teaching(mode='ambient', preset=ident))
        progress = self.client.get('/api/teaching/settings/en').json()['progress']
        self.assertEqual(progress['next']['unit_id'], 'writing-note-method')               # a holder is never the next lesson
        taken = self.post('start', {'language': 'en', 'lesson_id': 'reading-short-practice', 'practice': True}, 201)['lesson']
        self.assertEqual((taken['set']['id'], len(taken['set']['groups'][0]['items'])), ('set-a', 5))
        self.assertEqual(taken['practice']['brief'], PARTS['reading-short'][1]['practice']['brief'])
        self.post('stop', status=200)
        taken = self.post('start', {'language': 'en', 'lesson_id': 'listening-talks-main'}, 201)['lesson']
        self.assertEqual((taken['venue'], taken['practice']), ('page', None))
        self.post('stop', status=200)
        taken = self.post('start', {'language': 'en', 'lesson_id': 'writing-note-practice', 'practice': True}, 201)['lesson']
        self.assertEqual(([c['type'] for c in taken['cards']], taken['venue']), (['write'], 'chat'))   # the rubric stays hidden
        marker = self.model(sheet(next=''))
        done = self.post('submit', {'text': ESSAY, 'seconds': 300})['lesson']
        self.assertEqual(done['sheet']['score'], 4)
        (prompt,) = marker.prompts                                             # the marking call got this exam's rubric
        given = json.loads(prompt.split('\n')[-2])
        holder = self.lesson(ident, 'writing-note-practice')
        self.assertEqual(given['rubric'], holder['cards'][0]['levels'])
        self.assertTrue(given['rubric'])


class Known(Building):
    def test_an_exam_that_ships_with_the_app_is_not_built(self):
        model = self.use(Teacher(PLAN))
        with self.assertRaises(course.builder.Shipped) as caught:
            course.builder.start('en', ' cet-6 ')
        self.assertEqual(caught.exception.detail, '这门课已经有了：《大学英语六级（CET-6）》，在「学习 › 课程」里选它就行')
        refused = self.client.post('/api/teaching/build', json={'language': 'ja', 'exam': 'JLPT N1'})
        self.assertEqual((refused.status_code, refused.json()['detail']),
                         (409, '这门课已经有了：《日语能力考 JLPT N1》，在「学习 › 课程」里选它就行'))
        self.assertEqual((model.prompts, self.launched, list(self.home.glob('*'))), ([], [], []))
        for ident, entry in EXAMS.items():                                     # every name points at a course that ships
            title = json.loads((DATA / ident / 'course.json').read_text('utf-8'))['title']
            for name in [*entry['names'], title]:
                with self.subTest(name=name), self.assertRaises(course.builder.Shipped) as caught:
                    course.builder.start('en', name)
                self.assertIn('《' + title + '》', caught.exception.detail)

    def test_the_routes_start_list_stop_resume_and_delete(self):
        self.use(Teacher(PLAN))
        made = self.client.post('/api/teaching/build', json={'language': 'en', 'exam': '演示考试'})
        self.assertEqual(made.status_code, 202)
        ident = made.json()['course_id']
        route = '/api/teaching/build/' + ident
        again = self.client.post('/api/teaching/build', json={'language': 'en', 'exam': '另一门考试'})
        self.assertEqual((again.status_code, again.json()['detail']), (409, '有一门课正在做'))
        builds = self.client.get('/api/teaching/build').json()['builds']
        self.assertEqual([(b['course_id'], b['title'], b['status']) for b in builds], [(ident, '演示考试', 'running')])
        self.assertEqual(self.client.post(route + '/stop').status_code, 200)
        self.assertEqual(self.state(ident)['status'], 'stopped')
        other = course.builder.start('en', '另一门考试')
        self.assertNotEqual(ident, other)
        course.builder.stop(other)
        self.assertEqual(self.client.post(route + '/resume').status_code, 202)
        self.assertEqual((self.state(ident)['status'], self.launched), ('running', [ident, other, ident]))
        asyncio.run(course.builder.run(ident))
        self.assertEqual(self.state(ident)['status'], 'done')
        with closing(db.get_conn()) as conn, conn:
            course.save_language_settings(conn, 'en', course.Teaching(mode='ambient', preset=ident))
        self.assertEqual(self.client.delete(route).status_code, 200)
        self.assertFalse((self.home / ident).exists())
        self.assertNotIn(ident, lessons.courses())
        self.assertIsNone(self.client.get('/api/teaching/settings/en').json()['progress']['next'])
        self.assertEqual(self.client.delete('/api/teaching/build/toefl-2026').status_code, 404)   # only courses the user had made
        (self.home / 'my-broken').mkdir()
        (self.home / 'my-broken' / 'build.json').write_text('{"status": "stopped", "exam": "x", "language": "en", "updated_at": "2026-11-16 10:00:00", "lessons": []}', 'utf-8')
        self.assertIn('my-broken', [b['course_id'] for b in self.client.get('/api/teaching/build').json()['builds']])   # a half-made folder breaks nothing


class Trouble(Building):
    def one(self):
        return {**PLAN, 'sections': PLAN['sections'][1:2]}

    def test_a_lesson_that_breaks_a_rule_is_written_again_with_what_the_lint_found(self):
        model = Teacher(self.one(), spoil={'reading-short-main': 1})
        ident = self.build(model)
        self.assertEqual([row['status'] for row in self.state(ident)['lessons']], ['done'] * 3)
        tries = model.lessons('reading-short-main')
        self.assertEqual(len(tries), 2)
        self.assertNotIn(SPECS['retry'][:10], tries[0])
        self.assertIn('banned wording', tries[1].rsplit('\n', 1)[-1])
        self.assertNotIn('你记住', json.dumps(self.lesson(ident, 'reading-short-main'), ensure_ascii=False))

    def test_a_lesson_that_never_passes_fails_alone_and_resuming_redoes_only_it(self):
        model = Teacher(self.one(), spoil={'reading-short-method': 3})
        ident = self.build(model)
        state = self.state(ident)
        self.assertEqual((state['status'], [(row['id'], row['status']) for row in state['lessons']]),
                         ('done', [('reading-short-practice', 'done'), ('reading-short-method', 'failed'), ('reading-short-main', 'done')]))
        self.assertIn('banned wording', state['lessons'][1]['error'])
        self.assertEqual(len(model.lessons('reading-short-method')), 3)
        self.assertFalse((self.home / ident / 'reading-short-method.json').exists())
        self.assertNotIn('reading-short-method', [u['id'] for u in lessons.preset(lessons.courses()[ident])['units']])
        before = len(model.prompts)
        asyncio.run(course.builder.run(ident))                                 # nothing was asked to be redone
        self.assertEqual(len(model.prompts), before)
        self.assertEqual(self.client.post('/api/teaching/build/' + ident + '/resume').status_code, 202)
        asyncio.run(course.builder.run(ident))
        self.assertEqual([row['status'] for row in self.state(ident)['lessons']], ['done'] * 3)
        redone = [p for p in model.prompts[before:] if not p.startswith((SPECS['blind'], SPECS['blind_blank'], SPECS['blind_order']))]
        self.assertEqual([sent(p, BUILDER['lesson'])['lesson']['id'] for p in redone], ['reading-short-method'])   # the plan and the practice are kept

    def test_a_blueprint_that_breaks_the_rules_is_asked_for_again(self):
        broken = copy.deepcopy(self.one())
        broken['sections'][0]['parts'][0]['practice']['points'][0]['lesson'] = 'reading-elsewhere'   # taught by no lesson of the part
        model = Teacher(broken)
        ident = self.build(model)
        self.assertEqual(len(model.of(BUILDER['blueprint'])), 3)
        self.assertEqual((self.state(ident)['status'], self.state(ident)['lessons']), ('stopped', []))

    def test_code_settles_a_photo_part_a_misplaced_skipped_and_a_long_brief(self):
        plan = copy.deepcopy(self.one())
        photo = copy.deepcopy(plan['sections'][0]['parts'][0])
        photo['title'] = '照片描述'
        plan['sections'][0]['parts'].append(photo)
        plan['sections'][0]['skipped'] = [{'item': '口语', 'why': '不考。'}]
        plan['skipped'] = [*plan.get('skipped', []), {'item': '口语', 'why': '这门考试不考口语。'}]   # named twice
        plan['sections'][0]['parts'][0]['practice']['brief'] = ['一。', '二。', '三。', '四。', '五。']
        tidy = course.builder._tidy(plan)
        self.assertEqual([p['title'] for p in tidy['sections'][0]['parts']], [self.one()['sections'][0]['parts'][0]['title']])
        self.assertEqual(len(tidy['sections'][0]['parts'][0]['practice']['brief']), 4)
        self.assertNotIn('skipped', tidy['sections'][0])
        items = [s['item'] for s in tidy['skipped']]
        self.assertEqual(items.count('口语'), 1)
        self.assertEqual(items[-1], '照片描述')


class Concierge(Building):
    def test_the_concierge_offers_a_build_and_never_applies_it_itself(self):
        import app.services.workspace_agent as agent
        async def answer(prompt, context, tools, **more):
            self.assertIn('course.build', tools)
            return {'reply': '我来做一门六级课。', 'test_source_id': None,
                    'operations': [{'tool': 'course.build', 'args': {'language': 'en', 'exam': '六级', 'notes': '先做阅读'}}]}
        with patch.object(agent, 'get_conn', db.get_conn), patch.object(agent.workspace_agent_runtime, 'generate', answer):
            result = asyncio.run(agent.plan('帮我做一门六级的课', {}))
            self.assertEqual((result['proposal'], result['build']), (None, {'language': 'en', 'exam': '六级', 'notes': '先做阅读', 'material': ''}))
            with self.assertRaises(agent.AgentError):
                agent.preview_operations([agent.Operation(tool='course.build', args={'language': 'en', 'exam': '六级'})], {})
        self.assertEqual(self.launched, [])


if __name__ == '__main__':
    unittest.main()
