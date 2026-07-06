const json = (body, init = {}) =>
  new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      ...(init.headers || {})
    }
  });

const cleanId = value => String(value || "")
  .trim()
  .replace(/[^a-zA-Z0-9_-]/g, "")
  .slice(0, 48);

const cleanPayload = value => {
  const symbols = Array.isArray(value.symbols)
    ? [...new Set(value.symbols.map(String).filter(item => /^[01]\.\d{6}$/.test(item)))].slice(0, 80)
    : [];
  const refreshSeconds = Math.max(1, Math.min(3600, Math.round(Number(value.refreshSeconds) || 5)));
  const theme = ["auto", "light", "dark"].includes(value.theme) ? value.theme : "auto";
  return {
    symbols,
    refreshSeconds,
    theme,
    updatedAt: new Date().toISOString()
  };
};

export async function onRequestGet({ request, env }) {
  const id = cleanId(new URL(request.url).searchParams.get("id"));
  if (!id) return json({ error: "missing id" }, { status: 400 });
  const data = await env.STOCK_SYNC.get(`sync:${id}`, "json");
  if (!data) return json({ error: "not found" }, { status: 404 });
  return json(data);
}

export async function onRequestPut({ request, env }) {
  const id = cleanId(new URL(request.url).searchParams.get("id"));
  if (!id) return json({ error: "missing id" }, { status: 400 });
  const payload = cleanPayload(await request.json().catch(() => ({})));
  await env.STOCK_SYNC.put(`sync:${id}`, JSON.stringify(payload));
  return json({ ok: true, ...payload });
}
