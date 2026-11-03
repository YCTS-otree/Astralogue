from pathlib import Path
import pytest
from astralogue.accounts import Account, AccountStore, allowed_scope
from astralogue.storypack import StoryPack


def test_scope_is_fail_closed_for_other_packs(pack_path):
    with StoryPack(pack_path) as p:
        with pytest.raises(ValueError,match='仅开放'):allowed_scope(p,Account('id','普通用户'))
        assert allowed_scope(p,Account('id','0')) is None


def test_real_only_first_task_in_scope():
    path=Path('data/packs/prologue-exploration-v112.storypack')
    if not path.exists():pytest.skip('Real prologue pack unavailable')
    with StoryPack(path) as p:
        scope=allowed_scope(p,Account('id','玩家'))
        arc=next(iter(p.metadata['story_arcs'].values()))
        assert arc['task_boundaries'][0]['entry'] in scope['nodes']
        assert arc['task_boundaries'][0]['exit']==scope['exit']
        assert all(b['entry'] not in scope['nodes'] for b in arc['task_boundaries'][1:])


def test_duplicate_registration_keeps_entire_record(tmp_path):
    with AccountStore(tmp_path) as s:
        a=s.register('Alice','test')
        before=tuple(s.con.execute('SELECT * FROM accounts WHERE id=?',(a.id,)).fetchone())
        with pytest.raises(ValueError,match='已存在'):s.register('ＡＬＩＣＥ','replacement')
        assert tuple(s.con.execute('SELECT * FROM accounts WHERE id=?',(a.id,)).fetchone())==before
        assert s.login('Alice','test')==a
