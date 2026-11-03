"""Evidence-preserving section inventory, not an automatic world-state simulator."""
import re
from .bwiki import templates, dialogue_body
from astralogue.model import digest


def classify_page(page):
    text = page['wikitext']; sections = []
    # Parse the complete balanced document before assigning section ownership.
    # Headings can occur inside a multiline fold; slicing first breaks it.
    document_templates = templates(text)
    headers = list(re.finditer(r'^===\s*(.*?)\s*===\s*$', text, re.M))
    for i, h in enumerate(headers):
        end = headers[i+1].start() if i+1<len(headers) else len(text)
        section = {'id':'bwiki-section:'+digest([page['page_id'],h.group(1)])[:24],
                   'title':h.group(1),'start':h.start(),'end':end,'interactions':[]}
        for t in document_templates:
            if not h.end() <= t['start'] < end: continue
            if t['name'] != '折叠': continue
            title = t['params'].get('标题',''); body = t['params'].get('内容','')
            rows, unknown = dialogue_body(body)
            # "调查" alone proves neither optional status nor mainline status.
            kind = 'optional_dialogue' if title.startswith('额外对话') else 'unknown'
            section['interactions'].append({'id':'bwiki-interaction:'+digest([page['page_id'],h.group(1),t['start']])[:24],
                'label':title,'kind':kind,'rows':rows,'unknown':unknown,
                'repeat_policy':'unknown','availability':'unknown','affects_mainline':'unknown',
                'source':{'page_id':page['page_id'],'revision_id':page['revision_id'],
                          'sha256':page['snapshot_sha256'],'start':t['start'],'raw':t['raw']},
                'evidence_level':'WIKI_ALIGNED','raw':body})
        sections.append(section)
    return {'title':page['title'],'page_id':page['page_id'],'revision_id':page['revision_id'],
            'sha256':page['snapshot_sha256'],'sections':sections,
            'choices':page['choices'],'stage_directions':page['stage_directions']}
