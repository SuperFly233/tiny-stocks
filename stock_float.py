import json
import math
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
DEFAULT_SYMBOLS = ["1.000001", "0.399001", "1.600519", "0.000001"]


def load_config():
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(data.get("symbols"), list):
                return data
        except Exception:
            pass
    return {
        "symbols": DEFAULT_SYMBOLS,
        "refresh_seconds": 15,
        "always_on_top": True,
        "opacity": 0.92,
        "geometry": "268x360+80+80",
    }


def save_config(config):
    CONFIG_FILE.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def normalize_symbol(raw):
    text = str(raw or "").strip().lower().replace(" ", "")
    if not text:
        return None
    if len(text) == 8 and text[1] == "." and text[0] in "01" and text[2:].isdigit():
        return text
    if text.startswith("sh") and text[2:].isdigit() and len(text) == 8:
        return "1." + text[2:]
    if text.startswith("sz") and text[2:].isdigit() and len(text) == 8:
        return "0." + text[2:]
    if len(text) == 6 and text.isdigit():
        if text[0] in "569":
            return "1." + text
        return "0." + text
    return None


def display_code(secid):
    market, code = secid.split(".")
    return ("SH" if market == "1" else "SZ") + code


def fetch_json(url, params):
    request = Request(
        url + "?" + urlencode(params),
        headers={"User-Agent": "Mozilla/5.0"},
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_quotes(symbols):
    if not symbols:
        return {}
    payload = fetch_json(
        QUOTE_API,
        {
            "fltt": "2",
            "secids": ",".join(symbols),
            "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18",
        },
    )
    items = payload.get("data", {}).get("diff", []) or []
    return {f"{item.get('f13')}.{item.get('f12')}": item for item in items}


def fetch_trend(secid):
    payload = fetch_json(
        TREND_API,
        {
            "secid": secid,
            "fields1": "f1,f2,f3",
            "fields2": "f51,f53",
            "iscr": "0",
            "iscca": "0",
            "ndays": "1",
        },
    )
    points = []
    for row in payload.get("data", {}).get("trends", []) or []:
        try:
            when, price = str(row).split(",", 1)
            points.append((when[-5:], float(price)))
        except ValueError:
            continue
    return points


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
    if number >= 100000000:
        return f"{number / 100000000:.1f}亿"
    if number >= 10000:
        return f"{number / 10000:.1f}万"
    return f"{number:.0f}"


class SparkLine(tk.Canvas):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            height=22,
            bg="#101114",
            highlightthickness=0,
            bd=0,
            **kwargs,
        )
        self.points = []
        self.color = "#d84646"
        self.bind("<Configure>", lambda _event: self.draw())

    def set_data(self, points, color):
        self.points = points
        self.color = color
        self.draw()

    def draw(self):
        self.delete("all")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        if len(self.points) < 2:
            self.create_text(
                4,
                height // 2,
                anchor="w",
                text="--",
                fill="#6f7580",
                font=("Microsoft YaHei UI", 8),
            )
            return
        values = [item[1] for item in self.points]
        low, high = min(values), max(values)
        span = max(high - low, abs(high) * 0.001, 0.01)
        coords = []
        for index, value in enumerate(values):
            x = 3 + index / (len(values) - 1) * (width - 6)
            y = 3 + (high - value) / span * (height - 6)
            coords.extend((x, y))
        self.create_line(0, height // 2, width, height // 2, fill="#262b32")
        self.create_line(*coords, fill=self.color, width=1.7, smooth=True)


class StockRow(tk.Frame):
    def __init__(self, master, secid, on_remove):
        super().__init__(master, bg="#15171c", padx=7, pady=5)
        self.secid = secid
        self.on_remove = on_remove
        self.quote = None

        top = tk.Frame(self, bg="#15171c")
        top.pack(fill="x")
        self.name = tk.Label(
            top,
            text=display_code(secid),
            fg="#eff2f6",
            bg="#15171c",
            font=("Microsoft YaHei UI", 9, "bold"),
            anchor="w",
        )
        self.name.pack(side="left", fill="x", expand=True)
        self.change = tk.Label(
            top,
            text="--",
            fg="#9aa3ad",
            bg="#15171c",
            font=("Consolas", 9, "bold"),
            anchor="e",
        )
        self.change.pack(side="right")

        mid = tk.Frame(self, bg="#15171c")
        mid.pack(fill="x", pady=(1, 2))
        self.price = tk.Label(
            mid,
            text="--",
            fg="#eff2f6",
            bg="#15171c",
            font=("Consolas", 15, "bold"),
            anchor="w",
        )
        self.price.pack(side="left")
        self.meta = tk.Label(
            mid,
            text="额 --",
            fg="#8d96a1",
            bg="#15171c",
            font=("Microsoft YaHei UI", 8),
            anchor="e",
        )
        self.meta.pack(side="right", fill="x", expand=True)

        self.spark = SparkLine(self)
        self.spark.pack(fill="x")

        self.bind_all_widgets("<Button-3>", self.show_menu)

    def bind_all_widgets(self, event, callback):
        self.bind(event, callback)
        for child in self.winfo_children():
            child.bind(event, callback)
            for grandchild in child.winfo_children():
                grandchild.bind(event, callback)

    def show_menu(self, event):
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label=f"删除 {display_code(self.secid)}", command=lambda: self.on_remove(self.secid))
        menu.tk_popup(event.x_root, event.y_root)

    def update_data(self, quote, trend):
        self.quote = quote
        name = quote.get("f14") or display_code(self.secid)
        pct = quote.get("f3")
        diff = quote.get("f4")
        color = "#d84646" if float(pct or 0) >= 0 else "#1fb57f"
        sign = "+" if float(pct or 0) > 0 else ""
        self.name.config(text=f"{name}  {display_code(self.secid)}")
        self.price.config(text=fmt(quote.get("f2")), fg=color)
        self.change.config(text=f"{sign}{fmt(pct)}%", fg=color)
        self.meta.config(text=f"{sign}{fmt(diff)}  额 {fmt_amount(quote.get('f6'))}")
        self.spark.set_data(trend, color)


class StockFloatApp:
    def __init__(self):
        self.config = load_config()
        self.symbols = list(dict.fromkeys(self.config.get("symbols", DEFAULT_SYMBOLS)))
        self.quotes = {}
        self.trends = {}
        self.rows = {}
        self.running = True
        self.drag_start = None

        self.root = tk.Tk()
        self.root.title("Tiny Stocks")
        self.root.geometry(self.config.get("geometry", "268x360+80+80"))
        self.root.configure(bg="#0d0f12")
        self.root.attributes("-topmost", bool(self.config.get("always_on_top", True)))
        self.root.attributes("-alpha", float(self.config.get("opacity", 0.92)))
        self.root.minsize(230, 170)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.build_ui()
        self.render_rows()
        self.start_refresh()

    def build_ui(self):
        self.titlebar = tk.Frame(self.root, bg="#0d0f12", padx=7, pady=4)
        self.titlebar.pack(fill="x")
        self.titlebar.bind("<ButtonPress-1>", self.begin_drag)
        self.titlebar.bind("<B1-Motion>", self.drag)

        self.title = tk.Label(
            self.titlebar,
            text="STOCKS",
            fg="#e7ebf0",
            bg="#0d0f12",
            font=("Consolas", 9, "bold"),
        )
        self.title.pack(side="left")
        self.status = tk.Label(
            self.titlebar,
            text="刷新中",
            fg="#87909b",
            bg="#0d0f12",
            font=("Microsoft YaHei UI", 8),
        )
        self.status.pack(side="left", padx=(8, 0))

        for text, command in [("+", self.add_symbol), ("↻", self.refresh_now), ("×", self.close)]:
            button = tk.Button(
                self.titlebar,
                text=text,
                command=command,
                width=2,
                height=1,
                relief="flat",
                bd=0,
                bg="#20242b",
                fg="#eef2f6",
                activebackground="#2d333c",
                activeforeground="#ffffff",
                font=("Microsoft YaHei UI", 8, "bold"),
            )
            button.pack(side="right", padx=(4, 0))

        self.body = tk.Frame(self.root, bg="#0d0f12")
        self.body.pack(fill="both", expand=True, padx=5, pady=(0, 5))

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="添加代码", command=self.add_symbol)
        self.menu.add_command(label="立即刷新", command=self.refresh_now)
        self.menu.add_separator()
        self.menu.add_command(label="切换置顶", command=self.toggle_topmost)
        self.menu.add_command(label="透明度 92%", command=lambda: self.set_opacity(0.92))
        self.menu.add_command(label="透明度 78%", command=lambda: self.set_opacity(0.78))
        self.menu.add_separator()
        self.menu.add_command(label="恢复默认自选", command=self.reset_symbols)
        self.root.bind("<Button-3>", self.show_root_menu)
        self.body.bind("<Button-3>", self.show_root_menu)

    def begin_drag(self, event):
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def drag(self, event):
        if not self.drag_start:
            return
        start_x, start_y, root_x, root_y = self.drag_start
        self.root.geometry(f"+{root_x + event.x_root - start_x}+{root_y + event.y_root - start_y}")

    def show_root_menu(self, event):
        self.menu.tk_popup(event.x_root, event.y_root)

    def render_rows(self):
        for child in self.body.winfo_children():
            child.destroy()
        self.rows.clear()
        for secid in self.symbols:
            row = StockRow(self.body, secid, self.remove_symbol)
            row.pack(fill="x", pady=(0, 5))
            self.rows[secid] = row

    def refresh_now(self):
        threading.Thread(target=self.refresh_data, daemon=True).start()

    def start_refresh(self):
        self.refresh_now()
        self.root.after(1000, self.refresh_loop)

    def refresh_loop(self):
        if not self.running:
            return
        now = time.time()
        if not hasattr(self, "next_refresh") or now >= self.next_refresh:
            self.next_refresh = now + int(self.config.get("refresh_seconds", 15))
            self.refresh_now()
        self.root.after(1000, self.refresh_loop)

    def refresh_data(self):
        try:
            quotes = fetch_quotes(self.symbols)
            trends = {}
            for secid in self.symbols:
                try:
                    trends[secid] = fetch_trend(secid)
                except Exception:
                    trends[secid] = self.trends.get(secid, [])
            self.root.after(0, lambda: self.apply_data(quotes, trends, None))
        except Exception as exc:
            self.root.after(0, lambda: self.apply_data({}, {}, exc))

    def apply_data(self, quotes, trends, error):
        if error:
            self.status.config(text="网络失败", fg="#d6a13a")
            return
        self.quotes = quotes
        self.trends.update(trends)
        for secid, row in self.rows.items():
            quote = quotes.get(secid)
            if quote:
                row.update_data(quote, self.trends.get(secid, []))
        stamp = time.strftime("%H:%M:%S")
        self.status.config(text=stamp, fg="#87909b")

    def add_symbol(self):
        raw = simpledialog.askstring("添加自选", "输入代码：600519 / sh000001 / sz399001", parent=self.root)
        secid = normalize_symbol(raw)
        if not secid or secid in self.symbols:
            return
        self.symbols.append(secid)
        self.config["symbols"] = self.symbols
        save_config(self.config)
        self.render_rows()
        self.refresh_now()

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
        self.refresh_now()

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


if __name__ == "__main__":
    StockFloatApp().run()
