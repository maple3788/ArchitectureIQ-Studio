import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Questions } from "./Questions";

afterEach(()=>{cleanup();vi.unstubAllGlobals();});
it("opens catalog details in the shared reader with a short title and exact prompt and provenance available",async()=>{
  const calls:{path:string;method:string}[]=[];
  vi.stubGlobal("fetch",async(path:string,init?:RequestInit)=>{
    calls.push({path,method:init?.method||"GET"});
    const value=path.startsWith("/api/studio/questions?") ? {items:[{key:"q_short@long-revision",id:"q_short",family:"bigram_lm",type:"mixed",model_types:["gru_lm"],choices:2,budget:8192,ready:true,issues:[],source_count:1}],total:1}
      : path==="/api/studio/sources" ? {items:[],total:0}
        : {metadata:{id:"q_short",key:"q_short@long-revision",family:"bigram_lm",type:"mixed"},detail:{prompt:"Exact original\n<answer>A</answer>",choices:[{letter:"A",files:{"candidate_spec.json":{model:{type:"gru_lm",num_layers:1}}}},{letter:"B",files:{"candidate_spec.json":{model:{type:"gru_lm",num_layers:2}}}}]},sources:[{origin:"frozen-source.json#q_short"}]};
    return new Response(JSON.stringify(value),{status:200});
  });
  render(<Questions version={0} act={async operation=>operation()} onSet={()=>{}}/>);
  fireEvent.click(await screen.findByRole("button",{name:"打开 q_short"}));
  await screen.findByRole("tab",{name:"题目概览"});
  expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe("二元序列建模 · 混合对比");
  expect(screen.getByRole("heading",{name:"候选对比"})).toBeTruthy();
  const provenance=screen.getByText("来源与记录标识").closest("details")!;
  expect(provenance.open).toBe(false);
  fireEvent.click(screen.getByText("来源与记录标识"));
  expect(screen.getByText("frozen-source.json#q_short")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab",{name:"原始 Prompt"}));
  expect(screen.getByRole("article",{name:"公开题面"}).textContent).toBe("Exact original\n<answer>A</answer>");
  fireEvent.click(screen.getByRole("button",{name:"关闭详情"}));
  await waitFor(()=>expect(screen.queryByRole("dialog")).toBeNull());
  expect(calls.every(call=>call.method==="GET")).toBe(true);
});
