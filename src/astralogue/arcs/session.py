"""Reader UI session: auditable traversal and snapshot navigation, Runtime unchanged."""
from copy import deepcopy
from pathlib import Path
import tempfile
import time
from astralogue.runtime import Runtime,State,DialogueEvent,ChoiceEvent,Option
from astralogue.player import PlayerProfile,ProfileEvent,validate_name,render
from astralogue.model import load_json,canonical

class ArcSession(Runtime):
    def __init__(self,pack,mission,lang='CHS'):
        super().__init__(pack,mission,lang);self.traversal=[];self.visited=[];self.choice_marks=[]
        self.profile_migration=False;self.migrations=[];self.profile_notice=None
        if self.avatars:self.state.variables.setdefault('player_profile',PlayerProfile().to_dict())
    @property
    def avatars(self):
        meta=self.pack.metadata.get('player_reader',{});avatars=meta.get('avatars',{})
        return {k:avatars[k] for k in meta.get('avatar_order',list(avatars))}
    @property
    def profile(self):
        raw=self.state.variables.get('player_profile',{})
        return PlayerProfile.parse(raw,self.avatars)
    def profile_event(self):
        p=self.profile
        stage=('avatar' if p.avatar_id is None else 'avatar_confirm') if not p.avatar_confirmed else ('name' if p.nickname is None else 'name_confirm')
        return ProfileEvent(self.state.node,stage,p.to_dict(),self.avatars,self.profile_migration)
    def set_story_variable(self,name,value):
        if not isinstance(name,str) or not name or name in {'player_profile','persistent_variables','profile_actions','profile_migration_required','profile_migration_completed','text_diagnostics'} or name.startswith('profile_'):
            raise ValueError('持久变量名称无效或已保留')
        canonical(value)  # Only save-compatible JSON values, no object handles.
        self.state.variables.setdefault('persistent_variables',{})[name]=deepcopy(value)
        self.state.variables[name]=deepcopy(value)
    def continue_to(self,pack,mission):
        if not self.state.node or self.pack.node(self.state.node).kind!='end':raise ValueError('需先抵达当前章节阅读出口')
        if not self.profile.name_confirmed:raise ValueError('需先完成玩家档案')
        rt=ArcSession(pack,mission,self.lang)
        PlayerProfile.parse(self.profile.to_dict(),rt.avatars)
        rt.state.variables['player_profile']=self.profile.to_dict()
        for name,value in self.state.variables.get('persistent_variables',{}).items():rt.set_story_variable(name,self.state.variables.get(name,value))
        rt.state.variables['profile_actions']=deepcopy(self.state.variables.get('profile_actions',[]))
        rt.migrations=[{'chapter_continuation':{'previous_pack':self.pack.metadata['pack_id'],
                       'previous_mission':self.state.mission,'previous_node':self.state.node,
                       'choices':deepcopy(self.state.choices),'audit':deepcopy(self.traversal)},
                       'policy':'explicit_reader_continuation; no new game control relation asserted'}]
        return rt
    def identity_input(self,value):
        """Transactional UI interaction; snapshots and save use the existing State."""
        node=self.pack.node(self.state.node)
        if not self.avatars or (node.data.get('player_action')!='initialize' and not self.profile_migration):
            raise ValueError('当前没有身份初始化事件')
        p=self.profile
        if p.name_confirmed:raise ValueError('身份已认证，普通剧情中不可更换')
        stage=self.profile_event().stage
        before=self.checkpoint()
        if stage=='avatar':
            if value not in self.avatars:raise ValueError('请选择有效载体')
            p.avatar_id=value;p.avatar_name=self.avatars[value]['name']
        elif stage=='avatar_confirm':
            if value=='back':p=PlayerProfile()
            elif value=='confirm':p.avatar_confirmed=True
            else:raise ValueError('请选择确认或返回')
        elif stage=='name':p.nickname=validate_name(value)
        elif stage=='name_confirm':
            if value=='back':p.nickname=None
            elif value=='confirm':p.name_confirmed=True
            else:raise ValueError('请选择确认或重新输入')
        self.visited.append(before)
        self.state.variables['player_profile']=p.to_dict()
        self.state.variables.setdefault('profile_actions',[]).append({'node':node.id,'stage':stage,'value':value})
        if p.name_confirmed:
            if self.profile_migration:
                self.profile_migration=False
                self.state.variables['profile_migration_completed']=True
            else:
                first=next(m for m in self.visited if m['state']['node']==node.id and m['state']['variables'].get('player_profile',{}).get('avatar_id') is None)
                self.choose('confirm')
                self.choice_marks[-1]=deepcopy(first)
                prior=deepcopy(first['state']);prior['choices']=deepcopy(self.state.choices[:first['choice_count']])
                self.history[-1]=prior
    def present(self,text,annotations=()):
        result,issues=render(text,self.profile,self.avatars,annotations)
        for issue in issues:
            row={'node':self.state.node,'diagnostic':issue}
            if row not in self.state.variables.setdefault('text_diagnostics',[]):self.state.variables['text_diagnostics'].append(row)
        return result
    def checkpoint(self):
        state=self.snapshot();count=len(state['choices']);state['choices']=None
        return {'state':state,'choice_count':count,'trace':len(self.traversal),'history':len(self.history),'choice_marks':len(self.choice_marks)}
    def record(self,source,target,value=None):
        edges=[e for e in self.pack.edges(source) if e.target==target and (value is None or e.value==value)]
        if len(edges)!=1:raise ValueError('Arc traversal needs unique explicit edge')
        e=edges[0];self.traversal.append({'edge':e.id,'source':source,'target':target,'value':e.value,'provenance':self.pack.metadata['narrative']['relations'].get(e.id)})
    def _move(self,edge,transition=False):
        source=self.state.node
        super()._move(edge,transition)
        self.record(source,self.state.node,edge.value)
    def next(self,step_limit=1000):
        node=self.pack.node(self.state.node) if self.state.node else None
        if self.avatars and not self.profile.name_confirmed and (self.profile_migration or node and node.data.get('player_action')=='initialize'):
            return self.profile_event()
        if self.avatars and self.profile.name_confirmed and node and node.data.get('player_action')=='initialize':
            self.choose('confirm')
            return self.next(step_limit)
        before=self.checkpoint();event=super().next(step_limit)
        if isinstance(event,DialogueEvent):
            self.visited.append(before)
            node=self.pack.node(event.node)
            return DialogueEvent(event.node,self.present(event.speaker),self.present(event.text,node.data.get('text_parameters',[])))
        if isinstance(event,ChoiceEvent):
            node=self.pack.node(event.node)
            return ChoiceEvent(event.node,tuple(Option(o.value,self.present(o.text,[a for a in node.data.get('text_parameters',[]) if a.get('option') in {None,o.value} and a.get('language',self.lang)==self.lang]),o.target) for o in event.options))
        return event
    def choose(self,value):
        if self.pack.node(self.state.node).data.get('player_action')=='initialize' and not self.profile.name_confirmed:
            raise ValueError('请先完成载体与代号认证')
        mark=self.checkpoint();self.choice_marks.append(mark)
        try:super().choose(value)
        except Exception:self.choice_marks.pop();raise
        self.visited.append(mark)
    def restore(self,mark):
        state=deepcopy(mark['state']);state['choices']=deepcopy(self.state.choices[:mark['choice_count']]) if 'choice_count' in mark else state['choices'];self.state=State(**state);self.traversal=self.traversal[:mark['trace']];self.history=self.history[:mark['history']];self.choice_marks=self.choice_marks[:mark['choice_marks']]
        self.profile_migration=bool(self.state.variables.get('profile_migration_required') and not self.profile.name_confirmed)
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
        if path.resolve()==self.pack.path.resolve():raise ValueError('存档不能覆盖 StoryPack')
        data={'save_schema':1,'pack_id':self.pack.metadata['pack_id'],'pack_version':self.pack.metadata['pack_version'],
              'pack_schema':self.pack.metadata['schema_version'],'language':self.lang,'state':self.snapshot(),'history':self.history,
              'arc_session':{'traversal':self.traversal,'visited':self.visited,'choice_marks':self.choice_marks,'migrations':self.migrations}}
        path.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf8',dir=path.parent,delete=False) as f:
            temporary=Path(f.name);f.write(canonical(data)+'\n')
        try:
            # Windows indexers can transiently hold a just-replaced autosave.
            # Retry atomic replacement; never leave a partial base-only save.
            for attempt in range(6):
                try:temporary.replace(path);break
                except PermissionError:
                    if attempt==5:raise
                    time.sleep(.03*(attempt+1))
        finally:temporary.unlink(missing_ok=True)
    @classmethod
    def load(cls,pack,path):
        base=Runtime.load(pack,path);data=load_json(path).get('arc_session')
        if data is None:raise ValueError('Story Arc save is missing audit context')
        rt=cls(pack,base.state.mission,base.lang);rt.state=base.state;rt.history=base.history
        rt.traversal=data['traversal'];rt.visited=data['visited'];rt.choice_marks=data['choice_marks']
        rt.migrations=data.get('migrations',[])
        if not rt.avatars and 'player_profile' not in rt.state.variables:
            rt.profile_notice='此旧数据包不含载体与代号定义，当前进度已保留；如需玩家身份，请使用 arcs migrate-save 显式迁移到增强包。'
        if rt.avatars:
            for state in [rt.snapshot(),*rt.history,*[m['state'] for m in rt.visited+rt.choice_marks]]:
                PlayerProfile.parse(state['variables'].get('player_profile',{}),rt.avatars)
            if 'player_profile' not in rt.state.variables:
                rt.profile_migration=True;rt.state.variables['profile_migration_required']=True
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


def migrate_save(old_pack,new_pack,path,output):
    """Explicit progress migration, preserving old audit as an immutable receipt.

    Rewind across an altered graph is intentionally not synthesized. The prior
    choices/audit remain inspectable in the receipt; new snapshots start here.
    """
    from astralogue.model import digest,file_hash
    if output.resolve() in {path.resolve(),old_pack.path.resolve(),new_pack.path.resolve()}:
        raise ValueError('迁移输出必须使用新文件，保留原存档与数据包')
    old=ArcSession.load(old_pack,path);mid=old.state.mission
    previous=old_pack.metadata['story_arcs'][mid];current=new_pack.metadata['story_arcs'][mid]
    if digest(previous['plan'])!=digest(current['plan']) or previous['hf']['revision']!=current['hf']['revision']:
        raise ValueError('章节或来源版本变化，不能自动迁移')
    old_source=old_pack.metadata.get('mission_manifest',{}).get('source')
    new_source=new_pack.metadata.get('mission_manifest',{}).get('source')
    if not old_source or old_source!=new_source or any(previous['hf']['files'][t['hf']]['sha256']!=current['hf']['files'][t['hf']]['sha256'] for t in current['plan']['tasks']):
        raise ValueError('游戏版本或转录资源哈希变化，不能自动迁移')
    target=new_pack.node(old.state.node);source=old_pack.node(old.state.node)
    if target.mission!=mid or target.kind!=source.kind or target.data.get('hf_index')!=source.data.get('hf_index'):
        raise ValueError('当前位置结构已变化，需要人工迁移')
    rt=ArcSession(new_pack,mid,old.lang);initial=deepcopy(rt.state.variables);rt.state=deepcopy(old.state)
    for key,value in initial.items():
        if key!='player_profile':rt.state.variables.setdefault(key,value)
    converted=[]
    for choice in old.state.choices:
        node=new_pack.node(choice['node']);value=choice['value']
        if node.kind=='dialogue' and node.data.get('selected_option_echo'):
            continue  # This old click is retained verbatim in the migration receipt.
        edges=[e for e in new_pack.edges(node.id) if e.kind=='option' and e.value==value]
        if not edges and value=='recorded':
            edges=[e for e in new_pack.edges(node.id) if e.kind=='option' and e.value==node.data.get('recorded_value')]
        if len(edges)!=1:raise ValueError('旧选择无法映射，迁移已停止')
        e=edges[0];converted.append({'node':node.id,'edge':e.id,'value':e.value})
        if node.data.get('reader_action')=='optional_inquiry':
            key=node.id+':asked:'+e.value
            if key in rt.state.variables:rt.state.variables[key]=True
    rt.state.choices=converted
    rt.migrations=deepcopy(old.migrations)+[{'save_sha256':file_hash(path),'old_pack_id':old_pack.metadata['pack_id'],
        'new_pack_id':new_pack.metadata['pack_id'],'position':old.state.node,'choices':deepcopy(old.state.choices),
        'traversal':deepcopy(old.traversal),'rewind_boundary':'old audit retained; navigation resumes from this explicit migration'}]
    if 'player_profile' not in rt.state.variables:
        rt.state.variables['profile_migration_required']=True;rt.profile_migration=True
    else:PlayerProfile.parse(rt.state.variables['player_profile'],rt.avatars)
    rt.save(output)
    return rt
