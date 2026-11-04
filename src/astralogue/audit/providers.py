"""Explicit local OpenAI-compatible or budgeted DeepSeek requests; never logs keys."""
import ipaddress
import json
import time
from pathlib import Path
import urllib.parse
import urllib.request
from astralogue.http import verified_opener

class ProviderPreflightError(ValueError):
    """No HTTP request was sent."""


class Provider:
    def __init__(self,endpoint,model,name='local',key_file=None,input_price=None,output_price=None,revision=None):
        self.endpoint=endpoint.rstrip('/');self.model=model;self.name=name;self.key_file=key_file
        self.input_price=input_price;self.output_price=output_price
        self.revision=revision
        url=urllib.parse.urlparse(endpoint)
        if name=='local':
            if url.hostname not in {'localhost','127.0.0.1','::1'}:raise ValueError('Local provider must use loopback')
        elif name!='deepseek' or url.scheme!='https' or url.hostname!='api.deepseek.com':raise ValueError('Unsupported remote provider endpoint')
    def run(self,messages,max_tokens=2048,response_schema=None):
        headers={'Content-Type':'application/json'}
        if self.name=='deepseek':
            if self.key_file is None:raise ValueError('Explicit API key file required')
            if Path(self.key_file).resolve().name.upper()!='DEEPSEEK.KEY':raise ValueError('Only the explicitly designated DEEPSEEK.key credential file is supported')
            # Contents stay in this process's HTTP Authorization header only.
            try:key=Path(self.key_file).read_text(encoding='utf-8-sig').strip()
            except (OSError,UnicodeError) as e:raise ProviderPreflightError('API credential could not be loaded') from None
            if not key or '\n' in key:raise ProviderPreflightError('Invalid API key file format')
            headers['Authorization']='Bearer '+key
        payload={'model':self.model,'messages':messages,'max_tokens':max_tokens,'temperature':0,
                 'response_format':{'type':'json_object'}}
        if self.name=='deepseek':
            payload.pop('temperature');payload.update(thinking={'type':'enabled'},reasoning_effort='low')
        elif response_schema:
            payload['response_format']={'type':'json_schema','json_schema':{'name':'narrative_audit','strict':True,'schema':response_schema}}
        body=json.dumps(payload).encode()
        start=time.perf_counter()
        req=urllib.request.Request(self.endpoint+'/chat/completions',data=body,headers=headers)
        # urllib errors are deliberately not echoed: response bodies can contain
        # untrusted documents or credential-related diagnostics.
        try:
            with verified_opener().open(req,timeout=600) as r:data=json.load(r)
        except Exception as e:raise RuntimeError('Provider request failed: '+type(e).__name__) from None
        usage=data.get('usage',{});a=usage.get('prompt_tokens');b=usage.get('completion_tokens')
        if type(a)!=int or type(b)!=int:raise ValueError('Provider did not report token usage')
        cost=0.0 if self.name=='local' else (a*self.input_price+b*self.output_price)/1e6
        return data['choices'][0]['message']['content'],{'input_tokens':a,'output_tokens':b,'seconds':time.perf_counter()-start,
            'cost':cost,'cost_currency':'CNY' if self.name=='deepseek' else 'none','price_basis':'configured_peak_cache_miss_upper_bound' if self.name=='deepseek' else 'local',
            'reasoning_effort':'low' if self.name=='deepseek' else 'off','model':data.get('model',self.model),'usage':usage,'timings':data.get('timings'),'provider':self.name}
