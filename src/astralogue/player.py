"""Reader identity and presentation variables; raw evidence is never rewritten."""
from dataclasses import dataclass, asdict
import re
import unicodedata


@dataclass
class PlayerProfile:
    avatar_id: str | None = None
    avatar_name: str | None = None
    nickname: str | None = None
    avatar_confirmed: bool = False
    name_confirmed: bool = False
    profile_version: int = 1

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, value, avatars):
        try:
            p = cls(**value)
        except (TypeError, ValueError) as ex:
            raise ValueError('玩家档案字段无效') from ex
        if p.profile_version != 1 or type(p.avatar_confirmed) is not bool or type(p.name_confirmed) is not bool:
            raise ValueError('玩家档案版本/确认状态无效')
        if p.avatar_id is not None:
            if p.avatar_id not in avatars or avatars[p.avatar_id]['name'] != p.avatar_name:
                raise ValueError('玩家载体与数据包身份定义不兼容')
        elif p.avatar_name is not None or p.avatar_confirmed:
            raise ValueError('玩家载体缺失')
        if p.nickname is not None:
            validate_name(p.nickname)
        if p.name_confirmed and (not p.avatar_confirmed or p.nickname is None):
            raise ValueError('玩家代号确认状态无效')
        return p


def validate_name(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('代号不能为空或全为空白')
    # Application limit, not a claim about the game's nickname limit.
    if len(value) > 32:
        raise ValueError('Astralogue 应用限制：代号最多 32 个 Unicode 字符')
    if any(unicodedata.category(c).startswith('C') or c in '\u2028\u2029' for c in value):
        raise ValueError('代号不能包含控制、格式或换行字符')
    return value.strip()


@dataclass(frozen=True)
class ProfileEvent:
    node: str
    stage: str
    profile: dict
    avatars: dict
    migration: bool = False


def render(text, profile, avatars, annotations=()):
    """Return presentation and unresolved markers; annotations are offset-bound."""
    diagnostics = []
    for a in sorted(annotations, key=lambda x: x['start'], reverse=True):
        if text[a['start']:a['end']] != a['literal']:
            diagnostics.append('stale_text_annotation')
            continue
        if a['parameter'] == 'nickname' and profile.name_confirmed:
            text = text[:a['start']] + profile.nickname + text[a['end']:]
    if profile.name_confirmed:
        text = text.replace('{NICKNAME}', profile.nickname)
    gender = avatars.get(profile.avatar_id, {}).get('text_variant')
    if gender in {'M', 'F'}:
        text = re.sub(r'\{([MF])#([^{}]*)\}', lambda m: m[2] if m[1] == gender else '', text)
    diagnostics += ['unresolved_placeholder:' + x for x in re.findall(r'\{[^{}]+\}', text)]
    text = re.sub(r'</?(?:color|size)(?:=[^>]*)?>', '', text, flags=re.I)
    return text, diagnostics
