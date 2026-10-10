import {afterEach,expect,it} from 'vitest';
import {cleanup,render,screen} from '@testing-library/react';
import {InitialKBPreview} from './InitialKBPreview';
afterEach(cleanup);

it('explains the actual selected, excluded and budget-omitted experience instead of the catalog total',()=>{
 render(<InitialKBPreview preview={{initial_kb:{name:'回归学习经验',kind:'experience',counts:{active_lessons:8}},requests:[{initial_experience:{lessons:[{id:'used'}],omitted:{lessons:2},excluded:{lessons_with_excluded_sources:5}}}]}}/>);
 expect(screen.getByText('回归学习经验')).toBeTruthy();
 expect(screen.getByText(/本题实际带入 1 条起始经验/)).toBeTruthy();
 expect(screen.getByText(/2 条因输入长度限制省略/)).toBeTruthy();
 expect(screen.getByText(/5 条未通过本题检索条件/)).toBeTruthy();
});

it('does not report selected formal knowledge as applied when no rules match the question',()=>{
 render(<InitialKBPreview preview={{initial_kb:{name:'受控实验规律',kind:'formal',counts:{verified_enabled:9}},requests:[{knowledge:[]}]}}/>);
 expect(screen.getByText(/本题匹配 0 条已验证知识/)).toBeTruthy();
 expect(screen.getByText(/所选 KB 没有内容进入本题的首轮请求/)).toBeTruthy();
});

it('keeps an unavailable initial request distinct from an empty initial KB',()=>{
 render(<InitialKBPreview preview={{initial_kb:{name:'回归学习经验',kind:'experience'}}}/>);
 expect(screen.getByText(/实际带入数量尚未返回/)).toBeTruthy();
 expect(screen.queryByText(/空经验开始/)).toBeNull();
});
