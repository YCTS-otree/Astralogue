"""Human review projections. Plot order comes from recorded paths / source sections."""
import html
import json
import re
from astralogue.adapters.wiki import normalize
from astralogue.adapters.wiki.bwiki import templates,inline,dialogue_body

OPS={'move_to_optional_interaction':'改为主动互动','attach_to_exploration_phase':'放入自由探索阶段','mark_as_required':'保留为必经剧情',
     'classify_conditional':'改为条件触发','split_dialogue_sequence':'拆开混在一起的对话','merge_verified_sequence':'合并已核实的连续对话',
     'add_missing_choice':'补充对话选项','add_stage_direction':'补充画面说明','report_conflict':'复核来源冲突','leave_unresolved':'暂时保持原样'}
STATUS={'revision_submitted':'已提交返修申请','revision_failed':'修改失败，需重试','withdrawn':'已随研究撤回','superseded':'已由后续返修替代','invalid_revision':'未落实修改意见，已退回模型','awaiting_revision':'等待修改','pending':'待审核','approved':'已批准','rejected':'已驳回','deferred':'暂缓','acknowledged':'已阅研究结论'}
CATEGORY={'MAIN_REQUIRED':'必经剧情','MAIN_CHOICE':'主线选项','OPTIONAL_NPC':'NPC 额外对话','OPTIONAL_OBJECT':'物件调查','CONDITIONAL':'条件内容','AMBIENT':'环境闲聊','STAGE_DIRECTION':'画面或旁白','UNKNOWN':'尚未确定'}
SOURCE={'LLM':'模型建议','DETERMINISTIC_SOURCE_CROSSCHECK':'原文交叉检查'}

def esc(value):return html.escape(str(value),quote=True)
def text(value):
    if isinstance(value,dict):return value.get('CHS') or next(iter(value.values()),'')
    return value if isinstance(value,str) else ''

def line(speaker,content,highlight=False):
    speaker=text(speaker).removeprefix('社区转录·') or '旁白'
    content=text(content)
    return '<article class="utterance'+(' selected' if highlight else '')+'"><div class="speaker">'+esc(speaker)+'</div><p>'+esc(content).replace('\n','<br>')+'</p></article>'


def wiki_fragment(raw,depth=0):
    if depth>5:return '<p class="notice">这段还有嵌套分支，需进一步核对原始来源。</p>'
    try:all_templates=templates(raw)
    except ValueError:return '<p class="notice">来源结构尚未解析完整，请暂缓。</p>'
    top=[];end=-1
    for t in all_templates:
        if t['start']>=end:top.append(t);end=t['end']
    def plain(value):
        output=''
        for part in value.splitlines():
            part=part.strip()
            if not part or part in {'<br>','----'}:continue
            match=re.match(r'^\*([^：]+)：(.*)',part)
            if match:output+=line(match[1],inline(match[2])['text'])
            else:
                cleaned=inline(part.lstrip(':'))['text']
                if cleaned:output+='<p class="stage">'+esc(cleaned)+'</p>'
        return output
    result='';cursor=0
    for t in top:
        # Inline formatting belongs to its enclosing dialogue line, not a block.
        if t['name'] not in {'折叠','剧情选项'}:continue
        result+=plain(raw[cursor:t['start']]);cursor=t['end']
        if t['name']=='折叠':
            result+='<div class="source-block"><h4>'+esc(t['params'].get('标题','来源片段'))+'</h4>'+wiki_fragment(t['params'].get('内容',''),depth+1)+'</div>'
        else:
            result+='<div class="choice-preview"><h4>玩家选项</h4>'
            for k in sorted((k for k in t['params'] if re.fullmatch('选项[0-9]+',k)),key=lambda k:int(k[2:])):
                n=k[2:];label=inline(t['params'][k])['text'];body=t['params'].get('剧情'+n,'')
                result+='<details><summary>'+esc(label)+'</summary>'+wiki_fragment(body,depth+1)+'</details>'
            result+='</div>'
    result+=plain(raw[cursor:]);return result


def bindings(payload):
    ctx=payload['context'];return {**ctx.get('reference_instances',{}),**ctx.get('instances',{})}

def selected(payload):
    mapped=bindings(payload)
    return [mapped[x] for x in payload['suggestion']['instances'] if x in mapped]

def phase_candidates(payload):
    p=payload['suggestion'];ctx=payload['context'];after=p['after'];values=after.get('candidate_phases',[]) or [after.get('phase_id') or after.get('scene')]
    values=[v for v in values if v]
    if not values:values=[x for x in p['targets'] if x in ctx.get('scenes',{})]
    phases=[]
    for value in values:
        if value in ctx.get('scenes',{}):phases.append((value,ctx['scenes'][value]))
        else:
            phases.extend((key,s) for key,s in ctx.get('scenes',{}).items() if s.get('id')==value)
    return list({key:(key,s) for key,s in phases}.values())


def location(payload,baseline):
    ctx=payload['context'];scenes=ctx.get('scenes',{});items=selected(payload);positions=[];scene_hits=[]
    for item in items:
        start=item.get('source',{}).get('start')
        if isinstance(start,int):
            matches=[(key,s) for key,s in scenes.items() if s.get('start',-1)<=start<s.get('end',-1)]
            scene_hits.extend(matches);positions.append(start)
    wiki=ctx.get('evidence',{}).get('wiki',{})
    start=wiki.get('source',{}).get('start')
    if isinstance(start,int):
        scene_hits.extend((key,s) for key,s in scenes.items() if s.get('start',-1)<=start<s.get('end',-1));positions.append(start)
    # Exact source-text containment is an association candidate, not proof of
    # Unity timing. Never use file names or numeric node IDs as chronology.
    raw=ctx.get('wiki_wikitext','')
    for item in ([] if scene_hits else items):
        value=normalize(text(item.get('text')))
        if value and len(value)>=6 and isinstance(raw,str):
            for key,s in scenes.items():
                fragment=raw[s.get('start',0):s.get('end',len(raw))]
                if value in normalize(fragment):scene_hits.append((key,s))
    unique={s.get('id',key):(key,s) for key,s in scene_hits}
    if not unique:
        for key,s in phase_candidates(payload):unique[s.get('id',key)]=(key,s)
    unique=dict(sorted(unique.items(),key=lambda pair:pair[1][1].get('start',10**9)))
    titles=list(dict.fromkeys(s.get('title','待定位') for _,s in unique.values()))
    section=titles[0] if len(titles)==1 else '跨小节：'+'、'.join(titles[:3]) if titles else '待定位到具体小节'
    label=payload['suggestion']['after'].get('interaction') or wiki.get('label') or next((i.get('label') for i in items if i.get('label')),None)
    if not label:
        first=next((text(i.get('text')) for i in items if text(i.get('text'))),'')
        label=(first[:30]+'…' if len(first)>30 else first) or ('任务级研究结论' if all(not i.get('node') and not i.get('source') for i in items) else '待补充片段名称')
    nodes={i.get('node') for i in items if i.get('node')}
    order={r['node']:n for n,r in enumerate(baseline or [])}
    ranks=[order[n] for n in nodes if n in order]
    source_order=min([s.get('start',10**9) for _,s in unique.values()] or positions or [10**9])
    return {'section':section,'label':label,'scene_order':source_order,'path_order':min(ranks) if ranks else None,'candidates':list(unique.values())}


def reviewable(payload):
    items=selected(payload);op=payload['suggestion']['operation']
    if payload['suggestion'].get('additions'):return False
    if not items or any(not i.get('node') or not text(i.get('text')) for i in items):return False
    if op=='move_to_optional_interaction':
        if any(re.search(r'(?:^|\n)\s*再次调查',text(i.get('text'))) for i in items):return False
        return len(phase_candidates(payload))==1
    return op=='mark_as_required'


def body(payload):
    result=''
    segments=payload['suggestion']['after'].get('segments',[])
    if segments:
        for segment in segments:
            result+='<h4>'+('再次主动调查时' if segment['trigger']=='repeat_inspection' else '首次主动调查时')+'</h4>'+line('旁白',segment['text'],True)
        return result+'<p class="notice">首次与再次调查应分开触发，不能顺序自动播出；具体条件仍待审核。</p>'
    for item in selected(payload):
        value=text(item.get('text'))
        if item.get('kind')=='wiki_source_instance':
            raw=item.get('source',{}).get('raw') or value
            result+=wiki_fragment(raw)
        elif value:result+=line(item.get('speaker'),value,True)
        elif item.get('source',{}).get('raw'):result+=wiki_fragment(item['source']['raw'])
    return result or '<p class="notice">这份结论没有绑定具体剧情文本，暂不能作为播放修改审批。</p>'


def windows(payload,baseline,count=3):
    ids={i.get('node') for i in selected(payload)};positions=[i for i,r in enumerate(baseline) if r['node'] in ids]
    if positions:
        start=min(positions);end=max(positions)
        contiguous=len(positions)==len(ids) and all(baseline[i]['node'] in ids for i in range(start,end+1))
        return baseline[max(0,start-count):start],baseline[end+1:end+1+count],contiguous
    ctx=payload['context'];return ctx.get('overlap_before',[])[-count:],ctx.get('overlap_after',[])[:count],False


def proposed_explanation(payload):
    op=payload['suggestion']['operation'];phases=phase_candidates(payload)
    phase=phases[0][1].get('title','指定阶段') if len(phases)==1 else '尚未确定的阶段'
    if op=='move_to_optional_interaction':return '在「'+phase+'」提供一个可选入口。选择后阅读下面这段内容，结束后返回菜单；直接推进主线时不自动播放。'
    if op=='mark_as_required':return '将下面这段标记为必经剧情，保留当前位置和正文，不额外增加选项。'
    if op=='split_dialogue_sequence' and payload['suggestion']['after'].get('segments'):return '当前一条台词混合了首次与再次调查的内容。按来源标记拆开，保留为独立访问内容；不会自动应用到剧情包。'
    if op=='attach_to_exploration_phase':return '把主动互动放入对应小节的探索入口；是否必经、何时可用仍待核实。'
    return '这项建议还没有形成可执行的具体分支计划，先作为研究结论记录。'

def option_preview(payload,current=()):
    """Show actual player-facing labels separately from branch dialogue."""
    suggestion=payload['suggestion'];after=suggestion['after'];op=suggestion['operation'];labels=[]
    if op=='move_to_optional_interaction':labels=[after.get('interaction') or '额外互动']
    else:
        options=after.get('options',after.get('choices',[]))
        if isinstance(options,list):
            for option in options:
                label=option if isinstance(option,str) else option.get('label') or option.get('option_text') or option.get('text') if isinstance(option,dict) else ''
                if text(label):labels.append(text(label))
    result='<section class="card"><h3>玩家看到的分支选项</h3>'
    if current:
        result+='<div class="label">当前已有选项</div>'
        for option in current:result+='<p><span class="pill">'+esc(option['label'])+'</span> <small>'+esc(option.get('detail',''))+'</small></p>'
    if labels:
        result+='<div class="label">建议选项文字（Reader 入口）</div>'
        for label in labels:result+='<p class="selected" style="padding:12px">选择「'+esc(label)+'」 → 对应下方分支正文</p>'
        if op=='move_to_optional_interaction':result+='<p>互动结束后返回菜单；另有「推进主线」入口。</p>'
    elif op=='mark_as_required':result+='<p>此项只标记必经剧情，不新增玩家选项。</p>'
    else:result+='<p class="notice">此申请未提供新增选项文字。不能把分支正文当作选项；若需要新增入口，请退回补充。</p>'
    return result+'</section>'


def submission_time(timestamp):
    if timestamp is None:return '未记录（旧申请）'
    from datetime import datetime,timezone,timedelta
    return datetime.fromtimestamp(timestamp,timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
