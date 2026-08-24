"""
Salary Tracker – Desktop Widget
Rate is always stored in USD internally.
All displays convert USD → chosen currency using live FX rates.
Switching currency instantly updates input field + every label.
"""

import tkinter as tk
import json
import threading
import urllib.request
from datetime import datetime, date
from pathlib import Path

CONFIG_PATH = Path.home() / ".salary_tracker.json"
FX_URL      = "https://openexchangerates.org/api/latest.json?app_id={key}"

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
    "USD":"$",   "EUR":"€",   "GBP":"£",   "JPY":"¥",   "PLN":"zł",
    "CHF":"Fr",  "CAD":"C$",  "AUD":"A$",  "SEK":"kr",  "NOK":"kr",
    "DKK":"kr",  "INR":"₹",   "BRL":"R$",  "MXN":"$",   "SGD":"S$",
    "HKD":"HK$", "NZD":"NZ$", "KRW":"₩",   "CNY":"¥",   "TRY":"₺",
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
        d = d.replace(day=d.day + 1)
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

        # ── Core: rate is ALWAYS stored in USD ──────────────────────
        self.hourly_rate_usd = 0.0   # single source of truth
        self.currency        = "USD"
        self.api_key         = ""
        self.fx_rates        = {}    # {"PLN": 4.02, "EUR": 0.92, …} all vs USD
        self.sessions        = []

        self.accumulated_seconds = 0.0
        self.session_start       = None
        self.is_running          = False

        self.rates_visible    = True
        self.settings_visible = False
        self.history_visible  = False
        self._drag_x = self._drag_y = 0

        self.load_config()
        self.build_ui()
        # Auto-open FX panel if rates not yet loaded so user knows what to do
        if not self.fx_rates:
            self.root.after(150, self.toggle_settings)
            self.root.after(160, lambda: self.fx_status_var.set(
                "⚠  Fetch rates to enable currency conversion"))
        # Auto-refresh rates on startup whenever an API key is stored
        if self.api_key:
            self.root.after(900, self._auto_fetch)
        self.update_display()
        self.position_window()

    # ── Helpers: USD ↔ local ────────────────────────────────────────

    def usd_to_local(self, usd: float, cur: str = None) -> float:
        """Convert a USD amount to the selected (or given) currency."""
        c = cur or self.cur_var.get()
        if c == "USD":
            return usd
        return usd * self.fx_rates.get(c, 1.0)

    def local_to_usd(self, local: float, cur: str = None) -> float:
        """Convert a local-currency amount back to USD."""
        c = cur or self.cur_var.get()
        if c == "USD":
            return local
        rate = self.fx_rates.get(c, 1.0)
        return local / rate if rate else local

    def get_local_rate(self, cur: str = None) -> float:
        """Hourly rate in chosen currency."""
        return self.usd_to_local(self.hourly_rate_usd, cur)

    def fmt(self, amount: float, cur: str = None) -> str:
        c = cur or self.cur_var.get()
        sym = CUR_SYMBOLS.get(c, c + " ")
        if c in NO_DECIMAL:
            return f"{sym}{amount:,.0f}"
        return f"{sym}{amount:,.2f}"

    # ── Persistence ─────────────────────────────────────────────────

    def load_config(self):
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text())
                self.hourly_rate_usd = cfg.get("hourly_rate_usd", 0.0)
                self.currency        = cfg.get("currency", "USD")
                self.api_key         = cfg.get("api_key", "")
                self.fx_rates        = cfg.get("fx_rates", {})
                self.sessions        = cfg.get("sessions", [])
            except Exception:
                pass

    def save_config(self):
        try:
            CONFIG_PATH.write_text(json.dumps({
                "hourly_rate_usd": self.hourly_rate_usd,
                "currency":        self.currency,
                "api_key":         self.api_key,
                "fx_rates":        self.fx_rates,
                "sessions":        self.sessions[-100:],
            }, indent=2))
        except Exception:
            pass

    # ── FX ──────────────────────────────────────────────────────────

    def fetch_fx(self, event=None):
        key = self.api_key_var.get().strip()
        if not key:
            self.fx_status_var.set("⚠  Enter API key first")
            return
        self.api_key = key
        self.fx_status_var.set("Fetching rates…")
        threading.Thread(target=self._fetch_thread, args=(key,), daemon=True).start()

    def _fetch_thread(self, key):
        try:
            with urllib.request.urlopen(FX_URL.format(key=key), timeout=10) as r:
                data = json.loads(r.read())
            if data.get("error"):
                raise ValueError(data.get("message", "API error"))
            self.fx_rates = data.get("rates", {})
            self.root.after(0, self._fx_ok)
        except Exception as e:
            self.root.after(0, lambda err=str(e): self._fx_err(err))

    def _fx_ok(self):
        self.fx_status_var.set("✓  Rates updated — switch currencies freely")
        self.save_config()
        # Refresh input field + all labels with new rates
        self._refresh_input_field()
        self.update_rate_labels()

    def _fx_err(self, msg):
        self.fx_status_var.set(f"✗  {msg[:40]}")

    def _auto_fetch(self):
        """Silently re-fetch rates on startup when an API key is already saved."""
        self.api_key_var.set(self.api_key)
        self.fetch_fx()

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

        # ── Currency & FX settings (collapsible) ─────────────────────
        self.settings_hdr = tk.Frame(m, bg=BG)
        self.settings_hdr.pack(fill=tk.X, pady=(0, 4))
        tk.Label(self.settings_hdr, text="Currency & FX", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.settings_btn = tk.Label(self.settings_hdr, text="Show ▼", bg=BG, fg=YELLOW,
                                     font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.settings_btn.pack(side=tk.RIGHT)
        self.settings_btn.bind("<Button-1>", self.toggle_settings)

        self.settings_frame = tk.Frame(m, bg=ACCENT, padx=6, pady=6)

        # API key row
        api_row = tk.Frame(self.settings_frame, bg=ACCENT)
        api_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(api_row, text="API key", bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), width=8, anchor="w").pack(side=tk.LEFT)
        self.api_key_var = tk.StringVar(value=self.api_key)
        tk.Entry(api_row, textvariable=self.api_key_var, width=22,
                 bg=HIGHLIGHT, fg=TEXT, insertbackground=TEXT,
                 relief=tk.FLAT, font=("Segoe UI", 8), bd=3, show="*").pack(side=tk.LEFT, padx=4)

        # Currency picker
        cur_row = tk.Frame(self.settings_frame, bg=ACCENT)
        cur_row.pack(fill=tk.X, pady=(0, 4))
        tk.Label(cur_row, text="Display", bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), width=8, anchor="w").pack(side=tk.LEFT)
        self.cur_var = tk.StringVar(value=self.currency)
        menu = tk.OptionMenu(cur_row, self.cur_var, *CURRENCIES, command=self._on_cur_change)
        menu.configure(bg=HIGHLIGHT, fg=GREEN, activebackground=HIGHLIGHT, activeforeground=GREEN,
                       relief=tk.FLAT, font=("Segoe UI", 9, "bold"), bd=0, highlightthickness=0)
        menu["menu"].configure(bg=HIGHLIGHT, fg=TEXT, activebackground=HIGHLIGHT, font=("Segoe UI", 8))
        menu.pack(side=tk.LEFT, padx=4)

        # Fetch button + status
        fetch_row = tk.Frame(self.settings_frame, bg=ACCENT)
        fetch_row.pack(fill=tk.X, pady=(4, 0))
        fetch_btn = tk.Label(fetch_row, text="↻  Fetch live rates", bg=HIGHLIGHT, fg=GREEN,
                             font=("Segoe UI", 8, "bold"), padx=6, pady=2, cursor="hand2")
        fetch_btn.pack(side=tk.LEFT)
        fetch_btn.bind("<Button-1>", self.fetch_fx)
        self.fx_status_var = tk.StringVar(value="")
        tk.Label(fetch_row, textvariable=self.fx_status_var, bg=ACCENT, fg=DIM,
                 font=("Segoe UI", 7), padx=6).pack(side=tk.LEFT)

        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(4, 8))

        # ── Hourly rate input ─────────────────────────────────────────
        input_row = tk.Frame(m, bg=BG)
        input_row.pack(fill=tk.X, pady=(0, 6))
        self.rate_lbl = tk.Label(input_row, text=f"Hourly rate ({self.currency})",
                                 bg=BG, fg=DIM, font=("Segoe UI", 8))
        self.rate_lbl.pack(side=tk.LEFT)
        self.salary_entry = tk.Entry(input_row, width=9, bg=HIGHLIGHT, fg=TEXT,
                                     insertbackground=TEXT, relief=tk.FLAT,
                                     font=("Segoe UI", 10, "bold"), bd=4, justify="right")
        self.salary_entry.pack(side=tk.LEFT, padx=(6, 6))
        # Populate with local-currency rate on startup
        local_on_start = self.get_local_rate()
        self.salary_entry.insert(0, f"{local_on_start:.2f}")
        self.salary_entry.bind("<Return>", self.set_salary)
        set_btn = tk.Label(input_row, text="Set", bg=HIGHLIGHT, fg=GREEN,
                           font=("Segoe UI", 8, "bold"), padx=6, pady=2, cursor="hand2")
        set_btn.pack(side=tk.LEFT)
        set_btn.bind("<Button-1>", self.set_salary)

        # ── Controls ─────────────────────────────────────────────────
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

        # ── Elapsed timer ─────────────────────────────────────────────
        el = tk.Frame(m, bg=BG)
        el.pack(fill=tk.X, pady=(0, 6))
        tk.Label(el, text="Session", bg=BG, fg=DIM, font=("Segoe UI", 8),
                 width=8, anchor="w").pack(side=tk.LEFT)
        self.elapsed_lbl = tk.Label(el, text="00:00:00", bg=BG, fg=TEXT,
                                    font=("Courier", 10, "bold"), anchor="e")
        self.elapsed_lbl.pack(side=tk.RIGHT)

        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(0, 8))

        # ── Rate breakdown (collapsible) ──────────────────────────────
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

        # ── Live earnings ─────────────────────────────────────────────
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

        # ── Session history (collapsible) ─────────────────────────────
        tk.Frame(m, bg=HIGHLIGHT, height=1).pack(fill=tk.X, pady=(8, 4))
        hist_hdr = tk.Frame(m, bg=BG)
        hist_hdr.pack(fill=tk.X, pady=(0, 2))
        tk.Label(hist_hdr, text="Session history", bg=BG, fg=DIM,
                 font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self.hist_btn = tk.Label(hist_hdr, text="Show ▼", bg=BG, fg=YELLOW,
                                 font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.hist_btn.pack(side=tk.RIGHT)
        self.hist_btn.bind("<Button-1>", self.toggle_history)
        self.hist_frame  = tk.Frame(m, bg=ACCENT)
        self.hist_inner  = tk.Frame(self.hist_frame, bg=ACCENT)
        self.hist_inner.pack(fill=tk.X, padx=4, pady=4)

        tk.Label(m, text="drag to move  •  Enter to set salary",
                 bg=BG, fg="#444455", font=("Segoe UI", 7)).pack(pady=(6, 0))

        self.update_rate_labels()

    # ── Collapsible panels ──────────────────────────────────────────

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
            val  = s.get("earned_local", s.get("earned", 0))
            fmtd = f"{sym}{val:,.0f}" if cur in NO_DECIMAL else f"{sym}{val:,.2f}"
            tk.Label(row, text=fmtd, bg=ACCENT, fg=GREEN,
                     font=("Segoe UI", 8, "bold"), anchor="e").pack(side=tk.RIGHT)

    # ── Actions ─────────────────────────────────────────────────────

    def set_salary(self, event=None):
        """Read the local-currency value and convert to USD for storage."""
        try:
            val_local = float(self.salary_entry.get().replace(",", "."))
            self.hourly_rate_usd = max(0.0, self.local_to_usd(val_local))
        except ValueError:
            self.hourly_rate_usd = 0.0
        self.update_rate_labels()
        self.save_config()

    def _on_cur_change(self, new_cur: str):
        """User switched display currency → convert input field and refresh all labels."""
        self.currency = new_cur
        self.rate_lbl.configure(text=f"Hourly rate ({new_cur})")
        # Guard: if rates not loaded yet, open settings and show a clear warning
        if new_cur != "USD" and not self.fx_rates:
            if not self.settings_visible:
                self.toggle_settings()
            self.fx_status_var.set(f"⚠  Rates not loaded — values shown in USD, not {new_cur}")
        self._refresh_input_field()
        self.update_rate_labels()
        self.save_config()

    def _refresh_input_field(self):
        """Update the salary entry to show the rate in the currently selected currency."""
        local = self.get_local_rate()
        self.salary_entry.delete(0, tk.END)
        self.salary_entry.insert(0, f"{local:.4f}" if local < 0.01 else f"{local:.2f}")

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
        cur = self.cur_var.get()
        earned_usd   = (secs / 3600.0) * self.hourly_rate_usd
        earned_local = self.usd_to_local(earned_usd, cur)
        self.sessions.append({
            "date":         datetime.now().strftime("%Y-%m-%d %H:%M"),
            "duration":     self.fmt_time(secs),
            "earned_usd":   round(earned_usd, 4),
            "earned_local": round(earned_local, 2),
            "currency":     cur,
        })

    # ── Display ──────────────────────────────────────────────────────

    def update_rate_labels(self):
        """Rate breakdown — all values converted from USD to display currency."""
        h = self.get_local_rate()
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

        # Earn in USD, convert to local for display
        today_usd = total_hours * self.hourly_rate_usd
        week_usd  = (weekdays_before_today_this_week(today)  * HOURS_PER_DAY + total_hours) * self.hourly_rate_usd
        month_usd = (weekdays_before_today_this_month(today) * HOURS_PER_DAY + total_hours) * self.hourly_rate_usd

        self.earned_labels["today"].configure(text=self.fmt(self.usd_to_local(today_usd)))
        self.earned_labels["week"].configure(text=self.fmt(self.usd_to_local(week_usd)))
        self.earned_labels["month"].configure(text=self.fmt(self.usd_to_local(month_usd)))

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