export const api = {
  qr: "/api/qr_code",
  events: "/api/events",
  printerAvailability: "/api/printer/availability",
  sessionCurrent: "/api/session/current",
  preview: "/api/preview",
  print: "/api/print",
  cleanup: "/api/cleanup",
};

export async function getJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function postJson(url, data) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data || {}),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || json.success === false) {
    throw new Error(json.message || `HTTP ${res.status}`);
  }
  return json;
}
