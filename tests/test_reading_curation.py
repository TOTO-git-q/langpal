"""Offline actual-route regression; extract function to avoid providers/production DB imports."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

BASE=Path(__file__).parent
source=ast.parse((BASE.parent/'backend/app/routers/reading.py').read_text(encoding='utf8'))
func=next(n for n in source.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='news')
func.decorator_list=[]
for arg in [*func.args.args,*func.args.kwonlyargs]: arg.annotation=None
func.returns=None
module=ast.fix_missing_locations(ast.Module(body=[func],type_ignores=[]))
class HTTPException(Exception): pass
async def run():
    full=[{'title':f'Original {i}','text':'Original words '*30,'url':f'https://example.org/{i}','source':'NASA','feedOnly':False} for i in range(8)]
    summary={'title':'BBC summary','text':'Short summary.','url':'https://example.org/summary','source':'BBC World','feedOnly':True}
    async def news(lang,sources): return {'items':[*full,summary],'unavailable':[]}
    calls=[]
    async def screen(*args): calls.append(args); raise HTTPException('offline')
    env={'asyncio':asyncio,'Query':lambda x,**kw:x,'HTTPException':HTTPException,
         'selected_format':lambda *a:None,'select_sources':lambda *a:[{'builtin':True,'id':'builtin-nasa','name':'NASA'}],
         'Depends':lambda f:True,'private_fetch_allowed':None,
         'reading_sources':SimpleNamespace(collect=lambda kind,rows,lang,include_private:news(lang,rows)),
         'reading':SimpleNamespace(news=news),
         'reading_formats':SimpleNamespace(limits=lambda *a:(15,1400),article_length=lambda *a:60,allowed=lambda *a:True,profiles=lambda *a:{'daily':{'label':'Daily reading'}}),
         'screen_candidates':screen}
    exec(compile(module,'actual_reading_route','exec'),env)
    route=env['news']
    links=await route('en',view='links')
    assert len(links['items'])==9 and links['items'][0]['text']==full[0]['text']
    assert links['has_candidates'] and not calls
    assert all('format' not in row for row in links['items'])
    failed=await route('en')
    assert len(failed['items'])==9 and failed['curation_pending']
    assert failed['items'][0]['curation_status']=='unavailable'
    assert all('format' not in row for row in failed['items'])
    async def partial(*args): return [None,{'format':'daily','level':'B2'},None,None,None,None]
    env['screen_candidates']=partial
    result=await route('en')
    assert result['items'][0]['title']=='Original 1'
    assert result['items'][0]['format']=='Daily reading'
    assert result['items'][1]['title']=='Original 0'
    assert len(result['items'])==9
    assert all('format' not in row for row in result['items'][1:])
    assert result['items'][6]['curation_status']=='pending'
    assert result['items'][-1]['feedOnly']
    filtered=await route('en',min_length=50,max_length=80)
    assert len(filtered['items'])==8 and not any(x.get('feedOnly') for x in filtered['items'])
    print('PASS: immediate original reading without screening; provider failure retains 8 originals; accepted order retained; rejected/unreviewed readable without exam badge; explicit range still applies; no network/model/DB imports.')
asyncio.run(run())
