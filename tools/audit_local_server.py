"""Explicitly launched, loopback-only Transformers text inference using existing runtime."""
import argparse
import json
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser();p.add_argument('--model-path',type=Path,required=True);p.add_argument('--port',type=int,default=8338)
    p.add_argument('--context',type=int,default=16384);p.add_argument('--int4',action='store_true');p.add_argument('--gpu-approved',action='store_true')
    p.add_argument('--prefill-chunk',type=int,default=256)
    args=p.parse_args()
    if not args.gpu_approved:raise SystemExit('GPU use must be explicitly approved before model load')
    import torch
    from transformers import AutoTokenizer,Qwen3_5ForCausalLM,BitsAndBytesConfig,StoppingCriteria,StoppingCriteriaList
    if not torch.cuda.is_available():raise SystemExit('CUDA runtime unavailable')
    tokenizer=AutoTokenizer.from_pretrained(str(args.model_path),local_files_only=True,trust_remote_code=False)
    options={'local_files_only':True,'trust_remote_code':False,'use_safetensors':True,'dtype':torch.bfloat16,'device_map':'cuda:0','attn_implementation':'sdpa'}
    if args.int4:options['quantization_config']=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',bnb_4bit_compute_dtype=torch.bfloat16,bnb_4bit_use_double_quant=True)
    model=Qwen3_5ForCausalLM.from_pretrained(str(args.model_path),**options);model.eval()
    print(json.dumps({'ready':True,'model':str(args.model_path),'context':args.context,'cuda_allocated':torch.cuda.memory_allocated()},ensure_ascii=False),flush=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data):
            raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            self.send(200,{'data':[{'id':args.model_path.name,'context':args.context}]})
        def do_POST(self):
            if self.path!='/v1/chat/completions':self.send(404,{'error':'unknown route'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<4*1024*1024:raise ValueError('request size')
                data=json.loads(self.rfile.read(length));messages=data['messages']
                text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
                inputs=tokenizer(text,return_tensors='pt').to(model.device);size=inputs['input_ids'].shape[-1]
                maximum=min(int(data.get('max_tokens',2048)),8192)
                if size+maximum>args.context:self.send(400,{'error':'context capacity exceeded','prompt_tokens':size,'context':args.context});return
                class StopJson(StoppingCriteria):
                    def __call__(self,input_ids,scores,**kw):
                        ids=input_ids[0,size:]
                        if len(ids)<2:return False
                        last=tokenizer.decode(ids[-1:],skip_special_tokens=True)
                        if '}' not in last:return False
                        try:
                            content=tokenizer.decode(ids,skip_special_tokens=True).strip();obj,end=json.JSONDecoder().raw_decode(content)
                            return isinstance(obj,dict) and not content[end:].strip()
                        except ValueError:return False
                torch.cuda.reset_peak_memory_stats();start=time.perf_counter()
                with torch.inference_mode():
                    cache=None
                    # Bounded prefill avoids allocating long fallback attention
                    # intermediates for the entire document at once.
                    for pos in range(0,max(0,size-1),args.prefill_chunk):
                        end=min(size-1,pos+args.prefill_chunk)
                        prefix=model(input_ids=inputs['input_ids'][:,pos:end],attention_mask=inputs['attention_mask'][:,:end],
                                     past_key_values=cache,use_cache=True,logits_to_keep=1)
                        cache=prefix.past_key_values
                        del prefix
                    out=model.generate(**inputs,past_key_values=cache,max_new_tokens=maximum,do_sample=False,stopping_criteria=StoppingCriteriaList([StopJson()]))
                torch.cuda.synchronize();elapsed=time.perf_counter()-start
                generated=out[0,size:];content=tokenizer.decode(generated,skip_special_tokens=True)
                self.send(200,{'model':args.model_path.name,'choices':[{'message':{'role':'assistant','content':content}}],
                    'usage':{'prompt_tokens':size,'completion_tokens':len(generated),'context_limit':args.context,
                             'seconds':elapsed,'tokens_per_second':len(generated)/elapsed,'peak_cuda_bytes':torch.cuda.max_memory_allocated()}})
                del inputs,out,generated
            except Exception as e:
                self.send(500,{'error':type(e).__name__})
    HTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__':main()
