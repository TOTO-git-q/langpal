"""Practice generation details: a word bank shown A-Z, and practices that take turns between kinds.

Written by the project lead. Fake model output only; no network."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.course import generate, lessons

SHIPPED = ROOT / 'backend/app/data/lessons'


class Alphabetical(unittest.TestCase):
    def test_answers_follow_their_words_when_the_bank_is_sorted(self):
        bank = ['silence', 'demand', 'rarely', 'broken', 'operate']
        item = {'groups': [{'items': [{'options': list(bank), 'answer': index} for index in (1, 4, 2)]}]}
        generate._alphabetize(item)
        questions = item['groups'][0]['items']
        self.assertEqual(questions[0]['options'], ['broken', 'demand', 'operate', 'rarely', 'silence'])
        self.assertEqual([q['options'][q['answer']] for q in questions], ['demand', 'operate', 'rarely'])

    def test_only_the_cet4_bank_is_sorted_and_only_after_the_blind_check(self):
        checks = lessons.kinds('cet4')['banked']['checks']
        self.assertTrue(checks['alphabetical'])
        calls = []

        async def fake_blind(item, *args, **kwargs):
            calls.append(list(item['groups'][0]['items'][0]['options']))

        definition = {**lessons.kinds('cet4')['banked']}
        example = definition['example']

        async def answer(*args, **kwargs):
            return json.loads(json.dumps(example))
        with patch.object(generate, '_call', answer), patch.object(generate, '_blind', fake_blind):
            made = asyncio.run(generate.item('en', definition, example, 'topic',
                                             [{'id': p, 'label': p} for p in ('pos', 'collocation', 'meaning')], 'g1'))
        self.assertIsNotNone(made)
        self.assertEqual(calls[0], example['groups'][0]['bank'])                     # the blind check sees the model's order
        shown = made['groups'][0]['items'][0]['options']
        self.assertEqual(shown, sorted(example['groups'][0]['bank'], key=str.casefold))
        for question, source in zip(made['groups'][0]['items'], example['groups'][0]['items']):
            self.assertEqual(question['options'][question['answer']], example['groups'][0]['bank'][source['answer']])


class Spread(unittest.TestCase):
    def test_answers_move_round_the_positions_and_the_explanation_follows(self):
        from app.services.course import builder
        card = {'type': 'quiz', 'sets': [{'groups': [{'items': [
            {'options': [f'right {n}', 'b', 'c', 'd'], 'answer': 0, 'why': '第一项对；第二项只对了一半。'} for n in range(8)]}]}]}
        builder._spread(card, 'seed')
        questions = card['sets'][0]['groups'][0]['items']
        positions = [q['answer'] for q in questions]
        self.assertEqual(sorted(positions), [0, 0, 1, 1, 2, 2, 3, 3])
        for n, question in enumerate(questions):
            self.assertEqual(question['options'][question['answer']], f'right {n}')
            first = '第' + builder.ORDINALS[question['answer']] + '项'
            self.assertTrue(question['why'].startswith(first + '对'), question['why'])
            if question['answer'] == 1:
                self.assertIn('第一项只对了一半', question['why'])          # the option that moved takes its new name

    def test_a_shared_option_list_is_left_alone(self):
        from app.services.course import builder
        shared = ['A', 'B', 'C', 'D', 'E']
        card = {'type': 'check', 'groups': [{'items': [{'options': list(shared), 'answer': 0, 'why': ''} for _ in range(3)]}]}
        builder._spread(card, 'seed')
        self.assertEqual([q['answer'] for q in card['groups'][0]['items']], [0, 0, 0])


class BuiltKinds(unittest.TestCase):
    def kind(self, **checks):
        from app.services.course import builder
        return builder._kind({'spec': 'x', 'checks': checks, 'topics': [f't{n}' for n in range(10)]}, 'reading')['checks']

    def test_numbers_a_model_sets_for_itself_are_widened(self):
        checks = self.kind(groups=1, text=[96, 144], items=[2, 5], total=[43, 65])
        self.assertEqual((checks['text'], checks['items'], checks['total']), ([48, 432], [1, 10], [1, 130]))
        self.assertNotIn('keep', checks)

    def test_single_sentences_keep_as_many_as_asked_when_one_fails_the_blind_check(self):
        checks = self.kind(groups=1, text=[0, 20], items=[10, 12], total=[10, 12])
        self.assertEqual((checks['text'], checks['keep']), ([0, 60], 10))


class TakingTurns(unittest.TestCase):
    def test_ielts_practices_name_their_second_kind(self):
        for lesson_id, kinds in (('listening-part2', ['part2', 'part2-short']), ('reading-completion', ['completion', 'completion-bank'])):
            card = lessons.load('ielts', lesson_id).cards[-1]
            self.assertEqual(card.more.every, kinds)
        self.assertIn('extract', lessons.load('ielts', 'listening-part2').cards[-1].points)


if __name__ == '__main__':
    unittest.main()
