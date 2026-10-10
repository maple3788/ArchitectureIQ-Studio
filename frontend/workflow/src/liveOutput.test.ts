import { describe, expect, it } from 'vitest';
import { appendStreamEvent, emptyStream, matchingStream } from './streamState';

describe('live model output', () => {
  const event = (seq:number, text:string, extra:any={}) => ({seq,wire_key:'wire-0',node_id:'solver',round_index:1,operation_key:'q1',kind:'chunk',chunk:{choices:[{index:0,delta:{content:text}}]},...extra});
  it('appends real deltas once and separates server reasoning from response text', () => {
    let s=appendStreamEvent(emptyStream(),event(1,'你'));
    s=appendStreamEvent(s,event(1,'你'));
    s=appendStreamEvent(s,event(2,'', {chunk:{choices:[{index:0,delta:{reasoning_content:'checking'}}]}}));
    s=appendStreamEvent(s,event(3,'好'));
    expect(s.calls['wire-0'].content).toBe('你好');
    expect(s.calls['wire-0'].reasoning).toBe('checking');
    expect(s.calls['wire-0'].done).toBe(false);
  });
  it('a transport done does not pretend to be a committed answer', () => {
    const s=appendStreamEvent(appendStreamEvent(emptyStream(),event(1,'{"ranking":')),event(2,'',{kind:'done',chunk:null}));
    expect(s.calls['wire-0'].done).toBe(true);
    expect(s.calls['wire-0'].content).toBe('{"ranking":');
    expect((s.calls['wire-0'] as any).ranking).toBeUndefined();
  });
  it('does not mix operations, rounds, nodes, or retry identities', () => {
    let s=appendStreamEvent(emptyStream(),event(1,'first'));
    s=appendStreamEvent(s,event(2,'second',{wire_key:'wire-1',round_index:2}));
    expect(matchingStream(s,'solver',1,'q1')?.content).toBe('first');
    expect(matchingStream(s,'solver',2,'q1')?.content).toBe('second');
    expect(matchingStream(s,'discoverer',1,'q1')).toBeUndefined();
    expect(matchingStream(s,'solver',1,'q2')).toBeUndefined();
    expect(matchingStream(s,'solver',undefined,undefined)).toBeUndefined();
  });
});

it('keeps previous output when a raw journal chunk has malformed choices', () => {
  const base={wire_key:'w',node_id:'solver',round_index:1,operation_key:'q',kind:'chunk'};
  let state=appendStreamEvent(emptyStream(),{...base,seq:1,chunk:{choices:[{index:0,delta:{content:'valid'}}]}});
  for(const choices of [{invalid:true},[null,3,{delta:null}],'wrong'])state=appendStreamEvent(state,{...base,seq:state.lastSeq+1,chunk:{choices}});
  expect(state.calls.w.content).toBe('valid');
});
