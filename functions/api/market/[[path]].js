const json = (body, init = {}) =>
  new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "public, max-age=10",
      ...(init.headers || {})
    }
  });

const EASTMONEY_TREND = "https://push2his.eastmoney.com/api/qt/stock/trends2/get";

export async function onRequest({ request }) {
  const url = new URL(request.url);
  const parts = url.pathname.split("/").filter(Boolean);
  const action = parts[2];
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
      "cache-control": "public, max-age=10"
    }
  });
}
