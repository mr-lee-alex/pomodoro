import tkinter as tk
from tkinter import ttk
import time
import threading
import winsound
import json
import os
from pathlib import Path


CONFIG_FILE = Path.home() / ".pomodoro_config.json"

DEFAULT_CONFIG = {
    "work_minutes": 25,
    "break_minutes": 5,
    "long_break_minutes": 15,
    "sessions_before_long_break": 4,
    "always_on_top": False,
    "window_x": None,
    "window_y": None,
}


class PomodoroTimer:
    COLORS = {
        "bg": "#1a1a2e",
        "fg": "#e0e0e0",
        "accent": "#e94560",
        "accent2": "#0f3460",
        "green": "#16c79a",
        "yellow": "#f5a623",
        "red": "#e94560",
        "gray": "#16213e",
        "light_gray": "#4a4a6a",
    }

    STATE_IDLE = "idle"
    STATE_RUNNING = "running"
    STATE_PAUSED = "paused"
    MODE_WORK = "work"
    MODE_BREAK = "break"
    MODE_LONG_BREAK = "long_break"

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("番茄钟")
        self.load_config()

        self.root.configure(bg=self.COLORS["bg"])
        self.root.resizable(False, False)
        self.root.overrideredirect(True)

        self.mode = self.MODE_WORK
        self.state = self.STATE_IDLE
        self.session_count = 0
        self.remaining_seconds = self._get_mode_seconds(self.MODE_WORK)
        self._paused_remaining = None
        self._timer_running = False
        self._drag_data = {"x": 0, "y": 0}

        self._build_ui()
        self._apply_position()
        self._bind_events()

        self._update_display()

    # ── config ──────────────────────────────────────────────

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                self.config = json.loads(CONFIG_FILE.read_text())
            except Exception:
                self.config = dict(DEFAULT_CONFIG)
        else:
            self.config = dict(DEFAULT_CONFIG)

    def save_config(self):
        try:
            CONFIG_FILE.write_text(json.dumps(self.config, indent=2))
        except Exception:
            pass

    # ── geometry helpers ───────────────────────────────────

    W = 320
    H = 420

    def _apply_position(self):
        x = self.config.get("window_x")
        y = self.config.get("window_y")
        if x is None or y is None:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x = (sw - self.W) // 2
            y = (sh - self.H) // 2
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _save_position(self):
        self.root.update_idletasks()
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.config["window_x"] = x
        self.config["window_y"] = y
        self.save_config()

    # ── mode helpers ───────────────────────────────────────

    def _get_mode_seconds(self, mode):
        if mode == self.MODE_WORK:
            return self.config["work_minutes"] * 60
        elif mode == self.MODE_LONG_BREAK:
            return self.config["long_break_minutes"] * 60
        else:
            return self.config["break_minutes"] * 60

    @property
    def mode_label(self):
        return {"work": "工作", "break": "休息", "long_break": "长休息"}[self.mode]

    @property
    def mode_color(self):
        return {"work": self.COLORS["red"], "break": self.COLORS["green"],
                "long_break": self.COLORS["green"]}[self.mode]

    # ── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        # title bar (drag handle)
        self.title_bar = tk.Frame(self.root, bg=self.COLORS["accent2"], height=32)
        self.title_bar.pack(fill=tk.X, side=tk.TOP)
        self.title_bar.pack_propagate(False)

        tk.Label(self.title_bar, text="🍅 番茄钟", bg=self.COLORS["accent2"],
                 fg=self.COLORS["fg"], font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=10)

        self.btn_min = tk.Label(self.title_bar, text="─", bg=self.COLORS["accent2"],
                                fg=self.COLORS["fg"], font=("Segoe UI", 14))
        self.btn_min.pack(side=tk.RIGHT, padx=4)

        self.btn_close = tk.Label(self.title_bar, text="✕", bg=self.COLORS["accent2"],
                                  fg=self.COLORS["fg"], font=("Segoe UI", 13))
        self.btn_close.pack(side=tk.RIGHT, padx=8)

        # main
        main = tk.Frame(self.root, bg=self.COLORS["bg"])
        main.pack(fill=tk.BOTH, expand=True)

        # mode indicator
        self.lbl_mode = tk.Label(main, text=self.mode_label, bg=self.COLORS["bg"],
                                 fg=self.mode_color, font=("Segoe UI", 13, "bold"))
        self.lbl_mode.pack(pady=(16, 0))

        # session count
        self.lbl_sessions = tk.Label(main, text="", bg=self.COLORS["bg"],
                                     fg=self.COLORS["light_gray"], font=("Segoe UI", 9))
        self.lbl_sessions.pack()

        # canvas – circular timer
        self.canvas = tk.Canvas(main, width=220, height=220, bg=self.COLORS["bg"],
                                highlightthickness=0)
        self.canvas.pack(pady=(6, 0))
        self._draw_canvas_base()

        # time label
        self.lbl_time = tk.Label(main, text="25:00", bg=self.COLORS["bg"],
                                 fg=self.COLORS["fg"], font=("Segoe UI", 40, "bold"))
        self.lbl_time.place(in_=self.canvas, relx=0.5, rely=0.5, anchor=tk.CENTER)

        # controls
        ctrl = tk.Frame(main, bg=self.COLORS["bg"])
        ctrl.pack(pady=(4, 0))

        self.btn_start = self._ctrl_btn(ctrl, "▶ 开始", self.COLORS["green"], self._on_start)
        self.btn_start.pack(side=tk.LEFT, padx=4)

        self.btn_pause = self._ctrl_btn(ctrl, "⏸ 暂停", self.COLORS["yellow"], self._on_pause)
        self.btn_reset = self._ctrl_btn(ctrl, "↺ 重置", self.COLORS["light_gray"], self._on_reset)

        # settings row
        set_row = tk.Frame(main, bg=self.COLORS["bg"])
        set_row.pack(pady=(10, 6))

        tk.Label(set_row, text="工作", bg=self.COLORS["bg"], fg=self.COLORS["light_gray"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.spin_work = tk.Spinbox(set_row, from_=1, to=120, width=3,
                                     bg=self.COLORS["gray"], fg=self.COLORS["fg"],
                                     buttonbackground=self.COLORS["accent2"],
                                     font=("Segoe UI", 9), justify=tk.CENTER)
        self.spin_work.delete(0, tk.END)
        self.spin_work.insert(0, str(self.config["work_minutes"]))
        self.spin_work.pack(side=tk.LEFT, padx=(2, 8))

        tk.Label(set_row, text="休息", bg=self.COLORS["bg"], fg=self.COLORS["light_gray"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.spin_break = tk.Spinbox(set_row, from_=1, to=60, width=3,
                                      bg=self.COLORS["gray"], fg=self.COLORS["fg"],
                                      buttonbackground=self.COLORS["accent2"],
                                      font=("Segoe UI", 9), justify=tk.CENTER)
        self.spin_break.delete(0, tk.END)
        self.spin_break.insert(0, str(self.config["break_minutes"]))
        self.spin_break.pack(side=tk.LEFT, padx=(2, 0))

        self._set_always_on_top(self.config.get("always_on_top", False))

    def _ctrl_btn(self, parent, text, color, cmd):
        btn = tk.Label(parent, text=text, bg=self.COLORS["gray"], fg=color,
                       font=("Segoe UI", 11), padx=10, pady=4, cursor="hand2")
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e: btn.configure(bg=self.COLORS["accent2"]))
        btn.bind("<Leave>", lambda e: btn.configure(bg=self.COLORS["gray"]))
        return btn

    def _draw_canvas_base(self):
        self.canvas.delete("all")
        cx, cy, r = 110, 110, 95
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                outline=self.COLORS["gray"], width=6, tags="bg")
        self.arc = self.canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                                          start=90, extent=0,
                                          outline=self.mode_color, width=6,
                                          style=tk.ARC, tags="arc")

    def _bind_events(self):
        self.title_bar.bind("<Button-1>", self._drag_start)
        self.title_bar.bind("<B1-Motion>", self._drag_move)
        self.btn_close.bind("<Button-1>", lambda e: self._on_close())
        self.btn_min.bind("<Button-1>", lambda e: self._on_minimize())

    # ── window controls ────────────────────────────────────

    def _drag_start(self, e):
        self._drag_data["x"] = e.x_root - self.root.winfo_x()
        self._drag_data["y"] = e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        x = e.x_root - self._drag_data["x"]
        y = e.y_root - self._drag_data["y"]
        self.root.geometry(f"+{x}+{y}")

    def _on_close(self):
        self._timer_running = False
        self.save_config()
        self.root.destroy()

    def _on_minimize(self):
        self.root.iconify()
        # standard title bar for taskbar support
        self.root.overrideredirect(False)
        self.root.attributes("-topmost", self.config.get("always_on_top", False))
        self.root.bind("<Map>", lambda e: self._on_restore())

    def _on_restore(self):
        self.root.overrideredirect(True)
        self._set_always_on_top(self.config.get("always_on_top", False))
        self._update_display()

    def _set_always_on_top(self, val):
        self.root.attributes("-topmost", val)
        self.config["always_on_top"] = val

    # ── timer logic ────────────────────────────────────────

    def _on_start(self):
        if self.state == self.STATE_IDLE:
            self._apply_spinner_values()
            self.remaining_seconds = self._get_mode_seconds(self.mode)
            self.state = self.STATE_RUNNING
            self.btn_start.pack_forget()
            self.btn_pause.pack(side=tk.LEFT, padx=4)
            self.btn_reset.pack(side=tk.LEFT, padx=4)
            self._spin_enabled(False)
            self._start_timer_thread()
        elif self.state == self.STATE_PAUSED:
            self.state = self.STATE_RUNNING
            self.btn_start.configure(text="▶ 继续")
            self._start_timer_thread()

    def _on_pause(self):
        if self.state == self.STATE_RUNNING:
            self.state = self.STATE_PAUSED
            self._paused_remaining = self.remaining_seconds
            self.btn_pause.pack_forget()
            self.btn_reset.pack_forget()
            self.btn_start.pack(side=tk.LEFT, padx=4)
            self.btn_start.configure(text="▶ 继续")
            self.btn_pause.pack(side=tk.LEFT, padx=4)

    def _on_reset(self):
        self.state = self.STATE_IDLE
        self._timer_running = False
        self.remaining_seconds = self._get_mode_seconds(self.mode)
        self._show_idle_controls()
        self._spin_enabled(True)
        self._update_display()

    def _show_idle_controls(self):
        self.btn_pause.pack_forget()
        self.btn_reset.pack_forget()
        self.btn_start.pack_forget()
        self.btn_start.configure(text="▶ 开始")
        self.btn_start.pack(side=tk.LEFT, padx=4)

    def _spin_enabled(self, val):
        st = "normal" if val else "disabled"
        self.spin_work.configure(state=st)
        self.spin_break.configure(state=st)

    def _apply_spinner_values(self):
        try:
            self.config["work_minutes"] = max(1, int(self.spin_work.get()))
        except ValueError:
            pass
        try:
            self.config["break_minutes"] = max(1, int(self.spin_break.get()))
        except ValueError:
            pass
        self.save_config()

    def _start_timer_thread(self):
        self._timer_running = True
        t = threading.Thread(target=self._tick, daemon=True)
        t.start()

    def _tick(self):
        while self._timer_running and self.state == self.STATE_RUNNING and self.remaining_seconds > 0:
            time.sleep(0.5)
            if self.state != self.STATE_RUNNING:
                break
            self.remaining_seconds -= 0.5
            if self.remaining_seconds < 0:
                self.remaining_seconds = 0
            self.root.after(0, self._update_display)

        if self._timer_running and self.remaining_seconds <= 0:
            self.root.after(0, self._on_timer_done)

    def _on_timer_done(self):
        self._timer_running = False
        self._play_alarm()

        if self.mode == self.MODE_WORK:
            self.session_count += 1
            if self.session_count % self.config["sessions_before_long_break"] == 0:
                self.mode = self.MODE_LONG_BREAK
            else:
                self.mode = self.MODE_BREAK
        else:
            self.mode = self.MODE_WORK

        self.remaining_seconds = self._get_mode_seconds(self.mode)
        self.state = self.STATE_IDLE
        self._show_idle_controls()
        self._spin_enabled(True)
        self._update_display()

        self._show_notification()

    def _play_alarm(self):
        for _ in range(3):
            try:
                winsound.Beep(880, 300)
                time.sleep(0.15)
            except Exception:
                pass

    def _show_notification(self):
        try:
            from plyer import notification
            if self.mode in (self.MODE_BREAK, self.MODE_LONG_BREAK):
                msg = f"完成第 {self.session_count} 个番茄！休息一下吧 ☕"
            else:
                msg = "休息结束，开始工作！💪"
            notification.notify(title="🍅 番茄钟", message=msg, timeout=5)
        except Exception:
            # fallback: flash window
            try:
                self.root.attributes("-topmost", False)
                time.sleep(0.1)
                self.root.attributes("-topmost", self.config.get("always_on_top", True))
            except Exception:
                pass

    # ── display ────────────────────────────────────────────

    def _update_display(self):
        total = self._get_mode_seconds(self.mode)
        secs = int(self.remaining_seconds)
        mins, sec = divmod(secs, 60)
        self.lbl_time.configure(text=f"{mins:02d}:{sec:02d}")

        total_secs = self._get_mode_seconds(self.mode)
        pct = 0 if total_secs == 0 else self.remaining_seconds / total_secs
        extent = -360 * (1 - pct)
        self.canvas.itemconfig("arc", extent=extent, outline=self.mode_color)

        self.lbl_mode.configure(text=self.mode_label, fg=self.mode_color)

        if self.session_count > 0:
            self.lbl_sessions.configure(text=f"已完成 {self.session_count} 个番茄 🍅")
        else:
            self.lbl_sessions.configure(text="")


def main():
    app = PomodoroTimer()
    app.root.mainloop()


if __name__ == "__main__":
    main()
