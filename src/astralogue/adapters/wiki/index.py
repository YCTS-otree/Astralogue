"""Language-neutral candidate lookup shared by Wiki and dataset adapters."""
from collections import defaultdict
from difflib import SequenceMatcher
from . import normalize as wiki_normalize
from astralogue.model import load_json

def normalize(text):
    # Explicit typographic width alias only; keep raw text and all candidates.
    return wiki_normalize(text).replace('～','~')

class DialogueIndex:
    def __init__(self,source,language='CHS'):
        self.rows={};self.raw=defaultdict(list);self.normalized=defaultdict(list);self.speakers=defaultdict(list)
        mapping=load_json(source/'TextMap'/('TextMap'+language+'.json'))
        for row in load_json(source/'ExcelOutput/TalkSentenceConfig.json'):
            sid=row.get('TalkSentenceID');h=str(row.get('TalkSentenceText',{}).get('Hash'))
            if sid is None or h not in mapping:continue
            text=mapping[h];speaker=mapping.get(str(row.get('TextmapTalkSentenceName',{}).get('Hash')))
            item={'id':sid,'hash':h,'text':text,'speaker':speaker}
            self.rows[sid]=item;self.raw[text].append(sid);self.normalized[normalize(text)].append(sid);self.speakers[speaker].append(sid)
    def match(self,text,speaker=None,owned=frozenset()):
        ids=self.raw.get(text,[]);method='exact'
        if not ids:ids=self.normalized.get(normalize(text),[]);method='normalized_exact'
        candidates=[{**self.rows[sid],'method':method,'score':1.,'owned':sid in owned,'speaker_consistent':None if not self.rows[sid]['speaker'] else speaker==self.rows[sid]['speaker']} for sid in ids]
        selected=None;basis=None
        if len(ids)==1:
            selected=ids[0];basis=method
        elif ids:
            scoped=[x for x in ids if x in owned]
            role=[x for x in ids if self.rows[x]['speaker'] and self.rows[x]['speaker']==speaker]
            if len(scoped)==1:selected=scoped[0];basis='mission_control_membership'
            elif len(role)==1:selected=role[0];basis='exact_speaker'
        if selected is not None:
            row=self.rows[selected]
            if row['speaker'] and speaker and row['speaker']!=speaker and selected not in owned:
                selected=None;basis=None
        fuzzy=[]
        if not ids and len(text)>=6:
            q=normalize(text);qchars=set(q)
            pool=self.speakers.get(speaker,[]) if speaker in self.speakers else self.rows.keys()
            # Bounded retrieval only; all fuzzy IDs remain unselected.
            possible=[]
            for sid in pool:
                t=normalize(self.rows[sid]['text'])
                if abs(len(t)-len(q))>max(6,len(q)//3):continue
                overlap=len(qchars & set(t))/max(1,len(qchars|set(t)))
                if overlap>=.55:possible.append((overlap,sid,t))
            for overlap,sid,t in sorted(possible,reverse=True)[:128]:
                score=SequenceMatcher(None,q,t,autojunk=False).ratio()
                if score>=.8:fuzzy.append({**self.rows[sid],'method':'fuzzy_candidate','score':score,'owned':sid in owned})
            fuzzy=sorted(fuzzy,key=lambda x:(-x['score'],x['id']))[:5]
        return {'candidates':candidates,'fuzzy_candidates':fuzzy,'selected':selected,'basis':basis,'exact_count':len(ids),'speaker':speaker,'original':text}
