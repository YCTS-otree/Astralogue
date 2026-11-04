"""Exact task-scoped source bindings; formatting whitespace is not narrative order."""
import re
from pathlib import Path
from astralogue.adapters.wiki import normalize
from astralogue.adapters.wiki.bwiki import inline
from astralogue.storypack import StoryPack


def source_key(text):
    return re.sub(r"\s+","",normalize(text))


def bind_sources(store,context):
    path=store.setting('publication_pack')
    if not path:return
    title=(context.get('task') or {}).get('title')
    with StoryPack(Path(path)) as pack:
        scopes=[(mid,i) for mid,arc in pack.metadata.get('story_arcs',{}).items()
                for i,task in enumerate(arc.get('plan',{}).get('tasks',[])) if task.get('title')==title]
        if len(scopes)!=1:return
        mid,index=scopes[0];bundle=pack.bundle()
        candidates=[n for n in bundle.nodes if n.mission==mid and n.kind=='dialogue' and n.data.get('task')==index]
        for alias,item in context.get('instances',{}).items():
            if item.get('node') or item.get('kind')!='wiki_source_instance':continue
            raw=item.get('text','');raw=raw.get('CHS','') if isinstance(raw,dict) else raw
            needle=source_key(inline(raw)['text'])
            matches=[n for n in candidates if needle and source_key(bundle.texts.get(n.text,{}).get('CHS',''))==needle]
            if len(matches)!=1:continue
            n=matches[0]
            item.update({'node':n.id,'kind':'dialogue','source_raw_text':raw,'text':bundle.texts.get(n.text,{}),
                         'speaker':bundle.texts.get(n.speaker,{}),'data':n.data,
                         'binding_evidence':{'method':'unique_task_scoped_text_ignoring_formatting_whitespace','source':item.get('source')}})
