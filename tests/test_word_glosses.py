"""Isolated caches and controlled providers: no real user data or credentials."""
import asyncio
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services import explain, word_glosses as service


def tokens(*words):
    return [dict(surface=word, lemma=word.casefold(), clickable=True, pos='', reading='') for word in words]


class GlossTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'cache.db'
        with closing(sqlite3.connect(self.db)) as conn, conn:
            schema = (Path(__file__).resolve().parents[1] / 'backend/db/schema.sql').read_text(encoding='utf-8')
            table = schema[schema.index('CREATE TABLE IF NOT EXISTS explain_cache'):].split(';', 1)[0]
            conn.execute(table)
        def connect():
            conn = sqlite3.connect(self.db)
            conn.row_factory = sqlite3.Row
            return conn
        self.patch = patch.object(explain, 'get_conn', connect)
        self.patch.start()
        self.calls = []
        self.started = asyncio.Event()
        self.release = None
        self.active = self.peak = 0
        class Provider:
            async def generate_json(inner, prompt, schema):
                self.calls.append(prompt)
                self.active += 1
                self.peak = max(self.peak, self.active)
                self.started.set()
                try:
                    if self.release:
                        await self.release.wait()
                    await asyncio.sleep(0.01)
                    if schema is explain.WORD_CARD_SCHEMA:
                        return {'meaning_zh': '完整词卡', 'grammar_note': '详细语法'}
                    data = json.loads(prompt.split('\n', 1)[1])
                    return {'words': {str(row['id']): data['text'] + ':' + row['surface'] for row in data['words']}}
                finally:
                    self.active -= 1
        self.provider = patch.object(explain, 'get_utility_provider', return_value=Provider())
        self.provider.start()

    async def asyncTearDown(self):
        await asyncio.gather(*list(service._warmups), return_exceptions=True)
        self.provider.stop(); self.patch.stop(); self.tmp.cleanup()

    async def test_all_clickable_words_including_function_words_one_call(self):
        ts = tokens('I', 'am', 'in', 'a', 'bookshop', 'and', 'it', 'is', 'quiet')
        ts += [dict(surface='.', clickable=False), ts[0]]
        result = await service.explain_words('I am in a bookshop and it is quiet.', 'en', ts)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['words']), 10)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(word['detail'] == 'brief' for word in result['words']))
        again = await service.explain_words('I am in a bookshop and it is quiet.', 'en', ts)
        self.assertEqual(again, result)
        self.assertEqual(len(self.calls), 1)

    async def test_same_bubble_context_survives_whitespace_not_other_bubbles(self):
        ts = tokens('bank')
        await service.explain_words('  a\n bank  ', 'en', ts)
        await service.explain_words('a bank', 'en', ts)
        river = await service.explain_words('river bank', 'en', ts)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(river['words'][0]['meaning_zh'], 'river bank:bank')

    async def test_foreground_joins_warmup_and_cancel_does_not_cancel_shared_job(self):
        self.release = asyncio.Event()
        first = asyncio.create_task(service.explain_words('a bank', 'en', tokens('bank')))
        await self.started.wait()
        second = asyncio.create_task(service.explain_words('a bank', 'en', tokens('bank')))
        first.cancel()
        with self.assertRaises(asyncio.CancelledError): await first
        self.release.set()
        self.assertTrue((await second)['complete'])
        self.assertEqual(len(self.calls), 1)

    async def test_summary_never_populates_full_cache_and_detail_is_deduplicated(self):
        await service.explain_words('a bank', 'en', tokens('bank'))
        self.assertIsNone(explain._get_cached('word', explain._word_cache_key('en', 'bank', 'a bank')))
        results = await asyncio.gather(*(explain.explain_word('en', 'bank', 'bank', 'a bank') for _ in range(3)))
        self.assertTrue(all(card['grammar_note'] == '详细语法' for card in results))
        self.assertEqual(len(self.calls), 2)
        cached = await service.explain_words('a bank', 'en', tokens('bank'))
        self.assertEqual(cached['words'][0]['detail'], 'full')

    async def test_batch_size_and_global_concurrency_bound(self):
        result = await service.explain_words('many words', 'en', tokens(*(f'word{i}' for i in range(65))))
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['words']), 65)
        self.assertEqual(len(self.calls), 3)
        self.assertLessEqual(self.peak, 2)

    async def test_japanese_local_readings_and_surface_are_preserved(self):
        from app.services.tokenize import tokenize
        ts = tokenize('昨日は本を読みました。', 'ja')
        result = await service.explain_words('昨日は本を読みました。', 'ja', ts)
        self.assertTrue(result['complete'])
        self.assertIn('は', [word['surface'] for word in result['words']])
        for word in result['words']:
            original = next(token for token in ts if token['surface'] == word['surface'])
            self.assertEqual(word['reading'], original.get('reading', ''))

    async def test_invalid_model_ids_empty_meanings_and_noncanonical_ids_not_trusted(self):
        async def invalid(*args):
            return {'words': {'-1': '错位', 'true': '错位', '00': '覆盖', '0': '正确', '1': ' ', '2': '错位'}}
        with patch.object(explain.get_utility_provider(), 'generate_json', invalid):
            result = await service.explain_words('a bank', 'en', tokens('a', 'bank'))
        self.assertFalse(result['complete'])
        self.assertEqual([word['meaning_zh'] for word in result['words']], ['正确'])

    async def test_provider_failure_leaves_existing_cache_usable(self):
        await service.explain_words('a bank', 'en', tokens('bank'))
        async def fail(*args): raise RuntimeError('offline')
        with patch.object(explain.get_utility_provider(), 'generate_json', fail):
            partial = await service.explain_words('a bank', 'en', tokens('a', 'bank'))
            self.assertFalse(partial['complete'])
            self.assertEqual(len(partial['words']), 1)
            with self.assertRaises(RuntimeError):
                await service.explain_words('different', 'en', tokens('different'))

    async def test_multilingual_fallback_tokens_work_without_pos(self):
        result = await service.explain_words('Bonjour le monde.', 'fr')
        self.assertTrue(result['complete'])
        self.assertEqual([word['surface'] for word in result['words']], ['Bonjour', 'le', 'monde'])

    async def test_cached_glosses_attach_without_network(self):
        ts = tokens('bank')
        await service.explain_words('a bank', 'en', ts)
        result = service.attach_cached(ts, 'a bank', 'en')
        self.assertEqual(result[0]['gloss']['meaning_zh'], 'a bank:bank')
        self.assertEqual(len(self.calls), 1)

    async def test_repeated_surface_gets_separate_occurrence_and_meaning(self):
        async def distinct(prompt, schema):
            data = json.loads(prompt.split('\n', 1)[1])
            return {'words': {str(row['id']): '银行' if row['occurrence'] == 0 else '河岸' for row in data['words']}}
        ts = tokens('bank', 'bank')
        with patch.object(explain.get_utility_provider(), 'generate_json', distinct):
            result = await service.explain_words('I left the bank for the river bank.', 'en', ts)
        self.assertEqual([word['meaning_zh'] for word in result['words']], ['银行', '河岸'])
        attached = service.attach_cached(ts, 'I left the bank for the river bank.', 'en')
        self.assertEqual(attached[1]['gloss']['meaning_zh'], '河岸')
        self.assertEqual(attached[1]['lookup_occurrence'], 1)

    async def test_detailed_cards_are_separated_by_occurrence_too(self):
        text = 'a bank near the river bank'
        await explain.explain_word('en', 'bank', 'bank', text, occurrence=0)
        await explain.explain_word('en', 'bank', 'bank', text, occurrence=1)
        await explain.explain_word('en', 'bank', 'bank', text, occurrence=1)
        self.assertEqual(len(self.calls), 2)
        self.assertIn('第 2 次出现', self.calls[1])


class RouteBoundsTests(unittest.TestCase):
    def test_batch_input_bounds_before_any_model_work(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.routers.explain import router
        app = FastAPI(); app.include_router(router)
        with TestClient(app) as client, patch.object(service, 'explain_words') as call:
            for text in ['', 'a' * 6001]:
                self.assertEqual(client.post('/explain/words', json={'sentence': text, 'language': 'en'}).status_code, 422)
            call.assert_not_called()


if __name__ == '__main__': unittest.main()
