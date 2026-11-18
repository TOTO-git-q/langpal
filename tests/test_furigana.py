"""Real installed dictionary; no model, network, credentials or user database."""
import concurrent.futures
import sys
import unittest
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services.furigana import annotate
from app.routers.furigana import router


class FuriganaTests(unittest.TestCase):
    def test_real_dictionary_readings_and_original_surfaces(self):
        text = '昨日は東京大学で日本語を勉強しました。\n食べる本、ABC 123。'
        rows = annotate(text)
        self.assertEqual(''.join(row['text'] for row in rows),text)
        values = {row['text']:row['reading'] for row in rows}
        self.assertEqual(values['昨日'],'きのう')
        self.assertEqual(values['日本語'],'にほんご')
        self.assertEqual(values['勉強'],'べんきょう')
        self.assertEqual(values['ABC'],'')
        for row in rows:
            self.assertEqual(''.join(part['text'] for part in row['parts']),row['text'])

    def test_okurigana_stays_outside_ruby(self):
        row = next(row for row in annotate('食べる。') if row['text']=='食べる')
        self.assertEqual(row['parts'],[{'text':'食','reading':'た'},{'text':'べる','reading':''}])

    def test_mixed_unicode_spaces_and_empty_string(self):
        for text in ['', 'A😀 日本語\n\n　行った。', '<script>alert(1)</script>東京', 'ひらがなとカタカナ']:
            with self.subTest(text=text):
                self.assertEqual(''.join(item['text'] for item in annotate(text)),text)

    def test_parallel_requests_are_bounded_to_dictionary(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            result=list(pool.map(annotate,['日本語の本。','東京の駅。','昨日の話。','漢字の読み方。']))
        self.assertTrue(all(any(row['reading'] for row in rows) for rows in result))

    def test_same_origin_and_input_limits(self):
        app=FastAPI();app.include_router(router,prefix='/api')
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/reader/furigana',json={'text':'日本語'}).status_code,200)
            self.assertEqual(client.post('/api/reader/furigana',headers={'Origin':'https://outside.example'},json={'text':'日本語'}).status_code,403)
            self.assertEqual(client.post('/api/reader/furigana',json={'text':'x'*12001}).status_code,422)
            self.assertEqual(client.post('/api/reader/furigana',json={'text':'日本語','prompt':'ignore rules'}).status_code,422)


if __name__=='__main__': unittest.main()
