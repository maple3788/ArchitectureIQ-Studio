import {
  useEffect,
  useState,
  useId,
  Children,
  isValidElement,
  cloneElement,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  ChevronRight,
  LoaderCircle,
  X,
} from "lucide-react";
import { api } from "./api";
export const pretty = (value: any) =>
  typeof value === "string" ? value : JSON.stringify(value, null, 2);
export function useResource<T>(path: string | null, version = 0, poll = 0) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setData(undefined);
    setError("");
    setLoading(true);
    const load = async () => {
      if (!path) {
        setLoading(false);
        return;
      }
      try {
        const next = await api<T>(path);
        if (active) {
          setData(next);
          setError("");
        }
      } catch (e) {
        if (active) setError(String((e as Error).message));
      } finally {
        if (active) setLoading(false);
      }
    };
    void load();
    const timer = poll ? setInterval(load, poll) : undefined;
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [path, version, poll]);
  return { data, error, loading, setData };
}
export function Status({ value }: { value?: string | boolean }) {
  const text =
    value === true
      ? "已验证"
      : value === false
        ? "待检查"
        : String(value || "未知");
  const positive =
    /complete|verified|ready|succeeded|success|已验证|已完成|运行中|running/.test(text);
  const bad = /failed|error|offline|invalid|运行失败|已中断/.test(text);
  return (
    <span className={`status ${positive ? "positive" : bad ? "bad" : ""}`}>
      <i />
      {text}
    </span>
  );
}
export function Empty({
  title = "这里还没有记录",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark">◇</span>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle size={20} className="spin" />
      正在读取服务端记录…
    </div>
  );
}
export function ErrorBox({ error }: { error?: string }) {
  return error ? (
    <div className="error" role="alert">
      <AlertCircle size={17} />
      <span>{error}</span>
    </div>
  ) : null;
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Check size={16} />
      {children}
    </div>
  );
}
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  const generatedId = useId();
  const childrenList = Children.toArray(children);
  const control = childrenList.find(
    (child) =>
      isValidElement<Record<string, any>>(child) &&
      typeof child.type === "string" &&
      ["input", "select", "textarea"].includes(child.type),
  );
  const controlId = isValidElement<Record<string, any>>(control)
    ? control.props.id || generatedId
    : undefined;
  const hintId = generatedId + "-hint";
  const rendered = childrenList.map((child) =>
    child === control && isValidElement<Record<string, any>>(child)
      ? cloneElement(child, {
          id: controlId,
          "aria-describedby":
            [child.props["aria-describedby"], hint ? hintId : undefined]
              .filter(Boolean)
              .join(" ") || undefined,
        })
      : child,
  );
  return (
    <div className="field">
      <label id={generatedId + "-label"} htmlFor={controlId}>
        {label}
      </label>
      {control ? (
        rendered
      ) : (
        <div role="group" aria-labelledby={generatedId + "-label"}>
          {rendered}
        </div>
      )}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}
export function Card({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title && (
        <div className="card-head">
          <div>
            <h3>{title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
export function Drawer({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const fn = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", fn);
    return () => window.removeEventListener("keydown", fn);
  }, [onClose]);
  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="drawer-title">
          <div>
            <span className="eyebrow">DETAILS</span>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            aria-label="关闭详情"
            className="icon-button"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </div>
        <div className="drawer-content">{children}</div>
      </aside>
    </div>
  );
}
export function Tabs({
  tabs,
  value,
  onChange,
}: {
  tabs: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          role="tab"
          aria-selected={value === tab}
          className={value === tab ? "active" : ""}
          key={tab}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
export function JsonView({
  value,
  empty = "服务未提供此项记录",
}: {
  value: any;
  empty?: string;
}) {
  return value === undefined || value === null ? (
    <Empty title={empty} />
  ) : (
    <pre className="code">{pretty(value)}</pre>
  );
}
export function LinkButton({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-button" onClick={onClick}>
      {children}
      <ArrowUpRight size={14} />
    </button>
  );
}
export function Chevron() {
  return <ChevronRight size={14} />;
}
