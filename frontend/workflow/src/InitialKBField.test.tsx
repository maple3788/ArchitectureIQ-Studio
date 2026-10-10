import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, within} from '@testing-library/react';
import {InitialKBField} from './InitialKBField';

const items = [
 {id:'formal-hash',version:'v1',kind:'formal',name:'已验证的优化器规律',counts:{verified_enabled:2,records:3},snapshot:{claims:[{id:'c',text:'小批量下需要调整学习率',status:'replicated_in_scope',enabled:true}]}},
 {id:'experience-hash',version:'v2',kind:'experience',name:'多元回归 · 学习经验',counts:{active_lessons:1,lessons:1,episodes:2},snapshot:{lessons:[{id:'l',status:'active',text:'先检查目标函数是否振荡',conditions:['目标具有周期性'],exceptions:['极小样本'],revision:2}]}},
 {id:'archive-hash',version:'v3',kind:'formal',name:'历史导入知识',counts:{verified_enabled:0,records:299,legacy_unverified:299},snapshot:{claims:[{id:'legacy',text:'历史主张',status:'legacy_unverified',enabled:false}]}},
];
const onChange = vi.fn();
afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.clearAllMocks();});
function setup(value:any=null) {
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items}))));
 return render(<InitialKBField value={value} onChange={onChange} version={0}/>);
}
it('classifies KBs and selects an immutable version after reading its conditions',async()=>{
 setup();
 fireEvent.click(screen.getByRole('button',{name:'选择 KB'}));
 const dialog=await screen.findByRole('dialog',{name:'选择起始 KB'});
 await within(dialog).findByText('多元回归 · 学习经验');
 fireEvent.click(within(dialog).getByRole('button',{name:'学习经验 · 1'}));
 expect(within(dialog).queryByText('已验证的优化器规律')).toBeNull();
 fireEvent.click(within(dialog).getByRole('button',{name:'查看内容'}));
 expect(within(dialog).getByText('先检查目标函数是否振荡')).toBeTruthy();
 expect(within(dialog).getByText('目标具有周期性')).toBeTruthy();
 expect(onChange).not.toHaveBeenCalled();
 fireEvent.click(within(dialog).getByRole('button',{name:'使用这个 KB'}));
 expect(onChange).toHaveBeenCalledWith({id:'experience-hash',version:'v2'});
 expect(screen.queryByRole('dialog')).toBeNull();
});
it('keeps unverified historic rules inspectable without enabling them',async()=>{
 setup();
 fireEvent.click(screen.getByRole('button',{name:'选择 KB'}));
 const dialog=screen.getByRole('dialog');
 await within(dialog).findByText('历史导入知识');
 fireEvent.click(within(dialog).getByRole('button',{name:'历史导入 · 1'}));
 expect((within(dialog).getByRole('button',{name:'使用这个 KB'}) as HTMLButtonElement).disabled).toBe(true);
 expect(within(dialog).getByText(/尚无已验证且启用的知识/)).toBeTruthy();
 fireEvent.click(within(dialog).getByRole('button',{name:'查看内容'}));
 expect(within(dialog).getByText('历史主张')).toBeTruthy();
 expect(onChange).not.toHaveBeenCalled();
});
it('shows the chosen KB and lets the user explicitly return to an empty start',async()=>{
 setup({id:'experience-hash',version:'v2'});
 await screen.findByText('多元回归 · 学习经验');
 expect(screen.getByText(/1 条可用经验/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'清除起始 KB'}));
 expect(onChange).toHaveBeenCalledWith(null);
});
it('does not replace a stale frozen selection with newly updated content',async()=>{
 setup({id:'experience-hash',version:'old-version'});
 await screen.findByRole('alert');
 expect(screen.getByText(/所选 KB 已有新版本/)).toBeTruthy();
 expect(screen.queryByText('先检查目标函数是否振荡')).toBeNull();
 expect(onChange).not.toHaveBeenCalled();
});
it('shows a fetch failure and allows a retry without discarding the selection',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValueOnce(new Error('连接失败')).mockResolvedValue(new Response(JSON.stringify({items}))));
 render(<InitialKBField value={{id:'experience-hash',version:'v2'}} onChange={onChange} version={0}/>);
 await screen.findByRole('alert');
 expect(onChange).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'重新读取 KB'}));
 await screen.findByText('多元回归 · 学习经验');
});
