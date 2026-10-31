"""Reader UI session: auditable traversal and snapshot navigation, Runtime unchanged."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from astralogue.runtime import Runtime,State,DialogueEvent,ChoiceEvent
from astralogue.model import load_json
from astralogue.adapters.hf import write

class ArcSession(Runtime):
    def __init__(self,pack,mission,lang='CHS'):
        super().__init__(pack,mission,lang);self.traversal=[];self.visited=[];self.choice_marks=[]
    def checkpoint(self):
        state=self.snapshot();count=len(state['choices']);state['choices']=None
        return {'state':state,'choice_count':count,'trace':len(self.traversal),'history':len(self.history),'choice_marks':len(self.choice_marks)}
    def record(self,source,target,value=None):
        edges=[e for e in self.pack.edges(source) if e.target==target and (value is None or e.value==value)]
        if len(edges)!=1:raise ValueError('Arc traversal needs unique explicit edge')
        e=edges[0];self.traversal.append({'edge':e.id,'source':source,'target':target,'value':e.value,'provenance':self.pack.metadata['narrative']['relations'].get(e.id)})
    def next(self,step_limit=1000):
        before=self.checkpoint();event=super().next(step_limit)
        if isinstance(event,DialogueEvent):
            self.visited.append(before);self.record(event.node,self.state.node)
        return event
    def choose(self,value):
        mark=self.checkpoint();self.choice_marks.append(mark)
        try:super().choose(value)
        except Exception:self.choice_marks.pop();raise
        self.visited.append(mark);self.record(mark['state']['node'],self.state.node,value)
    def restore(self,mark):
        state=deepcopy(mark['state']);state['choices']=deepcopy(self.state.choices[:mark['choice_count']]) if 'choice_count' in mark else state['choices'];self.state=State(**state);self.traversal=self.traversal[:mark['trace']];self.history=self.history[:mark['history']];self.choice_marks=self.choice_marks[:mark['choice_marks']]
    def previous(self):
        if not self.visited:raise ValueError('没有已访问内容')
        self.restore(self.visited.pop())
    def back(self):
        if not self.choice_marks:raise ValueError('没有可回溯选择')
        mark=self.choice_marks[-1];self.restore(mark)
        self.visited=[m for m in self.visited if m['trace']<mark['trace']]
    def progress(self):
        meta=self.pack.metadata['story_arcs'][self.state.mission];node=self.pack.node(self.state.node)
        task=node.data.get('task');return {'chapter':meta['plan']['title'],'task':task+1 if task is not None else None,'total_tasks':len(meta['plan']['tasks']),'task_title':meta['plan']['tasks'][task]['title'] if task is not None else None,'edges':len(self.traversal)}
    def save(self,path):
        super().save(path);data=load_json(path);data['arc_session']={'traversal':self.traversal,'visited':self.visited,'choice_marks':self.choice_marks};write(path,data)
    @classmethod
    def load(cls,pack,path):
        base=Runtime.load(pack,path);data=load_json(path).get('arc_session')
        if data is None:raise ValueError('Story Arc save is missing audit context')
        rt=cls(pack,base.state.mission,base.lang);rt.state=base.state;rt.history=base.history
        rt.traversal=data['traversal'];rt.visited=data['visited'];rt.choice_marks=data['choice_marks']
        for row in rt.traversal:
            if not any(e.id==row['edge'] and e.target==row['target'] for e in pack.edges(row['source'])):raise ValueError('Invalid saved arc trace')
        for mark in rt.visited+rt.choice_marks:
            state=mark['state'];node=pack.node(state['node'])
            if state['mission'] not in pack.metadata['story_arcs'] or node.mission!=state['mission'] or not 0<=mark['choice_count']<=len(rt.state.choices) or not 0<=mark['trace']<=len(rt.traversal):raise ValueError('Invalid saved arc navigation')
        return rt

def session(pack,mission,lang='CHS'):
    return ArcSession(pack,mission,lang) if mission in pack.metadata.get('story_arcs',{}) else Runtime(pack,mission,lang)
def load_session(pack,path):
    saved=load_json(path)
    return ArcSession.load(pack,path) if saved['state']['mission'] in pack.metadata.get('story_arcs',{}) else Runtime.load(pack,path)
