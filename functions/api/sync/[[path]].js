const json = (body, init = {}) =>
  new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,PUT,OPTIONS",
      "access-control-allow-headers": "content-type",
      ...(init.headers || {})
    }
  });

const cleanId = value => String(value || "")
  .trim()
  .replace(/[^a-zA-Z0-9_-]/g, "")
  .slice(0, 48);

const cleanPayload = value => {
  const symbols = Array.isArray(value.symbols)
    ? [...new Set(value.symbols.map(String).filter(item => /^[0-9A-Z]+\.[A-Za-z0-9_.-]+$/.test(item)))].slice(0, 80)
    : [];
  const refreshSeconds = Math.max(1, Math.min(3600, Math.round(Number(value.refreshSeconds) || 5)));
  const theme = ["auto", "light", "dark"].includes(value.theme) ? value.theme : "auto";
  const displayMetrics = {};
  if (value.displayMetrics && typeof value.displayMetrics === "object") {
    for (const [secid, metric] of Object.entries(value.displayMetrics)) {
      if (/^[0-9A-Z]+\.[A-Za-z0-9_.-]+$/.test(secid) && ["price", "pct", "diff", "amount"].includes(metric)) {
        displayMetrics[secid] = metric;
      }
    }
  }
  const sourceFloat = value.floatSettings && typeof value.floatSettings === "object"
    ? value.floatSettings
    : {};
  const floatSettings = {
    sizeMode: ["micro", "tiny", "normal"].includes(sourceFloat.sizeMode) ? sourceFloat.sizeMode : "normal",
    layoutMode: ["auto", "list", "row", "grid"].includes(sourceFloat.layoutMode) ? sourceFloat.layoutMode : "auto"
  };
  const reminders = Array.isArray(value.reminders)
    ? value.reminders
      .filter(item => item && /^[0-9A-Z]+\.[A-Za-z0-9_.-]+$/.test(String(item.secid || "")))
      .map(item => ({
        id: String(item.id || "").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 48) || crypto.randomUUID(),
        secid: String(item.secid),
        metric: ["price", "pct"].includes(item.metric) ? item.metric : "price",
        op: ["gte", "lte"].includes(item.op) ? item.op : "gte",
        value: Number(item.value),
        mode: ["toast", "fullscreen"].includes(item.mode) ? item.mode : "toast",
        armed: item.armed !== false,
        createdAt: String(item.createdAt || ""),
        lastTriggeredAt: String(item.lastTriggeredAt || "")
      }))
      .filter(item => Number.isFinite(item.value))
      .slice(0, 120)
    : [];
  return {
    symbols,
    refreshSeconds,
    theme,
    displayMetrics,
    rightEdge: value.rightEdge === "latest" ? "latest" : "close",
    reminders,
    accountMode: value.accountMode === "reserved-default" ? "reserved-default" : "reserved-default",
    defaultUserId: "default-user",
    floatSettings,
    updatedAt: new Date().toISOString()
  };
};

export async function onRequest({ request, env }) {
  if (request.method === "OPTIONS") return json({ ok: true });

  const url = new URL(request.url);
  const id = cleanId(url.searchParams.get("id"));
  if (!id) return json({ error: "missing id" }, { status: 400 });

  if (request.method === "GET") {
    const data = await env.STOCK_SYNC.get(`sync:${id}`, "json");
    if (!data) return json({ error: "not found" }, { status: 404 });
    return json(data);
  }

  if (request.method === "PUT" || request.method === "POST") {
    const payload = cleanPayload(await request.json().catch(() => ({})));
    await env.STOCK_SYNC.put(`sync:${id}`, JSON.stringify(payload));
    return json({ ok: true, ...payload });
  }

  return json({ error: "method not allowed" }, { status: 405 });
}
