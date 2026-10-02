import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .ai import AI, GeminiAI
from .network import request_budget
from .connectors import Connectors
from .security import Problem, RateLimit, Vault, digest, equal, origin, signature
from .store import Store
from .worker import Worker, validate_documents

ROOT = Path(__file__).resolve().parents[2]

class Application:
    def __init__(self, db_path=None, encryption_key=None, admin_token=None, ai=None, base_url=None):
        self.base_url = (base_url or os.environ.get('VOCA_BASE_URL','http://127.0.0.1:8787')).rstrip('/')
        p = urlsplit(self.base_url)
        if p.scheme != 'https' and not (p.scheme=='http' and p.hostname in ('127.0.0.1','localhost')):
            raise Problem('VOCA_BASE_URL must use HTTPS outside local development.',503)
        if p.path or p.query or p.fragment or p.username:
            raise Problem('VOCA_BASE_URL must be an origin without a path.',503)
        self.admin_token = admin_token if admin_token is not None else os.environ.get('VOCA_ADMIN_TOKEN','')
        if len(self.admin_token) < 32:
            raise Problem('Set a random VOCA_ADMIN_TOKEN of at least 32 characters. Run the setup helper.',503)
        self.store = Store(db_path or os.environ.get('VOCA_DB',str(ROOT/'data'/'voca.sqlite')),
                           Vault(encryption_key or os.environ.get('VOCA_ENCRYPTION_KEY','')))
        saved_ai = self.store.get_settings('ai')
        self.ai = ai or AI(key=saved_ai.get('key') or None,model=saved_ai.get('model') or None,
            gemini_key=saved_ai.get('gemini_key') or None,gemini_model=saved_ai.get('gemini_model') or None)
        self.connectors = Connectors(self.store,self.base_url,ROOT/'widget'/'widget.js')
        self.worker = Worker(self.store,self.ai,self.connectors,int(os.environ.get('VOCA_MAX_PAGES','300')),int(os.environ.get('VOCA_REFRESH_SECONDS','21600')))
        self.chat_limit = RateLimit(20,60)
        self.site_limit = RateLimit(250,3600)
        self.admin_limit = RateLimit(120,60)
        self.test_limit = RateLimit(10,60)
        self.event_limit = RateLimit(30,60)

    def public_site(self, site_id, request_origin):
        site = self.store.get_site(site_id)
        if not site['enabled']:
            raise Problem('This website guide is disabled.',403)
        if request_origin not in site['origins'] and request_origin != self.base_url:
            raise Problem('This website is not allowed to use the guide.',403)
        return site

class Handler(BaseHTTPRequestHandler):
    server_version = 'Voca/1.0'
    protocol_version = 'HTTP/1.1'

    @property
    def app(self):
        return self.server.app

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, fmt, *args):
        # No query strings, credentials, request bodies or conversations in access logs.
        pass

    def reply(self, body, status=200, kind='application/json', headers=None):
        raw = json.dumps(body,ensure_ascii=False).encode() if kind=='application/json' else body.encode() if isinstance(body,str) else body
        self.send_response(status)
        self.send_header('Content-Type',kind+('; charset=utf-8' if kind.startswith('text/') else ''))
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        if kind=='text/html':
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key,value in (headers or {}).items():
            self.send_header(key,value)
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise Problem('Chunked request bodies are unsupported.',400)
        try:
            size = int(self.headers.get('Content-Length','0'))
        except ValueError:
            raise Problem('Invalid request size.')
        if not 0 < size <= 2_000_000:
            raise Problem('Request exceeds the allowed size.',413)
        raw = self.rfile.read(size)
        try:
            result = json.loads(raw)
            if not isinstance(result,dict):
                raise ValueError()
        except (ValueError,UnicodeError):
            raise Problem('Send a JSON object.')
        return result,raw

    def auth(self):
        self.app.admin_limit.check(self.client_address[0])
        value = self.headers.get('Authorization','')
        if not equal(value,'Bearer '+self.app.admin_token):
            raise Problem('Administrator sign-in is required.',401)
        if self.headers.get('Origin') not in (None,self.app.base_url):
            raise Problem('Administrator requests must come from this service.',403)

    def cors(self, site):
        value = self.headers.get('Origin','')
        self.app.public_site(site['id'],value)
        return {'Access-Control-Allow-Origin':value,'Vary':'Origin','Access-Control-Allow-Headers':'Content-Type','Access-Control-Allow-Methods':'GET,POST,OPTIONS'}

    def client_ip(self):
        peer = self.client_address[0]
        if os.environ.get('VOCA_TRUST_LOCAL_PROXY')=='1' and ipaddress.ip_address(peer).is_loopback:
            try:
                return str(ipaddress.ip_address(self.headers.get('X-Real-IP','')))
            except ValueError:
                pass
        return peer

    def do_OPTIONS(self):
        self.dispatch('OPTIONS')

    def do_GET(self):
        self.dispatch('GET')

    def do_POST(self):
        self.dispatch('POST')

    def do_DELETE(self):
        self.dispatch('DELETE')

    def dispatch(self, method):
        try:
            self.route(method)
        except Problem as e:
            headers = {}
            try:
                p = urlsplit(self.path)
                q = parse_qs(p.query)
                site_id = q.get('site',[''])[0]
                if site_id and p.path.startswith('/api/widget/'):
                    headers = self.cors(self.app.store.get_site(site_id))
            except Problem:
                pass
            self.reply({'error':str(e)},e.status,headers=headers)
        except (BrokenPipeError,ConnectionResetError):
            pass
        except Exception:
            self.reply({'error':'The service could not complete this request.'},500)

    def route(self, method):
        p = urlsplit(self.path)
        path = p.path
        q = {k:v[0] for k,v in parse_qs(p.query).items()}
        if method=='GET' and path=='/health':
            return self.reply({'status':'ok'})
        static = {'/':ROOT/'admin'/'index.html','/admin':ROOT/'admin'/'index.html','/admin.js':ROOT/'admin'/'admin.js','/admin.css':ROOT/'admin'/'admin.css','/widget/v1/widget.js':ROOT/'widget'/'v1'/'widget.js','/widget/v2/widget.js':ROOT/'widget'/'widget.js'}
        if method=='GET' and path in static:
            file = static[path]
            return self.reply(file.read_bytes(),kind=mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        if path.startswith('/api/widget/'):
            site = self.app.public_site(q.get('site',''),self.headers.get('Origin',''))
            cors = self.cors(site)
            if method=='OPTIONS':
                return self.reply({},headers=cors)
            if method=='GET' and path=='/api/widget/config':
                return self.reply({'appearance':self.app.store.appearance(site['id']),'name':site['name'],'status':site['status'],'ai_configured':self.app.ai.configured,'openai_configured':bool(self.app.ai.key),'gemini_configured':bool(self.app.ai.gemini_key),'gemini_model':self.app.ai.gemini_model,'documents':site['documents'],'languages':['auto','en-US','ur-PK','ar-SA','hi-IN','es-ES','fr-FR','de-DE','pt-BR','zh-CN','ja-JP']},headers=cors)
            if method=='POST' and path=='/api/widget/handoff':
                self.app.event_limit.check(site['id']+':'+self.client_ip())
                b,_ = self.body()
                if not self.app.store.appearance(site['id'])['handoff_url']:
                    raise Problem('Contact handoff is not configured.',404)
                self.app.store.record_usage(site['id'],handoff=True)
                return self.reply({'recorded':True},headers=cors)
            if method=='POST' and path=='/api/widget/chat':
                self.app.chat_limit.check(site['id']+':'+self.client_ip())
                self.app.site_limit.check(site['id'])
                b,_ = self.body()
                message = b.get('message')
                lang = b.get('language','auto')
                history = b.get('history',[])
                if not isinstance(message,str) or not message.strip() or len(message)>2000:
                    raise Problem('Ask a question of up to 2,000 characters.')
                if not isinstance(lang,str) or not re.fullmatch(r'auto|[a-z]{2,3}(?:-[A-Za-z]{2,4})?',lang):
                    raise Problem('Invalid language.')
                if not isinstance(history,list) or len(history)>8 or any(not isinstance(h,dict) or h.get('role') not in ('user','assistant') or not isinstance(h.get('content'),str) or len(h['content'])>4000 for h in history):
                    raise Problem('Invalid conversation history.')
                started = time.monotonic()
                try:
                    result = self.app.ai.answer(self.app.store,site,message.strip(),lang,history)
                    try:
                        self.app.store.record_usage(site['id'],answer=result,seconds=time.monotonic()-started)
                    except Exception:
                        pass  # Analytics must not interrupt an answer.
                    return self.reply(result,headers=cors)
                except Problem as e:
                    try:
                        self.app.store.record_usage(site['id'],error=True)
                    except Exception:
                        pass
                    return self.reply({'error':str(e)},e.status,headers=cors)
        if path.startswith('/api/plugin/'):
            b,raw = self.body() if method=='POST' else (q,None)
            site_id = b.get('site','')
            value = self.headers.get('Authorization','')
            site = self.app.store.verify_ingest(site_id,value[7:] if value.startswith('Bearer ') else '')
            if site['platform']!='wordpress':
                raise Problem('This endpoint is for the WordPress plugin.')
            if path=='/api/plugin/exclusions' and method=='GET':
                return self.reply({'documents':[d['id'] for d in self.app.store.excluded_documents(site_id)]})
            if path=='/api/plugin/status' and method=='GET':
                return self.reply(self.app.store.get_site(site_id))
            if path=='/api/plugin/sync' and method=='POST':
                docs = validate_documents(site,b.get('documents',[]))
                if len(docs)>50:
                    raise Problem('Send no more than 50 documents per batch.')
                deleted = b.get('deleted',[])
                if not isinstance(deleted,list) or any(not isinstance(d,str) or len(d)>300 for d in deleted):
                    raise Problem('Invalid deletion list.')
                run_id = b.get('run_id')
                if run_id:
                    if not isinstance(run_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',run_id) or not isinstance(b.get('final',False),bool):
                        raise Problem('Invalid sync run.')
                    if b.get('abort') is True:
                        self.app.store.abort_snapshot(site_id,run_id)
                        return self.reply({'accepted':True,'aborted':True},202)
                    job_id = self.app.store.stage_snapshot(site_id,run_id,docs,b.get('final',False))
                else:
                    job_id = self.app.store.enqueue(site_id,'ingest',{'documents':docs,'deleted':deleted})
                return self.reply({'accepted':True,'job_id':job_id},202)
        if path.startswith('/api/admin/'):
            self.auth()
            if method=='POST' and path=='/api/admin/ai':
                b,_ = self.body()
                key = b.get('key') or self.app.ai.key
                model = b.get('model') or self.app.ai.model
                gemini_key = b.get('gemini_key') or self.app.ai.gemini_key
                gemini_model = b.get('gemini_model') or self.app.ai.gemini_model
                if not isinstance(key,str) or (key and (not key.startswith('sk-') or not 20<=len(key)<=500)):
                    raise Problem('Enter a valid OpenAI API key, or leave it blank to keep the saved key.')
                if not isinstance(gemini_key,str) or (gemini_key and not re.fullmatch(r'[a-zA-Z0-9._-]{20,500}',gemini_key)):
                    raise Problem('Enter a valid Gemini API key.')
                if not key and not gemini_key:
                    raise Problem('Enter an OpenAI or Gemini API key.')
                if any(not isinstance(m,str) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}',m) for m in (model,gemini_model)):
                    raise Problem('Enter valid model names.')
                self.app.store.set_settings('ai',{'key':key,'model':model,'gemini_key':gemini_key,'gemini_model':gemini_model})
                self.app.ai.key,self.app.ai.model = key,model
                self.app.ai.gemini_key,self.app.ai.gemini_model = gemini_key,gemini_model
                self.app.ai.fallback_until = 0
                self.app.ai.generation_fallback_until = 0
                for s in self.app.store.sites():
                    if s['enabled']:
                        self.app.store.enqueue(s['id'],'embed')
                return self.reply({'saved':True,'indexing_queued':True})
            if method=='POST' and path=='/api/admin/ai/check':
                self.app.test_limit.check('connection')
                b,_ = self.body()
                provider = b.get('provider')
                if provider not in ('openai','gemini'):
                    raise Problem('Choose OpenAI or Gemini.')
                current = self.app.ai
                client = AI(key=current.key,model=current.model,gemini_key='') if provider=='openai' else GeminiAI(current.gemini_key,current.gemini_model)
                if not client.key:
                    raise Problem('Save this provider key first.')
                started = time.monotonic()
                schema = {'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
                with request_budget():
                    client.embed(['A fictional blue cube.'])
                    result = client.call('responses',{'model':client.model,'store':False,'instructions':'Return JSON with answer set to OK.',
                        'input':'Connection test with fictional content only.','max_output_tokens':100,
                        'text':{'format':{'type':'json_schema','name':'connection_test','strict':True,'schema':schema}}})
                text = ''.join(c.get('text','') for item in result.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
                try:
                    valid = json.loads(text).get('answer') == 'OK'
                except (ValueError,AttributeError):
                    valid = False
                if not valid:
                    raise Problem('The provider responded, but its answer format was unexpected.',502)
                return self.reply({'ok':True,'provider':provider,'model':client.model,'seconds':round(time.monotonic()-started,2)})
            if method=='GET' and path=='/api/admin/status':
                return self.reply({'ai_configured':self.app.ai.configured,'openai_configured':bool(self.app.ai.key),'gemini_configured':bool(self.app.ai.gemini_key),'gemini_model':self.app.ai.gemini_model,'model':self.app.ai.model,'answer_provider':('Gemini' if self.app.ai.gemini_key and (not self.app.ai.key or time.monotonic()<self.app.ai.generation_fallback_until) else 'OpenAI'),'base_url':self.app.base_url,'shopify_configured':bool(os.environ.get('SHOPIFY_CLIENT_ID') and os.environ.get('SHOPIFY_CLIENT_SECRET')),'webflow_configured':bool(os.environ.get('WEBFLOW_CLIENT_ID') and os.environ.get('WEBFLOW_CLIENT_SECRET'))})
            if path=='/api/admin/sites':
                if method=='GET':
                    return self.reply({'sites':self.app.store.sites()})
                if method=='POST':
                    b,_ = self.body()
                    name,platform = b.get('name',''),b.get('platform','')
                    if not isinstance(name,str) or not 1<=len(name.strip())<=120 or platform not in ('wordpress','shopify','webflow'):
                        raise Problem('Enter a website name and select its platform.')
                    website = origin(b.get('website',''))
                    extra = b.get('extra_origins',[])
                    if not isinstance(extra,list) or len(extra)>10:
                        raise Problem('Invalid additional domains.')
                    extra = [origin(x) for x in extra]
                    remote_id = b.get('remote_id','')
                    if platform=='webflow' and (not isinstance(remote_id,str) or not re.fullmatch(r'[a-fA-F0-9]{24}',remote_id)):
                        raise Problem('Enter the 24-character Webflow site ID.')
                    site = self.app.store.create_site(name.strip(),platform,website,extra)
                    if remote_id:
                        self.app.store.update(site['id'],remote_id=remote_id)
                        site['remote_id'] = remote_id
                    return self.reply(site,201)
            match = re.fullmatch(r'/api/admin/sites/(site_[a-f0-9]{32})(?:/(\w+))?',path)
            if match:
                site_id,action = match.groups()
                site = self.app.store.get_site(site_id,True)
                if method=='GET':
                    if action=='appearance':
                        return self.reply(self.app.store.appearance(site_id))
                    if action=='usage':
                        return self.reply(self.app.store.usage(site_id))
                    if action=='preview':
                        return self.reply(self.app.store.document_preview(site_id,q.get('document','')))
                    if action=='documents':
                        documents=self.app.store.documents(site_id)
                        stale_after=72*3600 if site['platform']=='wordpress' else max(18*3600,self.app.worker.refresh_seconds*3)
                        now=time.time()
                        for document in documents:
                            document['fresh']=now-document['updated']<=stale_after
                        return self.reply({'documents':documents,'excluded':self.app.store.excluded_documents(site_id),'stale_after_seconds':stale_after,'truncated':len(documents)>=1000})
                    if action=='jobs':
                        return self.reply({'jobs':self.app.store.jobs(site_id)})
                    if not action:
                        return self.reply(self.app.store.get_site(site_id))
                if method=='POST':
                    b,_ = self.body()
                    if action=='appearance':
                        value = self.app.store.appearance(site_id)
                        limits={'name':80,'welcome':400,'launcher':40,'handoff_label':60,'handoff_url':1000,'color':7,'position':5}
                        if set(b)-set(limits):
                            raise Problem('Unknown appearance setting.')
                        for field,item in b.items():
                            if not isinstance(item,str) or len(item)>limits[field]:
                                raise Problem('A customization field is too long or invalid.')
                            value[field]=item.strip()
                        if not re.fullmatch(r'#[0-9a-fA-F]{6}',value['color']) or value['position'] not in ('left','right'):
                            raise Problem('Choose a valid color and position.')
                        url=value['handoff_url']
                        if url:
                            parsed=urlsplit(url)
                            email=bool(re.fullmatch(r'mailto:[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',url))
                            https=parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
                            local=parsed.scheme=='http' and origin(url)==site['origin']
                            if any(c.isspace() or ord(c)<32 for c in url) or not (email or https or local):
                                raise Problem('Use an HTTPS contact URL or a mailto email address.')
                        self.app.store.save_appearance(site_id,value)
                        return self.reply({'saved':True})
                    if action in ('exclude','include'):
                        if set(b)!={'document'}:
                            raise Problem('Send one document ID.')
                        doc_id=b.get('document')
                        if not isinstance(doc_id,str):
                            raise Problem('Choose a valid page.')
                        if action=='exclude':
                            self.app.store.exclude_document(site_id,doc_id)
                            return self.reply({'excluded':True})
                        if site['platform']!='wordpress' and not site.get('credentials',{}).get('access_token'):
                            raise Problem('Reconnect this platform before restoring and refreshing the page.',409)
                        self.app.store.include_document(site_id,doc_id)
                        if site['platform']=='wordpress':
                            return self.reply({'included':True,'refresh_required':True})
                        job_id=self.app.store.enqueue(site_id,'scan')
                        return self.reply({'included':True,'refresh_required':False,'job_id':job_id},202)
                    if action=='test':
                        self.app.test_limit.check(site_id)
                        question,language = b.get('message',''),b.get('language','auto')
                        if not isinstance(question,str) or not 1<=len(question.strip())<=2000:
                            raise Problem('Enter a question of up to 2,000 characters.')
                        if not isinstance(language,str) or not re.fullmatch(r'auto|[a-z]{2,3}(?:-[A-Za-z]{2,4})?',language):
                            raise Problem('Choose a valid language.')
                        started = time.monotonic()
                        result = self.app.ai.answer(self.app.store,site,question.strip(),language,[],debug=True)
                        result['seconds'] = round(time.monotonic()-started,2)
                        return self.reply(result)
                    if action=='connect':
                        url,cookie = self.app.connectors.start(site_id,site['platform'],b.get('shop',''))
                        secure = '; Secure' if self.app.base_url.startswith('https://') else ''
                        return self.reply({'url':url},headers={'Set-Cookie':'voca_oauth='+cookie+'; Path=/oauth/; HttpOnly; SameSite=Lax; Max-Age=600'+secure})
                    if action in ('scan','embed','install_widget'):
                        if action=='embed' and not self.app.ai.configured:
                            raise Problem('Configure an OpenAI or Gemini key before preparing AI search.',503)
                        if action=='install_widget' and site['platform']!='webflow':
                            raise Problem('Automatic widget installation is for Webflow only.')
                        return self.reply({'job_id':self.app.store.enqueue(site_id,action)},202)
                    if action=='rotate_key':
                        return self.reply({'connection_key':self.app.store.rotate_key(site_id)})
                    if action=='enabled':
                        if not isinstance(b.get('enabled'),bool):
                            raise Problem('Send an enabled value.')
                        self.app.store.update(site_id,enabled=int(b['enabled']))
                        return self.reply({'enabled':b['enabled']})
                    if action=='disconnect':
                        if site['platform']=='webflow':
                            self.app.connectors.remove_webflow(site)
                        self.app.store.update(site_id,enabled=0,credentials={},status='not_connected')
                        return self.reply({'disconnected':True,'publish_required':site['platform']=='webflow'})
                if method=='DELETE' and not action:
                    if site['platform']=='webflow' and site['credentials']:
                        self.app.connectors.remove_webflow(site)
                    self.app.store.delete_site(site_id)
                    return self.reply({'deleted':True,'publish_required':site['platform']=='webflow'})
        callback = re.fullmatch(r'/oauth/(shopify|webflow)/callback',path)
        if method=='GET' and callback:
            cookies = SimpleCookie()
            cookies.load(self.headers.get('Cookie',''))
            cookie = cookies.get('voca_oauth')
            site_id = self.app.connectors.callback(callback[1],q,cookie.value if cookie else '')
            self.app.store.enqueue(site_id,'scan')
            if callback[1]=='webflow':
                self.app.store.enqueue(site_id,'install_widget')
            return self.reply(b'',302,'text/plain',{'Location':'/admin?connected='+site_id,'Set-Cookie':'voca_oauth=; Path=/oauth/; HttpOnly; SameSite=Lax; Max-Age=0'})
        if method=='POST' and path=='/webhooks/shopify':
            b,raw = self.body()
            secret = os.environ.get('SHOPIFY_CLIENT_SECRET','')
            if not secret or not signature(secret,raw,self.headers.get('X-Shopify-Hmac-Sha256','')):
                raise Problem('Invalid webhook signature.',401)
            shop = self.headers.get('X-Shopify-Shop-Domain','')
            topic = self.headers.get('X-Shopify-Topic','')
            for s in self.app.store.sites():
                if s['platform']=='shopify' and s['shop']==shop:
                    if topic=='shop/redact':
                        self.app.store.delete_site(s['id'])
                    elif topic=='app/uninstalled':
                        self.app.store.update(s['id'],enabled=0,credentials={},status='not_connected')
                    elif topic in ('customers/data_request','customers/redact'):
                        pass  # This agent stores no customer data or visitor transcripts.
                    elif topic.endswith('/delete') and b.get('id'):
                        kind = {'products/delete':'Product','collections/delete':'Collection','pages/delete':'Page'}.get(topic)
                        if kind:
                            self.app.store.save_documents(s['id'],[],deleted=['gid://shopify/'+kind+'/'+str(b['id'])])
                        self.app.store.enqueue(s['id'],'scan')
                    else:
                        self.app.store.enqueue(s['id'],'scan')
            return self.reply({'received':True})
        if method=='POST' and path=='/webhooks/webflow':
            b,raw = self.body()
            secret = os.environ.get('WEBFLOW_CLIENT_SECRET','')
            stamp = self.headers.get('X-Webflow-Timestamp','')
            supplied = self.headers.get('X-Webflow-Signature','')
            try:
                recent = abs(time.time()*1000-int(stamp))<=300000
            except ValueError:
                recent = False
            compact = json.dumps(b,separators=(',',':'),ensure_ascii=False).encode()
            expected = hmac.new(secret.encode(),stamp.encode()+b':'+compact,hashlib.sha256).hexdigest()
            raw_expected = hmac.new(secret.encode(),stamp.encode()+b':'+raw,hashlib.sha256).hexdigest()
            if not secret or not recent or not (equal(expected,supplied) or equal(raw_expected,supplied)):
                raise Problem('Invalid webhook signature.',401)
            remote = b.get('payload',{}).get('siteId','')
            for s in self.app.store.sites():
                if s['platform']=='webflow' and s['remote_id']==remote and s['enabled']:
                    self.app.store.enqueue(s['id'],'scan')
            return self.reply({'received':True})
        raise Problem('Endpoint not found.',404)


def make_server(app, address=('127.0.0.1',8787)):
    server = ThreadingHTTPServer(address,Handler)
    server.daemon_threads = True
    server.app = app
    return server


def load_env(filename):
    if not Path(filename).exists():
        return
    for line in Path(filename).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key,value = line.split('=',1)
            if re.fullmatch(r'[A-Z][A-Z0-9_]*',key):
                os.environ.setdefault(key,value.strip().strip('"').strip("'"))


def main():
    load_env(ROOT/'.env')
    app = Application()
    app.worker.start()
    server = make_server(app,(os.environ.get('VOCA_BIND','127.0.0.1'),int(os.environ.get('PORT','8787'))))
    print('Voca service ready at '+app.base_url,flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.worker.stop_event.set()
        server.server_close()

if __name__=='__main__':
    main()
