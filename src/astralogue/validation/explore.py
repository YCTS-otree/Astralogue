"""Bounded automatic exploration through the same runtime used by the CLI."""
from collections import deque
from copy import deepcopy

from astralogue.model import canonical
from astralogue.runtime import BlockedEvent, ChoiceEvent, DialogueEvent, EndEvent, Runtime
from astralogue.storypack import StoryPack


def explore(pack: StoryPack, mission: str, lang: str = "CHS", max_states: int = 1000, max_steps: int = 10000) -> dict:
    if max_states < 1 or max_steps < 1: raise ValueError("探索上限必须为正数")
    queue = deque([Runtime(pack, mission, lang)])
    seen, endings, blocked, choices = set(), [], [], set()
    merged = 0
    dialogues = set()
    steps = 0
    truncated = False
    while queue:
        rt = queue.popleft()
        while steps < max_steps:
            state = rt.snapshot()
            state.pop("choices")
            marker = canonical(state)
            if marker in seen:
                merged += 1; break
            if len(seen) >= max_states:
                truncated = True; break
            seen.add(marker); steps += 1
            event = rt.next()
            if isinstance(event, DialogueEvent): dialogues.add(event.node)
            if isinstance(event, ChoiceEvent):
                for opt in event.options:
                    choices.add((event.node, opt.value, opt.target))
                    child = Runtime(pack, rt.state.mission, lang)
                    child.state = deepcopy(rt.state)
                    child.choose(opt.value)
                    queue.append(child)
                break
            if isinstance(event, EndEvent):
                endings.append({"node": event.node, "choices": rt.state.choices}); break
            if isinstance(event, BlockedEvent):
                blocked.append({"node": event.node, "code": event.code, "reason": event.reason}); break
        if truncated or steps >= max_steps:
            truncated = True; break
    return {"states": len(seen), "steps": steps, "endings": endings, "blocked": blocked, "truncated": truncated,
            "choices_explored": [{"node": n, "value": v, "target": t} for n, v, t in sorted(choices)], "merged_states": merged,
            "dialogue_nodes": sorted(dialogues),
            "note": "相同执行状态合并；此报告不穷举任意初始变量或原游戏外部事件"}
