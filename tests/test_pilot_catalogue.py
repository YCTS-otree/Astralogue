from astralogue.adapters.wiki.pilot_catalogue import mission_links


def test_only_mission_rows_expand_queue():
    html='<h2>第一幕</h2><a href="/sr/角色">角色</a><div class="mission-line-child-kt"><div><a href="/sr/任务甲">任务甲</a></div></div><h2>均衡等级突破</h2><div class="mission-line-child-kt"><a href="/sr/试炼">试炼</a></div>'
    assert mission_links(html)==[('任务甲','第一幕')]


def test_persistent_work_schedule_and_quota(tmp_path,monkeypatch):
    from datetime import datetime,timezone,timedelta
    from astralogue.adapters.wiki.pilot import Pilot
    p=Pilot(tmp_path)
    with p.db:p.db.execute("INSERT INTO settings VALUES('work_schedule','enabled')")
    monkeypatch.setattr('astralogue.adapters.wiki.pilot.random.randint',lambda a,b:a)
    def at(hour,minute=0):return datetime(2026,11,3,hour,minute,tzinfo=timezone(timedelta(hours=8))).timestamp()
    assert not p.work_window(at(7)) and p.work_window(at(8))
    for _ in range(4):p.count_cycle_page()
    assert not p.work_window(at(8,5))
    assert not p.work_window(at(8,10)) # Starts the 10-minute rest.
    p.close();p=Pilot(tmp_path)
    assert not p.work_window(at(8,19)) and p.work_window(at(8,20))
    assert not p.work_window(at(12)) and not p.work_window(at(13))
    assert p.work_window(at(14)) and not p.work_window(at(22))
    p.close()
