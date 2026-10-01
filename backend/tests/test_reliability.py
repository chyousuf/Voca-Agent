import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch,Mock
from cryptography.fernet import Fernet
from voca.ai import AI,GeminiAI
from voca.network import ProviderError,RequestDeadline,request_budget,remaining,api
from voca.security import Problem,Vault
from voca.store import Store
from voca.worker import Worker
from test_agent import FakeAI,doc

class Reliability(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db',Vault(Fernet.generate_key().decode()))
        self.site=self.store.create_site('Shop','wordpress','https://shop.example.com');self.ai=FakeAI()
        self.store.save_documents(self.site['id'],self.ai.prepare(self.store,self.site['id'],[doc('old')]))
    def tearDown(self):self.tmp.cleanup()
    def test_withdrawal_survives_embedding_failure(self):
        with patch.object(self.ai,'embed',side_effect=ProviderError(503)):
            with self.assertRaises(Problem):Worker(self.store,self.ai,None).run_job({'site_id':self.site['id'],'kind':'ingest','payload':{'documents':[doc('new')],'replace':True}})
        self.assertEqual(self.store.search_chunks(self.site['id']),[])
    def test_explicit_deletion_survives_embedding_failure(self):
        with patch.object(self.ai,'embed',side_effect=ProviderError(429)):
            with self.assertRaises(Problem):Worker(self.store,self.ai,None).run_job({'site_id':self.site['id'],'kind':'ingest','payload':{'documents':[doc('new')],'deleted':['old']}})
        self.assertEqual(self.store.search_chunks(self.site['id']),[])
    def test_partial_crawl_keeps_unconfirmed_pages(self):
        self.store.retire_documents(self.site['id'],[doc('new')],replace=False)
        self.assertEqual(len(self.store.search_chunks(self.site['id'])),1)
    def test_authoritative_prefix_does_not_retire_crawl_pages(self):
        self.store.retire_documents(self.site['id'],[],authoritative_prefix='gid://shopify/')
        self.assertEqual(len(self.store.search_chunks(self.site['id'])),1)
    def test_preview_is_tenant_scoped(self):
        other=self.store.create_site('Other','wordpress','https://other.example')
        with self.assertRaises(Problem):self.store.document_preview(other['id'],'old')
        self.assertIn('$20',self.store.document_preview(self.site['id'],'old')['text'])
    def test_embed_queue_deduplicated(self):
        a=self.store.enqueue(self.site['id'],'embed');self.store.next_job()
        self.assertEqual(a,self.store.enqueue(self.site['id'],'embed'))
    def test_removed_during_generation_not_returned(self):
        original=self.ai.call
        def call(path,body):
            if path=='responses':self.store.retire_documents(self.site['id'],[],replace=True)
            return original(path,body)
        with patch.object(self.ai,'call',side_effect=call):
            with self.assertRaisesRegex(Problem,'content changed'):self.ai.answer(self.store,self.site,'shoes','auto',[])
    def test_generation_failover_for_outage_and_unavailable_model(self):
        for status in (404,503):
            client=AI(key='openai',gemini_key='gemini')
            with patch('voca.ai.api',side_effect=ProviderError(status)),patch.object(GeminiAI,'call',return_value={'output':[]}) as fallback:
                self.assertEqual(client.call('responses',{'model':'test'}),{'output':[]});fallback.assert_called_once()
    def test_auth_failure_not_hidden(self):
        client=AI(key='openai',gemini_key='gemini')
        with patch('voca.ai.api',side_effect=ProviderError(401)),patch.object(GeminiAI,'call') as fallback:
            with self.assertRaises(ProviderError):client.call('responses',{'model':'test'})
            fallback.assert_not_called()
    def test_gemini_index_can_use_openai_answer(self):
        client=AI(key='openai',gemini_key='gemini')
        self.store.save_documents(self.site['id'],[(doc('old'),[('Shoes cost $20.',[1,0],GeminiAI.EMBEDDING_MODEL)])])
        with patch.object(GeminiAI,'embed',return_value=[[1,0]]),patch('voca.ai.api',return_value={'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'answer':'$20','source_ids':['S1']})}]}]}):
            result=client.answer(self.store,self.site,'price','auto',[],debug=True)
        self.assertEqual(result['provider'],'OpenAI');self.assertEqual(result['search_model'],GeminiAI.EMBEDDING_MODEL)
    def test_both_answer_providers_fail_without_reindex(self):
        client=AI(key='openai',gemini_key='gemini')
        self.store.save_documents(self.site['id'],[(doc('old'),[('Shoes cost $20.',[1,0],client.embedding_model)])])
        with patch.object(client,'embed',return_value=[[1,0]]),patch('voca.ai.api',side_effect=ProviderError(503)):
            with self.assertRaises(Problem):client.answer(self.store,self.site,'price','auto',[])
        self.assertEqual(self.store.jobs(self.site['id']),[])
    def test_expired_deadline_prevents_network_request(self):
        with request_budget(1),patch('voca.network.time.monotonic',return_value=time.monotonic()+2),patch('voca.network.http.client.HTTPSConnection') as conn:
            with self.assertRaises(RequestDeadline):api('https://example.com',{})
            conn.assert_not_called()
        self.assertEqual(remaining(),45)
    def test_debug_excerpts_not_in_public_answers(self):
        answer=self.ai.answer(self.store,self.site,'price','auto',[])
        self.assertNotIn('excerpts',answer)
        answer=self.ai.answer(self.store,self.site,'shoes','auto',[],debug=True)
        self.assertIn('excerpts',answer)
    def test_low_relevance_abstains_without_generation(self):
        self.ai.min_relevance=.2
        self.ai.calls.clear()
        result=self.ai.answer(self.store,self.site,'unrelated topic','ur-PK',[])
        self.assertEqual(result['sources'],[])
        self.assertIn('قابلِ اعتماد معلومات',result['answer'])
        self.assertEqual([path for path,_ in self.ai.calls],['embeddings'])
    def test_answer_without_citations_is_replaced_by_abstention(self):
        original=self.ai.call
        def call(path,body):
            if path=='responses':
                return {'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps({'answer':'Unsupported claim.','source_ids':[]})}]}]}
            return original(path,body)
        with patch.object(self.ai,'call',side_effect=call):
            result=self.ai.answer(self.store,self.site,'shoes','en-US',[])
        self.assertIn('couldn’t find reliable information',result['answer'])
        self.assertEqual(result['sources'],[])
    def test_relevance_threshold_must_be_valid(self):
        with patch.dict('os.environ',{'VOCA_MIN_RELEVANCE_SCORE':'1.5'}):
            with self.assertRaisesRegex(Problem,'between 0 and 1'):
                AI(key='test')
    def test_deadline_during_response_stops_without_retry(self):
        now=[100.0]
        response=Mock(status=200)
        def chunk(n):now[0]+=2;return b'{}'
        response.read1.side_effect=chunk
        conn=Mock();conn.getresponse.return_value=response
        with patch('voca.network.time.monotonic',side_effect=lambda:now[0]),patch('voca.network.http.client.HTTPSConnection',return_value=conn) as factory:
            with request_budget(1):
                with self.assertRaises(RequestDeadline):api('https://example.com',{})
            self.assertEqual(factory.call_count,1);conn.close.assert_called_once()
