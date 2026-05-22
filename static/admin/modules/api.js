const apiBase = "/api/admin";

export async function requestAdmin(path, options = {}) {
  const response = await fetch(`${apiBase}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.success === false) {
    const fallback = Array.isArray(data.errors) ? data.errors.join("，") : "";
    throw new Error(data.message || fallback || `请求失败: ${response.status}`);
  }
  return data;
}
