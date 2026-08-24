import tkinter as tk
import json
import threading
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

CONFIG_PATH = Path.home() / ".salary_tracker.json"
FX_URLS     = (
    "https://api.frankfurter.dev/v1/latest?base=USD",
    "https://api.frankfurter.app/latest?from=USD",
)
DEFAULT_CURRENCY = "USD"


HOURS_PER_DAY   = 8
DAYS_PER_WEEK   = 5
WEEKS_PER_MONTH = 52 / 12

BG        = "#1a1a2e"
ACCENT    = "#16213e"
HIGHLIGHT = "#0f3460"
TEXT      = "#e0e0e0"
DIM       = "#888899"
GREEN     = "#4ecca3"
YELLOW    = "#f5a623"
ORANGE    = "#e94560"

CURRENCIES = [
    "USD","EUR","GBP","PLN","CHF","JPY","CAD","AUD",
    "SEK","NOK","DKK","CZK","HUF","INR","BRL","MXN",
    "SGD","HKD","NZD","KRW","CNY","TRY","ZAR",
]
CUR_SYMBOLS = {
    "USD":"$",  "EUR":"€",  "GBP":"£",  "JPY":"¥",  "PLN":"zł",
    "CHF":"Fr", "CAD":"C$", "AUD":"A$", "SEK":"kr", "NOK":"kr",
    "DKK":"kr", "INR":"₹",  "BRL":"R$", "MXN":"$",  "SGD":"S$",
    "HKD":"HK$","NZD":"NZ$","KRW":"₩",  "CNY":"¥",  "TRY":"₺",
    "ZAR":"R",
}
NO_DECIMAL = {"JPY", "KRW", "HUF", "CZK"}


def weekdays_before_today_this_week(today: date) -> int:
    return min(today.weekday(), DAYS_PER_WEEK)


def weekdays_before_today_this_month(today: date) -> int:
    count, d = 0, today.replace(day=1)
    while d < today:
        if d.weekday() < DAYS_PER_WEEK:
            count += 1
        d += timedelta(days=1)
    return count


class SalaryTracker:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Salary Tracker")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        self.hourly_rate = 0.0
        self.currency    = DEFAULT_CURRENCY
        self.base_hourly_rate = self.hourly_rate
        self.base_currency = self.currency
        self.api_key     = ""
        self.fx_rates    = {}
        self.sessions    = []

        self.accumulated_seconds = 0.0
        self.session_start       = None
        self.is_running          = False

        self.rates_visible    = True
        self.settings_visible = False
        self.history_visible  = False
        self._drag_x = self._drag_y = 0

        self.load_config()
        self.base_hourly_rate = self.hourly_rate
        self.base_currency = self.currency
        self.build_ui()
        self.update_display()
        self.position_window()

    # ── Persistence ─────────────────────────────────────────────────

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text())
                self.hourly_rate = cfg.get("hourly_rate", 0.0)
                self.currency    = cfg.get("currency", DEFAULT_CURRENCY)
                self.api_key     = cfg.get("api_key", "")
                self.fx_rates    = cfg.get("fx_rates", {})
                self.sessions    = cfg.get("sessions", [])
            except Exception:
                pass

    def save_config(self):
        try:
            CONFIG_PATH.write_text(json.dumps({
                "hourly_rate": self.hourly_rate,
                "currency":    self.currency,
                "api_key":     self.api_key,
                "fx_rates":    self.fx_rates,
                "sessions":    self.sessions[-100:],
            }, indent=2))
        except Exception:
            pass

    # ── FX ──────────────────────────────────────────────────────────

    def fetch_fx(self, event=None):
        self.fx_status_var.set("Fetching…")
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        errors = []
        request_headers = {"User-Agent": "SalaryTracker/2.0"}
        for url in FX_URLS:
            try:
                request = urllib.request.Request(url, headers=request_headers)
                with urllib.request.urlopen(request, timeout=10) as r:
                    data = json.loads(r.read())
                if data.get("error"):
                    raise ValueError(data.get("message", "API error"))
                rates = data.get("rates", {})
                if not rates:
                    raise ValueError("No exchange rates returned")
                self.fx_rates = rates
                self.root.after(0, self._fx_ok)
                return
            except Exception as e:
                errors.append(str(e))
        message = errors[-1] if errors else "No exchange-rate service available"
        self.root.after(0, lambda err=message: self._fx_err(err))

    def _fx_ok(self):
        self.fx_status_var.set("✓  Rates updated")
        self.save_config()
        self.update_rate_labels()

    def _fx_err(self, msg):
        self.fx_status_var.set(f"✗  {msg[:35]}")

    def fmt(self, amount: float) -> str:
        cur = self.cur_var.get()
        sym = CUR_SYMBOLS.get(cur, cur + " ")
        if cur in NO_DECIMAL:
            return f"{sym}{amount:,.0f}"
        return f"{sym}{amount:,.2f}"

    # ── Build UI ────────────────────────────────────────────────────

    def build_ui(self):
        PAD = 10

        title_bar = tk.Frame(self.root, bg=ACCENT, height=32)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)
        title_lbl = tk.Label(title_bar, text="💰  Salary Tracker",
                             bg=ACCENT, fg=TEXT, font=("Segoe UI", 9, "bold"), padx=8)
        title_lbl.pack(side=tk.LEFT, pady=5)
        close_btn = tk.Label(title_bar, text="✕", bg=ACCENT, fg=DIM,
                             font=("Segoe UI", 10, "bold"), cursor="hand2", padx=10)
        close_btn.pack(side=tk.RIGHT, pady=4)
        close_btn.bind("<Button-1>", lambda e: self._on_close())
        close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=ORANGE))
        close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=DIM))
        for w in (title_bar, title_lbl):
            w.bind("<Button-1>", self.start_drag)
            w.bind("<B1-Motion>", self.do_drag)

        m = tk.Frame(self.root, bg=BG, padx=PAD, pady=PAD)
        m.pack(fill=tk.BOTH, expand=True)

        # ── currency & FX header ─────────────────────────────────────
        self.settings_hdr = tk.Frame(m, bg=BG)
        self.settings_hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(self.settings_hdr, text="Currency & FX", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.settings_btn = tk.Label(self.settings_hdr, text="Show ▼", bg=BG, fg=YELLOW,
                                     font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.settings_btn.pack(side=tk.RIGHT)
        self.settings_btn.bind("<Button-1>", self.toggle_settings)

        # ── FX panel (hidden by default) ─────────────────────────────
        self.settings_frame = tk.Frame(m, bg=ACCENT, padx=6, pady=6)

        api_row = tk.Frame(self.settings_frame, bg=ACCENT)
        api_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(api_row, text="API key", bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), width=8, anchor="w").pack(side=tk.LEFT)
        self.api_key_var = tk.StringVar(value=self.api_key)
        tk.Entry(api_row, textvariable=self.api_key_var, width=22,
                 bg=HIGHLIGHT, fg=TEXT, insertbackground=TEXT,
                 relief=tk.FLAT, font=("Segoe UI", 8), bd=3, show="*").pack(side=tk.LEFT, padx=4)

        cur_row = tk.Frame(self.settings_frame, bg=ACCENT)
        cur_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(cur_row, text="Currency", bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), width=8, anchor="w").pack(side=tk.LEFT)
        self.cur_var = tk.StringVar(value=self.currency)
        menu = tk.OptionMenu(cur_row, self.cur_var, *CURRENCIES, command=self._on_cur_change)
        menu.configure(bg=HIGHLIGHT, fg=TEXT, activebackground=HIGHLIGHT, activeforeground=GREEN,
                       relief=tk.FLAT, font=("Segoe UI", 8), bd=0, highlightthickness=0)
        menu["menu"].configure(bg=HIGHLIGHT, fg=TEXT, activebackground=HIGHLIGHT, font=("Segoe UI", 8))
        menu.pack(side=tk.LEFT, padx=4)

        fetch_row = tk.Frame(self.settings_frame, bg=ACCENT)
        fetch_row.pack(fill=tk.X, pady=(4, 0))
        fetch_btn = tk.Label(fetch_row, text="↻  Fetch live rates", bg=HIGHLIGHT, fg=GREEN,
                             font=("Segoe UI", 8, "bold"), padx=6, pady=2, cursor="hand2")
        fetch_btn.pack(side=tk.LEFT)
        fetch_btn.bind("<Button-1>", self.fetch_fx)
        self.fx_status_var = tk.StringVar(value="")
        tk.Label(fetch_row, textvariable=self.fx_status_var, bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), padx=6).pack(side=tk.LEFT)

        # ── separator ────────────────────────────────────────────────
        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(4, 8))

        # ── hourly rate input ─────────────────────────────────────────
        input_row = tk.Frame(m, bg=BG)
        input_row.pack(fill=tk.X, pady=(0, 6))
        self.rate_lbl = tk.Label(input_row, text=f"Hourly rate ({self.currency})",
                                 bg=BG, fg=DIM, font=("Segoe UI", 8))
        self.rate_lbl.pack(side=tk.LEFT)
        self.salary_entry = tk.Entry(input_row, width=9, bg=HIGHLIGHT, fg=TEXT,
                                     insertbackground=TEXT, relief=tk.FLAT,
                                     font=("Segoe UI", 10, "bold"), bd=4, justify="right")
        self.salary_entry.pack(side=tk.LEFT, padx=(6, 6))
        self.salary_entry.insert(0, f"{self.hourly_rate:.2f}")
        self.salary_entry.bind("<Return>", self.set_salary)
        set_btn = tk.Label(input_row, text="Set", bg=HIGHLIGHT, fg=GREEN,
                           font=("Segoe UI", 8, "bold"), padx=6, pady=2, cursor="hand2")
        set_btn.pack(side=tk.LEFT)
        set_btn.bind("<Button-1>", self.set_salary)

        # ── controls ─────────────────────────────────────────────────
        ctrl = tk.Frame(m, bg=BG)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        self.start_btn = tk.Label(ctrl, text="▶  Start", bg=GREEN, fg="#1a1a2e",
                                  font=("Segoe UI", 8, "bold"), padx=8, pady=3,
                                  cursor="hand2", relief=tk.FLAT)
        self.start_btn.pack(side=tk.LEFT)
        self.start_btn.bind("<Button-1>", self.toggle_tracking)
        rst = tk.Label(ctrl, text="↺  Reset", bg=HIGHLIGHT, fg=DIM,
                       font=("Segoe UI", 8, "bold"), padx=8, pady=3, cursor="hand2")
        rst.pack(side=tk.LEFT, padx=(6, 0))
        rst.bind("<Button-1>", self.reset_tracking)
        rst.bind("<Enter>", lambda e: rst.configure(fg=YELLOW))
        rst.bind("<Leave>", lambda e: rst.configure(fg=DIM))
        self.status_lbl = tk.Label(ctrl, text="Stopped", bg=BG, fg=DIM,
                                   font=("Segoe UI", 8), padx=8)
        self.status_lbl.pack(side=tk.LEFT)

        # ── elapsed timer ─────────────────────────────────────────────
        el = tk.Frame(m, bg=BG)
        el.pack(fill=tk.X, pady=(0, 6))
        tk.Label(el, text="Session", bg=BG, fg=DIM, font=("Segoe UI", 8),
                 width=8, anchor="w").pack(side=tk.LEFT)
        self.elapsed_lbl = tk.Label(el, text="00:00:00", bg=BG, fg=TEXT,
                                    font=("Courier", 10, "bold"), anchor="e")
        self.elapsed_lbl.pack(side=tk.RIGHT)

        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(0, 8))

        # ── rate breakdown ───────────────────────────────────────────
        rb_hdr = tk.Frame(m, bg=BG)
        rb_hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(rb_hdr, text="Rate breakdown", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.rates_btn = tk.Label(rb_hdr, text="Hide ▲", bg=BG, fg=YELLOW,
                                  font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.rates_btn.pack(side=tk.RIGHT)
        self.rates_btn.bind("<Button-1>", self.toggle_rates)

        self.rates_frame = tk.Frame(m, bg=BG)
        self.rates_frame.pack(fill=tk.X, pady=(0, 6))
        self.rate_labels = {}
        for key, label in [("per_minute","Per minute"), ("per_hour","Per hour"),
                           ("per_day","Per day"),       ("per_week","Per week"),
                           ("per_month","Per month")]:
            row = tk.Frame(self.rates_frame, bg=BG)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=label, bg=BG, fg=DIM, font=("Segoe UI", 8),
                     width=10, anchor="w").pack(side=tk.LEFT)
            lbl = tk.Label(row, text="—", bg=BG, fg=TEXT,
                           font=("Segoe UI", 9, "bold"), anchor="e")
            lbl.pack(side=tk.RIGHT)
            self.rate_labels[key] = lbl

        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(2, 8))

        # ── live earnings ─────────────────────────────────────────────
        tk.Label(m, text="Earnings (live)", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))
        earn = tk.Frame(m, bg=ACCENT, padx=8, pady=6)
        earn.pack(fill=tk.X)
        self.earned_labels = {}
        for key, label, color in [("today","Today",GREEN), ("week","Week",YELLOW), ("month","Month",ORANGE)]:
            row = tk.Frame(earn, bg=ACCENT)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, bg=ACCENT, fg=DIM,
                     font=("Segoe UI", 8), width=6, anchor="w").pack(side=tk.LEFT)
            lbl = tk.Label(row, text="—", bg=ACCENT, fg=color,
                           font=("Segoe UI", 11, "bold"), anchor="e")
            lbl.pack(side=tk.RIGHT)
            self.earned_labels[key] = lbl

        # ── session history ───────────────────────────────────────────
        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(8, 4))
        hist_hdr = tk.Frame(m, bg=BG)
        hist_hdr.pack(fill=tk.X, pady=(0, 2))
        tk.Label(hist_hdr, text="Session history", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.hist_btn = tk.Label(hist_hdr, text="Show ▼", bg=BG, fg=YELLOW,
                                 font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.hist_btn.pack(side=tk.RIGHT)
        self.hist_btn.bind("<Button-1>", self.toggle_history)
        self.hist_frame = tk.Frame(m, bg=ACCENT)
        self.hist_inner = tk.Frame(self.hist_frame, bg=ACCENT)
        self.hist_inner.pack(fill=tk.X, padx=4, pady=4)

        tk.Label(m, text="drag to move  •  Enter to set salary",
                 bg=BG, fg="#444455", font=("Segoe UI", 7)).pack(pady=(6, 0))

        self.update_rate_labels()

    # ── Collapsibles ─────────────────────────────────────────────────

    def toggle_settings(self, event=None):
        self.settings_visible = not self.settings_visible
        if self.settings_visible:
            self.settings_frame.pack(fill=tk.X, pady=(0, 6), after=self.settings_hdr)
            self.settings_btn.configure(text="Hide ▲")
        else:
            self.settings_frame.pack_forget()
            self.settings_btn.configure(text="Show ▼")

    def toggle_rates(self, event=None):
        self.rates_visible = not self.rates_visible
        if self.rates_visible:
            self.rates_frame.pack(fill=tk.X, pady=(0, 6))
            self.rates_btn.configure(text="Hide ▲")
        else:
            self.rates_frame.pack_forget()
            self.rates_btn.configure(text="Show ▼")

    def toggle_history(self, event=None):
        self.history_visible = not self.history_visible
        if self.history_visible:
            self._rebuild_history()
            self.hist_frame.pack(fill=tk.X, pady=(0, 6))
            self.hist_btn.configure(text="Hide ▲")
        else:
            self.hist_frame.pack_forget()
            self.hist_btn.configure(text="Show ▼")

    def _rebuild_history(self):
        for w in self.hist_inner.winfo_children():
            w.destroy()
        recent = list(reversed(self.sessions[-15:]))
        if not recent:
            tk.Label(self.hist_inner, text="No sessions saved yet.",
                     bg=ACCENT, fg=DIM, font=("Segoe UI", 8)).pack(pady=4)
            return
        for s in recent:
            row = tk.Frame(self.hist_inner, bg=ACCENT)
            row.pack(fill=tk.X, pady=1)
            tk.Label(row, text=s["date"], bg=ACCENT, fg=DIM,
                     font=("Segoe UI", 7), anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=s["duration"], bg=ACCENT, fg=TEXT,
                     font=("Courier", 7), padx=6).pack(side=tk.LEFT)
            cur  = s.get("currency", "USD")
            sym  = CUR_SYMBOLS.get(cur, cur + " ")
            val  = s.get("earned", 0)
            fmtd = f"{sym}{val:,.0f}" if cur in NO_DECIMAL else f"{sym}{val:,.2f}"
            tk.Label(row, text=fmtd, bg=ACCENT, fg=GREEN,
                     font=("Segoe UI", 8, "bold"), anchor="e").pack(side=tk.RIGHT)

    # ── Actions ─────────────────────────────────────────────────────

    def set_salary(self, event=None):
        try:
            val = float(self.salary_entry.get().replace(",", "."))
            self.hourly_rate = max(0.0, val)
        except ValueError:
            self.hourly_rate = 0.0
        self.base_hourly_rate = self.hourly_rate
        self.base_currency = self.cur_var.get()
        self.update_rate_labels()
        self.save_config()

    def _on_cur_change(self, *args):
        new_cur = self.cur_var.get()

        if not self.fx_rates:
            self.cur_var.set(self.currency)
            self.fx_status_var.set("Fetch live rates to convert salary")
            return

        base_cur = self.base_currency
        base_rate = self.base_hourly_rate

        # convert base currency -> USD
        if base_cur == "USD":
            usd_amount = base_rate
        else:
            usd_amount = base_rate / self.fx_rates.get(base_cur, 1.0)

        # convert USD -> target currency
        if new_cur == "USD":
            converted = usd_amount
        else:
            converted = usd_amount * self.fx_rates.get(new_cur, 1.0)

        self.hourly_rate = round(converted, 4)

        self.salary_entry.delete(0, tk.END)
        self.salary_entry.insert(0, f"{self.hourly_rate:.2f}")

        self.currency = new_cur
        self.base_currency = new_cur
        self.base_hourly_rate = self.hourly_rate
        self.rate_lbl.configure(text=f"Hourly rate ({new_cur})")

        self.update_rate_labels()
        self.save_config()

    def toggle_tracking(self, event=None):
        if self.is_running:
            self.accumulated_seconds += (datetime.now() - self.session_start).total_seconds()
            self.session_start = None
            self.is_running = False
            self.start_btn.configure(text="▶  Start", bg=GREEN)
            self.status_lbl.configure(text="Paused")
        else:
            self.session_start = datetime.now()
            self.is_running = True
            self.start_btn.configure(text="⏹  Pause", bg=ORANGE)
            self.status_lbl.configure(text="Running")

    def reset_tracking(self, event=None):
        total = self.get_total_seconds()
        if total > 1:
            self._record_session(total)
            if self.history_visible:
                self._rebuild_history()
        self.is_running = False
        self.session_start = None
        self.accumulated_seconds = 0.0
        self.start_btn.configure(text="▶  Start", bg=GREEN)
        self.status_lbl.configure(text="Stopped")
        self.save_config()

    def _record_session(self, secs: float):
        self.sessions.append({
            "date":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "duration": self.fmt_time(secs),
            "earned":   round((secs / 3600.0) * self.hourly_rate, 2),
            "currency": self.cur_var.get(),
        })

    # ── Display ──────────────────────────────────────────────────────

    def update_rate_labels(self):
        h = self.hourly_rate
        self.rate_labels["per_minute"].configure(text=self.fmt(h / 60))
        self.rate_labels["per_hour"].configure(text=self.fmt(h))
        self.rate_labels["per_day"].configure(text=self.fmt(h * HOURS_PER_DAY))
        self.rate_labels["per_week"].configure(text=self.fmt(h * HOURS_PER_DAY * DAYS_PER_WEEK))
        self.rate_labels["per_month"].configure(
            text=self.fmt(h * HOURS_PER_DAY * DAYS_PER_WEEK * WEEKS_PER_MONTH))

    def get_total_seconds(self) -> float:
        total = self.accumulated_seconds
        if self.is_running and self.session_start:
            total += (datetime.now() - self.session_start).total_seconds()
        return total

    def fmt_time(self, secs: float) -> str:
        s = int(secs)
        h, rem = divmod(s, 3600)
        m, sc = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sc:02d}"

    def update_display(self):
        total_secs  = self.get_total_seconds()
        total_hours = total_secs / 3600.0
        today       = date.today()

        self.elapsed_lbl.configure(text=self.fmt_time(total_secs))

        today_e = total_hours * self.hourly_rate
        week_e  = (weekdays_before_today_this_week(today)  * HOURS_PER_DAY + total_hours) * self.hourly_rate
        month_e = (weekdays_before_today_this_month(today) * HOURS_PER_DAY + total_hours) * self.hourly_rate

        self.earned_labels["today"].configure(text=self.fmt(today_e))
        self.earned_labels["week"].configure(text=self.fmt(week_e))
        self.earned_labels["month"].configure(text=self.fmt(month_e))

        self.root.after(1000, self.update_display)

    # ── Window ───────────────────────────────────────────────────────

    def _on_close(self):
        total = self.get_total_seconds()
        if total > 1:
            self._record_session(total)
        self.save_config()
        self.root.destroy()

    def position_window(self):
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        self.root.geometry(f"{w}x{h}+{self.root.winfo_screenwidth() - w - 24}+60")

    def start_drag(self, event):
        self._drag_x = event.x_root - self.root.winfo_x()
        self._drag_y = event.y_root - self.root.winfo_y()

    def do_drag(self, event):
        self.root.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    SalaryTracker().run()