import argparse
import ctypes
import json
import math
import re
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
SYNC_API = "https://tiny-stocks.pages.dev/api/sync"
DEFAULT_SYNC_ID = "default-user"

DEFAULT_SYMBOLS = ["1.000001", "0.399001", "0.920186", "1.600519"]
DEFAULT_CONFIG = {
    "symbols": DEFAULT_SYMBOLS,
    "refresh_seconds": 5,
    "trend_seconds": 45,
    "always_on_top": True,
    "opacity": 0.97,
    "geometry": "",
    "display_metrics": {},
    "size_mode": "normal",
    "layout_mode": "list",
    "focus_index": 0,
    "cloud_sync": True,
}


GEOMETRIES = {
    "micro": "172x138",
    "tiny": "226x330",
    "normal": "308x520",
}

INDEX_SECIDS = {"1.000001", "0.399001", "0.399006", "1.000300", "1.000016", "0.399300"}


def usable_geometry(value):
    match = re.match(r"^(\d+)x(\d+)([+-]\d+[+-]\d+)?$", str(value or ""))
    if not match:
        return ""
    width = int(match.group(1))
    height = int(match.group(2))
    if width < 160 or height < 120:
        return ""
    return value


def size_mode(config):
    return config.get("size_mode") if config.get("size_mode") in GEOMETRIES else "normal"


def layout_mode(config):
    return config.get("layout_mode") if config.get("layout_mode") in {"list", "row", "grid"} else "list"


def is_index(secid):
    return secid in INDEX_SECIDS


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


def clean_cloud_symbols(value):
    if not isinstance(value, list):
        return []
    items = []
    for item in value:
        text = str(item)
        if re.match(r"^[01]\.\d{6}$", text) and text not in items:
            items.append(text)
    return items


def fetch_cloud_sync(timeout=4):
    try:
        return fetch_json(SYNC_API, {"id": DEFAULT_SYNC_ID}, timeout=timeout, retries=0)
    except Exception:
        return {}


def apply_cloud_sync(config):
    if not config.get("cloud_sync", True):
        return config
    data = fetch_cloud_sync()
    if not data:
        return config
    symbols = clean_cloud_symbols(data.get("symbols"))
    if symbols:
        config["symbols"] = symbols
    refresh_seconds = int(data.get("refreshSeconds") or 0)
    if refresh_seconds >= 1:
        config["refresh_seconds"] = min(3600, refresh_seconds)
    if isinstance(data.get("displayMetrics"), dict):
        config["display_metrics"] = data["displayMetrics"]
    float_settings = data.get("floatSettings") if isinstance(data.get("floatSettings"), dict) else {}
    if float_settings.get("sizeMode") in GEOMETRIES:
        config["size_mode"] = float_settings["sizeMode"]
    if float_settings.get("layoutMode") in {"list", "row", "grid"}:
        config["layout_mode"] = float_settings["layoutMode"]
    return config


def upload_cloud_sync(config):
    if not config.get("cloud_sync", True):
        return
    payload = {
        "symbols": clean_cloud_symbols(config.get("symbols")) or DEFAULT_SYMBOLS,
        "refreshSeconds": int(config.get("refresh_seconds", 5) or 5),
        "theme": "auto",
        "displayMetrics": config.get("display_metrics") or {},
        "accountMode": "reserved-default",
        "defaultUserId": DEFAULT_SYNC_ID,
        "floatSettings": {
            "sizeMode": size_mode(config),
            "layoutMode": layout_mode(config),
        },
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{SYNC_API}?{urlencode({'id': DEFAULT_SYNC_ID})}",
        data=body,
        method="PUT",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=6) as response:
        response.read()


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
        items = payload.get("data", {}).get("diff", []) or []
        if not items:
            payload = fetch_json(QUOTE_PROXY, {"secids": ",".join(symbols)}, timeout=14, retries=1)
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
        points = parse_trend(fetch_json(TREND_API, params, timeout=8, retries=1))
        if points:
            return points
    except Exception:
        pass
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


METRICS = ("price", "pct", "diff", "amount")


def metric_value(metric, quote):
    pct = quote.get("f3")
    diff = quote.get("f4")
    sign_pct = "+" if float(pct or 0) > 0 else ""
    sign_diff = "+" if float(diff or 0) > 0 else ""
    if metric == "pct":
        return f"{sign_pct}{fmt(pct)}%"
    if metric == "diff":
        return f"{sign_diff}{fmt(diff)}"
    if metric == "amount":
        return fmt_amount(quote.get("f6"))
    return fmt(quote.get("f2"))


def metric_label(metric):
    return {
        "price": "PX",
        "pct": "%",
        "diff": "+/-",
        "amount": "VOL",
    }.get(metric, metric.upper())


def metric_color(metric, quote):
    if metric in ("pct", "diff", "price"):
        return color_for_pct(quote.get("f3"))
    return "#a8b0bf"


class SparkLine(tk.Canvas):
    def __init__(self, master, mode="normal"):
        height = 14 if mode == "micro" else 28 if mode == "tiny" else 48
        super().__init__(master, height=height, bg="#05070a", highlightthickness=0, bd=0)
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


class IndexChip(tk.Frame):
    def __init__(self, master, secid, mode="normal"):
        self.mode = mode
        pad_x = 3 if mode == "micro" else 5
        super().__init__(master, bg="#111721", padx=pad_x, pady=1)
        self.secid = secid
        small = mode == "micro"
        self.name = tk.Label(
            self,
            text=display_code(secid),
            fg="#9aa4b5",
            bg="#111721",
            font=("Microsoft YaHei UI", 6 if small else 7, "bold"),
        )
        self.name.pack(side="left")
        self.value = tk.Label(
            self,
            text="--",
            fg="#f2f5fb",
            bg="#111721",
            font=("Consolas", 6 if small else 8, "bold"),
        )
        self.value.pack(side="left", padx=(4, 0))

    def update(self, quote):
        name = quote.get("f14") or display_code(self.secid)
        self.name.config(text=name[:3] if self.mode == "micro" else name[:5])
        self.value.config(text=metric_value("pct", quote), fg=color_for_pct(quote.get("f3")))


class StockRow(tk.Frame):
    def __init__(self, master, secid, remove_callback, metric_callback, drag_callback, mode="normal"):
        self.mode = mode
        micro = mode == "micro"
        super().__init__(master, bg="#0b0f16", padx=4 if micro else 5 if mode == "tiny" else 8, pady=3 if micro else 4 if mode == "tiny" else 7)
        self.secid = secid
        self.remove_callback = remove_callback
        self.metric_callback = metric_callback
        self.drag_callback = drag_callback
        self.quote = None
        self.main_metric = "price"

        self.top = tk.Frame(self, bg="#0b0f16")
        self.top.pack(fill="x")
        self.name = tk.Label(
            self.top,
            text=display_code(secid),
            fg="#f2f5fb",
            bg="#0b0f16",
            font=("Microsoft YaHei UI", 6 if micro else 7 if mode == "tiny" else 8, "bold"),
            anchor="w",
        )
        self.name.pack(side="left", fill="x", expand=True)
        self.code = tk.Label(
            self.top,
            text="--",
            fg="#657084",
            bg="#0b0f16",
            font=("Consolas", 6 if micro else 7 if mode == "tiny" else 8),
            anchor="e",
        )
        self.code.pack(side="right")

        self.mid = tk.Frame(self, bg="#0b0f16")
        self.mid.pack(fill="x", pady=(1 if micro else 3, 1 if micro else 3))
        self.main_value = tk.Label(
            self.mid,
            text="--",
            fg="#f2f5fb",
            bg="#0b0f16",
            font=("Consolas", 13 if micro else 15 if mode == "tiny" else 19, "bold"),
            anchor="w",
        )
        self.main_value.pack(side="left", fill="x", expand=True)

        self.side = tk.Frame(self.mid, bg="#0b0f16")
        self.side.pack(side="right")
        self.side_labels = {}
        for metric in METRICS:
            label = tk.Label(
                self.side,
                text="--",
                fg="#798292",
                bg="#0b0f16",
                font=("Consolas", 6 if micro else 7 if mode == "tiny" else 8, "bold"),
                anchor="e",
                cursor="hand2",
            )
            label.bind("<Button-1>", lambda event, m=metric: self.metric_callback(self.secid, m))
            self.side_labels[metric] = label

        self.spark = SparkLine(self, mode=mode)
        if micro:
            self.spark.pack_forget()
        else:
            self.spark.pack(fill="x")

        self.bind_recursive("<Button-3>", self.menu)
        self.bind_recursive("<ButtonPress-1>", lambda event: self.drag_callback("start", self.secid, event))
        self.bind_recursive("<ButtonRelease-1>", lambda event: self.drag_callback("end", self.secid, event))

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

    def set_main_metric(self, metric):
        self.main_metric = metric if metric in METRICS else "price"
        if self.quote:
            self.paint_metrics()

    def paint_metrics(self):
        quote = self.quote
        color = metric_color(self.main_metric, quote)
        self.main_value.config(text=metric_value(self.main_metric, quote), fg=color)
        visible = [metric for metric in METRICS if metric != self.main_metric]
        if self.mode == "micro":
            visible = visible[:1]
        for metric, label in self.side_labels.items():
            if metric == self.main_metric:
                label.pack_forget()
                continue
            if metric not in visible:
                label.pack_forget()
                continue
            label.config(
                text=f"{metric_label(metric)} {metric_value(metric, quote)}",
                fg=metric_color(metric, quote),
            )
            if not label.winfo_manager():
                label.pack(anchor="e")

    def update(self, quote, trend, main_metric="price"):
        self.quote = quote
        self.main_metric = main_metric if main_metric in METRICS else "price"
        color = color_for_pct(quote.get("f3"))
        limit = 5 if self.mode == "micro" else 12
        self.name.config(text=(quote.get("f14") or display_code(self.secid))[:limit])
        self.code.config(text=display_code(self.secid))
        self.paint_metrics()
        self.spark.set_data(trend, color)


class TinyStockWindow:
    def __init__(self):
        self.config = apply_cloud_sync(load_config())
        self.symbols = list(dict.fromkeys(self.config.get("symbols", DEFAULT_SYMBOLS)))
        self.quotes = {}
        self.trends = {}
        self.rows = {}
        self.index_chips = {}
        self.display_metrics = dict(self.config.get("display_metrics") or {})
        self.mode = size_mode(self.config)
        self.layout = layout_mode(self.config)
        self.running = True
        self.next_quote_at = 0
        self.next_trend_at = 0
        self.drag_origin = None
        self.row_drag = None
        self.sync_timer = None

        self.root = tk.Tk()
        self.root.title("Tiny Stocks")
        self.root.configure(bg="#05070a")
        self.root.attributes("-topmost", bool(self.config.get("always_on_top", True)))
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.9)))
        self.root.resizable(True, True)
        self.root.minsize(162 if self.mode == "micro" else 190 if self.mode == "tiny" else 280, 118 if self.mode == "micro" else 220 if self.mode == "tiny" else 360)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        geometry = usable_geometry(self.config.get("geometry"))
        if geometry:
            self.root.geometry(geometry)
        else:
            geometry_size = GEOMETRIES[self.mode]
            self.root.geometry(f"{geometry_size}+120+80")
            self.root.update_idletasks()
            width = int(geometry_size.split("x")[0])
            x = max(0, self.root.winfo_screenwidth() - width - 18)
            y = 42
            self.root.geometry(f"{geometry_size}+{x}+{y}")

        self.build()
        self.render_rows()
        self.tick()

    def save_and_sync(self):
        save_config(self.config)
        if self.sync_timer:
            self.root.after_cancel(self.sync_timer)
        self.sync_timer = self.root.after(650, self.sync_async)

    def sync_async(self):
        self.sync_timer = None
        config = dict(self.config)
        config["symbols"] = list(self.symbols)
        config["display_metrics"] = dict(self.display_metrics)
        config["size_mode"] = self.mode
        config["layout_mode"] = self.layout
        threading.Thread(target=lambda: self.sync_worker(config), daemon=True).start()

    def sync_worker(self, config):
        try:
            upload_cloud_sync(config)
        except Exception:
            pass

    def build(self):
        self.header = tk.Frame(self.root, bg="#05070a", padx=6 if self.mode == "micro" else 8, pady=3 if self.mode == "micro" else 6)
        self.header.pack(fill="x")

        self.title = tk.Label(
            self.header,
            text="STOCKS",
            fg="#f2f5fb",
            bg="#05070a",
            font=("Consolas", 8 if self.mode == "micro" else 9, "bold"),
        )
        self.title.pack(side="left")
        self.status = tk.Label(
            self.header,
            text="boot",
            fg="#798292",
            bg="#05070a",
            font=("Consolas", 7 if self.mode == "micro" else 8),
        )
        self.status.pack(side="left", padx=(8, 0))

        for text, cmd in [("+", self.add_symbol), ("↻", self.force_refresh)]:
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

        self.index_bar = tk.Frame(self.root, bg="#05070a", padx=4, pady=0)
        self.index_bar.pack(fill="x")

        self.body = tk.Frame(self.root, bg="#05070a", padx=4 if self.mode == "micro" else 6, pady=2)
        self.body.pack(fill="both", expand=True)

        self.root.bind("<Button-3>", self.menu)
        self.index_bar.bind("<Button-3>", self.menu)
        self.body.bind("<Button-3>", self.menu)

    def menu(self, event):
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Add code", command=self.add_symbol)
        menu.add_command(label="Refresh now", command=self.force_refresh)
        menu.add_separator()
        menu.add_command(label="Settings...", command=self.settings_panel)
        menu.add_command(label="Topmost on/off", command=self.toggle_topmost)
        menu.add_command(label="Opacity 100%", command=lambda: self.set_opacity(1.0))
        menu.add_command(label="Opacity 90%", command=lambda: self.set_opacity(0.9))
        menu.add_command(label="Micro mode", command=lambda: self.set_size_mode("micro"))
        menu.add_command(label="Tiny mode", command=lambda: self.set_size_mode("tiny"))
        menu.add_command(label="Normal mode", command=lambda: self.set_size_mode("normal"))
        menu.add_separator()
        menu.add_command(label="Layout: list", command=lambda: self.set_layout_mode("list"))
        menu.add_command(label="Layout: row", command=lambda: self.set_layout_mode("row"))
        menu.add_command(label="Layout: grid", command=lambda: self.set_layout_mode("grid"))
        menu.add_command(label="Reset symbols", command=self.reset_symbols)
        menu.tk_popup(event.x_root, event.y_root)

    def settings_panel(self):
        panel = tk.Toplevel(self.root)
        panel.title("Tiny Stocks Settings")
        panel.configure(bg="#0b0f16")
        panel.geometry(f"286x270+{self.root.winfo_x()+24}+{self.root.winfo_y()+48}")
        panel.attributes("-topmost", True)
        tk.Label(panel, text="Refresh seconds", fg="#f2f5fb", bg="#0b0f16", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        refresh_value = tk.IntVar(value=int(self.config.get("refresh_seconds", 5)))
        refresh = tk.Scale(
            panel,
            from_=1,
            to=60,
            resolution=1,
            orient="horizontal",
            variable=refresh_value,
            command=lambda v: self.set_refresh_seconds(int(float(v))),
            bg="#0b0f16",
            fg="#f2f5fb",
            troughcolor="#1a2230",
            highlightthickness=0,
        )
        refresh.pack(fill="x", padx=12)

        tk.Label(panel, text="Opacity", fg="#f2f5fb", bg="#0b0f16", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 0))
        value = tk.DoubleVar(value=float(self.root.attributes("-alpha")))
        slider = tk.Scale(
            panel,
            from_=0.7,
            to=1.0,
            resolution=0.01,
            orient="horizontal",
            variable=value,
            command=lambda v: self.set_opacity(float(v)),
            bg="#0b0f16",
            fg="#f2f5fb",
            troughcolor="#1a2230",
            highlightthickness=0,
        )
        slider.pack(fill="x", padx=12)

        tk.Label(panel, text="Size mode", fg="#f2f5fb", bg="#0b0f16", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(6, 0))
        row = tk.Frame(panel, bg="#0b0f16")
        row.pack(fill="x", padx=12, pady=6)
        for label, mode in [("micro", "micro"), ("tiny", "tiny"), ("normal", "normal")]:
            tk.Button(row, text=label, command=lambda m=mode: self.set_size_mode(m), bg="#121823", fg="#e8edf6", relief="flat").pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Label(panel, text="Layout", fg="#f2f5fb", bg="#0b0f16", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=12, pady=(4, 0))
        layout_row = tk.Frame(panel, bg="#0b0f16")
        layout_row.pack(fill="x", padx=12, pady=6)
        for label, mode in [("list", "list"), ("row", "row"), ("grid", "grid")]:
            tk.Button(layout_row, text=label, command=lambda m=mode: self.set_layout_mode(m), bg="#121823", fg="#e8edf6", relief="flat").pack(side="left", fill="x", expand=True, padx=(0, 6))

    def set_size_mode(self, mode):
        self.mode = mode if mode in GEOMETRIES else "normal"
        self.config["size_mode"] = self.mode
        self.config["geometry"] = ""
        self.save_and_sync()
        geometry_size = GEOMETRIES[self.mode]
        self.root.minsize(162 if self.mode == "micro" else 190 if self.mode == "tiny" else 280, 118 if self.mode == "micro" else 220 if self.mode == "tiny" else 360)
        self.root.geometry(f"{geometry_size}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.header.destroy()
        self.index_bar.destroy()
        self.body.destroy()
        self.build()
        self.render_rows()
        self.apply_data(self.quotes, self.trends, None)

    def set_layout_mode(self, mode):
        self.layout = mode if mode in {"list", "row", "grid"} else "list"
        self.config["layout_mode"] = self.layout
        self.save_and_sync()
        self.render_rows()
        self.apply_data(self.quotes, self.trends, None)

    def set_refresh_seconds(self, seconds):
        seconds = max(1, min(60, int(seconds or 5)))
        self.config["refresh_seconds"] = seconds
        self.next_quote_at = 0
        self.save_and_sync()

    def set_row_metric(self, secid, metric):
        if metric not in METRICS:
            return
        self.display_metrics[secid] = metric
        self.config["display_metrics"] = self.display_metrics
        self.save_and_sync()
        row = self.rows.get(secid)
        if row:
            row.set_main_metric(metric)

    def row_drag_event(self, action, secid, event):
        if action == "start":
            self.row_drag = {"secid": secid, "y": event.y_root}
            return
        if action != "end" or not self.row_drag or self.row_drag.get("secid") != secid:
            return
        if abs(event.y_root - self.row_drag["y"]) < 12:
            self.row_drag = None
            return
        target_index = 0
        for index, row_secid in enumerate(self.symbols):
            row = self.rows.get(row_secid)
            if row and event.y_root > row.winfo_rooty() + row.winfo_height() / 2:
                target_index = index + 1
        self.move_symbol(secid, target_index)
        self.row_drag = None

    def move_symbol(self, secid, target_index):
        if secid not in self.symbols:
            return
        current = self.symbols.index(secid)
        item = self.symbols.pop(current)
        if target_index > current:
            target_index -= 1
        target_index = max(0, min(target_index, len(self.symbols)))
        self.symbols.insert(target_index, item)
        self.config["symbols"] = self.symbols
        self.save_and_sync()
        self.render_rows()
        self.apply_data(self.quotes, self.trends, None)

    def render_rows(self):
        for child in self.index_bar.winfo_children():
            child.destroy()
        for child in self.body.winfo_children():
            child.destroy()
        self.rows.clear()
        self.index_chips.clear()

        index_symbols = [secid for secid in self.symbols if is_index(secid)]
        visible_indexes = index_symbols[:3 if self.mode == "micro" else 6]
        for secid in visible_indexes:
            chip = IndexChip(self.index_bar, secid, self.mode)
            chip.pack(side="left", fill="x", expand=True, padx=(0, 3), pady=(0, 2))
            self.index_chips[secid] = chip

        stock_symbols = [secid for secid in self.symbols if not is_index(secid)]
        if self.mode == "micro":
            focus = max(0, min(int(self.config.get("focus_index", 0) or 0), max(0, len(stock_symbols) - 1)))
            stock_symbols = stock_symbols[focus:focus + 1]

        for index, secid in enumerate(stock_symbols):
            row = StockRow(self.body, secid, self.remove_symbol, self.set_row_metric, self.row_drag_event, self.mode)
            row.set_main_metric(self.display_metrics.get(secid, "price"))
            if self.layout == "row":
                row.pack(side="left", fill="both", expand=True, padx=(0, 5), pady=(0, 5))
            elif self.layout == "grid":
                columns = 2 if self.root.winfo_width() < 560 else 3
                row.grid(row=index // columns, column=index % columns, sticky="nsew", padx=3, pady=3)
                self.body.grid_columnconfigure(index % columns, weight=1)
            else:
                row.pack(fill="x", pady=(0, 6))
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
        for secid, chip in self.index_chips.items():
            quote = self.quotes.get(secid)
            if quote:
                chip.update(quote)
        for secid, row in self.rows.items():
            quote = self.quotes.get(secid)
            if quote:
                row.update(quote, self.trends.get(secid, []), self.display_metrics.get(secid, "price"))
                updated += 1
        self.status.config(text=time.strftime("%H:%M:%S"), fg="#798292" if updated else "#e0a942")

    def add_symbol(self):
        raw = simpledialog.askstring("Add stock", "Code: 600519 / 920186 / sh000001 / sz399001", parent=self.root)
        secid = normalize_symbol(raw)
        if not secid or secid in self.symbols:
            return
        self.symbols.append(secid)
        self.config["symbols"] = self.symbols
        self.save_and_sync()
        self.render_rows()
        self.force_refresh()

    def remove_symbol(self, secid):
        self.symbols = [item for item in self.symbols if item != secid]
        self.config["symbols"] = self.symbols
        self.save_and_sync()
        self.render_rows()

    def reset_symbols(self):
        self.symbols = DEFAULT_SYMBOLS[:]
        self.config["symbols"] = self.symbols
        self.save_and_sync()
        self.render_rows()
        self.force_refresh()

    def toggle_topmost(self):
        value = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", value)
        self.config["always_on_top"] = value
        self.save_and_sync()

    def set_opacity(self, value):
        self.root.attributes("-alpha", value)
        self.config["opacity"] = value
        self.save_and_sync()

    def close(self):
        self.running = False
        self.config["geometry"] = self.root.geometry()
        self.config["symbols"] = self.symbols
        self.config["display_metrics"] = self.display_metrics
        self.config["size_mode"] = self.mode
        self.config["layout_mode"] = self.layout
        save_config(self.config)
        try:
            upload_cloud_sync(self.config)
        except Exception:
            pass
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
    if len(trend) < 1:
        raise RuntimeError("trend API returned no points")
    print(f"trend_points={len(trend)} first={trend[0]} last={trend[-1]}")
    print("DATA_OK")


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    enable_dpi_awareness()
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
