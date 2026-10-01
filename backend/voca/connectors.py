import base64
import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode, urlsplit
from .content import clean, crawl
from .network import api
from .security import Problem, equal, origin, token, valid_shop

SHOPIFY_SCOPES = 'read_products,read_content'
WEBFLOW_SCOPES = 'sites:read,custom_code:read,custom_code:write,sites:write'

class Connectors:
    def __init__(self, store, service_url, widget_file):
        self.store, self.url, self.widget_file = store, service_url, widget_file

    def start(self, site_id, provider, shop=''):
        site = self.store.get_site(site_id)
        if site['platform'] != provider or provider not in ('shopify','webflow'):
            raise Problem('Wrong platform for this website.')
        client = os.environ.get(provider.upper()+'_CLIENT_ID','')
        secret = os.environ.get(provider.upper()+'_CLIENT_SECRET','')
        if not client or not secret:
            raise Problem('The platform app credentials have not been configured.',503)
        state, cookie = token(), token()
        if provider == 'shopify':
            shop = valid_shop(shop)
            self.store.update(site_id,shop=shop)
            auth = 'https://' + shop + '/admin/oauth/authorize'
            scopes = SHOPIFY_SCOPES
        else:
            if not re.fullmatch(r'[a-fA-F0-9]{24}',site['remote_id']):
                raise Problem('Enter the Webflow site ID before connecting.')
            auth = 'https://webflow.com/oauth/authorize'
            scopes = WEBFLOW_SCOPES
        self.store.oauth_start(site_id,provider,state,cookie)
        query = {'client_id':client,'scope':scopes,'redirect_uri':self.url+'/oauth/'+provider+'/callback','state':state,'response_type':'code'}
        return auth+'?'+urlencode(query), cookie

    def callback(self, provider, params, cookie):
        if provider not in ('shopify','webflow'):
            raise Problem('Unknown authorization provider.')
        if not params.get('code') or not params.get('state'):
            raise Problem('Authorization was cancelled or returned no code.')
        secret = os.environ.get(provider.upper()+'_CLIENT_SECRET','')
        client = os.environ.get(provider.upper()+'_CLIENT_ID','')
        if not client or not secret:
            raise Problem('Platform credentials are not configured.',503)
        if provider == 'shopify':
            shop = valid_shop(params.get('shop',''))
            message = '&'.join(k+'='+params[k] for k in sorted(params) if k not in ('hmac','signature'))
            expected = hmac.new(secret.encode(),message.encode(),hashlib.sha256).hexdigest()
            if not equal(expected,params.get('hmac','')):
                raise Problem('Invalid Shopify authorization signature.',403)
        site_id = self.store.oauth_consume(provider,params['state'],cookie)
        site = self.store.get_site(site_id)
        if provider == 'shopify':
            if shop != site['shop']:
                raise Problem('The authorized store does not match the selected website.',403)
            credentials = api('https://'+shop+'/admin/oauth/access_token',{'client_id':client,'client_secret':secret,'code':params['code'],'expiring':1})
            granted = set(credentials.get('scope','').split(','))
            if not all(s in granted or s.replace('read_','write_') in granted for s in SHOPIFY_SCOPES.split(',')):
                raise Problem('Required Shopify permissions were not granted.',403)
            credentials['expires_at'] = time.time()+credentials['expires_in'] if credentials.get('expires_in') else None
            self.store.update(site_id,credentials=credentials,status='connected')
            authorized = self.shop_query(self.store.get_site(site_id,True),'query {shop {primaryDomain {url}}}')
            if origin(authorized['shop']['primaryDomain']['url']) != site['origin']:
                self.store.update(site_id,credentials={},status='not_connected')
                raise Problem('Use this Shopify store’s primary storefront domain when adding the website.',403)
        else:
            credentials = api('https://api.webflow.com/oauth/access_token',{'client_id':client,'client_secret':secret,'code':params['code'],'grant_type':'authorization_code','redirect_uri':self.url+'/oauth/webflow/callback'})
            if not credentials.get('access_token'):
                raise Problem('Webflow authorization returned no access token.',502)
            headers = {'Authorization':'Bearer '+credentials['access_token']}
            remote = api('https://api.webflow.com/v2/sites/'+site['remote_id'],headers=headers)
            domains = api('https://api.webflow.com/v2/sites/'+site['remote_id']+'/custom_domains',headers=headers)
            if isinstance(domains,dict):
                domains = domains.get('customDomains',domains.get('domains',[]))
            allowed = {remote.get('shortName','')+'.webflow.io'} | {d.get('url','').replace('https://','').rstrip('/') for d in domains}
            if urlsplit(site['origin']).hostname not in allowed:
                raise Problem('The website domain does not belong to the authorized Webflow site.',403)
            self.store.update(site_id,credentials=credentials,status='connected')
        return site_id

    def shop_token(self, site):
        credentials = site['credentials']
        if not credentials.get('access_token'):
            raise Problem('Connect Shopify before scanning.',503)
        if credentials.get('expires_at') and time.time() >= credentials['expires_at']-60:
            if not credentials.get('refresh_token'):
                raise Problem('Reconnect Shopify to renew its access.',503)
            result = api('https://'+valid_shop(site['shop'])+'/admin/oauth/access_token',{
                'client_id':os.environ.get('SHOPIFY_CLIENT_ID',''),'client_secret':os.environ.get('SHOPIFY_CLIENT_SECRET',''),
                'grant_type':'refresh_token','refresh_token':credentials['refresh_token']})
            if not result.get('access_token') or not result.get('refresh_token'):
                raise Problem('Reconnect Shopify to renew its access.',503)
            result['expires_at'] = time.time()+result['expires_in'] if result.get('expires_in') else None
            self.store.update(site['id'],credentials=result)
            site['credentials'] = credentials = result
        return credentials['access_token']

    def shop_query(self, site, query, variables=None):
        version = os.environ.get('SHOPIFY_API_VERSION','2026-10')
        if not re.fullmatch(r'20\d\d-(01|04|07|10)',version):
            raise Problem('Invalid Shopify API version.',503)
        result = api('https://'+valid_shop(site['shop'])+'/admin/api/'+version+'/graphql.json',
                     {'query':query,'variables':variables or {}},{'X-Shopify-Access-Token':self.shop_token(site)})
        if result.get('errors'):
            raise Problem('Shopify rejected a content query. Check app scopes and the pinned API version.',502)
        return result['data']

    def shop_nodes(self, site, field, fields, query=''):
        after = None
        for _ in range(500):
            gql = 'query($after:String){'+field+'(first:50,after:$after'+query+'){nodes{'+fields+'}pageInfo{hasNextPage endCursor}}}'
            result = self.shop_query(site,gql,{'after':after})[field]
            yield from result['nodes']
            if not result['pageInfo']['hasNextPage']:
                return
            after = result['pageInfo']['endCursor']
            time.sleep(.25)
        raise Problem('Store import exceeded 25,000 records. Increase the importer limit for this store.',502)

    def scan_shopify(self, site):
        docs = []
        info = self.shop_query(site,'query {shop {currencyCode shopPolicies {id title body url}}}')['shop']
        currency = info['currencyCode']
        for p in self.shop_nodes(site,'products','id title descriptionHtml onlineStoreUrl status priceRangeV2 {minVariantPrice {amount currencyCode} maxVariantPrice {amount currencyCode}}',',query:"status:active"'):
            if not p.get('onlineStoreUrl') or p['status'] != 'ACTIVE':
                continue
            prices = p['priceRangeV2']
            text = clean(p['descriptionHtml'])+'\nPrice range: '+prices['minVariantPrice']['amount']+'–'+prices['maxVariantPrice']['amount']+' '+currency+'. Verify current price and availability on the product page.'
            docs.append({'id':p['id'],'url':p['onlineStoreUrl'],'title':p['title'],'text':text,'kind':'product'})
        for p in self.shop_nodes(site,'collections','id title descriptionHtml onlineStoreUrl'):
            if p.get('onlineStoreUrl'):
                docs.append({'id':p['id'],'url':p['onlineStoreUrl'],'title':p['title'],'text':clean(p['descriptionHtml']) or p['title'],'kind':'collection'})
        for p in self.shop_nodes(site,'pages','id title body handle isPublished'):
            if p['isPublished']:
                docs.append({'id':p['id'],'url':site['origin']+'/pages/'+p['handle'],'title':p['title'],'text':clean(p['body']),'kind':'page'})
        for p in info['shopPolicies']:
            if p['body']:
                docs.append({'id':p['id'],'url':p['url'],'title':p['title'],'text':clean(p['body']),'kind':'policy'})
        # Published storefront traversal picks up articles, FAQs and theme-rendered content.
        try:
            pages, report = crawl(site['origin'],int(os.environ.get('VOCA_MAX_PAGES','300')))
            known = {d['url'].rstrip('/') for d in docs}
            docs.extend(d for d in pages if d['url'].rstrip('/') not in known)
        except Problem as e:
            report = {'pages':0,'errors':[{'error':str(e)}],'limit_reached':False,'partial':True}
        return docs,report

    def webflow_api(self, site, path, body=None, method=None):
        key = site['credentials'].get('access_token')
        if not key:
            raise Problem('Connect Webflow before installing or scanning.',503)
        return api('https://api.webflow.com/v2/'+path,body,{'Authorization':'Bearer '+key},method)

    def install_webflow(self, site):
        # Publish is deliberately left to the owner because it publishes all staged changes.
        content = self.widget_file.read_bytes()
        name = 'Voca-'+site['id'][-8:]
        version = '1.1.0'
        path = 'sites/'+site['remote_id']
        scripts = self.webflow_api(site,path+'/registered_scripts')
        entries = scripts.get('registeredScripts',scripts.get('scripts',[])) if isinstance(scripts,dict) else scripts
        existing = next((s for s in entries if s.get('displayName')==name and s.get('version')==version),None)
        script = existing or self.webflow_api(site,path+'/registered_scripts/hosted',{
            'displayName':name,'version':version,'canCopy':False,
            'hostedLocation':self.url+'/widget/v2/widget.js',
            'integrityHash':'sha256-'+base64.b64encode(hashlib.sha256(content).digest()).decode()})
        previous = self.webflow_api(site,path+'/custom_code').get('scripts',[])
        applied = [s for s in previous if s.get('id') not in (script['id'],site.get('script_id'))]
        applied.append({'id':script['id'],'location':'footer','version':version,'attributes':{'data-voca-site':site['id'],'data-voca-api':self.url}})
        self.webflow_api(site,path+'/custom_code',{'scripts':applied},'PUT')
        self.store.update(site['id'],script_id=script['id'])
        return {'installed':True,'publish_required':True,'message':'The guide is added. Publish your Webflow site when ready.'}

    def remove_webflow(self, site):
        if not site['script_id']:
            return
        path = 'sites/'+site['remote_id']+'/custom_code'
        scripts = self.webflow_api(site,path).get('scripts',[])
        self.webflow_api(site,path,{'scripts':[s for s in scripts if s.get('id') != site['script_id']]},'PUT')
        self.store.update(site['id'],script_id='')
