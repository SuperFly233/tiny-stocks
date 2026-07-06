import argparse
import json
import math
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import simpledialog
from urllib.parse import urlencode
from urllib.request import Request, urlopen


APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "stock_float_config.json"

QUOTE_API = "https://push2.eastmoney.com/api/qt/ulist.np/get"
TREND_API = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
QUOTE_PROXY = "https://tiny-stocks.pages.dev/api/market/quote"
TREND_PROXY = "https://tiny-stocks.pages.dev/api/market/trend"

DEFAULT_SYMBOLS = ["1.000001", "0.399001", "0.920186", "1.600519"]
DEFAULT_CONFIG = {
    "symbols": DEFAULT_SYMBOLS,
    "refresh_seconds": 5,
    "trend_seconds": 45,
    "always_on_top": True,
    "opacity": 0.9,
    "geometry": "",
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            merged = {**DEFAULT_CONFIG, **data}
            if not isinstance(merged.get("symbols"), list) or not merged["symbols"]:
                merged["symbols"] = DEFAULT_SYMBOLS[:]
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config):
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_symbol(raw):
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    if len(text) == 8 and text[1] == "." and text[0] in "01" and text[2:].isdigit():
        return text
    if text.startswith("sh") and len(text) == 8 and text[2:].isdigit():
        return "1." + text[2:]
    if text.startswith("sz") and len(text) == 8 and text[2:].isdigit():
        return "0." + text[2:]
    if len(text) == 6 and text.isdigit():
        if text.startswith(("6", "5")):
            return "1." + text
        return "0." + text
    return None


def display_code(secid):
    market, code = secid.split(".")
    if market == "1":
        return "SH" + code
    if code.startswith(("8", "9")):
        return "BJ" + code
    return "SZ" + code


def fetch_json(url, params, timeout=8, retries=2):
    query = urlencode(params)
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = Request(
                f"{url}?{query}",
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            with urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw)
        except Exception as exc:
            last_error = exc
            time.sleep(0.35 + attempt * 0.45)
    raise last_error


def fetch_quotes(symbols):
    if not symbols:
        return {}
    params = {
        "fltt": "2",
        "secids": ",".join(symbols),
        "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18",
    }
    try:
        payload = fetch_json(QUOTE_API, params, timeout=10, retries=2)
    except Exception:
        payload = fetch_json(QUOTE_PROXY, {"secids": ",".join(symbols)}, timeout=14, retries=1)
    items = payload.get("data", {}).get("diff", []) or []
    return {f"{item.get('f13')}.{item.get('f12')}": item for item in items}


def parse_trend(payload):
    points = []
    for row in payload.get("data", {}).get("trends", []) or []:
        try:
            when, price = str(row).split(",", 1)
            points.append((when[-5:], float(price)))
        except ValueError:
            continue
    return points


def fetch_trend(secid):
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3",
        "fields2": "f51,f53",
        "iscr": "0",
        "iscca": "0",
        "ndays": "1",
    }
    try:
        return parse_trend(fetch_json(TREND_API, params, timeout=8, retries=1))
    except Exception:
        return parse_trend(fetch_json(TREND_PROXY, {"secid": secid, "days": "1"}, timeout=14, retries=1))


def fmt(value, digits=2):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number) or number == -1:
        return "--"
    return f"{number:.{digits}f}"


def fmt_amount(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number) or number <= 0:
        return "--"
    if number >= 1e12:
        return f"{number / 1e12:.1f}T"
    if number >= 1e8:
        return f"{number / 1e8:.1f}Y"
    if number >= 1e4:
        return f"{number / 1e4:.1f}W"
    return f"{number:.0f}"


def color_for_pct(pct):
    try:
        value = float(pct)
    except (TypeError, ValueError):
        return "#a8b0bf"
    return "#f05a72" if value >= 0 else "#39b86f"


class SparkLine(tk.Canvas):
    def __init__(self, master):
        super().__init__(master, height=18, bg="#05070a", highlightthickness=0, bd=0)
        self.points = []
        self.line_color = "#39b86f"
        self.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, points, color):
        self.points = points or []
        self.line_color = color
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(8, self.winfo_width())
        h = max(8, self.winfo_height())
        if len(self.points) < 2:
            self.create_line(2, h // 2, w - 2, h // 2, fill="#2a303b")
            return
        values = [p[1] for p in self.points[-80:]]
        low, high = min(values), max(values)
        span = max(high - low, abs(high) * 0.001, 0.01)
        coords = []
        for index, value in enumerate(values):
            x = 2 + index / max(1, len(values) - 1) * (w - 4)
            y = 2 + (high - value) / span * (h - 4)
            coords.extend((x, y))
        self.create_line(2, h // 2, w - 2, h // 2, fill="#1c222c")
        self.create_line(*coords, fill=self.line_color, width=1.4, smooth=True)


class StockRow(tk.Frame):
    def __init__(self, master, secid, remove_callback):
        super().__init__(master, bg="#0b0f16", padx=7, pady=5)
        self.secid = secid
        self.remove_callback = remove_callback

        self.top = tk.Frame(self, bg="#0b0f16")
        self.top.pack(fill="x")
        self.name = tk.Label(
            self.top,
            text=display_code(secid),
            fg="#f2f5fb",
            bg="#0b0f16",
            font=("Microsoft YaHei UI", 8, "bold"),
            anchor="w",
        )
        self.name.pack(side="left", fill="x", expand=True)
        self.pct = tk.Label(
            self.top,
            text="--",
            fg="#a8b0bf",
            bg="#0b0f16",
            font=("Consolas", 9, "bold"),
            anchor="e",
        )
        self.pct.pack(side="right")

        self.mid = tk.Frame(self, bg="#0b0f16")
        self.mid.pack(fill="x", pady=(1, 1))
        self.price = tk.Label(
            self.mid,
            text="--",
            fg="#f2f5fb",
            bg="#0b0f16",
            font=("Consolas", 14, "bold"),
            anchor="w",
        )
        self.price.pack(side="left")
        self.meta = tk.Label(
            self.mid,
            text="--",
            fg="#798292",
            bg="#0b0f16",
            font=("Consolas", 8),
            anchor="e",
        )
        self.meta.pack(side="right")

        self.spark = SparkLine(self)
        self.spark.pack(fill="x")

        self.bind_recursive("<Button-3>", self.menu)

    def bind_recursive(self, event_name, callback):
        self.bind(event_name, callback)
        for child in self.winfo_children():
            child.bind(event_name, callback)
            for grand in child.winfo_children():
                grand.bind(event_name, callback)

    def menu(self, event):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label=f"Remove {display_code(self.secid)}", command=lambda: self.remove_callback(self.secid))
        menu.tk_popup(event.x_root, event.y_root)

    def update(self, quote, trend):
        pct = quote.get("f3")
        diff = quote.get("f4")
        color = color_for_pct(pct)
        sign = "+" if float(pct or 0) > 0 else ""
        self.name.config(text=(quote.get("f14") or display_code(self.secid))[:12])
        self.price.config(text=fmt(quote.get("f2")), fg=color)
        self.pct.config(text=f"{sign}{fmt(pct)}%", fg=color)
        self.meta.config(text=f"{sign}{fmt(diff)}  {fmt_amount(quote.get('f6'))}")
        self.spark.set_data(trend, color)


class TinyStockWindow:
    def __init__(self):
        self.config = load_config()
        self.symbols = list(dict.fromkeys(self.config.get("symbols", DEFAULT_SYMBOLS)))
        self.quotes = {}
        self.trends = {}
        self.rows = {}
        self.running = True
        self.next_quote_at = 0
        self.next_trend_at = 0
        self.drag_origin = None

        self.root = tk.Tk()
        self.root.title("Tiny Stocks")
        self.root.configure(bg="#05070a")
        self.root.attributes("-topmost", bool(self.config.get("always_on_top", True)))
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.9)))
        self.root.minsize(196, 92)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        geometry = self.config.get("geometry")
        if geometry:
            self.root.geometry(geometry)
        else:
            self.root.geometry("228x285+120+80")
            self.root.update_idletasks()
            x = max(0, self.root.winfo_screenwidth() - 246)
            y = 42
            self.root.geometry(f"228x285+{x}+{y}")

        self.build()
        self.render_rows()
        self.tick()

    def build(self):
        self.header = tk.Frame(self.root, bg="#05070a", padx=7, pady=5)
        self.header.pack(fill="x")
        self.header.bind("<ButtonPress-1>", self.start_drag)
        self.header.bind("<B1-Motion>", self.drag)

        self.title = tk.Label(
            self.header,
            text="STOCKS",
            fg="#f2f5fb",
            bg="#05070a",
            font=("Consolas", 9, "bold"),
        )
        self.title.pack(side="left")
        self.status = tk.Label(
            self.header,
            text="boot",
            fg="#798292",
            bg="#05070a",
            font=("Consolas", 8),
        )
        self.status.pack(side="left", padx=(8, 0))

        for text, cmd in [("+", self.add_symbol), ("↻", self.force_refresh), ("×", self.close)]:
            btn = tk.Button(
                self.header,
                text=text,
                command=cmd,
                width=2,
                height=1,
                relief="flat",
                bd=0,
                bg="#121823",
                fg="#e8edf6",
                activebackground="#1d2635",
                activeforeground="#ffffff",
                font=("Microsoft YaHei UI", 8, "bold"),
            )
            btn.pack(side="right", padx=(4, 0))

        self.body = tk.Frame(self.root, bg="#05070a", padx=5)
        self.body.pack(fill="both", expand=True)

        self.root.bind("<Button-3>", self.menu)
        self.body.bind("<Button-3>", self.menu)

    def menu(self, event):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Add code", command=self.add_symbol)
        menu.add_command(label="Refresh now", command=self.force_refresh)
        menu.add_separator()
        menu.add_command(label="Topmost on/off", command=self.toggle_topmost)
        menu.add_command(label="Opacity 90%", command=lambda: self.set_opacity(0.9))
        menu.add_command(label="Opacity 75%", command=lambda: self.set_opacity(0.75))
        menu.add_command(label="Reset symbols", command=self.reset_symbols)
        menu.tk_popup(event.x_root, event.y_root)

    def start_drag(self, event):
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag(self, event):
        if not self.drag_origin:
            return
        sx, sy, wx, wy = self.drag_origin
        self.root.geometry(f"+{wx + event.x_root - sx}+{wy + event.y_root - sy}")

    def render_rows(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.rows.clear()
        for secid in self.symbols:
            row = StockRow(self.body, secid, self.remove_symbol)
            row.pack(fill="x", pady=(0, 4))
            self.rows[secid] = row

    def tick(self):
        if not self.running:
            return
        now = time.time()
        if now >= self.next_quote_at:
            self.next_quote_at = now + int(self.config.get("refresh_seconds", 5))
            include_trend = now >= self.next_trend_at
            if include_trend:
                self.next_trend_at = now + int(self.config.get("trend_seconds", 45))
            self.refresh_async(include_trend=include_trend)
        self.root.after(750, self.tick)

    def force_refresh(self):
        self.next_quote_at = 0
        self.next_trend_at = 0
        self.refresh_async(include_trend=True)

    def refresh_async(self, include_trend=False):
        threading.Thread(target=self.refresh_data, kwargs={"include_trend": include_trend}, daemon=True).start()

    def refresh_data(self, include_trend=False):
        try:
            quotes = fetch_quotes(self.symbols)
            trends = dict(self.trends)
            if include_trend:
                for secid in self.symbols:
                    try:
                        points = fetch_trend(secid)
                        if points:
                            trends[secid] = points
                    except Exception:
                        trends.setdefault(secid, self.trends.get(secid, []))
            self.root.after(0, lambda: self.apply_data(quotes, trends, None))
        except Exception as exc:
            self.root.after(0, lambda: self.apply_data({}, {}, exc))

    def apply_data(self, quotes, trends, error):
        if error:
            self.status.config(text="net err", fg="#e0a942")
            return
        if quotes:
            self.quotes = quotes
        self.trends = trends
        updated = 0
        for secid, row in self.rows.items():
            quote = self.quotes.get(secid)
            if quote:
                row.update(quote, self.trends.get(secid, []))
                updated += 1
        self.status.config(text=time.strftime("%H:%M:%S"), fg="#798292" if updated else "#e0a942")

    def add_symbol(self):
        raw = simpledialog.askstring("Add stock", "Code: 600519 / 920186 / sh000001 / sz399001", parent=self.root)
        secid = normalize_symbol(raw)
        if not secid or secid in self.symbols:
            return
        self.symbols.append(secid)
        self.config["symbols"] = self.symbols
        save_config(self.config)
        self.render_rows()
        self.force_refresh()

    def remove_symbol(self, secid):
        self.symbols = [item for item in self.symbols if item != secid]
        self.config["symbols"] = self.symbols
        save_config(self.config)
        self.render_rows()

    def reset_symbols(self):
        self.symbols = DEFAULT_SYMBOLS[:]
        self.config["symbols"] = self.symbols
        save_config(self.config)
        self.render_rows()
        self.force_refresh()

    def toggle_topmost(self):
        value = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", value)
        self.config["always_on_top"] = value
        save_config(self.config)

    def set_opacity(self, value):
        self.root.attributes("-alpha", value)
        self.config["opacity"] = value
        save_config(self.config)

    def close(self):
        self.running = False
        self.config["geometry"] = self.root.geometry()
        self.config["symbols"] = self.symbols
        save_config(self.config)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def check_data(symbols):
    print("checking quotes...")
    quotes = fetch_quotes(symbols)
    if not quotes:
        raise RuntimeError("quote API returned no rows")
    for secid, quote in quotes.items():
        print(f"{secid} {quote.get('f14')} price={quote.get('f2')} pct={quote.get('f3')}")

    trend_symbol = symbols[0]
    print(f"checking trend for {trend_symbol}...")
    trend = fetch_trend(trend_symbol)
    if len(trend) < 2:
        raise RuntimeError("trend API returned too few points")
    print(f"trend_points={len(trend)} first={trend[0]} last={trend[-1]}")
    print("DATA_OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-data", action="store_true", help="verify quote and trend data, then exit")
    parser.add_argument("symbols", nargs="*", help="optional secids/codes for --check-data")
    args = parser.parse_args()

    symbols = [normalize_symbol(item) or item for item in args.symbols] or DEFAULT_SYMBOLS
    if args.check_data:
        check_data(symbols)
        return 0

    TinyStockWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
