"""Offline source navigation and targeted audit requests; never fetches Wiki."""
import json
import re
import sqlite3
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlencode,parse_qs,urlparse
from astralogue.model import digest,canonical
from astralogue.adapters.wiki.bwiki import parse_page,inline
from astralogue.adapters.wiki.scenes import classify_page
from astralogue.adapters.wiki import normalize
from . import presentation as v

ROOT=Path(__file__).resolve().parents[3]


def chapter_label(key):return '序章 · 今天是昨天的明天' if key=='100001' else '章节 '+str(key)

def chapter_key(ctx):return str(ctx.get('chapter_id') or ('100001' if ctx.get('chapter')=='今天是昨天的明天' else ctx.get('chapter') or '未归属'))


@lru_cache(maxsize=128)
def cached_units(path,stamp,size,chapter):
    page=parse_page(Path(path));result=[]
    for section in classify_page(page)['sections']:
        raw=page['wikitext'][section['start']:section['end']]
        parts=[{'id':section['id'],'label':'小节原文','raw':raw,'kind':'section','source':{'start':section['start'],'raw':raw}}]+section['interactions']
        for part in parts:
            result.append({'id':'audit-source:'+digest([page['page_id'],page['snapshot_sha256'],part['id']])[:32],
                'chapter':chapter,'chapter_label':chapter_label(chapter),'task':page['title'],'section':section['title'],'section_id':section['id'],
                'part':part,'path':path,'sha256':page['snapshot_sha256'],'revision':page['revision_id'],'page_id':page['page_id'],
                'start':section['start'],'end':section['end'],'text':part.get('raw',part['source']['raw'])})
    return result


def catalog():
    paths={};queue=ROOT/'data/staging/bwiki-pilot/queue.sqlite'
    if queue.exists():
        con=sqlite3.connect(queue.resolve().as_uri()+'?mode=ro',uri=True)
        try:
            for title,chapter,path in con.execute('SELECT title,chapter,cache FROM pages WHERE cache IS NOT NULL'):
                candidate=queue.parent/path
                if candidate.is_file():paths[title]=(candidate,str(chapter))
        finally:con.close()
    # Prefer the snapshots used by the existing prologue audit where available.
    folder=ROOT/'data/staging/bwiki'
    if folder.exists():
        for path in folder.glob('*.json'):
            paths[path.stem]=(path,paths.get(path.stem,(None,'100001'))[1])
    result=[]
    for path,chapter in paths.values():
        try:
            st=path.stat();result.extend(cached_units(str(path),st.st_mtime_ns,st.st_size,chapter))
        except (ValueError,KeyError,TypeError):continue
    return result


def matches(text,query):
    terms=query.get('q',[''])[0].casefold().split()
    if not terms:return True
    hits=[term in text.casefold() for term in terms]
    return any(hits) if query.get('match',['all'])[0]=='any' else all(hits)


def filter_sources(units,query):
    return [u for u in units if all(not query.get(key,[''])[0] or u[field]==query[key][0] for key,field in [('chapter','chapter'),('mission','task'),('section','section')]) and matches(u['chapter_label']+' '+u['task']+' '+u['section']+' '+u['part']['label']+' '+u['text'],query)]


def filter_proposals(rows,query):
    result=[]
    for r in rows:
        ctx=r['payload']['context'];loc=r['location']
        if query.get('chapter',[''])[0] and chapter_key(ctx)!=query['chapter'][0]:continue
        if query.get('mission',[''])[0] and r['task']!=query['mission'][0]:continue
        if query.get('section',[''])[0] and query['section'][0] not in [s.get('title') for _,s in loc['candidates']]:continue
        text=' '.join([chapter_label(chapter_key(ctx)),r['task'],loc['section'],loc['label'],*[v.text(i.get('speaker'))+' '+v.text(i.get('text')) for i in v.selected(r['payload'])]])
        if matches(text,query):result.append(r)
    return result


def url(query,**updates):
    values={k:vals[0] for k,vals in query.items() if k in {'tab','status','chapter','mission','section','q','match','view','offset'}}
    values.update(updates);return '/?'+urlencode(values)


def filter_form(query,units,rows):
    chapters={u['chapter']:u['chapter_label'] for u in units}
    for row in rows:chapters.setdefault(chapter_key(row['payload']['context']),v.text(row['payload']['context'].get('chapter')))
    scope=[u for u in units if not query.get('chapter',[''])[0] or u['chapter']==query['chapter'][0]]
    missions=list(dict.fromkeys([u['task'] for u in scope]))
    sections=list(dict.fromkeys(u['section'] for u in scope if not query.get('mission',[''])[0] or u['task']==query['mission'][0]))
    def select(name,label,options):
        empty='all' if name=='status' else ''
        handler=("this.form.elements.mission.value='';this.form.elements.section.value='';" if name=='chapter' else "this.form.elements.section.value='';" if name=='mission' else '')+'this.form.submit()'
        return '<label>'+label+' <select name="'+name+'" onchange="'+handler+'"><option value="'+empty+'">全部</option>'+''.join('<option value="'+v.esc(key)+'"'+(' selected' if query.get(name,['pending' if name=='status' else ''])[0]==key else '')+'>'+v.esc(text)+'</option>' for key,text in options)+'</select></label>'
    body='<form method="get" class="card"><h2>按章 / 节 / 小节定位</h2><div class="actions">'
    body+=select('chapter','章',chapters.items())+select('mission','节 / 任务',[(m,m) for m in missions])+select('section','小节',[(s,s) for s in sections])
    body+='</div><p><label>关键词 <input name="q" value="'+v.esc(query.get('q',[''])[0])+'" placeholder="星核 容器 银狼"></label> <select name="match"><option value="all">包含全部关键词</option><option value="any"'+(' selected' if query.get('match',[''])[0]=='any' else '')+'>包含任一关键词</option></select></p>'
    body+='<input type="hidden" name="view" value="'+v.esc(query.get('view',[''])[0])+'"><input type="hidden" name="status" value="'+v.esc(query.get('status',['pending'])[0])+'">'
    body+='<input type="hidden" name="tab" value="'+v.esc(query.get('tab',['all'])[0])+'"><button>筛选 / 搜索</button><a href="/">清除</a><p class="subtle">多个关键词默认全部匹配，按中文子串搜索。原文范围也包括尚未提交申请的内容，审核类型和状态通过下方快捷入口选择。</p></form>'
    return body


def source_page(store,query,units,rows):
    selected=filter_sources(units,query)
    try:offset=max(0,int(query.get('offset',['0'])[0]))
    except ValueError:offset=0
    body='<a href="'+v.esc(url(query,view='',offset=0))+'">← 返回审核申请</a><h1>原文定位与主动审查</h1>'+filter_form(query,units,rows)+'<p>匹配 '+str(len(selected))+' 个来源块（小节与内部互动可能重叠，不是台词覆盖率）。</p>'
    for unit in selected[offset:offset+10]:
        part=unit['part'];body+='<section class="card"><div class="crumb">'+v.esc(unit['chapter_label']+' › '+unit['task']+' › '+unit['section'])+'</div><h2>'+v.esc(part['label'])+'</h2>'+v.wiki_fragment(unit['text'])
        linked=[]
        for row in rows:
            ctx=row['payload']['context'];proof=ctx.get('evidence',{}).get('wiki',{});source=proof.get('source',{})
            if ctx.get('source_unit_id')==unit['id'] or proof.get('sha256')==unit['sha256'] and (source.get('start')==part['source'].get('start') or part['kind']=='section' and unit['start']<=source.get('start',-1)<unit['end']):linked.append(row)
        body+='<h3>已有申请</h3>'+(''.join('<p><a href="'+v.esc(url(query,id=r['row']['id']))+'">'+v.esc(r['location']['label'])+'</a> · '+v.esc(v.STATUS.get(r['row']['status'],r['row']['status']))+'</p>' for r in linked) or '<p>该来源块暂无已关联申请，可以主动发起检查。</p>')
        body+='<form method="post"><input type="hidden" name="csrf" value="'+v.esc(store.setting('webui_csrf') or '')+'"><input type="hidden" name="source_id" value="'+unit['id']+'"><label>审核人 <input name="reviewer" required value="'+v.esc(store.setting('webui_reviewer') or '')+'"></label><p><label>问题 / 修改方向<textarea name="comment" maxlength="12000" placeholder="例如：此处应主动调查，首次与再次调查需要分开触发。"></textarea></label></p><select name="provider"><option value="local">本地离线模型</option><option value="deepseek">DeepSeek 低推理（累计预算5元）</option></select><div class="actions"><button name="action" value="source_parse">重新结构解析（不调用模型）</button><button name="action" value="source_model">向模型发起修改请求（需评论）</button></div></form></section>'
    body+='<nav class="nav"><a href="'+v.esc(url(query,offset=max(0,offset-10)))+'">上一页</a><a href="'+v.esc(url(query,offset=offset+10))+'">下一页</a></nav>'
    return body


def request_source(store,source_id,action,reviewer,comment='',provider='local'):
    if not reviewer.strip():raise ValueError('请填写审核人')
    if action=='source_model' and not comment.strip():raise ValueError('请填写问题或修改方向')
    if provider not in {'local','deepseek'}:raise ValueError('Unknown provider')
    unit=next((u for u in catalog() if u['id']==source_id),None)
    if not unit:raise ValueError('来源已变化或不存在，请刷新重新选择')
    from astralogue.storypack import StoryPack
    path=store.setting('publication_pack')
    if not path:raise ValueError('未设置当前游玩包')
    from .source_binding import source_key
    part=unit['part'];raw=part.get('raw',unit['text']);needles=[source_key(inline(raw)['text'])]+[source_key(r['text']) for r in part.get('rows',[])]
    with StoryPack(Path(path)) as pack:
        bundle=pack.bundle();arc=next(iter(pack.metadata.get('story_arcs',{}).values()),{});tasks=arc.get('plan',{}).get('tasks',[])
        candidates=[(mid,i) for mid,entry in pack.metadata.get('story_arcs',{}).items() for i,t in enumerate(entry.get('plan',{}).get('tasks',[])) if t['title']==unit['task']]
        mid,index=candidates[0] if len(candidates)==1 else (None,None)
        nodes=[n for n in bundle.nodes if index is not None and n.mission==mid and n.data.get('task')==index and n.kind=='dialogue']
        found=[n for n in nodes if any(value and source_key(v.text(bundle.texts.get(n.text,{})))==value for value in needles)]
        def view(n):return {'node':n.id,'text':bundle.texts.get(n.text,{}),'speaker':bundle.texts.get(n.speaker,{}),'data':n.data}
        instances={str(i):view(n) for i,n in enumerate(found)} or {'SOURCE':{'id':unit['id'],'kind':'wiki_source_instance','text':raw,'label':part['label'],'source':part['source']}}
        ctx={'review_round':store.setting('review_round'),'task':{'title':unit['task']},'chapter':unit['chapter_label'],'chapter_id':unit['chapter'],'source_unit_id':unit['id'],'instances':instances,
             'scenes':{'phase':{'id':unit['section_id'],'title':unit['section'],'start':unit['start'],'end':unit['end']}},
             'evidence':{'wiki':{'path':unit['path'],'sha256':unit['sha256'],'revision_id':unit['revision'],'interaction_requirement':part.get('interaction_requirement','unknown'),'source_role':part['kind'],'repeat_policy':part.get('repeat_policy','unknown'),'source':part['source'],'label':part['label']},'graph':{'source_hashes':pack.metadata.get('narrative',{}).get('source_hashes',{})}}}
    repeated=any(s['trigger']=='repeat_inspection' for s in part.get('segments',[]))
    operation='split_dialogue_sequence' if repeated and found else 'move_to_optional_interaction' if part['kind']=='optional_dialogue' and found else 'attach_to_exploration_phase' if found else 'leave_unresolved'
    suggestion={'operation':operation,'instances':list(instances),'targets':['phase'],'evidence':['wiki','graph'],'before':{'default_path_nodes':[n.id for n in found]},
        'after':{'candidate_phases':['phase'],'interaction':part['label'],'trigger_condition':'UNKNOWN','segments':part.get('segments',[])},'conflicts':[],
        'unknowns':['主动调查是否必经、开放时机及重复访问条件仍需审核。','部分文本匹配不代表整块原文已完整映射；全部原始结构保留在来源中。'],'rationale':'从固定版本来源结构重新检查；不按文件或台词ID推断执行顺序。'}
    pid=digest(['targeted-source-parser-v1',ctx,suggestion]);payload={'proposal_version':1,'context_hash':digest(ctx),'context':ctx,'suggestion':suggestion,'origin':'DETERMINISTIC_SOURCE_CROSSCHECK','game_verified':False}
    with store.db:store.db.execute('INSERT OR IGNORE INTO proposals(id,payload) VALUES(?,?)',(pid,canonical(payload)))
    if action=='source_model':
        from .feedback import submit_feedback
        job=submit_feedback(store,pid,'research_approve',reviewer,comment,provider)
        return {'message':'修改请求已保存并排队，模型将提交1–3份新申请供人工审核。','proposal':pid,'job':job,'count':1}
    return {'message':'结构解析完成，已生成或复用待审申请；未自动改写剧情。','proposal':pid,'count':1}
