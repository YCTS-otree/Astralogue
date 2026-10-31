"""Evidence-bound offline wiki trees and conservative cross-language alignment."""
from collections import defaultdict
from difflib import SequenceMatcher
import hashlib
import re
import unicodedata
from pathlib import Path
from astralogue.model import Bundle,Node,load_json,digest,file_hash
from astralogue.narrative import Reconstruction
from astralogue import __version__


def normalize(text):
    text=unicodedata.normalize('NFC',text)
    text=re.sub(r'<(?:color|size)(?:=[^>]*)?>|</(?:color|size)>','',text,flags=re.I)
    text=text.translate(str.maketrans({'“':'"','”':'"','’':"'",'‘':"'",'\u00a0':' '}))
    return ' '.join(text.split()).strip()


def parse(snapshot):
    """Parse a cached MediaWiki response or explicit audited wiki-tree-v1.

    Unsupported indentation/templates become blocking nodes, never guessed edges.
    """
    if snapshot.get('format')=='wiki-tree-v1':
        tree=snapshot['tree']
    else:
        content=snapshot.get('content','')
        if snapshot.get('format')!='wikitext':
            tree=[{'type':'unknown','raw':content,'reason':'HTML/template profile not verified'}]
        else:
            tree=[]
            for i,line in enumerate(content.splitlines()):
                if not line.strip():continue
                match=re.fullmatch(r":\s*'''([^']+):'''\s*(.+)",line)
                if match and not any(token in match[2] for token in ['{{','[[','<']):
                    tree.append({'type':'dialogue','speaker':match[1],'text':match[2],'position':i})
                elif line.startswith('='):
                    tree.append({'type':'scene','text':line.strip('= '),'position':i})
                else:tree.append({'type':'unknown','raw':line,'position':i})
    def check(nodes,depth=0):
        if depth>32:raise ValueError('Wiki tree depth limit')
        if not isinstance(nodes,list):raise ValueError('Wiki body must be a list')
        for n in nodes:
            if not isinstance(n,dict):raise ValueError('Invalid wiki node')
            if n.get('type')=='choice':
                if not n.get('options'):raise ValueError('Empty choice')
                for o in n['options']:check(o.get('body',[]),depth+1)
            elif n.get('type')=='optional':check(n.get('body',[]),depth+1)
    check(tree)
    provenance={k:snapshot.get(k) for k in ['url','page_id','revision_id','title','fetched_at','license']}
    return {'format':'parsed-wiki-v1','tree':tree,'provenance':provenance,'snapshot':snapshot,'sha256':digest(snapshot)}


def align(parsed,source,english):
    source=Path(source);english=Path(english)
    raw=english.read_bytes();index=load_json(source/'resource-index.json')
    expected=index['files']['TextMap/TextMapEN.json']['sha']
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=expected:raise ValueError('English map version/blob conflict')
    en=load_json(english);rows=load_json(source/'ExcelOutput/TalkSentenceConfig.json')
    candidates=defaultdict(list);by_id={}
    for row in rows:
        sid=row.get('TalkSentenceID');h=str(row.get('TalkSentenceText',{}).get('Hash'))
        if sid is None or h not in en:continue
        item={'id':sid,'hash':h,'english':en[h],'speaker':en.get(str(row.get('TextmapTalkSentenceName',{}).get('Hash')))}
        candidates[normalize(en[h])].append(item);by_id[str(sid)]=item
    results={}
    def visit(nodes,prefix='tree'):
        for i,n in enumerate(nodes):
            pos=prefix+'/'+str(i)
            if n.get('type')=='dialogue':match(n,pos)
            elif n.get('type')=='choice':
                for j,o in enumerate(n['options']):
                    p=pos+'/options/'+str(j);match(o,p);visit(o.get('body',[]),p+'/body')
            elif n.get('type')=='optional':visit(n.get('body',[]),pos+'/body')
    def match(n,pos):
        text=normalize(n.get('text',''));exact=candidates.get(text,[]) if text else []
        matches=[{**x,'score':1.0,'method':'normalized_exact','speaker_consistent':not n.get('speaker') or normalize(n['speaker'])==normalize(x.get('speaker') or '')} for x in exact]
        # Fuzzy retrieval is review-only; it never assigns an executable ID.
        if not matches and len(text)>=12:
            possible=[(SequenceMatcher(None,text,key).ratio(),key) for key in candidates if abs(len(key)-len(text))<max(12,len(text)//3) and key[:1]==text[:1]]
            for score,key in sorted(possible,reverse=True)[:3]:
                if score>=.8:matches.extend({**x,'score':score,'method':'fuzzy_candidate','speaker_consistent':None} for x in candidates[key])
        accepted=len(matches)==1 and matches[0]['method']=='normalized_exact' and matches[0]['speaker_consistent']
        results[pos]={'wiki':n,'candidates':matches,'selected':matches[0]['id'] if accepted else None,'status':'WIKI_ALIGNED' if accepted else 'CANDIDATE' if matches else 'UNRESOLVED','sequence_context':'tree position retained; no ID-order inference'}
    visit(parsed['tree'])
    return {'alignment_version':1,'parsed':parsed,'source':load_json(source/'source.json'),'bindings':results,'inputs':{'english':file_hash(english),'sentences':file_hash(source/'ExcelOutput/TalkSentenceConfig.json'),'chs':file_hash(source/'TextMap/TextMapCHS.json')},'review':None}


def review(alignment,decisions):
    if decisions.get('alignment_hash')!=digest(alignment):raise ValueError('Stale alignment/revision review')
    if not decisions.get('reviewer'):raise ValueError('Reviewer required')
    import copy
    result=copy.deepcopy(alignment)
    for position,selected in decisions['selections'].items():
        binding=result['bindings'][position]
        if selected is not None and selected not in [c['id'] for c in binding['candidates']]:raise ValueError('ID not in candidates')
        binding['selected']=selected;binding['status']='COMMUNITY_REVIEWED' if selected else 'UNRESOLVED'
    result['review']=decisions
    return result


def build(alignment,source,strict=None,namespace="wiki"):
    source=Path(source)
    if not alignment['parsed']['tree']:raise ValueError('Empty wiki scope')
    if file_hash(source/'TextMap/TextMapCHS.json')!=alignment['inputs']['chs'] or file_hash(source/'ExcelOutput/TalkSentenceConfig.json')!=alignment['inputs']['sentences']:raise ValueError('Stale game source')
    rows={str(r['TalkSentenceID']):r for r in load_json(source/'ExcelOutput/TalkSentenceConfig.json') if 'TalkSentenceID' in r};chs=load_json(source/'TextMap/TextMapCHS.json')
    if strict is None:
        strict=Bundle(metadata={'version':__version__});strict.text('default-title','Wiki 来源阅读')
    mid=namespace+':reader'
    r=Reconstruction(strict,mid,alignment['parsed']['provenance'].get('title') or 'Wiki',namespace+':consent');b=r.bundle
    r.info['entries']={'reader':mid};r.info['wiki_alignment']=alignment
    r.info['modes'][mid]['scope']='wiki_recorded_scope'
    r.node(namespace+':end','end',original_game_completion=False)
    def edge(a,z,**kw):return r.edge(a,z,'inferred',{'label':'WIKI_ALIGNED','wiki':alignment['parsed']['provenance']},'wiki_external_order',**kw)
    def line(node,pos,target):
        binding=alignment['bindings'][pos];sid=binding['selected'];nid=namespace+':'+pos
        if sid is None or str(sid) not in rows:
            r.node(nid,'unknown',operation='UnmatchedWikiDialogue',alignment=binding);return nid
        row=rows[str(sid)];h=str(row['TalkSentenceText']['Hash'])
        if h not in chs:r.node(nid,'unknown',operation='MissingCHSText',talk_sentence_id=sid);return nid
        key=b.text('hsr:text:'+h,chs[h]);speaker=None;name=str(row.get('TextmapTalkSentenceName',{}).get('Hash'))
        if name in chs:speaker=b.text('hsr:speaker:'+name,chs[name])
        b.nodes.append(Node(nid,mid,'dialogue',key,speaker,{'talk_sentence_id':sid,'alignment_status':binding['status']}));edge(nid,target);return nid
    def sequence(nodes,target,prefix='tree'):
        for i in range(len(nodes)-1,-1,-1):
            n=nodes[i];pos=prefix+'/'+str(i);nid=namespace+':'+pos;kind=n.get('type')
            if kind=='dialogue':target=line(n,pos,target)
            elif kind=='choice':
                r.node(nid,'choice',reader_action='wiki_choice',reader_message='Wiki 来源选项结构，非 GAME_VERIFIED')
                for j,o in enumerate(n['options']):
                    p=pos+'/options/'+str(j);binding=alignment['bindings'][p];sid=binding['selected']
                    destination=sequence(o.get('body',[]),target,p+'/body')
                    row=rows.get(str(sid));h=str(row.get('TalkSentenceText',{}).get('Hash')) if row else None
                    if not row or h not in chs:
                        blocked=nid+':unmatched:'+str(j);r.node(blocked,'unknown',operation='UnmatchedWikiOption',alignment=binding);destination=blocked
                        label=b.text(blocked+':label','未对齐选项（选择后阻塞）')
                    else:label=b.text('hsr:text:'+h,chs[h])
                    edge(nid,destination,kind='option',text=label,value=str(j))
                target=nid
            elif kind in {'scene','narration'}:
                r.confirm(nid,target,'Wiki 场景说明（外部资料）：'+n.get('text',''),action='wiki_narration');target=nid
            else:r.node(nid,'unknown',operation='UnsupportedWikiStructure',raw=n);target=nid
        return target
    entry=sequence(alignment['parsed']['tree'],namespace+':end')
    r.confirm(namespace+':consent',entry,'采用 Wiki 来源顺序，仅表示所记录范围；原文来自游戏 CHS，不证明完整任务',action='wiki_consent')
    return b


def report(alignment):
    bindings=list(alignment['bindings'].values())
    return {'entries':len(bindings),'unique_exact':sum(x['status']=='WIKI_ALIGNED' for x in bindings),'ambiguous':sum(len(x['candidates'])>1 for x in bindings),'unresolved':sum(x['selected'] is None for x in bindings),'fuzzy_verified':0,'game_control_conflicts':'not_evaluated','runtime_completed_scopes':'not_executed','full_game_tasks_proven':0}
