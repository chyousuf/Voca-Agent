import json,unittest
import test_agent
from voca.worker import Worker

class Features(unittest.TestCase):
    setUpClass=classmethod(test_agent.HTTP.setUpClass.__func__)
    tearDownClass=classmethod(test_agent.HTTP.tearDownClass.__func__)
    req=test_agent.HTTP.req
    site=test_agent.HTTP.site
    def test_branding_validation_and_public_config(self):
        s=self.site();path='/api/admin/sites/'+s['id']+'/appearance'
        self.assertEqual(self.req('POST',path,{'name':'Brand'})[0],401)
        for data in ({'handoff_url':'javascript:alert(1)'},{'color':'red'},{'position':'top'},{'name':'x'*81}):
            self.assertEqual(self.req('POST',path,data,key=self.key)[0],400)
        self.assertEqual(self.req('POST',path,{'name':'My guide','color':'#123456','handoff_url':'https://shop.example.com/contact'},key=self.key)[0],200)
        code,body,_=self.req('GET','/api/widget/config?site='+s['id'],origin=s['origin'])
        self.assertEqual(code,200);self.assertEqual(body['appearance']['name'],'My guide')
    def test_usage_aggregates_and_tenant_isolation(self):
        s=self.site();other=self.site();store=self.app.store
        store.record_usage(s['id'],answer={'answer':'PRIVATE TEXT','sources':[{}],'provider':'Gemini'},seconds=2)
        store.record_usage(s['id'],error=True)
        store.record_usage(s['id'],handoff=True)
        result=store.usage(s['id']);t=result['totals']
        self.assertEqual((t['requests'],t['answers'],t['errors'],t['handoffs'],t['gemini'],t['average_seconds']),(2,1,1,1,1,2))
        self.assertNotIn('PRIVATE TEXT',json.dumps(result));self.assertEqual(store.usage(other['id'])['totals']['requests'],0)
        store.delete_site(s['id'])
        with store.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM usage_daily WHERE site_id=?',(s['id'],)).fetchone()[0],0)
    def test_contact_event_requires_config_and_origin(self):
        s=self.site();url='/api/widget/handoff?site='+s['id']
        self.assertEqual(self.req('POST',url,{},origin=s['origin'])[0],404)
        self.app.store.save_appearance(s['id'],{'handoff_url':'mailto:help@example.com'})
        self.assertEqual(self.req('POST',url,{},origin='https://evil.example')[0],403)
        self.assertEqual(self.req('POST',url,{},origin=s['origin'])[0],200)
        self.assertEqual(self.app.store.usage(s['id'])['totals']['handoffs'],1)
    def test_content_health_exclusion_survives_future_imports_and_can_restore(self):
        site=self.site();store=self.app.store;ai=test_agent.FakeAI();document=test_agent.doc('managed-page')
        store.save_documents(site['id'],ai.prepare(store,site['id'],[document]))
        base='/api/admin/sites/'+site['id']
        code,body,_=self.req('GET',base+'/documents',key=self.key)
        self.assertEqual(code,200);self.assertTrue(body['documents'][0]['fresh']);self.assertEqual(body['excluded'],[])
        self.assertEqual(self.req('POST',base+'/exclude',{'document':document['id']},key=self.key)[0],200)
        self.assertEqual(store.documents(site['id']),[])
        Worker(store,ai,None).run_job({'site_id':site['id'],'kind':'ingest','payload':{'documents':[document],'replace':True}})
        self.assertEqual(store.documents(site['id']),[])
        code,body,_=self.req('GET',base+'/documents',key=self.key)
        self.assertEqual(len(body['excluded']),1);self.assertEqual(body['excluded'][0]['id'],document['id'])
        code,body,_=self.req('POST',base+'/include',{'document':document['id']},key=self.key)
        self.assertEqual(code,200);self.assertTrue(body['refresh_required']);self.assertEqual(store.excluded_documents(site['id']),[])
    def test_exclusion_is_tenant_scoped(self):
        first=self.site();second=self.site();store=self.app.store;ai=test_agent.FakeAI();document=test_agent.doc('shared-id')
        store.save_documents(first['id'],ai.prepare(store,first['id'],[document]))
        store.save_documents(second['id'],ai.prepare(store,second['id'],[document]))
        self.assertEqual(self.req('POST','/api/admin/sites/'+first['id']+'/exclude',{'document':document['id']},key=self.key)[0],200)
        self.assertEqual(len(store.documents(first['id'])),0);self.assertEqual(len(store.documents(second['id'])),1)
    def test_wordpress_can_fetch_exclusion_ids_only_with_its_connection_key(self):
        site=self.site();document=test_agent.doc('excluded-page');store=self.app.store;ai=test_agent.FakeAI()
        store.save_documents(site['id'],ai.prepare(store,site['id'],[document]))
        store.exclude_document(site['id'],document['id'])
        path='/api/plugin/exclusions?site='+site['id']
        self.assertEqual(self.req('GET',path)[0],401)
        self.assertEqual(self.req('GET',path,key=site['connection_key'])[0],200)
        auth=self.req('GET',path,key=site['connection_key'])[1]
        self.assertEqual(auth['documents'],[document['id']])
