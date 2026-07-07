const json = (body, init = {}) =>
  new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=10",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,OPTIONS",
      "access-control-allow-headers": "content-type",
      ...(init.headers || {})
    }
  });

const EASTMONEY_TREND = "https://push2his.eastmoney.com/api/qt/stock/trends2/get";
const EASTMONEY_QUOTE = "https://push2.eastmoney.com/api/qt/ulist.np/get";

export async function onRequest({ request }) {
  if (request.method === "OPTIONS") return json({ ok: true });

  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean);
  const action = parts[2];
  if (action === "quote") return quote(url);
  if (action !== "trend") return json({ error: "not found" }, { status: 404 });

  const secid = String(url.searchParams.get("secid") || "");
  const days = Math.max(1, Math.min(5, Math.round(Number(url.searchParams.get("days")) || 1)));
  if (!/^[01]\.\d{6}$/.test(secid)) return json({ error: "bad secid" }, { status: 400 });

  const qs = new URLSearchParams({
    secid,
    fields1: "f1,f2,f3",
    fields2: "f51,f53",
    iscr: "0",
    iscca: "0",
    ndays: String(days)
  });

  const res = await fetch(`${EASTMONEY_TREND}?${qs.toString()}`, {
    headers: { "user-agent": "Mozilla/5.0" },
    cf: { cacheTtl: 10, cacheEverything: true }
  });
  if (!res.ok) return json({ error: `upstream ${res.status}` }, { status: 502 });
  return new Response(await res.text(), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=10",
      "access-control-allow-origin": "*"
    }
  });
}

async function quote(url) {
  const secids = String(url.searchParams.get("secids") || "")
    .split(",")
    .map(item => item.trim())
    .filter(item => /^[01]\.\d{6}$/.test(item))
    .slice(0, 80);
  if (!secids.length) return json({ error: "bad secids" }, { status: 400 });

  const qs = new URLSearchParams({
    fltt: "2",
    secids: secids.join(","),
    fields: "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
  });
  const res = await fetch(`${EASTMONEY_QUOTE}?${qs.toString()}`, {
    headers: { "user-agent": "Mozilla/5.0" },
    cf: { cacheTtl: 3, cacheEverything: true }
  });
  if (!res.ok) return json({ error: `upstream ${res.status}` }, { status: 502 });
  return new Response(await res.text(), {
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=3",
      "access-control-allow-origin": "*"
    }
  });
}
