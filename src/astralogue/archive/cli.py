from pathlib import Path
from typing import Annotated
import json
import typer
from . import Archive, build
app=typer.Typer(no_args_is_help=True)
@app.command('build')
def build_cmd(source:Path, output:Path=Path('data/archive.sqlite'), pack:list[Path]=typer.Option([]), force:bool=False):
    from astralogue.cli import errors
    with errors():typer.echo(json.dumps(build(source,pack,output,force),ensure_ascii=False))
@app.command()
def recover(database:Path=Path('data/archive.sqlite'), output:Path=Path('data/archive-tasks.json')):
    with Archive(database) as a:
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(a.tasks(),ensure_ascii=False,indent=2),encoding='utf8')
@app.command()
def coverage(database:Path=Path('data/archive.sqlite')):
    with Archive(database) as a:typer.echo(json.dumps(a.coverage(),ensure_ascii=False))
def browse(database:Path=Path('data/archive.sqlite'),chapter:str|None=None,mission:str|None=None,speaker:str|None=None,search:str='',orphans:bool=False,json_output:bool=False,category:str|None=None):
    from astralogue.cli import console,errors
    with errors(),Archive(database) as a:
        page=0
        while True:
            rows=a.search(search,mission,chapter,speaker,orphans,page*20,category=category)
            if json_output:typer.echo(json.dumps(rows,ensure_ascii=False));return
            console.print('当前显示为资料浏览顺序，非已验证剧情发生顺序。',markup=False)
            for i,r in enumerate(rows,1):console.print(f"{i}. [{r['id']}] 【{r['speaker'] or '未标注'}】{r['text']}",markup=False)
            try:answer=console.input('n 下一页 / p 上一页 / 编号查看来源与关系 / q 返回 > ').strip()
            except (EOFError,KeyboardInterrupt):return
            if answer in {'q',':quit'}:return
            if answer=='n':page+=1
            elif answer=='p':page=max(0,page-1)
            elif answer.isdecimal() and 1<=int(answer)<=len(rows):
                detail=a.detail(rows[int(answer)-1]['id']);console.print(json.dumps(detail,ensure_ascii=False,indent=2),markup=False)
