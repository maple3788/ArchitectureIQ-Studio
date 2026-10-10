export type Timestamp = string | number;
/** The Studio API persists Unix seconds; ISO strings and browser milliseconds remain supported. */
export function formatTimestamp(value?: Timestamp | null) {
  if (value === undefined || value === null || value === "") return "未记录";
  const numeric =
    typeof value === "number"
      ? value
      : /^-?\d+(\.\d+)?$/.test(value)
        ? Number(value)
        : undefined;
  const date =
    numeric === undefined
      ? new Date(value)
      : new Date(
          Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric,
        );
  if (!Number.isFinite(date.getTime())) return "时间格式无效";
  return date.toLocaleString("zh-CN", { hour12: false });
}
