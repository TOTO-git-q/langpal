const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../frontend/js/sse.js'), 'utf8');
async function run(chunks, {open=false, abort=false}={}) {
  const events=[]; let cancelled=false;
  const context={window:{}, AbortController, TextDecoder, fetch:async () => {
    if(abort) throw new DOMException('cancelled','AbortError');
    return {ok:true, body:new ReadableStream({start(c){chunks.forEach(x=>c.enqueue(x));if(!open)c.close();},cancel(){cancelled=true;}})};
  }};
  vm.runInNewContext(source,context);
  context.window.LP.sse.postChat({persona_id:1,text:'test'}, {
    onDelta:x=>events.push(['delta',x.text]),onDone:()=>events.push(['done']),
    onQueued:()=>events.push(['queued']),onInterrupted:()=>events.push(['interrupted']),onError:x=>events.push(['error',x.message])
  });
  await new Promise(r=>setTimeout(r,20));
  return {events,cancelled};
}
const bytes=s=>new TextEncoder().encode(s);
test('LF, CRLF and CR frames stream incrementally and release open transport',async()=>{
  for(const sep of ['\n','\r\n','\r']) {
    const s=`event: delta${sep}data: {"text":"你好"}${sep}${sep}event: done${sep}data: {}${sep}${sep}`;
    const b=bytes(s); const chunks=Array.from(b,x=>Uint8Array.of(x));
    const result=await run(chunks,{open:true});
    assert.deepEqual(result.events,[['delta','你好'],['done']]);assert.equal(result.cancelled,true);
  }
});
test('terminal event fences later frames and releases transport',async()=>{
 for(const terminal of ['done','queued','interrupted']) {
  const result=await run([bytes(`event: ${terminal}\ndata: {}\n\nevent: delta\ndata: {"text":"late"}\n\n`)],{open:true});
  assert.deepEqual(result.events,[[terminal]]);assert.equal(result.cancelled,true);
 }
});
test('truncated stream and abort each report exactly one error',async()=>{
 assert.deepEqual((await run([])).events,[['error','回复连接提前结束，请重试']]);
 assert.deepEqual((await run([],{abort:true})).events,[['error','连接已取消']]);
});
test('comments, malformed frames, multiline data and final frame at EOF',async()=>{
 const result=await run([bytes(': heartbeat\n\nevent: delta\ndata: invalid\n\nevent: delta\ndata: {\ndata: "text":"ok"}\n\nevent: done\ndata: {}')]);
 assert.deepEqual(result.events,[['delta','ok'],['done']]);
});
