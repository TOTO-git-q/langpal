import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"backend"))
from unittest.mock import patch
import httpx
from app.services import model_catalog as catalog

class ModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_levels_are_display_only(self):
        row={'value':'opus','supportedEffortLevels':['low','high'],'default_reasoning_level':'high'}
        self.assertEqual(catalog.options(row),{'levels':[{'id':'low','label':'low'},{'id':'high','label':'high'}],'default':'high'})

    async def test_unknown_engine_has_no_catalog(self):
        for engine in ('chatgpt','codex','dsh'):
            with self.assertRaises(catalog.CatalogError): await catalog.discover(engine)

    async def test_preserves_provider_ids_labels_and_order(self):
        value={'data':[{'id':'org/model+v2@beta','name':'Custom label'},{'id':'模型/新版本','display_name':'中文模型'},{'id':'org/model+v2@beta'}]}
        self.assertEqual(catalog.parse(value),[{'id':'org/model+v2@beta','label':'Custom label'},{'id':'模型/新版本','label':'中文模型'}])

    async def test_empty_catalog_remains_empty_and_control_ids_are_rejected(self):
        self.assertEqual(catalog.parse({'data':[]}),[])
        with self.assertRaises(catalog.CatalogError): catalog.parse({'data':[{'id':'bad\nvalue'}]})

    async def test_custom_catalog_before_model_choice_uses_saved_connection_only(self):
        calls=[]
        def respond(request):
            calls.append(request)
            self.assertEqual(str(request.url),'https://saved.example/v1/models')
            self.assertEqual(request.headers['authorization'],'Bearer synthetic-provider-key')
            return httpx.Response(200,json={'data':[{'id':'any-vendor/latest+beta'}]})
        with patch.object(catalog,'_custom_config',return_value=('https://saved.example/v1','synthetic-provider-key','')) as config:
            models=await catalog.discover('custom',transport=httpx.MockTransport(respond))
        config.assert_called_once_with(require_model=False)
        self.assertEqual(models,[{'id':'any-vendor/latest+beta','label':'any-vendor/latest+beta'}])
        self.assertEqual(len(calls),1)

    async def test_redirect_and_error_do_not_expose_key(self):
        calls=[]
        def respond(request):
            calls.append(request)
            return httpx.Response(302,headers={'Location':'https://other.example/models'})
        with patch.object(catalog,'_deepseek_config',return_value=('https://saved.example','secret-value','current')):
            with self.assertRaises(catalog.CatalogError) as error:
                await catalog.discover('deepseek',transport=httpx.MockTransport(respond))
        self.assertNotIn('secret-value',str(error.exception))
        self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
