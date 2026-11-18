"""Offline shared-provider contract; no CLI, credential or network access."""
import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.services import listening_subscription as service

class SharedListeningTests(unittest.TestCase):
    def test_selection_comes_from_registry(self):
        with patch.object(service.registry,'get_feature_engine',return_value='deepseek') as resolve:
            self.assertEqual(service.selected_provider(),'deepseek')
            resolve.assert_called_once_with('listening')
    def test_schema_and_prompt_reach_shared_provider(self):
        provider=SimpleNamespace(generate_json=AsyncMock(return_value={'ok':True}))
        schema={'type':'object','properties':{'ok':{'type':'boolean'}}}
        with patch.object(service.registry,'get_feature_provider',return_value=provider) as resolve:
            self.assertEqual(asyncio.run(service.generate('synthetic',schema)),{'ok':True})
        resolve.assert_called_once_with('listening')
        provider.generate_json.assert_awaited_once_with('synthetic',schema)
    def test_failure_is_not_retried_on_another_provider(self):
        provider=SimpleNamespace(generate_json=AsyncMock(side_effect=RuntimeError('blocked')))
        with patch.object(service.registry,'get_feature_provider',return_value=provider) as resolve:
            with self.assertRaises(RuntimeError):asyncio.run(service.generate('synthetic',{}))
        self.assertEqual(resolve.call_count,1)
    def test_policy_failure_never_starts_process(self):
        with patch.object(service.registry,'get_feature_provider',side_effect=ValueError('Codex disabled')), patch('asyncio.create_subprocess_exec',side_effect=AssertionError('subprocess')):
            with self.assertRaises(ValueError):asyncio.run(service.generate('synthetic',{}))

if __name__=='__main__':unittest.main()
