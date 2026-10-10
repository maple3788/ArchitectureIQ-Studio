const ROOT = "/api/studio";
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}
export async function api<T = any>(
  path: string,
  body?: unknown,
  method?: string,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch(ROOT + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: any;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(
      `服务返回了非 JSON 内容（${response.status}）。请检查 API 连接。`,
    );
  }
  if (!response.ok) {
    const detail = data?.detail ?? data;
    throw new ApiError(
      typeof detail === "string" ? detail : JSON.stringify(detail),
      response.status,
    );
  }
  return data as T;
}
export async function uploadSource(file: File) {
  const response = await fetch(
    ROOT + "/sources/upload?name=" + encodeURIComponent(file.name),
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: await file.text(),
    },
  );
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
export function items<T>(value: { items: T[] } | T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : value?.items || [];
}
