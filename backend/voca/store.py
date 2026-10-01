import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from .security import Problem, digest, token
from .content import fingerprint

class Store:
    def __init__(self, filename, vault):
        self.filename, self.vault = str(filename), vault
        Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sites (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, platform TEXT NOT NULL,
              origin TEXT NOT NULL, origins TEXT NOT NULL, ingest_hash TEXT NOT NULL,
              credentials TEXT, status TEXT DEFAULT 'not_connected', last_sync REAL DEFAULT 0,
              error TEXT DEFAULT '', enabled INTEGER DEFAULT 1, created REAL NOT NULL,
              remote_id TEXT DEFAULT '', shop TEXT DEFAULT '', script_id TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS documents (
              site_id TEXT, id TEXT, url TEXT, title TEXT, text TEXT, kind TEXT,
              hash TEXT, updated REAL, PRIMARY KEY(site_id,id),
              FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS chunks (
              site_id TEXT, doc_id TEXT, position INTEGER, text TEXT, embedding TEXT,
              model TEXT, PRIMARY KEY(site_id,doc_id,position),
              FOREIGN KEY(site_id,doc_id) REFERENCES documents(site_id,id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, site_id TEXT, kind TEXT, payload TEXT, status TEXT,
              created REAL, started REAL, finished REAL, result TEXT, error TEXT DEFAULT '',
              FOREIGN KEY(site_id) REFERENCES sites(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS oauth (
              state_hash TEXT PRIMARY KEY, cookie_hash TEXT, site_id TEXT,
              provider TEXT, expires REAL);
            CREATE TABLE IF NOT EXISTS snapshots (
              site_id TEXT, run_id TEXT, doc_id TEXT, payload TEXT,
              PRIMARY KEY(site_id,run_id,doc_id));
            CREATE TABLE IF NOT EXISTS sync_runs (
              site_id TEXT, run_id TEXT, created REAL, job_id TEXT,
              PRIMARY KEY(site_id,run_id));
            CREATE TABLE IF NOT EXISTS appearance (
              site_id TEXT PRIMARY KEY REFERENCES sites(id) ON DELETE CASCADE, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS usage_daily (
              site_id TEXT REFERENCES sites(id) ON DELETE CASCADE, day TEXT,
              requests INTEGER DEFAULT 0, answers INTEGER DEFAULT 0, errors INTEGER DEFAULT 0,
              uncited INTEGER DEFAULT 0, latency REAL DEFAULT 0, handoffs INTEGER DEFAULT 0,
              openai INTEGER DEFAULT 0, gemini INTEGER DEFAULT 0, PRIMARY KEY(site_id,day));
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
        os.chmod(filename, 0o600)

    def get_settings(self, key):
        with self.db() as c:
            row = c.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return self.vault.decrypt(row['value']) if row else {}

    def set_settings(self, key, value):
        with self.db() as c:
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key,self.vault.encrypt(value)))

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.filename, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def create_site(self, name, platform, website, extra_origins=None):
        site_id = 'site_' + uuid.uuid4().hex
        connection_key = token()
        with self.db() as c:
            c.execute('INSERT INTO sites(id,name,platform,origin,origins,ingest_hash,created) VALUES(?,?,?,?,?,?,?)',
                      (site_id, name, platform, website, json.dumps([website] + (extra_origins or [])), digest(connection_key), time.time()))
        return {**self.get_site(site_id), 'connection_key': connection_key}

    def get_site(self, site_id, private=False):
        with self.db() as c:
            row = c.execute('SELECT * FROM sites WHERE id=?', (site_id,)).fetchone()
            if not row:
                raise Problem('Website not found.', 404)
            result = dict(row)
            result['origins'] = json.loads(result['origins'])
            result['documents'] = c.execute('SELECT count(*) FROM documents WHERE site_id=?', (site_id,)).fetchone()[0]
            result['chunks'] = c.execute('SELECT count(*) FROM chunks WHERE site_id=?', (site_id,)).fetchone()[0]
            result['embedded_chunks'] = c.execute('SELECT count(*) FROM chunks WHERE site_id=? AND embedding IS NOT NULL', (site_id,)).fetchone()[0]
        with self.db() as c:
            result['search_models'] = [r[0] for r in c.execute('SELECT DISTINCT model FROM chunks WHERE site_id=? AND embedding IS NOT NULL',(site_id,))]
        if private:
            result['credentials'] = self.vault.decrypt(result['credentials'])
        else:
            result.pop('credentials', None)
            result.pop('ingest_hash', None)
        return result

    def sites(self):
        with self.db() as c:
            ids = [r['id'] for r in c.execute('SELECT id FROM sites ORDER BY created DESC')]
        return [self.get_site(i) for i in ids]

    def update(self, site_id, **fields):
        allowed = {'name','status','last_sync','error','enabled','credentials','remote_id','shop','script_id'}
        if not fields or set(fields) - allowed:
            raise ValueError('Invalid site update')
        if 'credentials' in fields:
            fields['credentials'] = self.vault.encrypt(fields['credentials'])
        with self.db() as c:
            c.execute('UPDATE sites SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?', tuple(fields.values()) + (site_id,))

    def verify_ingest(self, site_id, key):
        from .security import equal
        site = self.get_site(site_id, True)
        if not equal(site['ingest_hash'], digest(key)) or not site['enabled']:
            raise Problem('Invalid connection key.', 401)
        return site

    def rotate_key(self, site_id):
        self.get_site(site_id)
        key = token()
        with self.db() as c:
            c.execute('UPDATE sites SET ingest_hash=? WHERE id=?', (digest(key), site_id))
        return key

    def retire_documents(self, site_id, docs, replace=False, deleted=None, authoritative_prefix=None):
        """Remove confirmed withdrawn content before any external AI request."""
        keep = {d['id'] for d in docs}
        explicit = set(deleted or [])
        with self.db() as c:
            rows = c.execute('SELECT id FROM documents WHERE site_id=?', (site_id,)).fetchall()
            for row in rows:
                ident = row['id']
                covered = replace or bool(authoritative_prefix and ident.startswith(authoritative_prefix))
                if ident in explicit or (covered and ident not in keep):
                    c.execute('DELETE FROM documents WHERE site_id=? AND id=?', (site_id, ident))

    def document_preview(self, site_id, doc_id):
        with self.db() as c:
            row = c.execute('SELECT id,title,url,text,kind FROM documents WHERE site_id=? AND id=?', (site_id,doc_id)).fetchone()
        if not row:
            raise Problem('Document not found.',404)
        result = dict(row)
        result['truncated'] = len(result['text']) > 20000
        result['text'] = result['text'][:20000]
        return result

    def save_documents(self, site_id, prepared, replace=False, kinds=None, deleted=None, authoritative_prefix=None):
        """Embeddings are prepared first; failed jobs never prune or partially replace a snapshot."""
        now = time.time()
        with self.db() as c:
            for doc, sections in prepared:
                c.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(site_id,id) DO UPDATE SET url=excluded.url,title=excluded.title,text=excluded.text,kind=excluded.kind,hash=excluded.hash,updated=excluded.updated',
                          (site_id, doc['id'], doc['url'], doc['title'], doc['text'], doc.get('kind','page'), fingerprint(doc), now))
                c.execute('DELETE FROM chunks WHERE site_id=? AND doc_id=?', (site_id, doc['id']))
                c.executemany('INSERT INTO chunks VALUES(?,?,?,?,?,?)',
                              [(site_id,doc['id'],i,text,json.dumps(vector) if vector is not None else None,model) for i,(text,vector,model) in enumerate(sections)])
            for doc_id in deleted or []:
                c.execute('DELETE FROM documents WHERE site_id=? AND id=?', (site_id,doc_id))
            if replace or authoritative_prefix:
                keep = {d['id'] for d,_ in prepared}
                rows = c.execute('SELECT id,kind FROM documents WHERE site_id=?', (site_id,)).fetchall()
                for row in rows:
                    covered = replace and (kinds is None or row['kind'] in kinds)
                    covered = covered or bool(authoritative_prefix and row['id'].startswith(authoritative_prefix))
                    if row['id'] not in keep and covered:
                        c.execute('DELETE FROM documents WHERE site_id=? AND id=?', (site_id,row['id']))
            c.execute("UPDATE sites SET last_sync=?,status='indexed',error='' WHERE id=?", (now, site_id))

    def existing(self, site_id, doc_id):
        with self.db() as c:
            d = c.execute('SELECT hash FROM documents WHERE site_id=? AND id=?', (site_id,doc_id)).fetchone()
            sections = c.execute('SELECT text,embedding,model FROM chunks WHERE site_id=? AND doc_id=? ORDER BY position', (site_id,doc_id)).fetchall()
        return (d['hash'] if d else None), [(r['text'],json.loads(r['embedding']) if r['embedding'] else None,r['model']) for r in sections]

    def search_chunks(self, site_id):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT c.*,d.title,d.url FROM chunks c JOIN documents d ON c.site_id=d.site_id AND c.doc_id=d.id WHERE c.site_id=?', (site_id,))]

    def documents(self, site_id):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT id,url,title,kind,updated FROM documents WHERE site_id=? ORDER BY title LIMIT 1000', (site_id,))]

    def enqueue(self, site_id, kind, payload=None):
        with self.db() as c:
            if kind in ('scan','embed'):
                old = c.execute("SELECT id FROM jobs WHERE site_id=? AND kind=? AND status IN ('queued','running')", (site_id,kind)).fetchone()
                if old:
                    return old['id']
            job_id = 'job_' + uuid.uuid4().hex
            c.execute('INSERT INTO jobs(id,site_id,kind,payload,status,created) VALUES(?,?,?,?,?,?)',
                      (job_id,site_id,kind,json.dumps(payload or {}),'queued',time.time()))
        return job_id

    def next_job(self):
        with self.db() as c:
            row = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                return None
            c.execute("UPDATE jobs SET status='running',started=? WHERE id=?", (time.time(),row['id']))
            result = dict(row)
            result['payload'] = json.loads(result['payload'])
            return result

    def finish_job(self, job_id, result=None, error=''):
        with self.db() as c:
            c.execute('UPDATE jobs SET status=?,finished=?,result=?,error=?,payload=? WHERE id=?',
                      ('failed' if error else 'succeeded',time.time(),json.dumps(result or {}),error,'{}',job_id))

    def jobs(self, site_id):
        with self.db() as c:
            return [dict(r) for r in c.execute('SELECT id,kind,status,created,finished,result,error FROM jobs WHERE site_id=? ORDER BY created DESC LIMIT 20', (site_id,))]

    def stage_snapshot(self, site_id, run_id, docs, final=False):
        with self.db() as c:
            prior = c.execute('SELECT job_id FROM sync_runs WHERE site_id=? AND run_id=?', (site_id,run_id)).fetchone()
            if prior and prior['job_id']:
                return prior['job_id']
            c.execute('INSERT OR IGNORE INTO sync_runs VALUES(?,?,?,NULL)', (site_id,run_id,time.time()))
            for d in docs:
                c.execute('INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)', (site_id,run_id,d['id'],json.dumps(d)))
            if final:
                documents = [json.loads(r[0]) for r in c.execute('SELECT payload FROM snapshots WHERE site_id=? AND run_id=?', (site_id,run_id))]
                job_id = 'job_' + uuid.uuid4().hex
                c.execute('INSERT INTO jobs(id,site_id,kind,payload,status,created) VALUES(?,?,?,?,?,?)',
                          (job_id,site_id,'ingest',json.dumps({'documents':documents,'replace':True}),'queued',time.time()))
                c.execute('DELETE FROM snapshots WHERE site_id=? AND run_id=?', (site_id,run_id))
                c.execute('UPDATE sync_runs SET job_id=? WHERE site_id=? AND run_id=?', (job_id,site_id,run_id))
                return job_id
        return None

    def abort_snapshot(self, site_id, run_id):
        with self.db() as c:
            c.execute('DELETE FROM snapshots WHERE site_id=? AND run_id=?', (site_id,run_id))
            c.execute('DELETE FROM sync_runs WHERE site_id=? AND run_id=? AND job_id IS NULL', (site_id,run_id))

    def oauth_start(self, site_id, provider, state, cookie):
        with self.db() as c:
            c.execute('DELETE FROM oauth WHERE expires<?', (time.time(),))
            c.execute('INSERT INTO oauth VALUES(?,?,?,?,?)', (digest(state),digest(cookie),site_id,provider,time.time()+600))

    def oauth_consume(self, provider, state, cookie):
        from .security import equal
        with self.db() as c:
            row = c.execute('SELECT * FROM oauth WHERE state_hash=?', (digest(state),)).fetchone()
            if not row or row['provider'] != provider or row['expires'] < time.time() or not equal(row['cookie_hash'],digest(cookie)):
                raise Problem('Authorization expired or came from another browser. Connect again.', 403)
            c.execute('DELETE FROM oauth WHERE state_hash=?', (digest(state),))
            return row['site_id']

    def delete_site(self, site_id):
        with self.db() as c:
            c.execute('DELETE FROM oauth WHERE site_id=?', (site_id,))
            c.execute('DELETE FROM snapshots WHERE site_id=?', (site_id,))
            c.execute('DELETE FROM sync_runs WHERE site_id=?', (site_id,))
            c.execute('DELETE FROM sites WHERE id=?', (site_id,))

    def appearance(self, site_id):
        self.get_site(site_id)
        defaults = {'name':'','color':'#3647e9','welcome':'','launcher':'','position':'right','handoff_label':'Contact our team','handoff_url':''}
        with self.db() as c:
            row = c.execute('SELECT value FROM appearance WHERE site_id=?',(site_id,)).fetchone()
        return defaults | (json.loads(row['value']) if row else {})

    def save_appearance(self, site_id, value):
        self.get_site(site_id)
        with self.db() as c:
            c.execute('INSERT INTO appearance VALUES(?,?) ON CONFLICT(site_id) DO UPDATE SET value=excluded.value',(site_id,json.dumps(value)))

    def record_usage(self, site_id, answer=None, error=False, seconds=0, handoff=False):
        # Aggregates only: no questions, answers, IPs, visitor IDs, or contact details.
        with self.db() as c:
            c.execute("DELETE FROM usage_daily WHERE day<date('now','-90 days')")
            c.execute("INSERT OR IGNORE INTO usage_daily(site_id,day) VALUES(?,date('now'))",(site_id,))
            c.execute("""UPDATE usage_daily SET requests=requests+?,answers=answers+?,errors=errors+?,
                uncited=uncited+?,latency=latency+?,handoffs=handoffs+?,openai=openai+?,gemini=gemini+?
                WHERE site_id=? AND day=date('now')""",
                (int(not handoff),int(answer is not None),int(error),int(answer is not None and not answer.get('sources')),max(0,seconds) if answer is not None else 0,int(handoff),
                 int(answer is not None and answer.get('provider')=='OpenAI'),int(answer is not None and answer.get('provider')=='Gemini'),site_id))

    def usage(self, site_id):
        self.get_site(site_id)
        with self.db() as c:
            rows=[dict(r) for r in c.execute("SELECT day,requests,answers,errors,uncited,latency,handoffs,openai,gemini FROM usage_daily WHERE site_id=? AND day>=date('now','-29 days') ORDER BY day DESC",(site_id,))]
        totals={key:sum(r[key] for r in rows) for key in ('requests','answers','errors','uncited','latency','handoffs','openai','gemini')}
        totals['average_seconds']=round(totals['latency']/totals['answers'],2) if totals['answers'] else 0
        return {'days':30,'timezone':'UTC','totals':totals,'daily':rows}
