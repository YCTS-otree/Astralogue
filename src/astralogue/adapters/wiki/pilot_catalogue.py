"""Only actual rendered mission rows create crawl candidates."""
from html.parser import HTMLParser
from urllib.parse import unquote


def mission_links(text):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__();self.stack=[];self.heading=False;self.chapter='';self.result=[]
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='h2':self.heading=True;self.chapter=''
            if tag=='div':self.stack.append('mission-line-child-kt' in a.get('class','').split())
            if tag=='a' and any(self.stack) and a.get('href','').startswith('/sr/') and '均衡等级' not in self.chapter:
                title=unquote(a['href'][4:]).replace('_',' ')
                if ':' not in title and '?' not in title:self.result.append((title,self.chapter.strip()))
        def handle_endtag(self,tag):
            if tag=='div' and self.stack:self.stack.pop()
            if tag=='h2':self.heading=False
        def handle_data(self,data):
            if self.heading:self.chapter+=data
    p=Parser();p.feed(text)
    return list(dict.fromkeys(p.result))
