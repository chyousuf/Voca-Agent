import threading
import time
from .content import crawl
from .security import Problem, origin


def validate_documents(site, docs):
    if not isinstance(docs,list) or len(docs) > 25000:
        raise Problem('Invalid document batch.')
    result, ids = [], set()
    for d in docs:
        if not isinstance(d,dict) or not all(isinstance(d.get(k),str) for k in ('id','url','title','text')):
            raise Problem('Each document needs an ID, URL, title and text.')
        if not d['id'] or len(d['id']) > 300 or len(d['title']) > 500 or len(d['text']) > 100000:
            raise Problem('Document exceeds size limits.')
        if origin(d['url']) not in site['origins']:
            raise Problem('Document URL is outside this website.')
        if d['id'] in ids:
            raise Problem('Duplicate document ID.')
        ids.add(d['id'])
        result.append({k:d[k] for k in ('id','url','title','text')} | {'kind':str(d.get('kind','page'))[:30]})
    return result


class Worker:
    def __init__(self, store, ai, connectors, max_pages=300, refresh_seconds=21600):
        self.store,self.ai,self.connectors = store,ai,connectors
        self.max_pages,self.refresh_seconds = max_pages,refresh_seconds
        self.stop_event = threading.Event()
        self.last_schedule = 0

    def run_job(self, job):
        site = self.store.get_site(job['site_id'],True)
        if not site['enabled']:
            raise Problem('This guide is disabled.')
        if job['kind'] == 'scan':
            self.store.update(site['id'],status='scanning',error='')
            if site['platform']=='shopify':
                docs, report = self.connectors.scan_shopify(site)
            elif site['platform']=='webflow':
                if not site['credentials'].get('access_token'):
                    raise Problem('Connect Webflow before scanning.',503)
                docs, report = crawl(site['origin'],self.max_pages)
            else:
                raise Problem('WordPress content sync is managed by the installed plugin.')
            docs = validate_documents(site,docs)
            partial = report.get('limit_reached') or report.get('errors') or report.get('partial')
            self.store.retire_documents(site['id'],docs,replace=not partial,
                authoritative_prefix='gid://shopify/' if site['platform']=='shopify' else None)
            self.store.save_documents(site['id'],self.ai.prepare(self.store,site['id'],docs),replace=not partial,
                authoritative_prefix='gid://shopify/' if site['platform']=='shopify' else None)
            if partial:
                self.store.update(site['id'],status='partial',error='Some pages were unavailable or the scan limit was reached. Previous content was retained; inspect the scan report.')
            return report | {'documents':len(docs),'ai_configured':self.ai.configured}
        if job['kind']=='ingest':
            docs = validate_documents(site,job['payload'].get('documents',[]))
            self.store.retire_documents(site['id'],docs,replace=bool(job['payload'].get('replace')),deleted=job['payload'].get('deleted',[]))
            self.store.save_documents(site['id'],self.ai.prepare(self.store,site['id'],docs),
                                      replace=bool(job['payload'].get('replace')),deleted=job['payload'].get('deleted',[]))
            return {'documents':len(docs),'ai_configured':self.ai.configured}
        if job['kind']=='embed':
            with self.store.db() as c:
                docs = [dict(r) for r in c.execute('SELECT * FROM documents WHERE site_id=?',(site['id'],))]
            self.store.save_documents(site['id'],self.ai.prepare(self.store,site['id'],docs))
            return {'documents':len(docs),'ai_configured':self.ai.configured}
        if job['kind']=='install_widget':
            return self.connectors.install_webflow(site)
        raise Problem('Unknown job type.')

    def loop(self):
        while not self.stop_event.is_set():
            try:
                if time.time()-self.last_schedule > 60:
                    self.last_schedule = time.time()
                    for s in self.store.sites():
                        retry = True
                        if s['status']=='error':
                            recent = self.store.jobs(s['id'])
                            retry = not recent or time.time()-(recent[0]['finished'] or recent[0]['created'])>900
                        if s['enabled'] and s['platform'] in ('shopify','webflow') and s['status']!='not_connected' and retry and time.time()-s['last_sync'] > self.refresh_seconds:
                            self.store.enqueue(s['id'],'scan')
                job = self.store.next_job()
                if job:
                    try:
                        result = self.run_job(job)
                        self.store.finish_job(job['id'],result)
                    except Exception as e:
                        error = str(e) if isinstance(e,Problem) else 'Import failed. Check service logs and reconnect the website if needed.'
                        self.store.finish_job(job['id'],error=error)
                        self.store.update(job['site_id'],status='error',error=error)
                else:
                    self.stop_event.wait(1)
            except Exception:
                self.stop_event.wait(3)

    def start(self):
        thread = threading.Thread(target=self.loop,daemon=True,name='voca-import-worker')
        thread.start()
        return thread
