import {Rag} from './Rag';
import {DataWorkspace} from './DataWorkspace';
import { useRef, useState } from "react";
import {
  ArrowUpRight,
  BookOpen,
  ChevronDown,
  CircleHelp,
  Command,
  Database,
  FlaskConical,
  Layers3,
  LoaderCircle,
  Menu,
  Network,
  RefreshCw,
  Server,
  Settings2,
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
const navigation = [
  {id:"data",name:"Data · 题库",en:"Datasets & questions",icon:Database},
  {id:"rag",name:"RAG 作答",en:"Question-aware retrieval",icon:BookOpen},
  { id: "questions", name: "题库", en: "Question catalog", icon: Database },
  { id: "workflow", name: "工作流", en: "Workflow canvas", icon: FlowIcon },
  { id: "models", name: "模型", en: "Model registry", icon: Layers3 },
  {
    id: "generation",
    name: "生成任务",
    en: "Generation jobs",
    icon: FlaskConical,
  },
  { id: "runs", name: "测试运行", en: "Evaluation & history", icon: Network },
  { id: "kb", name: "KB 知识库", en: "Knowledge base", icon: BookOpen },
];
export default function App() {
  const [page, setPage] = useState(() => {
    const id = location.hash.slice(1);
    return navigation.some((n) => n.id === id) ? id : "data";
  });
  const [version, setVersion] = useState(0);
  const bootstrap = useResource<Bootstrap>("/bootstrap", version);
  const [toast, setToast] = useState<{ message: string; error?: boolean }>();
  const [busy, setBusy] = useState(false);
  const locked = useRef(false);
  const [sidebar, setSidebar] = useState(false);
  const [ragQuestion,setRagQuestion]=useState<string>();
  const [setId, setSetId] = useState<string>();
  const [runId, setRunId] = useState<string>();
  const [workflowRunId, setWorkflowRunId] = useState<string>();
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
    setToast({ message: "题集已保存，可在测试运行中选择并执行。" });
  };
  const current = navigation.find((n) => n.id === page)!;
  const data = bootstrap.data;
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
        <div className="workspace-picker">
          <div className="workspace-icon">
            <Network size={17} />
          </div>
          <div>
            <b>KB 研究工作空间</b>
            <small>Scientific workflow</small>
          </div>
          <ChevronDown size={13} />
        </div>
        <div className="nav-label">工作空间</div>
        <nav>
          {navigation.map(({ id, name, en, icon: Icon }) => (
            <button
              key={id}
              onClick={() => navigate(id)}
              className={`nav-item ${page === id ? "active" : ""}`}
            >
              <Icon size={19} />
              <span>{name}</span>
              {id === "questions" && data?.stats?.questions !== undefined && (
                <i>{data.stats.questions.toLocaleString()}</i>
              )}
              {page === id && <span className="active-pin" />}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="research-note">
            <span className="note-symbol">✳</span>
            <b>从实验，到可复现的知识。</b>
            <p>
              完整输入、真实调用
              <br />
              和每一步证据，始终可见。
            </p>
          </div>
          <div className="server-chip">
            <span className={`server-dot ${data ? "connected" : ""}`} />
            <div>
              <b>
                {data
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
                className={`status-dot ${data?.service.execution_enabled ? "ok" : ""}`}
              />
              {data?.service.execution_enabled
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
          {page === "data" ? (
            data && <DataWorkspace version={version} act={act} bootstrap={data} onRag={key=>{setRagQuestion(key);navigate("rag");}} onRun={onRun}/>
          ) : page === "questions" ? (
            <Questions version={version} act={act} onSet={onSet} onRag={key=>{setRagQuestion(key);navigate("rag");}} />
          ) : page === "rag" ? (
            <Rag version={version} act={act} models={data?.models || []} executionEnabled={!!data?.service.execution_enabled} questionKey={ragQuestion} onQuestion={setRagQuestion} onRun={onRun}/>
          ) : page === "workflow" ? (
            <WorkflowWorkspace version={version} selectedRun={workflowRunId} act={act}>
              <Workflow
                rolePrompts={data?.role_prompts}
                version={version}
                act={act}
                executionEnabled={!!data?.service.execution_enabled}
                onRun={onWorkflowRun}
                onModels={()=>navigate("models")}
              />
            </WorkflowWorkspace>
          ) : page === "models" ? (
            <Models version={version} act={act} />
          ) : page === "generation" ? (
            <Generation
              capabilities={data?.capabilities}
              version={version}
              act={act}
              executionEnabled={!!data?.service.execution_enabled}
              onRun={onRun}
            />
          ) : page === "runs" ? (
            <Runs
              version={version}
              act={act}
              executionEnabled={!!data?.service.execution_enabled}
              initialSet={setId}
              selectedRun={runId}
              onRun={onRun}
              onWorkflowRun={onWorkflowRun}
            />
          ) : (
            <KB version={version} />
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
