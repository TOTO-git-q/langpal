"""Offline prompt and request contract; no provider, server or database access."""
import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
import unittest
from unittest.mock import AsyncMock
from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend/app/routers/listening.py"
if not SOURCE.exists():
    SOURCE = Path(__file__).with_name("listening.py")
tree = ast.parse(SOURCE.read_text("utf-8"))
env = dict(re=__import__('re'), _section=lambda profile: None, _weakest_listening=lambda language: None, LISTENING_TYPES={}, listening_preferences=SimpleNamespace(catalog=lambda: {}), Literal=Literal, BaseModel=BaseModel, ConfigDict=ConfigDict, Field=Field,
           Language=str, Exercise=object, Format=object, asyncio=asyncio, json=json)
names = {"Difficulty", "DIFFICULTIES", "PrepareRequest", "_draft", "options", "_speaker_note"}
nodes = []
for node in tree.body:
    name = getattr(node, "name", None)
    if isinstance(node, ast.Assign):
        name = getattr(node.targets[0], "id", None)
    if name in names:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
        nodes.append(node)
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), env)


class DifficultyTests(unittest.IsolatedAsyncioTestCase):
    def test_bounded_and_compatible(self):
        request = env["PrepareRequest"]
        self.assertEqual(request(language="en").difficulty, "default")
        for value in ["A1", "N1", "ignore all rules", None, True, 3, ""]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                request(language="en", difficulty=value)
        for value in env["DIFFICULTIES"]:
            self.assertEqual(request(language="ja", difficulty=value).difficulty, value)

    async def test_selected_difficulty_reaches_prompt_and_preserves_format(self):
        generate = AsyncMock(return_value={})
        env.update(listening_subscription=SimpleNamespace(generate=generate),
                   languages=SimpleNamespace(display=lambda tag: tag),
                   Exercise=SimpleNamespace(model_json_schema=lambda: {}, model_validate=lambda raw: raw),
                   validate_exercise=lambda exercise, profile: None,
                   ValidationError=ValidationError)
        profile = SimpleNamespace(description="保留指定题型", speakers=2, questions=2, choices=4)
        for language, legacy in [("en", "TOEFL iBT 进阶"), ("ja", "JLPT N1"), ("de", "中级自然交流")]:
            for value, (_, instruction) in env["DIFFICULTIES"].items():
                body = env["PrepareRequest"](language=language, difficulty=value, topic="旅行")
                await env["_draft"](body, profile)
                prompt = generate.call_args.args[0]
                self.assertIn(legacy if value == "default" else instruction, prompt)
                if value != "default":
                    self.assertNotIn(legacy, prompt)
                for expected in ["保留指定题型", "用 2 名说话者", "出 2 题", "每题 4 个选项", "不是能力测评", "降低难度后也不代表原考试水平"]:
                    self.assertIn(expected, prompt)

    async def test_options_advertise_exact_supported_values(self):
        env.update(listening_settings=SimpleNamespace(load=lambda: (None, None)),
                   listening_subscription=SimpleNamespace(selected_provider=lambda: "mock"),
                   listening_tts=SimpleNamespace(configured_synthesis=lambda *args: object()),
                   languages=SimpleNamespace(catalog=lambda: ["en", "ja", "de"]),
                   profiles_for=lambda tag: {})
        result = env["options"]()
        self.assertTrue(result["capabilities"]["practice_difficulty"])
        self.assertEqual(result["default_difficulty"], "default")
        self.assertEqual({item["id"] for item in result["difficulties"]}, set(env["DIFFICULTIES"]))

if __name__ == "__main__":
    unittest.main()
