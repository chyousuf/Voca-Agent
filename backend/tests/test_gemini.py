import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from cryptography.fernet import Fernet
from voca.ai import AI, GeminiAI
from voca.network import ProviderError
from voca.security import Problem, Vault
from voca.store import Store

class GeminiFallback(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'db',Vault(Fernet.generate_key().decode()))
        self.site=self.store.create_site('Shop','wordpress','https://shop.example.com')
        self.docs=[{'id':'one','url':'https://shop.example.com/one','title':'Shoes','text':'Blue shoes cost $20.','kind':'page'}]
        self.ai=AI(key='sk-test',gemini_key='test-gemini')
    def tearDown(self):self.tmp.cleanup()
    def fake(self,url,body,headers):
        if 'api.openai.com' in url:raise ProviderError(429)
        self.assertEqual(headers,{'x-goog-api-key':'test-gemini'})
        if url.endswith(':batchEmbedContents'):
            return {'embeddings':[{'values':[1.,0.]} for _ in body['requests']]}
        return {'candidates':[{'content':{'parts':[{'text':json.dumps({'answer':'Shoes cost $20.','source_ids':['S1','invalid']})}]}}]}
    def test_index_and_answer_fallback(self):
        with patch('voca.ai.api',side_effect=self.fake) as mocked:
            self.store.save_documents(self.site['id'],self.ai.prepare(self.store,self.site['id'],self.docs))
            self.assertTrue(all(r['model']==GeminiAI.EMBEDDING_MODEL for r in self.store.search_chunks(self.site['id'])))
            result=self.ai.answer(self.store,self.site,'shoes price','ur-PK',[])
            self.assertEqual(result['sources'],[{'title':'Shoes','url':'https://shop.example.com/one'}])
            self.assertEqual(sum('api.openai.com' in c.args[0] for c in mocked.call_args_list),2)
    def test_auth_error_does_not_trigger_fallback(self):
        with patch('voca.ai.api',side_effect=ProviderError(401)) as mocked:
            with self.assertRaises(ProviderError):self.ai.prepare(self.store,self.site['id'],self.docs)
            self.assertEqual(mocked.call_count,1)
    def test_missing_fallback_key_surfaces_limit(self):
        self.ai.gemini_key=''
        with patch('voca.ai.api',side_effect=ProviderError(429)):
            with self.assertRaises(ProviderError):self.ai.prepare(self.store,self.site['id'],self.docs)
    def test_gemini_only(self):
        self.ai.key=''
        with patch('voca.ai.api',side_effect=self.fake) as mocked:
            self.ai.prepare(self.store,self.site['id'],self.docs)
            self.assertTrue(all('googleapis.com' in c.args[0] for c in mocked.call_args_list))
    def test_query_limit_queues_one_rebuild_and_preserves_index(self):
        prepared=[(self.docs[0],[('Shoes cost $20.',[1.,0.],self.ai.embedding_model)])]
        self.store.save_documents(self.site['id'],prepared)
        with patch('voca.ai.api',side_effect=ProviderError(429)):
            for _ in range(2):
                with self.assertRaisesRegex(Problem,'Switching website search'):
                    self.ai.answer(self.store,self.site,'price','auto',[])
        self.assertEqual(len(self.store.jobs(self.site['id'])),1)
        self.assertEqual(self.store.search_chunks(self.site['id'])[0]['model'],self.ai.embedding_model)
    def test_generation_limit_reuses_retrieved_context(self):
        self.store.save_documents(self.site['id'],[(self.docs[0],[('Shoes cost $20.',[1.,0.],self.ai.embedding_model)])])
        def fake(url,body,headers):
            if url.endswith('/embeddings'):return {'data':[{'index':0,'embedding':[1.,0.]}]}
            return self.fake(url,body,headers)
        with patch('voca.ai.api',side_effect=fake):
            result=self.ai.answer(self.store,self.site,'price','auto',[])
        self.assertEqual(result['answer'],'Shoes cost $20.')
        self.assertEqual(self.store.jobs(self.site['id']),[])
    def test_gemini_limit_is_not_retried_as_openai(self):
        self.ai.key=''
        with patch('voca.ai.api',side_effect=ProviderError(429)):
            with self.assertRaisesRegex(Problem,'Gemini also reached'):
                self.ai.prepare(self.store,self.site['id'],self.docs)
    def test_saved_gemini_index_is_reused_after_restart(self):
        with patch('voca.ai.api',side_effect=self.fake):
            self.store.save_documents(self.site['id'],self.ai.prepare(self.store,self.site['id'],self.docs))
        fresh=AI(key='sk-test',gemini_key='test-gemini')
        with patch('voca.ai.api') as mocked:
            result=fresh.prepare(self.store,self.site['id'],self.docs)
            mocked.assert_not_called()
            self.assertEqual(result[0][1][0][2],GeminiAI.EMBEDDING_MODEL)
