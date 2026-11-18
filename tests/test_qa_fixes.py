"""Offline endpoint regressions for the tester's UI repair batch."""
import json
import io
from unittest.mock import patch
from PIL import Image

import test_lore as base
from app.services import chat as chat_service, workspace_conversations
from app.services.learning import store


class QAFixesTests(base.Base):
    def setUp(self):
        super().setUp()
        self.c = self.client()
        self.c = type(self.c)(self.c.app, base_url='http://127.0.0.1:8787', client=('127.0.0.1', 54321))
        self.c.put('/api/chat/main', json={'primary_id': 5})
        workspace_conversations._active.clear()
        self.addCleanup(workspace_conversations._active.clear)

    def test_new_main_preserves_archive_and_memories(self):
        self.sql("INSERT INTO messages (id,session_id,role,content) VALUES (81,19,'user','Original')")
        self.sql("INSERT INTO memory_items (persona_id,content,source_session_id) VALUES (5,'Remember',19)")
        response = self.c.post('/api/chat/main/new')
        self.assertEqual(response.status_code, 200, response.text)
        main = response.json()
        self.assertNotEqual(main['session_id'], 19)
        self.assertEqual(main, self.c.get('/api/chat/main').json())
        self.assertEqual(self.c.get('/api/chat/main/messages').json()['items'], [])
        self.assertEqual(self.sql('SELECT persona_id FROM sessions WHERE id=?', (main['session_id'],))[0][0], 5)
        self.assertIn(19, [a['session_id'] for a in self.c.get('/api/chat/archives').json()['items']])
        self.assertEqual(self.sql('SELECT content FROM memory_items')[0][0], 'Remember')
        # An empty main also becomes an archive.
        self.c.post('/api/chat/main/new')
        self.assertIn(main['session_id'], [a['session_id'] for a in self.c.get('/api/chat/archives').json()['items']])

    def test_new_main_refuses_busy_reply_and_batch(self):
        state = chat_service._state_for(19)
        with patch.object(chat_service, '_busy', return_value=True):
            self.assertEqual(self.c.post('/api/chat/main/new').status_code, 409)
        state.batch_texts.append('waiting')
        self.assertEqual(self.c.post('/api/chat/main/new').status_code, 409)
        self.assertEqual(self.c.get('/api/chat/main').json()['session_id'], 19)

    def test_archive_delete_clears_references_and_preserves_saved_text(self):
        self.sql("INSERT INTO messages (id,session_id,role,content) VALUES (81,19,'user','Original')")
        self.sql("INSERT INTO message_embeddings VALUES (81,'test',1,x'00000000')")
        self.sql("INSERT INTO vocab_entries (id,language,lemma,meaning,context_sentence,source_message_id) VALUES (91,'ja','word','meaning','Original',81)")
        self.sql("INSERT INTO pattern_entries (language,pattern_name,example_sentence,source_message_id) VALUES ('ja','pattern','Original',81)")
        self.sql("INSERT INTO memory_items (persona_id,content,source_session_id) VALUES (5,'Remember',19)")
        self.sql("INSERT INTO teaching_evidence VALUES (5,'outline','unit','evidence',81)")
        self.sql("INSERT INTO session_pointers (session_id,persona_id,engine,pointer) VALUES (19,5,'claude','pointer')")
        self.sql("INSERT INTO lore_state (session_id,persona_id,book_id,uid) VALUES (19,5,1,'entry')")
        self.sql("INSERT INTO chat_turns (session_id,persona_id) VALUES (19,5)")
        self.sql("INSERT INTO chat_seen VALUES (19,5,81)")
        self.c.post('/api/chat/main/new')
        response = self.c.delete('/api/chat/archives/19')
        self.assertEqual(response.status_code, 200, response.text)
        for table in ('messages', 'message_embeddings', 'session_pointers', 'lore_state', 'chat_turns', 'chat_seen', 'teaching_evidence'):
            self.assertEqual(self.sql(f'SELECT count(*) FROM {table}')[0][0], 0, table)
        vocab = self.c.get('/api/vocab/91').json()
        self.assertEqual(vocab['context_sentence'], 'Original')
        self.assertIsNone(vocab['source_message_id'])
        self.assertEqual(self.sql('SELECT example_sentence,source_message_id FROM pattern_entries')[0][:], ('Original', None))
        self.assertEqual(self.sql('SELECT content,source_session_id FROM memory_items')[0][:], ('Remember', None))
        self.assertEqual(self.c.delete('/api/chat/archives/19').status_code, 404)
        sid = self.c.get('/api/chat/main').json()['session_id']
        self.assertEqual(self.c.delete(f'/api/chat/archives/{sid}').status_code, 404)
        self.assertEqual(self.c.delete('/api/chat/archives/999').status_code, 404)

    def test_language_delete_and_refusals_keep_study_records(self):
        self.assertEqual(self.c.post('/api/languages', json={'tag': 'fr', 'label': 'Français'}).status_code, 201)
        self.sql("INSERT INTO vocab_entries (language,lemma,context_sentence) VALUES ('fr','mot','Un mot')")
        self.sql("INSERT INTO messages (session_id,role,content,language) VALUES (19,'user','Un mot','fr')")
        self.c.put('/api/chat/main', json={'language': 'fr'})
        busy = self.c.delete('/api/languages/fr')
        self.assertEqual(busy.status_code, 409)
        self.assertEqual(busy.json()['detail'], '先把聊天拨到别的语言。')
        self.c.put('/api/chat/main', json={'language': 'ja'})
        self.assertEqual(self.c.delete('/api/languages/en').status_code, 409)
        self.assertEqual(self.c.delete('/api/languages/unknown').status_code, 404)
        self.assertEqual(self.c.delete('/api/languages/fr').status_code, 200)
        self.assertNotIn('fr', [x['tag'] for x in self.c.get('/api/languages').json()['items']])
        self.assertEqual(self.sql("SELECT count(*) FROM vocab_entries WHERE language='fr'")[0][0], 1)
        self.assertEqual(self.sql("SELECT count(*) FROM messages WHERE language='fr'")[0][0], 1)

    def test_reading_error_delete_uses_composite_key_and_removes_review(self):
        payload = json.dumps({'items': [{'question': 'Q', 'options': ['A', 'B'], 'answer': 0}]})
        self.sql("INSERT INTO reading_exercises VALUES ('exercise','en','Title','',?)", (payload,))
        self.sql("INSERT INTO reading_errors (exercise_id,item_index,selected) VALUES ('exercise',0,1)")
        conn = self.connect()
        try:
            store.sync(conn)
            conn.commit()
        finally:
            conn.close()
        card = self.sql("SELECT id FROM review_cards WHERE kind='reading_q'")[0][0]
        self.sql("INSERT INTO review_log (card_id,at,rating) VALUES (?,'2026-01-01',1)", (card,))
        self.sql("INSERT INTO review_states (kind,item_id,item_index) VALUES ('reading','exercise',0)")
        self.sql("INSERT INTO review_attempts VALUES ('attempt','reading','exercise',0,'{}','{}','2026-01-01')")
        response = self.c.delete('/api/reading/errors/exercise:0')
        self.assertEqual(response.status_code, 200, response.text)
        for table in ('reading_errors', 'review_cards', 'review_log', 'review_states', 'review_attempts'):
            self.assertEqual(self.sql(f'SELECT count(*) FROM {table}')[0][0], 0, table)
        self.assertEqual(self.sql('SELECT count(*) FROM reading_exercises')[0][0], 1)
        for ident in ('exercise:0', 'missing:1', 'malformed'):
            self.assertEqual(self.c.delete('/api/reading/errors/' + ident).status_code, 404)
        self.sql("INSERT INTO reading_errors (exercise_id,item_index,selected) VALUES ('exercise',0,1)")
        self.assertEqual(self.c.delete('/api/reader/errors/exercise:0').status_code, 200)
        self.assertEqual(self.c.delete('/api/reader/errors/exercise:0').status_code, 404)

    def test_notebook_meaning_update_validation_and_unknown(self):
        self.sql("INSERT INTO vocab_entries (id,language,lemma,meaning,context_sentence) VALUES (91,'en','word','Old','A word')")
        response = self.c.put('/api/notebook/91', json={'meaning': 'New'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.c.get('/api/vocab/91').json()['meaning'], 'New')
        for meaning in ('', 'x' * 301, 123):
            self.assertEqual(self.c.put('/api/notebook/91', json={'meaning': meaning}).status_code, 422)
        self.assertEqual(self.c.put('/api/notebook/999', json={'meaning': 'New'}).status_code, 404)

    def test_conversation_delete_including_turns_and_attachment_bytes(self):
        cid = workspace_conversations.create_conversation()['id']
        attachment = workspace_conversations.upload(cid, 'file.txt', 'text/plain', b'Attached text')
        image = io.BytesIO()
        Image.new('RGB', (4, 4)).save(image, 'PNG')
        workspace_conversations.upload(cid, 'image.png', 'image/png', image.getvalue())
        workspace_conversations.begin_turn(cid, 'r1', 'Read', [attachment['id']], {})
        self.assertEqual(self.c.delete('/api/workspace-agent/conversations/' + cid).status_code, 409)
        workspace_conversations.finish_turn(cid, 'r1', {'reply': 'Read'})
        response = self.c.delete('/api/workspace-agent/conversations/' + cid)
        self.assertEqual(response.status_code, 200, response.text)
        for table in ('workspace_conversations', 'workspace_messages', 'workspace_attachments', 'workspace_attachment_images', 'study_documents'):
            self.assertEqual(self.sql(f'SELECT count(*) FROM {table}')[0][0], 0, table)
        self.assertEqual(self.c.delete('/api/workspace-agent/conversations/' + cid).status_code, 404)

    def test_new_writes_refuse_cross_origin(self):
        cases = [('POST', '/api/chat/main/new', None), ('DELETE', '/api/chat/archives/19', None),
                 ('DELETE', '/api/languages/fr', None), ('DELETE', '/api/reading/errors/exercise:0', None),
                 ('PUT', '/api/notebook/91', {'meaning': 'New'}), ('DELETE', '/api/workspace-agent/conversations/unknown', None)]
        for method, url, body in cases:
            with self.subTest(url=url):
                self.assertEqual(self.c.request(method, url, json=body, headers={'Origin': 'https://elsewhere.test'}).status_code, 403)
