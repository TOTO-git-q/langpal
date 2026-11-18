"""Learning side (docs/LEARNING.md): FSRS, unified queue, contexts, records, advice, today, dictation.

Temporary SQLite, fixed clock, fake model. No network, no real audio.
"""
import json
import math
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.routers import learning as learning_routes, listening, notebook, reading, reading_sources as reading_sources_routes, review as review_routes, teaching as teaching_routes
from app.services import clock, listening_errors, listening_sessions, reading_errors, reading_sources as reading_sources_service, review as review_service, course
from app.services.learning import cards, fsrs, insights, store, words
from app.services.listening_formats import Exercise, FORMATS

START = datetime(2026, 11, 12, 9, 0, 0)


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


class FSRSNumbers(unittest.TestCase):
    def test_first_rating_and_interval(self):
        out = fsrs.review({"state": "new"}, 3, START)
        self.assertAlmostEqual(out.stability, fsrs.W[2])
        self.assertAlmostEqual(out.difficulty, fsrs.W[4])
        self.assertEqual(out.interval_days, round(fsrs.W[2]))  # r = 0.9 makes I == S
        self.assertEqual(fsrs.review({"state": "new"}, 4, START).difficulty, fsrs.clamp_difficulty(fsrs.W[4] - fsrs.W[5]))
        again = fsrs.review({"state": "new"}, 1, START)
        self.assertTrue(again.again_in_session)
        self.assertEqual(again.due_at, START + timedelta(minutes=10))

    def test_recall_matches_formula(self):
        s, d = fsrs.W[2], fsrs.W[4]
        t = 3
        r = (1 + 19 / 81 * t / s) ** -0.5
        expected = s * (1 + math.exp(fsrs.W[8]) * (11 - d) * s ** -fsrs.W[9] * (math.exp(fsrs.W[10] * (1 - r)) - 1))
        out = fsrs.review({"state": "review", "stability": s, "difficulty": d, "last_review_at": START},
                          3, START + timedelta(days=t))
        self.assertAlmostEqual(out.retrievability, r)
        self.assertAlmostEqual(out.stability, expected)
        self.assertEqual(out.interval_days, round(expected))
        hard = fsrs.review({"state": "review", "stability": s, "difficulty": d, "last_review_at": START}, 2,
                           START + timedelta(days=t))
        easy = fsrs.review({"state": "review", "stability": s, "difficulty": d, "last_review_at": START}, 4,
                           START + timedelta(days=t))
        self.assertLess(hard.stability, out.stability)
        self.assertGreater(easy.stability, out.stability)
        self.assertAlmostEqual(out.difficulty, fsrs.clamp_difficulty(fsrs.W[7] * fsrs.W[4] + (1 - fsrs.W[7]) * d))

    def test_sequence_and_forgetting_never_raises_stability(self):
        card = {"state": "new"}
        now = START
        for rating in (3, 3, 4, 3):
            out = fsrs.review(card, rating, now)
            card = {"state": out.state, "stability": out.stability, "difficulty": out.difficulty, "last_review_at": now}
            now = out.due_at
        self.assertGreater(card["stability"], 20)
        forgot = fsrs.review(card, 1, now)
        self.assertLessEqual(forgot.stability, card["stability"])
        self.assertEqual(forgot.state, "relearning")
        # Same day: right again keeps the (lowered) stability.
        step = {"state": "relearning", "stability": forgot.stability, "difficulty": forgot.difficulty,
                "last_review_at": now}
        back = fsrs.review(step, 3, now + timedelta(minutes=10))
        self.assertEqual(back.stability, forgot.stability)
        self.assertEqual(back.state, "review")

    def test_higher_retention_means_shorter_interval(self):
        self.assertEqual(fsrs.interval(20, 0.90), 20)
        self.assertLess(fsrs.interval(20, 0.95), fsrs.interval(20, 0.90))
        self.assertGreater(fsrs.interval(20, 0.80), fsrs.interval(20, 0.90))
        self.assertEqual(fsrs.interval(10_000), 365)
        self.assertEqual(fsrs.interval(0.01), 1)

    def test_weak_evidence_grows_less(self):
        card = {"state": "review", "stability": 5.0, "difficulty": 5.0, "last_review_at": START}
        full = fsrs.review(card, 3, START + timedelta(days=5))
        weak = fsrs.review(card, 3, START + timedelta(days=5), weight=0.7)
        self.assertAlmostEqual(weak.stability - 5.0, (full.stability - 5.0) * 0.7)


class Base(unittest.TestCase):
    modules = (review_routes, notebook, learning_routes, reading, listening, teaching_routes, review_service,
               listening_sessions, listening_errors, reading_errors, course, reading_sources_service)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / 'learning.sqlite'

        def connect():
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=ON')
            return conn
        self.connect = connect
        with closing(connect()) as conn:
            conn.executescript((ROOT / 'backend/db/schema.sql').read_text('utf-8'))
            store.migrate(conn)
            conn.commit()
        for module in self.modules:
            if hasattr(module, 'get_conn'):
                patcher = patch.object(module, 'get_conn', connect)
                patcher.start()
                self.addCleanup(patcher.stop)
        self.clock = Clock(START)
        patcher = patch.object(clock, 'now', self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        hooks = patch('app.services.hooks.emit_soon')
        self.emitted = hooks.start()
        self.addCleanup(hooks.stop)
        app = FastAPI()
        for module in (review_routes, notebook, learning_routes, reading, listening, teaching_routes, reading_sources_routes):
            app.include_router(module.router, prefix='/api')
        self.client = TestClient(app)
        listening._prepared.clear()

    def tearDown(self):
        self.client.close()
        listening._prepared.clear()
        self.tmp.cleanup()

    def later(self, **delta):
        self.clock.at += timedelta(**delta)

    def save(self, lemma, sentence, language='en', meaning='意思', **extra):
        response = self.client.post('/api/vocab', json={'language': language, 'lemma': lemma, 'meaning': meaning,
                                                         'context_sentence': sentence, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rid(self):
        return uuid.uuid4().hex

    def queue(self, language='en', **params):
        response = self.client.get('/api/review/queue', params={'language': language, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def grade(self, card_id, **body):
        body.setdefault('request_id', self.rid())
        response = self.client.post(f'/api/review/cards/{card_id}/grade', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class Migration(Base):
    def test_old_rows_become_cards_once(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO vocab_entries (id, language, lemma, meaning, context_sentence, due_at, interval_days, reps)"
                         " VALUES (1, 'en', 'resilient', '有韧性的', 'She is resilient.', '2026-11-20 00:00:00', 8, 3)")
            conn.execute("INSERT INTO vocab_entries (id, language, lemma, context_sentence) VALUES (2, 'en', 'fresh', 'A fresh start.')")
            conn.execute("INSERT INTO pattern_entries (id, language, pattern_name, example_sentence) VALUES (1, 'ja', '〜ばかり', '食べたばかりです。')")
            conn.execute("INSERT INTO reading_exercises VALUES ('r2-x', 'en', 'T', '', ?)",
                         (json.dumps({'items': [{'question': 'Q', 'options': ['a', 'b', 'c', 'd'], 'answer': 1}]}),))
            conn.execute("INSERT INTO reading_errors (exercise_id, item_index, selected) VALUES ('r2-x', 0, 2)")
            conn.execute("INSERT INTO review_states (kind,item_id,item_index,attempt_count,stage,due_at,last_attempt_at)"
                         " VALUES ('reading','r2-x',0,2,2,'2026-11-15T00:00:00Z','2026-11-12T00:00:00Z')")
            conn.execute("INSERT INTO review_attempts VALUES ('a-1','reading','r2-x',0,'{}',?, '2026-11-12T00:00:00Z')",
                         (json.dumps({'outcome': 'correct'}),))
            for _ in range(3):
                store.migrate(conn)
            rows = {(r['kind'], r['ref_id']): dict(r) for r in conn.execute('SELECT * FROM review_cards')}
            self.assertEqual(set(rows), {('vocab', '1'), ('vocab', '2'), ('pattern', '1'), ('reading_q', 'r2-x:0'),
                                         ('vocab_produce', '1')})
            self.assertEqual((rows[('vocab', '1')]['state'], rows[('vocab', '1')]['stability']), ('review', 8.0))
            self.assertEqual(rows[('vocab', '2')]['state'], 'new')
            self.assertEqual((rows[('reading_q', 'r2-x:0')]['state'], rows[('reading_q', 'r2-x:0')]['stability']), ('review', 3.0))
            self.assertEqual(conn.execute('SELECT count(*) FROM review_log').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM vocab_contexts').fetchone()[0], 2)
            self.assertEqual(conn.execute('SELECT count(*) FROM review_states').fetchone()[0], 1)  # old table kept
            conn.execute("DELETE FROM vocab_entries WHERE id = 2")
            store.sync(conn)
            self.assertIsNone(conn.execute("SELECT 1 FROM review_cards WHERE ref_id = '2'").fetchone())


class Queue(Base):
    def test_mixed_new_cards_daily_cap_and_same_day_return(self):
        for i in range(15):
            self.save(f'word{i}', f'The word{i} is here.')
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO pattern_entries (language, pattern_name, example_sentence) VALUES ('en', 'as long as', 'Stay as long as you like.')")
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('review_new_per_day', '5')")
        data = self.queue()
        self.assertEqual(len(data['cards']), 5)
        self.assertEqual(data['cards'][1]['kind'], 'pattern')  # mixed, not all words first
        first = data['cards'][0]
        self.assertEqual(first['sentence'], f'The {cards.BLANK} is here.')
        self.assertNotIn('lemma', first)
        self.assertEqual(self.grade(first['id'], rating=1)['again_in_session'], True)
        for card in data['cards'][1:]:
            self.grade(card['id'], rating=3)
        data = self.queue()
        self.assertEqual(data['cards'], [])  # the cap is used up today
        self.assertEqual([item['id'] for item in data['later']], [first['id']])
        self.later(minutes=11)
        self.assertEqual([c['id'] for c in self.queue()['cards']], [first['id']])
        result = self.grade(first['id'], rating=3)
        self.assertFalse(result['again_in_session'])
        self.assertIsNotNone(result['session'])  # queue emptied: session closed
        self.assertEqual(result['session']['count'], 6)
        self.assertEqual(result['session']['forgot'], 1)
        self.emitted.assert_any_call('study.review_session_done', None, {'count': 6, 'forgot': 1, 'language': 'en'})
        self.later(days=1)
        # Tomorrow: five more new ones, plus the card forgotten today (its stability stayed 0.4 day).
        self.assertEqual(len(self.queue()['cards']), 6)

    def test_mix_switch_and_kind_filter(self):
        self.save('alpha', 'alpha one')
        self.save('beta', 'beta two')
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO pattern_entries (language, pattern_name, example_sentence) VALUES ('en', 'so that', 'Go so that you see.')")
            conn.execute("INSERT OR REPLACE INTO settings VALUES ('review_mix', '0')")
        self.assertEqual([c['kind'] for c in self.queue()['cards']], ['vocab', 'vocab', 'pattern'])
        self.assertEqual([c['kind'] for c in self.queue(kinds='pattern')['cards']], ['pattern'])

    def test_reveal_then_grade_versus_peek(self):
        self.save('alpha', 'alpha one')
        self.save('beta', 'beta two')
        a, b = self.queue()['cards']
        shown = self.client.post(f"/api/review/cards/{a['id']}/reveal").json()
        self.assertFalse(shown['peeked'])
        self.assertEqual(shown['back']['lemma'], 'alpha')
        self.assertEqual(set(shown['intervals']), {'1', '2', '3', '4'})
        self.assertEqual(self.grade(a['id'], rating=3)['rating'], 3)
        self.client.post(f"/api/review/cards/{b['id']}/reveal", json={'gave_up': True})
        result = self.grade(b['id'], rating=4)
        self.assertEqual((result['rating'], result['peeked']), (1, True))
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT peeked FROM review_log WHERE card_id = ?', (b['id'],)).fetchone()[0], 1)

    def test_objective_cards_are_graded_by_the_server(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO reading_exercises VALUES ('r2-y', 'en', 'T', '', ?)", (json.dumps({'items': [
                {'question': 'Q1', 'options': ['a', 'b', 'c', 'd'], 'answer': 1, 'paragraph': 'P', 'skill': 'detail'},
                {'question': 'Q2', 'options': ['a', 'b', 'c', 'd'], 'answer': 0, 'paragraph': 'P2'}]}),))
            conn.execute("INSERT INTO reading_errors (exercise_id, item_index, selected) VALUES ('r2-y', 0, 2), ('r2-y', 1, 3)")
        q1, q2 = self.queue()['cards']
        self.assertEqual((q1['kind'], q1['paragraph'], q1['skill']), ('reading_q', 'P', 'detail'))
        self.assertNotIn('answer', q1)
        right = self.client.post(f"/api/review/cards/{q1['id']}/reveal", json={'answer': 1}).json()
        self.assertEqual((right['peeked'], right['correct']), (False, True))
        self.assertEqual(self.grade(q1['id'], rating=1)['rating'], 3)  # client rating ignored
        peek = self.client.post(f"/api/review/cards/{q2['id']}/reveal").json()
        self.assertTrue(peek['peeked'])
        self.assertEqual(self.grade(q2['id'], answer=0)['rating'], 1)

    def test_request_id_counts_once(self):
        self.save('alpha', 'alpha one')
        card, = self.queue()['cards']
        rid = self.rid()
        first = self.grade(card['id'], rating=3, request_id=rid)
        again = self.grade(card['id'], rating=1, request_id=rid)
        self.assertEqual(again['rating'], 3)
        self.assertTrue(again['replayed'])
        self.assertEqual(again['next_due_at'], first['next_due_at'])
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM review_log').fetchone()[0], 1)
        self.assertEqual(self.client.post(f"/api/review/cards/{card['id']}/grade",
                                          json={'rating': 5, 'request_id': self.rid()}).status_code, 422)

    def test_suspend_and_produce_card_after_a_week(self):
        self.save('alpha', 'alpha one')
        card, = self.queue()['cards']
        self.assertEqual(self.client.put(f"/api/review/cards/{card['id']}", json={'suspended': True}).json()['suspended'], True)
        self.assertEqual(self.queue()['cards'], [])
        self.client.put(f"/api/review/cards/{card['id']}", json={'suspended': False})
        self.grade(card['id'], rating=4)  # S0 = 15.5 days > 7
        with closing(self.connect()) as conn:
            produce = conn.execute("SELECT * FROM review_cards WHERE kind = 'vocab_produce'").fetchone()
        self.assertIsNotNone(produce)
        front = next(c for c in self.queue(kinds='vocab_produce')['cards'])
        self.assertEqual(front['meaning'], '意思')
        result = self.grade(front['id'], answer='Alpha', answer_ms=2000)
        self.assertEqual((result['rating'], result['correct']), (4, True))

    def test_summary_retention_needs_twenty_samples(self):
        self.save('alpha', 'alpha one')
        summary = self.client.get('/api/review/summary', params={'language': 'en'}).json()
        self.assertEqual((summary['due_now'], summary['new_available']), (0, 1))
        self.assertIsNone(summary['retention_7d'])
        self.assertEqual(len(summary['forecast']), 7)
        with closing(self.connect()) as conn, conn:
            card_id = conn.execute("SELECT id FROM review_cards").fetchone()[0]
            for i in range(20):
                conn.execute("INSERT INTO review_log (card_id, at, rating, was_due) VALUES (?, ?, ?, 1)",
                             (card_id, clock.stamp(START - timedelta(hours=i)), 1 if i < 5 else 3))
        summary = self.client.get('/api/review/summary', params={'language': 'en'}).json()
        self.assertEqual(summary['retention_7d'], 0.75)

    def test_old_attempt_api_moves_the_card_once(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO reading_exercises VALUES ('r2-z', 'en', 'T', '', ?)", (json.dumps({'items': [
                {'question': 'Q1', 'options': ['a', 'b', 'c', 'd'], 'answer': 1}]}),))
            conn.execute("INSERT INTO reading_errors (exercise_id, item_index, selected) VALUES ('r2-z', 0, 2)")
        body = {'kind': 'reading', 'item_id': 'r2-z', 'item_index': 0, 'selection': 1, 'mode': 'independent',
                'attempt_id': str(uuid.uuid4())}
        self.assertEqual(self.client.post('/api/review/attempt', json=body).status_code, 200)
        self.assertEqual(self.client.post('/api/review/attempt', json=body).status_code, 200)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM review_log').fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT state FROM review_cards WHERE kind='reading_q'").fetchone()[0], 'review')


class Contexts(Base):
    def test_saving_again_adds_a_context_and_cloze_rotates(self):
        first = self.save('resilient', 'She stayed resilient.')
        self.assertTrue(first['created'])
        second = self.save('resilient', 'Resilient systems recover.', source_kind='reading', source_ref='https://a')
        self.assertFalse(second['created'])
        self.assertEqual(second['context_count'], 2)
        self.assertEqual(second['contexts'][1]['source_kind'], 'reading')
        self.assertEqual(self.save('resilient', 'She stayed resilient.')['context_count'], 2)  # same sentence once
        card, = self.queue()['cards']
        self.assertEqual(card['sentence'], f'She stayed {cards.BLANK}.')
        self.grade(card['id'], rating=1)
        self.later(minutes=11)
        card, = self.queue()['cards']
        self.assertEqual(card['sentence'], f'{cards.BLANK} systems recover.')
        vid = first['id']
        listed = self.client.get(f'/api/vocab/{vid}/contexts').json()['items']
        self.assertEqual(self.client.post(f'/api/vocab/{vid}/contexts', json={'sentence': 'Be resilient.'}).status_code, 201)
        self.assertEqual(self.client.delete(f'/api/vocab/{vid}/contexts', params={'context_id': listed[0]['id']}).status_code, 200)
        detail = self.client.get(f'/api/vocab/{vid}').json()
        self.assertEqual(detail['context_count'], 2)
        self.assertIsNotNone(detail['card'])

    def test_cloze_handles_inflection_and_japanese(self):
        self.assertEqual(cards.cloze('He decided to go.', ['decide'], 'en'), f'He {cards.BLANK} to go.')
        self.assertEqual(cards.cloze('昨日食べた。', ['食べる'], 'ja'), f'昨日{cards.BLANK}た。')
        self.assertEqual(cards.cloze('見直しが必要だ。', ['見直す'], 'ja'), f'{cards.BLANK}が必要だ。')  # never eats a particle
        self.assertIsNone(cards.hint_for('撤回', ['撤回する']))
        self.assertIsNone(cards.cloze('Nothing here.', ['absent'], 'en'))

    def test_encounters_once_per_ref(self):
        self.save('resilient', 'She stayed resilient.')
        body = {'language': 'en', 'text': 'Resilient people adapt. Resilient!', 'ref': 'https://x'}
        self.assertEqual(self.client.post('/api/learning/encounters', json=body).json()['words'], 1)
        self.assertEqual(self.client.post('/api/learning/encounters', json=body).json()['words'], 0)
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT encounters FROM vocab_entries').fetchone()[0], 1)
            self.assertEqual(words.encounter_lemmas(conn, 'en', ['Resilient', 'other']), 1)

    def test_due_vocab_and_chat_success_for_hooks(self):
        self.save('alpha', 'alpha one', meaning='第一')
        card, = self.queue()['cards']
        self.grade(card['id'], rating=3)
        with closing(self.connect()) as conn:
            self.assertEqual(cards.due_vocab(conn, 'en', 2), [])
            self.assertEqual(cards.reviews_due(conn, 'en'), 0)
        self.later(days=4)
        with closing(self.connect()) as conn, conn:
            due = cards.due_vocab(conn, 'en', 2)
            self.assertEqual([(d['lemma'], d['meaning']) for d in due], [('alpha', '第一')])
            self.assertEqual(cards.reviews_due(conn, 'en'), 1)
            self.assertEqual(cards.chat_success(conn, 'en', ['alpha']), [card['id']])
            self.assertEqual(conn.execute('SELECT weak FROM review_log ORDER BY id DESC').fetchone()[0], 1)
            self.assertEqual(cards.reviews_due(conn, 'en'), 0)


class Dictation(unittest.TestCase):
    def test_english_word_by_word(self):
        result = words.compare('The library closes at nine, right?', 'the library close at nine', 'en')
        self.assertEqual([w['status'] for w in result['words']], ['ok', 'ok', 'wrong', 'ok', 'ok', 'missing'])
        self.assertEqual(result['words'][2]['typed'], 'close')
        self.assertEqual(result['score'], round(4 / 6, 3))

    def test_japanese_by_tokens_and_kana(self):
        result = words.compare('図書館に行きます。', 'としょかんに行きます', 'ja')
        self.assertEqual(result['score'], 1.0)
        wrong = words.compare('明日は図書館に行きます。', '明日は学校に行きます', 'ja')
        self.assertEqual(next(w for w in wrong['words'] if w['text'] == '図書館')['status'], 'missing')
        self.assertIn('がっこう', wrong['extra'])
        self.assertLess(wrong['score'], 1)


class Records(Base):
    def add_events(self, skill, results, lookups=None, words_count=None, types=None):
        with closing(self.connect()) as conn, conn:
            for i, (correct, total) in enumerate(results):
                data = {'correct': correct, 'total': total}
                if skill == 'reading':
                    data.update(words=words_count or 500, lookups=lookups if lookups is not None else 1)
                if types:
                    data['items'] = types
                store.record_event(conn, skill, 'en', f'{skill}-{i}', data,
                                   at=clock.stamp(clock.now() - timedelta(hours=len(results) - i)))

    def test_advice_branches(self):
        self.assertIsNone(self.client.get('/api/learning/advice', params={'language': 'en'}).json()['reading']['level'])
        self.add_events('reading', [(5, 5)] * 5, lookups=2, words_count=500)
        self.add_events('listening', [(2, 5)] * 5)
        advice = self.client.get('/api/learning/advice', params={'language': 'en'}).json()
        self.assertEqual(advice['reading']['level'], 'up')
        self.assertIn('查词 0.4%', advice['reading']['basis'])
        self.assertEqual(advice['listening']['level'], 'down')
        self.later(hours=6)
        self.add_events('reading', [(4, 5)] * 5, lookups=50, words_count=500)  # 10% lookups
        self.assertEqual(self.client.get('/api/learning/advice', params={'language': 'en'}).json()['reading']['level'], 'down')
        self.later(hours=6)
        self.add_events('reading', [(4, 5)] * 5, lookups=20, words_count=500)
        self.assertEqual(self.client.get('/api/learning/advice', params={'language': 'en'}).json()['reading']['level'], 'keep')

    def test_type_diagnosis_needs_eight_and_tilts_the_next_set(self):
        items = [{'type': 'inference', 'correct': False}, {'type': 'detail', 'correct': True}]
        self.add_events('reading', [(1, 2)] * 7, types=items)
        with closing(self.connect()) as conn:
            self.assertEqual(insights.weak_types(conn, 'en'), [])
            self.assertIsNone(insights.weakest_type(conn, 'en', 'reading'))
        self.add_events('reading', [(1, 2)], types=items)
        with closing(self.connect()) as conn:
            weak = insights.weak_types(conn, 'en')
            self.assertEqual([(w['type'], w['n']) for w in weak], [('inference', 8), ('detail', 8)])
            self.assertEqual(insights.weakest_type(conn, 'en', 'reading'), 'inference')
        text = ('The museum opens at nine. Visitors must book online. The cafe closes early on Mondays. '
                'Groups of ten or more need a guide. Bags are not allowed in the gallery.')
        captured = {}

        async def fake_generate(instruction, payload, schema):
            captured['instruction'], captured['schema'] = instruction, schema
            n = int(instruction.split('出 ')[1].split(' 道')[0])
            return {'items': [{'question': f'Question {i}?', 'options': [f'o{i}a', f'o{i}b', f'o{i}c', f'o{i}d'],
                               'answer': 0, 'quote': 'Visitors must book online.', 'explanation': '依据',
                               'skill': 'inference' if i else 'bogus'} for i in range(n)]}
        screen = AsyncMock(return_value=[{'format': 'toefl_daily', 'reason': 'r', 'level': 'B2'}])
        with patch.object(reading, 'generate', fake_generate), patch.object(reading, 'screen_candidates', screen):
            result = self.client.post('/api/reader/exercises', json={'language': 'en', 'title': 'Museum', 'text': text})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(result.json()['items']), 3)  # 2 for a short daily text, +1 for the weak type
        self.assertIn('inference', captured['instruction'])
        self.assertIn('skill', captured['schema']['properties']['items']['items']['required'])
        self.assertEqual([i['skill'] for i in result.json()['items']], [None, 'inference', 'inference'])
        ident = result.json()['id']
        self.client.post('/api/reader/lookups', json={'language': 'en', 'doc': 'museum-doc', 'word': 'Visitors',
                                                       'lemma': 'visitor', 'sentence': 'Visitors must book online.'})
        self.client.post('/api/reader/lookups', json={'language': 'en', 'doc': 'museum-doc', 'word': 'visitor',
                                                       'lemma': 'visitor'})
        submitted = self.client.post(f'/api/reader/exercises/{ident}/submit', json={'choices': [0, 1, 0], 'doc': 'museum-doc'})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.client.post(f'/api/reader/exercises/{ident}/submit', json={'choices': [0, 0, 0], 'doc': 'museum-doc'})
        with closing(self.connect()) as conn:
            events = conn.execute("SELECT data_json FROM study_events WHERE kind='reading' AND ref=?", (ident,)).fetchall()
        self.assertEqual(len(events), 1)  # first submission only
        data = json.loads(events[0][0])
        from app.services import reading_formats
        self.assertEqual((data['correct'], data['total'], data['lookups'], data['words']),
                         (2, 3, 1, reading_formats.article_length('en', text)))
        self.assertEqual(data['items'][1], {'type': 'inference', 'correct': False})
        looked = self.client.get('/api/reader/lookups', params={'language': 'en', 'doc': 'museum-doc'}).json()['items']
        self.assertEqual([(w['lemma'], w['saved']) for w in looked], [('visitor', False)])

    def test_stats_are_null_without_data(self):
        stats = self.client.get('/api/learning/stats', params={'language': 'en'}).json()
        self.assertEqual((stats['reading'], stats['listening'], stats['review'], stats['words_encountered']),
                         (None, None, None, None))
        self.add_events('listening', [(1, 2)], types=[{'type': 'gist', 'correct': True}, {'type': 'detail', 'correct': False}])
        with closing(self.connect()) as conn, conn:
            store.record_event(conn, 'listening_cause', 'en', 'p', {'items': [{'index': 1, 'cause': 'not_heard'}]})
        stats = self.client.get('/api/learning/stats', params={'language': 'en'}).json()
        self.assertEqual(stats['listening']['causes'], {'not_heard': 1})
        self.assertEqual(stats['listening']['types']['gist']['accuracy'], 1.0)

    def test_today_order_and_done(self):
        self.save('alpha', 'alpha one')
        today = self.client.get('/api/today', params={'language': 'en'}).json()
        self.assertEqual([s['kind'] for s in today['steps']], ['review', 'reading', 'listening', 'output'])
        self.assertEqual((today['steps'][0]['count'], today['steps'][0]['done']), (1, False))
        self.add_events('reading', [(3, 4)] * 2)  # yesterday-ish and today: reading done more this week
        today = self.client.get('/api/today', params={'language': 'en'}).json()
        self.assertEqual([s['kind'] for s in today['steps']], ['review', 'listening', 'reading', 'output'])
        self.assertTrue(next(s for s in today['steps'] if s['kind'] == 'reading')['done'])
        card, = self.queue()['cards']
        self.grade(card['id'], rating=3)
        review = self.client.get('/api/today', params={'language': 'en'}).json()['steps'][0]
        self.assertEqual((review['count'], review['done']), (0, True))
        self.later(days=1)
        next_day = self.client.get('/api/today', params={'language': 'en'}).json()
        self.assertFalse(next_day['steps'][0]['done'])
        self.assertFalse(any(s['done'] for s in next_day['steps'] if s['kind'] in ('reading', 'listening')))
        with closing(self.connect()) as conn:
            before = conn.execute('SELECT count(*) FROM study_events').fetchone()[0]
        self.client.get('/api/today', params={'language': 'en'})
        with closing(self.connect()) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM study_events').fetchone()[0], before)  # read-only

    def test_summary_feedback_keeps_only_real_quotes(self):
        raw = {'points_right': ['讲了开放时间'], 'missed': '没提团体要导游',
               'fixes': [{'original': 'museum open', 'better': 'museum opens', 'why': '第三人称'},
                         {'original': 'invented words', 'better': 'x', 'why': 'y'},
                         {'original': 'nine', 'better': 'nine', 'why': '没改'}]}
        with patch.object(reading, 'generate', AsyncMock(return_value=raw)) as generate:
            result = self.client.post('/api/reader/summary-feedback', json={
                'language': 'en', 'title': 'Museum', 'text': 'The museum opens at nine.', 'summary': 'The museum open at nine.'}).json()
        self.assertEqual(result['fixes'], [{'original': 'museum open', 'better': 'museum opens', 'why': '第三人称'}])
        self.assertEqual(result['missed'], '没提团体要导游')
        self.assertIn('fixes', generate.await_args.args[2]['properties'])  # the JSON shape goes into the prompt


class ListeningSteps(Base):
    def setUp(self):
        super().setUp()
        self.exercise = Exercise.model_validate({
            'title': 'Library', 'script': [{'speaker': 'A', 'text': 'The library closes at nine tonight.'},
                                           {'speaker': 'B', 'text': 'Then I will return the books tomorrow.'},
                                           {'speaker': 'A', 'text': 'Remember the late fee.'}],
            'questions': [{'prompt': 'When does it close?', 'choices': ['At nine', 'At ten', 'At noon', 'Never'],
                           'answer': 0, 'evidence': [1], 'explanation': '第一句', 'skill': 'detail'},
                          {'prompt': 'What will B do?', 'choices': ['Return books', 'Pay', 'Study', 'Leave'],
                           'answer': 0, 'evidence': [2], 'explanation': '第二句', 'skill': 'inference'}]})
        import io
        import wave
        out = io.BytesIO()
        with wave.open(out, 'wb') as wav:
            wav.setparams((1, 2, 1000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x01\x00' * 3000)
        self.audio = out.getvalue()
        listening_sessions.create('p1', self.exercise, FORMATS['en_conversation'], self.audio,
                                  [{'start': 0, 'end': 1}, {'start': 1, 'end': 2}, {'start': 2, 'end': 3}],
                                  {'id': 'p1', 'language': 'en', 'format': 'x', 'count': 2})

    def test_play_grade_causes_lines_dictation(self):
        self.assertEqual(self.client.post('/api/listening/practice/p1/dictation', json={'line': 1, 'text': 'x'}).status_code, 409)
        self.assertEqual(self.client.get('/api/listening/practice/p1/lines').status_code, 409)
        for _ in range(3):
            plays = self.client.post('/api/listening/practice/p1/play').json()
        self.assertEqual(plays['replays'], 2)
        receipt = self.client.post('/api/listening/practice/p1/grade', json={'selections': [0, 2]}).json()
        self.assertEqual([r['skill'] for r in receipt['results']], ['detail', 'inference'])
        self.assertEqual(receipt['results'][1]['clips'], [{'start': 1, 'end': 2}])
        with closing(self.connect()) as conn:
            event = json.loads(conn.execute("SELECT data_json FROM study_events WHERE kind='listening'").fetchone()[0])
        self.assertEqual((event['correct'], event['total'], event['replays']), (1, 2, 2))
        self.assertEqual(self.client.post('/api/listening/practice/p1/causes',
                                          json={'items': [{'index': 0, 'cause': 'not_heard'}]}).status_code, 422)
        causes = self.client.post('/api/listening/practice/p1/causes', json={'items': [{'index': 1, 'cause': 'not_heard'}]}).json()
        self.assertEqual(causes['items'][0]['next'], 'dictation')
        lines = self.client.get('/api/listening/practice/p1/lines').json()
        self.assertEqual(lines['dictation'][0], {'line': 2, 'sentence': 1})  # evidence of the missed question first
        self.assertEqual(lines['lines'][1]['sentences'][0]['text'], 'Then I will return the books tomorrow.')
        self.assertEqual(self.client.get('/api/listening/practice/p1/lines/2/audio', params={'sentence': 2}).status_code, 404)
        self.assertEqual(lines['lines'][1]['start'], 1)
        clip = self.client.get('/api/listening/practice/p1/lines/2/audio')
        self.assertEqual(clip.status_code, 200)
        import io
        import wave
        with wave.open(io.BytesIO(clip.content)) as wav:
            self.assertEqual(wav.getnframes(), 1000)
        result = self.client.post('/api/listening/practice/p1/dictation',
                                  json={'line': 2, 'sentence': 1, 'text': 'then I will return the book tomorrow'}).json()
        self.assertEqual(result['reference'], 'Then I will return the books tomorrow.')
        self.assertEqual([w['status'] for w in result['words']].count('wrong'), 1)
        stats = self.client.get('/api/learning/stats', params={'language': 'en'}).json()['listening']
        self.assertEqual((stats['causes'], stats['replays']), ({'not_heard': 1}, 2))
        # The missed question is now a listening card with its clip.
        card = next(c for c in self.queue()['cards'] if c['kind'] == 'listening_q')
        self.assertEqual((card['clips'], card['skill']), ([{'start': 1, 'end': 2}], 'inference'))


class Origins(Base):
    def test_new_routes_reject_other_sites(self):
        evil = {'origin': 'https://evil.example'}
        for method, path in [('get', '/api/today?language=en'), ('get', '/api/learning/advice?language=en'),
                             ('get', '/api/learning/stats?language=en'), ('get', '/api/learning/settings'),
                             ('post', '/api/learning/encounters'), ('get', '/api/review/queue?language=en'),
                             ('post', '/api/review/cards/1/reveal'), ('post', '/api/review/cards/1/grade'),
                             ('put', '/api/review/cards/1'), ('get', '/api/review/summary?language=en'),
                             ('post', '/api/review/session/end'), ('get', '/api/vocab/1/contexts'),
                             ('post', '/api/reader/lookups'), ('get', '/api/reader/lookups?language=en&doc=x'),
                             ('post', '/api/reader/summary-feedback'), ('post', '/api/listening/practice/p/play'),
                             ('post', '/api/listening/practice/p/dictation'), ('post', '/api/listening/practice/p/causes'),
                             ('get', '/api/listening/practice/p/lines')]:
            self.assertEqual(getattr(self.client, method)(path, headers=evil).status_code, 403, path)

    def test_settings_defaults_and_clamps(self):
        self.assertEqual(self.client.get('/api/learning/settings').json()['review_new_per_day'], 12)
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO settings VALUES ('review_target_retention', '0.99'), ('review_new_per_day', 'x')")
            self.assertEqual(store.setting(conn, 'review_target_retention'), 0.95)
            self.assertEqual(store.setting(conn, 'review_new_per_day'), 12)

class ListeningPrompts(unittest.TestCase):
    def test_speakers_are_named_by_voice_not_letters(self):
        note = listening._speaker_note('ja', {'A': 'jf_alpha', 'B': 'jm_kumo'})
        self.assertIn('「女の人」「男の人」', note)
        self.assertIn('不要写 A、B', note)
        self.assertIn('the man', listening._speaker_note('en', {'A': 'am_adam', 'B': 'af_heart'}))
        self.assertIn('身份', listening._speaker_note('en', {'A': 'alloy', 'B': 'echo'}))

    def test_dictation_prefers_missed_evidence_and_holdable_sentences(self):
        sentences = lambda *texts: [{'sentence': i + 1, 'text': t, 'start': i, 'end': i + 1} for i, t in enumerate(texts)]
        rows = [{'line': 1, 'sentences': sentences('No, not at all.', 'There is still plenty of time before the midterm exam starts.')},
                {'line': 2, 'sentences': sentences('Yes.')},
                {'line': 3, 'sentences': sentences('I joined a study group that met twice a week in the library.')}]
        receipt = {'results': [{'correct': True, 'evidence': [{'line': 1}]}, {'correct': False, 'evidence': [{'line': 3}, {'line': 2}]}]}
        self.assertEqual(listening._dictation_picks(receipt, rows, 'en'),
                         [{'line': 3, 'sentence': 1}, {'line': 1, 'sentence': 2}])

class JLPTSections(Base):
    def test_japanese_excerpts_hit_the_three_lengths(self):
        from app.services import reading as reading_service
        paragraph = '水星は太陽に最も近い惑星であり、その表面は昼と夜で大きく温度が変わる。' * 3
        text = '\n'.join([paragraph] * 12)
        bands = dict(reading_service.japanese_excerpts(text))
        for name, (low, high) in {'短文': (150, 450), '中文': (350, 800), '長文': (700, 1400)}.items():
            self.assertTrue(low <= reading_service.ja_length(bands[name]) <= high, name)
        self.assertEqual(listening._section(FORMATS['ja_task']), 'jlpt_task')
        self.assertIsNone(listening._section(FORMATS['en_talk']))

    def test_a_jlpt_set_is_tagged_by_its_section(self):
        text = ('水星は太陽に最も近い惑星であり、その表面は昼と夜で大きく温度が変わる。' * 4 + '\n') * 4
        captured = {}

        async def fake_generate(instruction, payload, schema):
            captured['instruction'] = instruction
            return {'items': [{'question': f'問{i}はどれか。', 'options': [f'選択{i}{k}' for k in 'abcd'], 'answer': 0,
                               'quote': '水星は太陽に最も近い惑星であり', 'explanation': '依据', 'skill': 'detail'}
                              for i in range(3)]}
        screen = AsyncMock(return_value=[{'format': 'jlpt_mid', 'reason': 'r', 'level': 'N1'}])
        with patch.object(reading, 'generate', fake_generate), patch.object(reading, 'screen_candidates', screen):
            result = self.client.post('/api/reader/exercises', json={'language': 'ja', 'title': '水星', 'text': text})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual([i['skill'] for i in result.json()['items']], ['jlpt_mid'] * 3)
        self.assertIn('内容理解（中文）', captured['instruction'])

    def test_new_japanese_sources_are_listed(self):
        names = {row['name'] for row in self.client.get('/api/reader/sources', params={'lang': 'ja'}).json()['items']}
        self.assertTrue({'サイエンスポータル', '青空文庫', 'Wikipedia'} <= names)

class CausesAndJapaneseEvidence(ListeningSteps):
    def test_marked_causes_come_back_and_merge(self):
        self.client.post('/api/listening/practice/p1/grade', json={'selections': [1, 1]})
        detail = self.client.get('/api/listening/practice/p1').json()
        self.assertEqual(detail['causes'], {'items': [
            {'index': 0, 'cause': None, 'type': 'detail', 'next': None},
            {'index': 1, 'cause': None, 'type': 'inference', 'next': None}]})
        self.client.post('/api/listening/practice/p1/causes', json={'items': [{'index': 1, 'cause': 'misjudged'}]})
        merged = self.client.post('/api/listening/practice/p1/causes', json={'items': [{'index': 0, 'cause': 'not_heard'}]}).json()
        self.assertEqual([(i['index'], i['cause'], i['next']) for i in merged['items']],
                         [(0, 'not_heard', 'dictation'), (1, 'misjudged', 'evidence')])
        self.assertEqual(self.client.get('/api/listening/practice/p1').json()['causes'], merged)

    def test_japanese_evidence_is_the_quoted_paragraph(self):
        from app.services.reading_errors import evidence_paragraph, item_with_evidence
        first = '　水星は太陽に最も近い惑星である。表面の温度は昼と夜で大きく変わる。'
        second = '　ベピコロンボは二機の探査機で磁場を同時に計測する。太陽風の影響を切り分けるためだ。'
        text = first + '\n' + second + '\n' + '　最後の段落である。'
        quote = '太陽風の影響を切り分けるためだ。'
        self.assertEqual(evidence_paragraph(text, quote), second.strip())
        indented = first + second  # paragraphs marked only by the full-width indent
        self.assertEqual(evidence_paragraph(indented, quote), second.strip())
        long = '　' + ''.join(f'これは{i}番目の文で、内容を少しずつ説明している。' for i in range(30)) + quote + '最後に結論を述べる。'
        cut = evidence_paragraph(long, quote)
        self.assertIn(quote, cut)
        self.assertLess(len(cut), 120)
        self.assertTrue(cut.startswith('…') and cut.endswith('最後に結論を述べる。'))
        old = {'quote': quote, 'paragraph': text}
        self.assertEqual(item_with_evidence(old)['paragraph'], second.strip())  # old sets are cut when read


if __name__ == '__main__':
    unittest.main()
