"""Passage-oriented Chinese review pages; technical payloads are opt-in details."""
import json
from . import presentation as v

CSS='''
.feedback{position:fixed;inset:18px 16px auto auto;z-index:1000;max-width:min(560px,calc(100vw - 32px));display:flex;align-items:center;gap:16px;padding:16px 20px;background:#e4f8ed;color:#155c36;border:2px solid #35a267;border-radius:12px;box-shadow:0 8px 30px #17203333;font-weight:700}.feedback[hidden]{display:none}.feedback.error{background:#fff0ee;border-color:#d94b40;color:#9b271d}.feedback button{background:transparent;border:0;font-size:24px;flex-shrink:0}
*{box-sizing:border-box}body{margin:0;background:#f4f6fa;color:#25324a;font:16px/1.7 "Segoe UI","Microsoft YaHei",sans-serif}
a{color:#345fe0;text-decoration:none}a:hover{text-decoration:underline}.shell{max-width:1120px;margin:auto;padding:26px}
header{background:white;border-bottom:1px solid #dde4ef}.brand{font-size:20px;font-weight:700}.subtle,.crumb{color:#6b778d}
h1{font-size:28px;line-height:1.4}h2{font-size:21px}h3{font-size:18px}.card,.scene-group{background:white;border:1px solid #dfe5ee;border-radius:14px;padding:22px;margin:20px 0}
.nav,.stats,.actions,.toolbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.toolbar{justify-content:space-between}.nav a{padding:8px 12px}.active{background:#e7eeff;border-radius:8px;font-weight:700}
.stats>div{flex:1;min-width:160px;background:white;border:1px solid #dfe5ee;border-radius:12px;padding:16px}.stats strong{font-size:27px;display:block}
.proposal{display:grid;grid-template-columns:1fr auto;gap:16px;padding:18px 0;border-top:1px solid #e3e8f0}.proposal h3{margin:0}.preview{font-size:14px;color:#69758b}
.pill{display:inline-block;font-size:13px;padding:4px 12px;background:#eaf0ff;color:#3458aa;border-radius:20px}
.review-location{margin:16px 0;padding:12px 0;border-top:1px solid #dfe5ee;border-bottom:1px solid #dfe5ee}.review-location dt{font-size:13px;color:#6b778d}.review-location dd{margin:0 0 10px;overflow-wrap:anywhere;font-weight:600}.review-grid>aside{align-self:start;position:sticky;top:18px;max-height:calc(100vh - 36px);overflow:auto}.review-grid{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:24px}.label{font-size:14px;font-weight:700;color:#5e6c83;margin:22px 0 12px}
.utterance{padding:12px 18px;margin:10px 0;background:#f8f9fc;border-left:3px solid #dce3ee;border-radius:0 9px 9px 0}.utterance p{margin:4px 0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:17px}.speaker{font-weight:700;color:#425778;font-size:14px}.selected{background:#edf3ff;border-color:#4b70d7}
.point{padding:20px;border:2px dashed #7c96df;background:#f2f5ff;border-radius:12px;margin:22px 0}.point strong{font-size:18px}.branch{margin:18px 0 18px 18px;border-left:3px solid #7c96df;padding-left:18px}.return{padding:12px;border-radius:8px;background:#eaf6f1;color:#356456;font-size:14px}
.notice{padding:14px;background:#fff4da;color:#75541c;border-radius:9px}.stage{font-style:italic;color:#718099;padding:8px}.source-note{font-size:14px}
details{margin:18px 0}summary{cursor:pointer;color:#5f6f88}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#edf0f5;padding:18px;font-size:13px}
select{font:inherit;padding:8px;max-width:100%;border:1px solid #cbd4e2;border-radius:7px}form label{max-width:100%}input,textarea,button{font:inherit;padding:10px;border:1px solid #cbd4e2;border-radius:7px}textarea{width:100%;min-height:240px}button{background:white;color:#263750;cursor:pointer}button:disabled{background:#e4e7ed!important;color:#808a99!important;border-color:#cdd3dc!important;cursor:default}.primary{background:#345fe0;color:white;border-color:#345fe0}.actions{margin-top:18px}
@media(max-width:820px){.review-grid{grid-template-columns:1fr}.shell{padding:16px}.proposal{grid-template-columns:1fr}aside{order:-1;position:static!important;max-height:none!important}h1{font-size:24px}}
'''


FEEDBACK = """
<div id="review-feedback" class="feedback" role="status" aria-live="polite" hidden><span></span><button type="button" aria-label="关闭提交提示">×</button></div>
<script>
(()=>{
 const box=document.getElementById('review-feedback');let timer;
 function notify(message,error=false){clearTimeout(timer);box.querySelector('span').textContent=message;box.classList.toggle('error',error);box.hidden=false;if(!error)timer=setTimeout(()=>box.hidden=true,6000);}
 box.querySelector('button').onclick=()=>box.hidden=true;
 const saved=sessionStorage.getItem('audit-review-feedback');if(saved){sessionStorage.removeItem('audit-review-feedback');try{const notice=JSON.parse(saved);notify(notice.message,notice.error);}catch(_){notify(saved);}}
 const id=document.querySelector('input[name=id]')?.value;
 if(id)setInterval(async()=>{try{
  const response=await fetch('/?feedback_status='+encodeURIComponent(id));const state=await response.json();
  const key='revision-notice:'+id;const mark=JSON.stringify(state);
  if(state.children?.length&&sessionStorage.getItem(key)!==mark){sessionStorage.setItem(key,mark);notify('模型已重新提交 '+state.children.length+' 份申请，请再次审核。');const link=document.createElement('a');link.href='/?id='+encodeURIComponent(state.children[0]);link.textContent='查看新申请 →';box.querySelector('span').append(' ',link);}
 }catch(_){}},5000);
 document.querySelectorAll('form[method="post"]').forEach(form=>form.addEventListener('submit',async event=>{
  event.preventDefault();const submitter=event.submitter;const data=new FormData(form);if(submitter&&submitter.name)data.set(submitter.name,submitter.value);if(['request_changes','research_approve','source_model'].includes(data.get('action'))&&!String(data.get('comment')||'').trim()){notify('请填写评论，告知具体修改方向。',true);return;}
  const buttons=[...form.querySelectorAll('button')].map(b=>[b,b.disabled]);buttons.forEach(([b])=>b.disabled=true);notify('正在提交，请稍候…');
  try{
   const response=await fetch(form.action||location.href,{method:'POST',headers:{'Accept':'application/json'},body:new URLSearchParams(data)});
   const result=await response.json();if(!response.ok)throw new Error(result.message||'提交失败，未保存审核操作。');
   sessionStorage.setItem('audit-review-feedback',JSON.stringify({message:result.message,error:!!result.publication_failed}));location.reload();
  }catch(error){notify(error.message==='Failed to fetch'?'网络连接失败，提交结果尚未确认，请检查记录后再重试。':error.message,true);}
  finally{buttons.forEach(([b,disabled])=>b.disabled=disabled);}
 }));
})();
</script>
"""

def page(body):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Astralogue · 剧情审核</title><style>'+CSS+'</style><header><div class="shell toolbar"><span class="brand">Astralogue · 剧情审核</span><span class="subtle">看具体片段，决定怎样播放</span></div></header><main class="shell">'+body+'</main>'+FEEDBACK+'</html>'

def baseline(store):return (store.setting('first_task_findings') or {}).get('path',[])

def ordered(store,include_deleted=False):
    path=baseline(store);tasks={p['task']:i for i,p in enumerate(store.setting('audit_plan') or [])};rows=[]
    for r in store.db.execute('SELECT * FROM proposals'+('' if include_deleted else ' WHERE deleted_at IS NULL')):
        p=json.loads(r['payload']);loc=v.location(p,path);task=(p['context'].get('task') or {}).get('title','未归属任务');ready=v.reviewable(p)
        if ready and p['suggestion']['operation']=='move_to_optional_interaction':ready=v.windows(p,path)[2]
        rows.append({'row':dict(r),'payload':p,'location':loc,'task':task,'ready':ready})
    rows.sort(key=lambda x:(tasks.get(x['task'],10**6),0 if x['location']['path_order'] is not None else 1,x['location']['path_order'] if x['location']['path_order'] is not None else x['location']['scene_order'],x['row']['id']))
    return rows

def input_task(item):
    ctx=item['payload']['context']
    return bool(ctx.get('review_round') and not ctx.get('parent_proposal') and item['row']['status']!='pending')


def input_results(store,pid):
    latest=store.db.execute('SELECT job FROM review_comments WHERE proposal=? AND job IS NOT NULL ORDER BY id DESC LIMIT 1',(pid,)).fetchone()
    if not latest:return []
    return [r[0] for r in store.db.execute("SELECT id FROM proposals WHERE (job=? OR id IN (SELECT proposal FROM proposal_links WHERE job=?)) AND deleted_at IS NULL AND status NOT IN ('withdrawn','superseded','invalid_revision')",(latest[0],latest[0]))]


def filtered_applications(rows,query):
    from .navigation import filter_proposals
    rows=filter_proposals([r for r in rows if r['row'].get('deleted_at') is None],query)
    tab=query.get('tab',['all'])[0];status=query.get('status',['pending'])[0]
    pool=rows if status in {'awaiting_revision','revision_failed'} else [r for r in rows if not input_task(r)]
    return [r for r in pool if (tab=='all' or tab=='revisions' and r['payload']['context'].get('parent_proposal') or tab!='revisions' and r['ready']==(tab!='research')) and (status=='all' or r['row']['status']==status)]


def list_page(store,query):
    from .navigation import catalog,filter_form,filter_proposals,source_page,url
    rows=ordered(store);units=catalog()
    if query.get('view',[''])[0]=='source':return page(source_page(store,query,units,[r for r in rows if not input_task(r)]))
    all_rows=rows;rows=filter_proposals(rows,query)
    tab=query.get('tab',['all'])[0];status=query.get('status',['pending'])[0]
    content='<h1>按剧情顺序审核</h1><p class="subtle">章节 → 任务 → 小节 → 对话片段。按已知阅读路径与来源小节位置排列；未定位内容单独列出。</p><div class="stats">'
    applications=[r for r in rows if not input_task(r)]
    pending=[r for r in applications if r['row']['status']=='pending']
    cards=[(sum(r['ready'] for r in pending),'待审核 · 具体修改','pending','changes'),(sum(not r['ready'] for r in pending),'待审核 · 研究/待补全','pending','research'),
           (sum(r['row']['status']=='awaiting_revision' for r in rows),'模型处理中','awaiting_revision','all'),
           (sum(r['row']['status']=='approved' for r in applications),'人工已批准','approved','all'),(sum(r['row']['status']=='rejected' for r in applications),'人工已驳回','rejected','all')]
    for count,label,card_status,card_tab in cards:content+='<div><a href="'+v.esc(url(query,tab=card_tab,status=card_status,offset=0))+'"><strong>'+str(count)+'</strong>'+label+'</a></div>'
    content+='<p class="subtle">以上是当前章节/关键词范围的状态总览；已完成的自动输入任务不计作研究申请。</p>'
    content+='</div>'+filter_form(query,units,all_rows)+'<nav class="nav"><a href="/?tab=all">全部申请</a><a href="/?tab=changes">具体修改</a><a href="/?tab=research">研究结论与待定位</a><a href="/?tab=revisions">模型返修申请</a><a href="/?tab=all&status=revision_failed">修改失败</a><a href="/?tab=all&status=revision_submitted">已提交返修</a><a href="/?tab='+v.esc(tab)+'&status=awaiting_revision">等待修改</a><a href="/?tab='+v.esc(tab)+'&status=all">包含已处理项目</a></nav>'
    visible=filtered_applications(all_rows,query)
    try:offset=max(0,int(query.get('offset',['0'])[0]))
    except ValueError:offset=0
    token=store.setting('webui_csrf') or ''
    content+='<form method="post"><input type="hidden" name="csrf" value="'+v.esc(token)+'"><fieldset><legend>多选审核（本页）</legend><label>审核人 <input name="reviewer" required value="'+v.esc(store.setting('webui_reviewer') or '')+'"></label><label><input type="checkbox" onclick="this.form.querySelectorAll(\'input[name=ids]\').forEach(x=>x.checked=this.checked)">全选本页</label><button name="action" value="approve">通过所选</button><button name="action" value="reject">驳回所选</button></fieldset>'
    group=None
    for item in visible[offset:offset+40]:
        p=item['payload'];loc=item['location'];ctx=p['context'];key=(item['task'],loc['section'])
        if key!=group:
            if group:content+='</section>'
            content+='<section class="scene-group"><div class="crumb">'+v.esc(ctx.get('chapter','未归属章节'))+' · '+v.esc(item['task'])+'</div><h2>'+v.esc(loc['section'])+'</h2>';group=key
        preview=next((v.text(i.get('text')) for i in v.selected(p) if v.text(i.get('text'))),'需要补充具体剧情位置')
        if '{{' in preview:preview=loc['label']
        if ctx.get('parent_proposal'):content+='<p class="pill">'+('本轮复审结果 · 等待人工批准' if ctx.get('initial_case_review') else '模型返修申请 · 需重新人工批准')+'</p>'
        position='当前阅读路径第 '+str(loc['path_order']+1)+' 条' if loc['path_order'] is not None else '按来源小节位置排列；执行位置待核实'
        content+='<article class="proposal"><div><label><input type="checkbox" name="ids" value="'+v.esc(item['row']['id'])+'"'+(' disabled' if input_task(item) else '')+'>选择此项</label><h3><a href="/?id='+item['row']['id']+'">'+v.esc(loc['label'])+'</a></h3><div>'+v.esc(v.OPS.get(p['suggestion']['operation'],'待核实修改'))+'</div><p class="preview">'+v.esc(preview[:100])+('…' if len(preview)>100 else '')+'</p><small class="subtle">'+v.esc(position)+' · 提交 '+v.esc(v.submission_time(item['row'].get('created_at')))+' · '+v.esc(v.SOURCE.get(p.get('origin'),'模型建议'))+' · '+str(len(p['suggestion']['instances']))+' 个引用片段</small></div><div><span class="pill">'+v.esc(v.STATUS.get(item['row']['status'],'待处理'))+'</span></div></article>'
    if group:content+='</section>'
    content+='</form>'
    if not visible:
        content+='<div class="card">当前筛选：'+v.esc(v.STATUS.get(status,'全部状态'))+'，匹配 0 项。当前范围有 '+str(len(pending))+' 份待审核申请。<p><a href="'+v.esc(url(query,status='pending',tab='all',offset=0))+'">查看待审核申请 →</a></p></div>'
    content+='<nav class="nav"><a href="/?tab='+v.esc(tab)+'&status='+v.esc(status)+'&offset='+str(max(0,offset-40))+'">上一页</a><span>共 '+str(len(visible))+' 项</span><a href="/?tab='+v.esc(tab)+'&status='+v.esc(status)+'&offset='+str(offset+40)+'">下一页</a></nav>'
    content+='<p><a href="'+v.esc(url(query,view='source',offset=0))+'">在原文中定位 / 没有申请时主动发起审查 →</a></p>'
    import re
    def preserve(match):
        from urllib.parse import parse_qs,urlparse
        import html
        target=html.unescape(match.group(1))
        if target.startswith('/?tab=') or target.startswith('/?id='):
            values={k:vals[0] for k,vals in parse_qs(urlparse(target).query).items()}
            return 'href="'+v.esc(url({**query,'tab':[tab],'status':[status]},**values))+'"'
        return match.group(0)
    content=re.sub(r'href="([^"]+)"',preserve,content)
    return page(content+'<details><summary>审计进度与技术统计</summary><pre>'+v.esc(json.dumps(store.report(),ensure_ascii=False,indent=2))+'</pre></details>')

def detail_page(store,pid,token,reviewer,context_count=3,filter_query=None):
    rows=ordered(store,include_deleted=True);item=next((r for r in rows if r['row']['id']==pid),None)
    if not item:return None
    row=item['row'];p=item['payload'];ctx=p['context'];suggestion=p['suggestion'];loc=item['location'];op=suggestion['operation'];ready=item['ready']
    from .navigation import url
    filter_query=filter_query or {}
    if not any(key in filter_query for key in ['tab','status','chapter','mission','section','q','match','view']):filter_query={'tab':['changes' if ready else 'research'],'status':['pending']}
    before,after,contiguous=v.windows(p,baseline(store),context_count)
    content='<a href="'+v.esc(url(filter_query))+'">← 返回当前筛选列表</a><div class="crumb">'+v.esc(ctx.get('chapter','未归属章节'))+' › '+v.esc(item['task'])+' › '+v.esc(loc['section'])+'</div><h1>'+v.esc(loc['label'])+'</h1><div class="toolbar"><span>'+v.esc(v.OPS.get(op,'待核实修改'))+'</span><span class="pill">'+v.esc(v.STATUS.get(row['status'],'待处理'))+'</span></div>'
    if p.get('review_warnings'):
        content+='<section class="notice"><strong>请人工核对（未将此申请提前判为失败）</strong>'+''.join('<p>'+v.esc(warning)+'</p>' for warning in p['review_warnings'])+'</section>'
    if input_task(item):
        content+='<section class="notice"><strong>解析器输入历史，不是另一份待审申请</strong><p>正文与模型确认结果可能相同，不需要重复审核。请打开实际审核申请：</p>'
        for result in input_results(store,pid):content+='<p><a href="/?id='+result+'">查看实际审核申请 →</a></p>'
        content+='</section>'
    elif ctx.get('initial_case_review') and ctx.get('parent_proposal'):
        content+='<p class="source-note">这是模型提交的实际审核申请；<a href="/?id='+v.esc(ctx['parent_proposal'])+'&history=1">原始解析输入（历史，无需重复审核）</a></p>'
    if not ready:content+='<p class="notice">这项是研究结论或尚未定位的片段，还不能直接改变播放。请先补充具体台词与位置，不需要审批笼统描述。</p>'
    content+='<nav class="nav"><a href="'+v.esc(url(filter_query,id=pid,context=min(100,context_count+5)))+'">向前／向后各多加载 5 条剧情</a><span>当前前后各 '+str(context_count)+' 条，最多 100 条；沿当前已记录路径展示</span></nav>'
    content+='<div class="review-grid"><section><div class="label">上几条剧情</div>'+(''.join(v.line(r.get('speaker'),r.get('text')) for r in before) or '<p class="subtle">上文尚未定位，或已到任务开头。</p>')
    content+='<div class="point"><strong>'+('这里改为一个可选分支' if op=='move_to_optional_interaction' else v.OPS.get(op,'待补全的修改位置'))+'</strong><p>'+v.esc(v.proposed_explanation(p))+'</p>'
    phases=v.phase_candidates(p)
    if phases:content+='<span class="pill">所属小节：'+v.esc(' / '.join(s.get('title','待命名') for _,s in phases))+'</span>'
    current_options=[]
    for instance in v.bindings(p).values():
        if instance.get('kind')=='choice':
            for edge in instance.get('outgoing',[]):
                if edge.get('kind')=='option' and v.text(edge.get('option_text')):current_options.append({'label':v.text(edge['option_text']),'detail':'已有选项'})
    live_path=store.setting('publication_pack')
    if live_path:
        from pathlib import Path
        from astralogue.storypack import StoryPack
        try:
            with StoryPack(Path(live_path)) as live:
                selected_nodes={i.get('node') for i in v.selected(p)}
                scene_ids={scene.get('id',key) for key,scene in phases}
                for choice_row in live.con.execute("SELECT id,data FROM nodes WHERE kind='choice'"):
                    data=json.loads(choice_row['data']);edges=live.edges(choice_row['id'])
                    if data.get('scene_id') in scene_ids or any(e.target in selected_nodes for e in edges):
                        for edge in edges:
                            if edge.kind=='option':current_options.append({'label':live.text(edge.text,'CHS',edge.value),'detail':'当前游玩包 · '+('进入本段' if edge.target in selected_nodes else '其他入口')})
        except (OSError,ValueError):pass
    if ready and (op not in {'move_to_optional_interaction','mark_as_required'} or (any('再次调查' in v.text(instance.get('text')) for instance in v.selected(p)) and not suggestion.get('after',{}).get('segments'))):content+='<p class="notice">这是一份有明确目标的具体修改申请，但当前发布器尚未支持该类结构操作；批准会保存决定，不能假装已经完成发布。</p>'
    content+='</div>'+v.option_preview(p,current_options)
    rationale=suggestion.get('rationale','')
    explanation=suggestion.get('explanation') or (rationale if any('\u4e00'<=c<='\u9fff' for c in rationale) else '')
    if suggestion.get('additions'):
        content+='<section class="card"><h3>拟补入的来源原文（尚未编译）</h3>'
        for addition in suggestion['additions']:
            content+=v.line(addition['speaker'],addition['text'])+'<p>来源：'+v.esc(' / '.join(addition['evidence']))+'</p>'
        content+='<p class="notice">新增句子节点暂未接入发布器，批准也不会静默加入；需先完成来源与插入位置的编译支持。</p></section>'
    if explanation:content+='<section class="card"><h3>申请说明（不是剧情正文）</h3><p style="white-space:pre-wrap">'+v.esc(explanation)+'</p></section>'
    segments=suggestion.get('after',{}).get('segments',[])
    if op=='move_to_optional_interaction' and segments:
        content+='<div class="label">按调查次数触发的内容</div><p>入口始终保留；访问次数随存档保存，最后一个阶段可重复阅读。</p>'
        for index,segment in enumerate(segments):
            label='首次调查' if index==0 else '第 '+str(index+1)+' 次调查'
            if index==len(segments)-1:label+='及以后'
            content+='<section class="branch"><h3>'+label+'</h3>'+v.line(None,segment.get('text',''))+'</section>'
        content+='<details><summary>查看拆分前原文</summary>'+v.body(p)+'</details>'
    else:content+='<div class="label">'+('分支内容（原文保留）' if op=='move_to_optional_interaction' else '要审核的具体内容')+'</div><div class="branch">'+v.body(p)+'</div>'
    if op=='move_to_optional_interaction':content+='<div class="return">选择额外互动 → 阅读这段内容 → 返回本小节菜单；继续主线时跳过这段。</div>'
    content+='<div class="label">下几条剧情 / 主线继续位置</div>'+(''.join(v.line(r.get('speaker'),r.get('text')) for r in after) or '<p class="subtle">后续衔接尚未定位，或已到任务末尾。</p>')+'</section><aside><section class="card"><h3>你需要判断</h3><p>'+('这段是否应当由玩家主动选择，而不是自动混在主线里？' if op=='move_to_optional_interaction' else '这项建议是否与原作及已有来源相符？')+'</p><p class="source-note">来源：'+v.esc(v.SOURCE.get(p.get('origin'),'模型建议'))+'</p>'
    from .navigation import chapter_key,chapter_label
    chapter=chapter_label('100001') if chapter_key(ctx)=='100001' else v.text(ctx.get('chapter')) or '待确认'
    content+='<dl class="review-location"><dt>章</dt><dd>'+v.esc(chapter)+'</dd><dt>节 / 任务</dt><dd>'+v.esc(item['task'])+'</dd><dt>小节</dt><dd>'+v.esc(loc['section'])+'</dd></dl>'
    wiki=ctx.get('evidence',{}).get('wiki',{})
    if wiki:content+='<p class="source-note">BWIKI 缓存修订 '+v.esc(wiki.get('revision_id',wiki.get('revision','已固定版本')))+'</p>'
    if wiki.get('label'):content+='<p class="source-note">来源栏目：'+v.esc(wiki['label'])+'</p>'
    content+='<p class="source-note">原游戏触发条件仍待核实。批准的是文字阅读安排。</p>'
    if suggestion['conflicts']:content+='<p class="notice">有 '+str(len(suggestion['conflicts']))+' 项冲突，无法判断时请暂缓。</p>'
    content+='<p class="source-note">提交时间（北京时间）：'+v.esc(v.submission_time(row.get('created_at')))+'</p>'
    content+='</section></aside></div><section class="card"><h2>'+('处理这项修改' if ready else '处理研究结论')+'</h2><p class="subtle">批准后自动校验并增量发布到当前游玩包；失败原因会明确显示，不会清空存档。</p><form method="post"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="id" value="'+pid+'"><label>审核人 <input name="reviewer" value="'+v.esc(reviewer)+'" placeholder="你的称呼，只需填一次" required></label><div class="actions">'
    state=row['status'];deleted=bool(row.get('deleted_at'));locked=deleted or state in {'approved','rejected','awaiting_revision','withdrawn','revision_submitted','revision_failed','revision_no_change'}
    labels={'revision_no_change':'模型未修改','revision_submitted':'已提交返修申请','revision_failed':'修改失败','withdrawn':'已随研究撤回','approved':'已批准','rejected':'已驳回','awaiting_revision':'等待修改'}
    if locked:
        content+='<button disabled>'+('已从列表删除' if deleted else labels[state])+'</button>'
        if not deleted and state=='approved':content+='<button name="action" value="request_changes">提交后续修改建议（另建待审核申请）</button><span class="subtle">现有批准和发布保持有效，新申请需再次批准。</span>'
        if not deleted and state=='revision_no_change':
            content+=('<button name="action" value="approve">保留原方案并批准</button>' if ready else '<button name="action" value="research_approve">批准研究方向并建立具体申请（需评论）</button>')
        if not deleted and state in {'awaiting_revision','revision_failed','revision_no_change'}:content+='<button name="action" value="request_changes">补充意见并重新提交</button>'
    else:
        if ready:content+='<button class="primary" name="action" value="approve">批准</button><button name="action" value="request_changes">需要修改（提交评论）</button>'
        else:content+='<button class="primary" name="action" value="research_approve">批准研究方向（提交评论）</button>'
        content+='<button name="action" value="reject">驳回</button>'
    if not deleted and state=='rejected':content+='<button name="action" value="undo_reject">撤销驳回，恢复待审核</button>'
    if not deleted and store.db.execute("SELECT 1 FROM review_comments c JOIN jobs j ON j.id=c.job WHERE c.proposal=? AND c.action='research_approve' AND j.status!='cancelled'",(pid,)).fetchone():content+='<button name="action" value="undo_research">撤销研究批准及其后续申请</button>'
    content+='</div><label>判别模型 <select name="provider"><option value="local">本地离线模型（默认，无 API 费用）</option><option value="deepseek">DeepSeek v41f · 低推理（累计预算 5 元）</option></select></label><label>评论 / 修改方向（需要修改或批准研究方向时必填）<textarea name="comment" maxlength="12000" placeholder="请说明要改哪里、如何调整，以及依据。"></textarea></label></form></section>'
    publication=store.db.execute('SELECT result FROM publications WHERE proposal=?',(pid,)).fetchone()
    if publication:
        record=json.loads(publication[0]);content+='<p class="notice">'+('已发布到游玩包，修订 '+str(record.get('revision','')) if record['status'] in {'published','already_published'} else '批准已保存，但未发布：'+v.esc(record.get('error','未知错误')))+'</p>'
    if ctx.get('related_applications'):
        content+='<section class="card"><h3>生成前已额外复核的关联申请</h3>'
        for related in ctx['related_applications']:
            if related['id']==ctx.get('parent_proposal') and ctx.get('initial_case_review'):continue
            content+='<p><a href="/?id='+related['id']+'">关联申请</a> · '+v.esc(v.STATUS.get(related['status'],related['status']))+' · '+v.esc('、'.join(related['reasons']))+'</p>'
        content+='</section>'
    comments=list(store.db.execute('SELECT c.*,j.status AS job_status,j.error AS job_error FROM review_comments c LEFT JOIN jobs j ON j.id=c.job WHERE c.proposal=? ORDER BY c.id',(pid,)))
    if comments:
        content+='<section class="card"><h2>人工评论与模型修订进度</h2>'
        for comment in comments:
            status={None:'人工评论已保存（未调用模型）','pending':'排队中','running':'模型判别中','done':'模型已提交新申请，请再次人工审核','no_change':'模型未改变方案（不作为调用失败，不生成重复申请）','failed':'模型处理失败，原建议未自动应用','cancelled':'研究已撤销，任务已取消'}.get(comment['job_status'],'等待处理')
            content+='<h3>'+v.esc(comment['reviewer'])+'</h3><p>'+v.esc(comment['comment'])+'</p><p>'+status+'</p>'
            if comment['job']:
                job=store.db.execute('SELECT context FROM jobs WHERE id=?',(comment['job'],)).fetchone()
                if job and json.loads(job[0]).get('related_review_pass'):content+='<p>阶段：额外一轮关联复核（包含已批准申请）</p>'
                provider=json.loads(job[0]).get('feedback_provider','local') if job else 'local'
                content+='<p>使用模型：'+('DeepSeek v41f · 低推理' if provider=='deepseek' else '本地离线模型')+'</p>'
            if comment['job_status']=='no_change':
                response=store.db.execute('SELECT result FROM jobs WHERE id=?',(comment['job'],)).fetchone()
                for proposal in json.loads(response[0] or '{}').get('proposals',[]):content+='<p>'+v.esc(proposal.get('explanation') or proposal.get('rationale',''))+'</p>'
            if comment['job_error']:content+='<p class="notice">'+v.esc(comment['job_error'])+'</p>'
            children=list(store.db.execute('SELECT id FROM proposals WHERE job=? UNION SELECT proposal AS id FROM proposal_links WHERE job=?',(comment['job'],comment['job'])))
            if comment['job_status']=='done' and not children:content+='<p>该次旧流程只完成分类，未提交修订申请；不是仍在推理。请补充意见重新提交。</p>'
            for child in children:content+='<a href="/?id='+child['id']+'">查看模型修订提案 →</a><br>'
        content+='</section>'
    content+='<details><summary>技术详情：原始模型意见与 JSON（普通审核无需展开）</summary><pre>'+v.esc(json.dumps(p,ensure_ascii=False,indent=2))+'</pre><form method="post"><input type="hidden" name="csrf" value="'+token+'"><input type="hidden" name="id" value="'+pid+'"><input type="hidden" name="action" value="edit"><label>审核人 <input name="reviewer" value="'+v.esc(reviewer)+'" required></label><textarea name="suggestion">'+v.esc(json.dumps(suggestion,ensure_ascii=False,indent=2))+'</textarea><button>保存高级修改，重新审核</button></form></details>'
    nav_query=dict(filter_query)
    if nav_query.get('status',['pending'])[0] not in {'approved','rejected'}:nav_query['status']=['pending']
    peers=filtered_applications(rows,nav_query);rank={r['row']['id']:i for i,r in enumerate(rows)};at=rank[pid]
    previous=[r for r in peers if rank[r['row']['id']]<at];following=[r for r in peers if rank[r['row']['id']]>at]
    content+='<nav class="nav">'
    if previous:content+='<a href="'+v.esc(url(nav_query,id=previous[-1]['row']['id'],nav='previous' if nav_query.get('status')==['pending'] else 'history'))+'">← 上一片段（当前筛选）</a>'
    if following:content+='<a href="'+v.esc(url(nav_query,id=following[0]['row']['id'],nav='next' if nav_query.get('status')==['pending'] else 'history'))+'">下一片段（当前筛选） →</a>'
    return page(content+'</nav>')
