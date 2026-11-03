"""Small, cached BWIKI adapter. Branch boundaries come from template parameters."""
from datetime import datetime, timezone
from pathlib import Path
import html
import json
import re
import urllib.parse
import urllib.request

from astralogue.model import load_json, file_hash
from astralogue.adapters.hf import write


def fetch(title: str, output: Path, proxy: str | None = None):
    if output.exists():
        data = load_json(output)
        if data['parse']['title'] != title:
            raise ValueError('Cached page title mismatch')
        return data
    url = 'https://wiki.biligame.com/sr/api.php?' + urllib.parse.urlencode(
        {'action': 'parse', 'page': title, 'prop': 'wikitext|text|revid', 'format': 'json'})
    handlers = [urllib.request.ProxyHandler({'https': proxy})] if proxy else []
    request = urllib.request.Request(url, headers={'User-Agent': 'Astralogue offline narrative research/1.10'})
    with urllib.request.build_opener(*handlers).open(request, timeout=30) as response:
        data = json.load(response)
    if 'parse' not in data:
        raise ValueError('BWIKI returned no page content')
    data['retrieval'] = {'url': url, 'fetched_at': datetime.now(timezone.utc).isoformat()}
    write(output, data)
    return data


def split_parameters(text):
    parts = []; start = 0; depth = 0; links = 0; i = 0
    while i < len(text):
        token = text[i:i+2]
        if token == '{{': depth += 1; i += 2; continue
        if token == '}}': depth -= 1; i += 2; continue
        if token == '[[': links += 1; i += 2; continue
        if token == ']]': links -= 1; i += 2; continue
        if text[i] == '|' and depth == links == 0:
            parts.append(text[start:i]); start = i + 1
        i += 1
    parts.append(text[start:]); return parts


def templates(text):
    stack = []; result = []; i = 0
    while i < len(text)-1:
        token = text[i:i+2]
        if token == '{{': stack.append(i); i += 2; continue
        if token == '}}':
            if not stack: raise ValueError('Unbalanced wikitext template')
            start = stack.pop(); raw = text[start+2:i]; args = split_parameters(raw)
            params = {}; positional = []
            for value in args[1:]:
                key, sep, content = value.partition('=')
                if sep:
                    if key.strip() in params: raise ValueError('Duplicate template parameter')
                    params[key.strip()] = content.strip()
                else: positional.append(value.strip())
            result.append({'name': args[0].strip(), 'params': params, 'args': positional,
                           'start': start, 'end': i+2, 'raw': text[start:i+2]})
            i += 2; continue
        i += 1
    if stack: raise ValueError('Unbalanced wikitext template')
    return sorted(result, key=lambda x: x['start'])


def inline(text):
    """Retain resource positions; never infer an action from an item icon."""
    media = []; unknown = []
    # Innermost templates first, preserving original positions in media records.
    original = text
    # A dialogue line may close an enclosing multiline fold/template. Those
    # delimiters belong to its container, not to the line's inline content.
    while text.rstrip().endswith('}}') and text.count('}}') > text.count('{{'):
        text = text.rstrip()[:-2]
    for t in reversed(templates(text)):
        name = t['name']; a = t['args']; replacement = None
        if name in {'颜色', '注音'} and a: replacement = a[-1] if name == '颜色' else a[0]
        elif name == '黑幕' and a:
            replacement = ''; media.append({'type': 'editor_annotation', 'description': a[0],
                'start': t['start'], 'end': t['end'], 'raw': t['raw'], 'display': '（Wiki 注释：'+a[0]+'）'})
        elif name == '图标' and a:
            replacement = ''; media.append({'type': 'icon', 'description': a[0], 'start': t['start'],
                'end': t['end'], 'raw': t['raw'], 'display': '（Wiki 图标展示：'+a[0]+'）'})
        elif name in {'剧情选项', '选项图标'}: replacement = ''
        if replacement is None: unknown.append(t['raw']); continue
        # Do not apply nested offsets after an outer substitution has changed them.
        text = text.replace(t['raw'], replacement)
    def image(match):
        fields = match[1].split('|'); alt = next((v[4:] for v in fields[1:] if v.startswith('alt=')), None)
        title=next((v[6:] for v in fields[1:] if v.startswith('title=')),None);desc=alt or title
        record = {'type': 'image', 'resource': fields[0], 'description': desc, 'alt':alt, 'title':title, 'raw': match[0],
                  'start': match.start(), 'end': match.end(), 'display': '（Wiki 图片展示：'+desc+'）' if desc else None}
        media.append(record)
    pattern=r'\[\[(?:File|文件|Image):([^\]]+)\]\]'
    for match in re.finditer(pattern,original,re.I):image(match)
    text = re.sub(pattern, '', text, flags=re.I)
    text = re.sub(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', lambda m: m[2] or m[1], text)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]*>', '', text)
    return {'text': html.unescape(text).strip(), 'media': media, 'unknown': unknown, 'raw': original}


def dialogue_body(text):
    rows = []; unknown = []
    for line in text.splitlines():
        if not line.strip(): continue
        m = re.fullmatch(r'\*([^：\n]+)：(.*)', line.strip())
        if not m: unknown.append(line); continue
        try:
            parsed = inline(m[2])
        except ValueError:
            # A nested multiline template may begin on a speaker line. Keep
            # the complete parent raw structure; never flatten its branches.
            unknown.append(line)
            continue
        rows.append({'speaker': m[1], **parsed})
        unknown += parsed['unknown']
    return rows, unknown


def parse_page(path: Path):
    data = load_json(path); p = data['parse']; text = p['wikitext']['*']
    start = text.index('==剧情内容=='); body = text[start:]; choices = []
    for t in templates(body):
        if t['name'] != '剧情选项': continue
        options = []; unknown = []
        numbers = [int(k[2:]) for k in t['params'] if re.fullmatch('选项[0-9]+', k)]
        for n in sorted(numbers):
            label = inline(t['params']['选项'+str(n)]); rows, errors = dialogue_body(t['params'].get('剧情'+str(n), ''))
            options.append({'value': str(n), 'label': label, 'body': rows}); unknown += errors + label['unknown']
        choices.append({'start': start+t['start'], 'end': start+t['end'], 'raw': t['raw'],
                        'options': options, 'unknown': unknown})
    stages=[]
    for t in templates(body):
        if t['name']=='颜色' and len(t['args'])>=2 and t['args'][0]=='描述':
            stages.append({'kind':'source_direction','start':start+t['start'],'end':start+t['end'],**inline(t['args'][1])})
        elif t['name']=='任务描述':
            stages.append({'kind':'task_hint','start':start+t['start'],'end':start+t['end'],'raw':t['raw'],'arguments':t['args']})
    return {'title': p['title'], 'page_id': p['pageid'], 'revision_id': p['revid'],
            'url': 'https://wiki.biligame.com/sr/'+urllib.parse.quote(p['title']),
            'snapshot_sha256': file_hash(path), 'wikitext': text, 'choices': choices, 'stage_directions':stages,
            'retrieval': data.get('retrieval', {}), 'source': 'BWIKI community transcription; original game rights separate'}
