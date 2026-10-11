import type {KBRef} from './ruleRefinementTypes';
import {Rag} from './Rag';
import {DataWorkspace} from './DataWorkspace';
import { useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Command,
  Database,
  FlaskConical,
  LoaderCircle,
  Menu,
  RefreshCw,
  ShieldCheck,
  Workflow as FlowIcon,
  X,
} from "lucide-react";
import { Questions, type Action } from "./Questions";
import { Models } from "./Models";
import { Workflow } from "./Workflow";
import { WorkflowWorkspace } from "./WorkflowWorkspace";
import { Runs } from "./Runs";
import { Generation } from "./Generation";
import { KB } from "./KB";
import { ErrorBox, useResource } from "./ui";
import type { Bootstrap } from "./types";
const modules = [
  {id: "data", name: "Data", entry: "data", pages: ["data", "questions", "generation"], icon: Database},
  {id: "harness", name: "Harness", entry: "workflow", pages: ["workflow", "models"], icon: FlowIcon},
  {id: "kb", name: "KB", entry: "kb", pages: ["kb"], icon: BookOpen},
  {id: "task", name: "Task", entry: "rag", pages: ["rag", "runs"], icon: FlaskConical},
];
const modulePages = {
  harness: [{id: "workflow", name: "工作流"}, {id: "models", name: "模型配置"}],
  task: [{id: "rag", name: "RAG 作答"}, {id: "runs", name: "评测与记录"}],
};
const pageFromHash = () => {
  const id = location.hash.slice(1);
  return modules.some(module => module.pages.includes(id)) ? id : id ? undefined : "data";
};
export default function App() {
  const [page, setPage] = useState(() => pageFromHash() || "data");
  const [version, setVersion] = useState(0);
  const bootstrap = useResource<Bootstrap>("/bootstrap", version);
  const [lastBootstrap, setLastBootstrap] = useState<Bootstrap>();
  useEffect(() => {
    if (bootstrap.data) setLastBootstrap(bootstrap.data);
  }, [bootstrap.data]);
  const [toast, setToast] = useState<{ message: string; error?: boolean }>();
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const [sidebar, setSidebar] = useState(false);
  const [ragQuestion,setRagQuestion]=useState<string>();
  const [ruleKB,setRuleKB]=useState<KBRef>();
  const [setId, setSetId] = useState<string>();
  const [runId, setRunId] = useState<string>();
  const [workflowRunId, setWorkflowRunId] = useState<string>();
  useEffect(() => {
    const syncPage = () => {
      const nextPage = pageFromHash();
      // RAG citations use fragment anchors within the current run.
      if (!nextPage) return;
      setPage(nextPage);
      setSidebar(false);
    };
    window.addEventListener("hashchange", syncPage);
    return () => window.removeEventListener("hashchange", syncPage);
  }, []);
  const navigate = (id: string) => {
    setPage(id);
    location.hash = id;
    setSidebar(false);
  };
  const act: Action = async (operation, success) => {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    setToast(undefined);
    try {
      const data = await operation();
      setVersion((v) => v + 1);
      if (success) setToast({ message: success });
      return data;
    } catch (error) {
      setToast({
        message: (error as Error).message || String(error),
        error: true,
      });
      return undefined;
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const onRun = (id: string) => {
    setRunId(id);
    navigate("runs");
  };
  const onWorkflowRun = (id: string) => {
    setWorkflowRunId(id);
    navigate("workflow");
  };
  const onSet = (id: string) => {
    setSetId(id);
    setToast({ message: "题集已保存，可在 Task 的评测与记录中选择并执行。" });
  };
  const current = modules.find(module => module.pages.includes(page))!;
  const subpages = current.id === "harness" ? modulePages.harness : current.id === "task" ? modulePages.task : [];
  const data = bootstrap.data || lastBootstrap;
  const executionEnabled = !!bootstrap.data?.service.execution_enabled;
  return (
    <div className="app">
      <aside className={`sidebar ${sidebar ? "visible" : ""}`}>
        <a
          className="brand"
          href="#data"
          onClick={(e) => {
            e.preventDefault();
            navigate("data");
          }}
        >
          <span className="brand-mark">
            <Command size={23} />
          </span>
          <div>
            <strong>
              Architecture<span>IQ</span>
            </strong>
            <small>WORKFLOW STUDIO</small>
          </div>
        </a>
        <div className="nav-label">研究工作空间</div>
        <nav aria-label="核心模块">
          {modules.map(({ id, name, entry, icon: Icon }) => (
            <button
              key={id}
              onClick={() => navigate(entry)}
              aria-current={current.id === id ? "page" : undefined}
              className={`nav-item ${current.id === id ? "active" : ""}`}
            >
              <Icon size={19} />
              <span>{name}</span>
              {current.id === id && <span className="active-pin" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="server-chip">
            <span className={`server-dot ${bootstrap.data ? "connected" : ""}`} />
            <div>
              <b>
                {bootstrap.data
                  ? "Studio API 已连接"
                  : bootstrap.loading
                    ? "连接服务器…"
                    : "API 离线"}
              </b>
              <small>{data?.service.host || "等待服务连接"}</small>
            </div>
            <button
              className="icon-button"
              title="重新连接"
              onClick={() => setVersion((v) => v + 1)}
            >
              <RefreshCw size={13} />
            </button>
          </div>
        </div>
      </aside>
      {sidebar && (
        <button
          className="mobile-backdrop"
          aria-label="关闭导航"
          onClick={() => setSidebar(false)}
        />
      )}
      <div className="main-shell">
        <header className="topbar">
          <div>
            <button
              className="icon-button mobile-menu"
              aria-label="展开导航"
              onClick={() => setSidebar(!sidebar)}
            >
              <Menu size={20} />
            </button>
            <span className="breadcrumb">
              工作空间 <span>/</span>
            </span>
            <b>{current.name}</b>
          </div>
          <div>
            <span className="execution-chip">
              <span
                className={`status-dot ${executionEnabled ? "ok" : ""}`}
              />
              {executionEnabled
                ? "服务器执行已启用"
                : "只读 / 预览模式"}
            </span>
            <button
              className="icon-button"
              aria-label="刷新服务数据"
              onClick={() => setVersion((v) => v + 1)}
            >
              <RefreshCw size={16} />
            </button>
            <span className="avatar">AIQ</span>
          </div>
        </header>
        <main
          className={
            page === "workflow"
              ? "main-content workflow-content"
              : "main-content"
          }
        >
          <ErrorBox
            error={
              bootstrap.error
                ? `Studio API 未连接：${bootstrap.error}。请检查服务及 SSH 转发。`
                : undefined
            }
          />
          {subpages.length > 0 && <nav className="module-subnav" aria-label={`${current.name} 模块页面`}>
            {subpages.map(item => <button key={item.id} aria-current={page === item.id ? "page" : undefined} onClick={() => navigate(item.id)}>{item.name}</button>)}
          </nav>}
          {current.id === "data" ? (
            data && <DataWorkspace version={version} act={act} bootstrap={{...data,service:{...data.service,execution_enabled:executionEnabled}}} onRag={key=>{setRagQuestion(key);navigate("rag");}} onRun={onRun}
              tool={page === "questions" || page === "generation" ? page : undefined} onTool={tool => navigate(tool || "data")}>
              {page === "questions" && <Questions version={version} act={act} onSet={onSet} onRag={key=>{setRagQuestion(key);navigate("rag");}} />}
              {page === "generation" && <Generation capabilities={data.capabilities} version={version} act={act} executionEnabled={executionEnabled} onRun={onRun} />}
            </DataWorkspace>
          ) : page === "rag" ? (
            <Rag version={version} act={act} models={data?.models || []} executionEnabled={executionEnabled} questionKey={ragQuestion} onQuestion={setRagQuestion} onRun={onRun}/>
          ) : page === "workflow" ? (
            <WorkflowWorkspace version={version} selectedRun={workflowRunId} act={act}>
              <Workflow
                bootstrap={data}
                rolePrompts={data?.role_prompts}
                version={version}
                act={act}
                executionEnabled={executionEnabled}
                onRun={onWorkflowRun}
                onModels={()=>navigate("models")}
              />
            </WorkflowWorkspace>
          ) : page === "models" ? (
            <Models version={version} act={act} />
          ) : page === "runs" ? (
            <Runs
              version={version}
              act={act}
              executionEnabled={executionEnabled}
              ruleKB={ruleKB}
              initialSet={setId}
              selectedRun={runId}
              onRun={onRun}
              onWorkflowRun={onWorkflowRun}
            />
          ) : (
            <KB version={version} onEvaluate={ref=>{setRuleKB(ref);navigate("runs");}} />
          )}
        </main>
        <footer className="app-footer">
          <span>ArchitectureIQ · KB Workflow Studio</span>
          <span>
            <ShieldCheck size={12} />
            公开题面与私有反馈独立
          </span>
        </footer>
      </div>
      {busy && (
        <div className="busy-bar" role="status">
          <LoaderCircle size={16} className="spin" />
          正在处理服务器请求…
        </div>
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "toast-error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          <span>{toast.message}</span>
          <button
            className="icon-button"
            aria-label="关闭消息"
            onClick={() => setToast(undefined)}
          >
            <X size={17} />
          </button>
        </div>
      )}
    </div>
  );
}
