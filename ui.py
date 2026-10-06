import ctypes
import tkinter as tk
from tkinter import messagebox, ttk

app = None
root = None
running = False
overlay_windows = []
overlays_visible = True
size_labels = {}
OVERLAY_ALPHA = 0.3
GRIP_SIZE = 5
FIXED_SIZE = {'win_end_color', 'refresh_button', 'ball_start_color'}
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x20
WDA_EXCLUDEFROMCAPTURE = 0x11
HWND_TOPMOST = ctypes.c_void_p(-1)
SWP_TOPMOST_FLAGS = 0x0001 | 0x0002 | 0x0010 | 0x0020
BG, CARD, FG, MUTED = '#1e2229', '#2a3039', '#e6e6e6', '#9aa3ad'
FONT = 'Segoe UI'
user32 = ctypes.windll.user32

def on_button_press(event):
    window = event.widget.winfo_toplevel()
    window.start_x = event.x_root - window.winfo_x()
    window.start_y = event.y_root - window.winfo_y()

def on_drag(event):
    window = event.widget.winfo_toplevel()
    new_x = event.x_root - window.start_x
    new_y = event.y_root - window.start_y
    window.geometry(f'+{new_x}+{new_y}')
    with app.coordinate_lock:
        window.object_data['x'] = new_x
        window.object_data['y'] = new_y

def on_grip_press(event):
    window = event.widget.winfo_toplevel()
    window.start_x = event.x_root - window.winfo_width()
    window.start_y = event.y_root - window.winfo_height()

def on_grip_drag(event):
    window = event.widget.winfo_toplevel()
    width = max(GRIP_SIZE, event.x_root - window.start_x)
    height = max(GRIP_SIZE, event.y_root - window.start_y)
    data = window.object_data
    window.geometry(f"{width}x{height}+{data['x']}+{data['y']}")
    window.label.config(text=f"{data['name']} {width}x{height}")
    size_labels[data['name']].config(text=f'{width} x {height}')
    with app.coordinate_lock:
        data['width'] = width
        data['height'] = height

def raise_overlay(window):
    user32.SetWindowPos(window.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_TOPMOST_FLAGS)

def create_overlay(button, background, foreground):
    window = tk.Toplevel(root)
    window.geometry(f"{button['width']}x{button['height']}+{button['x']}+{button['y']}")
    window.overrideredirect(True)
    window.attributes('-alpha', OVERLAY_ALPHA)
    window.attributes('-topmost', True)
    window.object_data = button
    window.update_idletasks()
    window.hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
    user32.SetWindowDisplayAffinity(window.hwnd, WDA_EXCLUDEFROMCAPTURE)
    frame = tk.Frame(window, bg=background, highlightthickness=2)
    frame.pack(fill=tk.BOTH, expand=True)
    window.label = tk.Label(frame, text=button['name'], font=('Arial', 6), fg=foreground, bg=background, anchor='nw', padx=2, pady=2)
    window.label.place(x=0, y=0)
    for widget in (frame, window.label):
        widget.bind('<ButtonPress-1>', on_button_press)
        widget.bind('<B1-Motion>', on_drag)
    if button['name'] not in FIXED_SIZE:
        grip = tk.Frame(frame, bg=foreground, width=GRIP_SIZE, height=GRIP_SIZE, cursor='size_nw_se')
        grip.place(relx=1.0, rely=1.0, anchor='se')
        grip.bind('<ButtonPress-1>', on_grip_press)
        grip.bind('<B1-Motion>', on_grip_drag)
    raise_overlay(window)
    overlay_windows.append(window)

def toggle_overlays():
    global overlays_visible
    overlays_visible = not overlays_visible
    buttons['toggle'].config(text='Hide overlays' if overlays_visible else 'Show overlays')
    for window in overlay_windows:
        window.attributes('-alpha', OVERLAY_ALPHA if overlays_visible else 0.0)
        if overlays_visible:
            raise_overlay(window)

def set_running(value):
    global running
    running = value
    for window in overlay_windows:
        style = user32.GetWindowLongW(window.hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(window.hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT if value else style & ~WS_EX_TRANSPARENT)
        raise_overlay(window)
    buttons['start'].config(state='disabled' if value else 'normal')
    buttons['stop'].config(state='normal' if value else 'disabled')
    buttons['clear'].config(state='disabled' if value else 'normal')
    for check in mode_checks:
        check.config(state='disabled' if value else 'normal')

def update_status():
    if running and not app.worker_is_running():
        set_running(False)
    flow = app.flow
    state = 'WAITING' if running and flow.waiting else 'RUNNING' if running else 'STOPPED'
    status_label.config(text=state, fg={'WAITING': '#fbbf24', 'RUNNING': '#4ade80', 'STOPPED': '#f87171'}[state])
    phase_label.config(text=flow.phase_text if running else '')
    balance_label.config(text=f'{flow.balance:.2f}')
    delta_label.config(text=f'balance  ({flow.balance - app.cfg.balance:+.2f} this run)')
    pending = flow.pending
    total = len(flow.crashpoints)
    rate = f'{flow.rate_hits}/{total} {round(100 * flow.rate_hits / total)}%' if total else '0/0'
    hold = str(flow.hold_remaining) if flow.holding or flow.hold_plan else 'OFF'
    skip = str(flow.skip_remaining) if flow.skipping else 'OFF'
    values = (f'{flow.wins} / {flow.losses}', f'{flow.unknown} ({flow.unknown_stake:.2f})', f'{flow.base_loss_count} / {flow.base_loss_trigger}', f'T{pending.tier if pending is not None else 0}', f'{hold} / {skip}', rate if flow.rate_on else 'OFF')
    for label, value in zip(tile_values, values):
        label.config(text=value)
    if flow.best_mode:
        strategy_box.current(app.strategies.index(flow.strategy) + 1)
    notice_label.config(text='pattern swap queued' if flow.queued is not None else f'random {flow.strategy.label} {flow.strategy_losses}/{app.cfg.random_strategy_losses}' if flow.random_mode else f'next pick in {app.cfg.best_strategy_window - len(flow.window)}' if flow.best_mode else '')
    root.after(500, update_status)

def window_position():
    return {'x': root.winfo_x(), 'y': root.winfo_y()}

def show_error(message):
    messagebox.showerror('Crash Picker', message)

def apply_best():
    best = app.flow.best_mode
    strategy_box.config(state='disabled' if best else 'readonly')
    for key in ('bet_holding', 'max_loss_skipping'):
        feature_checks[key].config(state='disabled' if best else 'normal')

def best_toggled():
    app.set_best(best_var.get())
    apply_best()

def strategy_selected(event):
    root.focus_set()
    app.select_strategy(strategy_box.current())

def clear_images_clicked():
    if not messagebox.askyesno('Crash Picker', 'Delete every PNG in data/screenshots?'):
        return
    removed, failed = app.clear_images()
    messagebox.showinfo('Crash Picker', f'Removed {removed} image(s), {failed} failed.')

def build_ui(main_module):
    global app, root, watch_var, autoplay_var, best_var, mode_checks, feature_checks, buttons, status_label, phase_label, balance_label, delta_label, tile_values, strategy_box, notice_label
    app = main_module
    root = tk.Tk()
    root.title('Crash Picker')
    root.withdraw()
    root.config(bg=BG, padx=14, pady=12)
    for regions, background, foreground in ((app.inplay_objects, 'pink', 'black'), (app.restart_objects, 'blue', 'white')):
        for button in regions:
            create_overlay(button, background, foreground)
    top = tk.Frame(root, bg=BG)
    top.pack(fill=tk.X)
    status_label = tk.Label(top, text='STOPPED', fg='#f87171', bg=BG, font=(FONT, 11, 'bold'))
    status_label.pack(side=tk.LEFT)
    phase_label = tk.Label(top, text='', fg=FG, bg=BG, font=(FONT, 11))
    phase_label.pack(side=tk.RIGHT)
    balance_label = tk.Label(root, text='', fg=FG, bg=BG, font=(FONT, 30, 'bold'))
    balance_label.pack(anchor='w', pady=(6, 0))
    delta_label = tk.Label(root, text='', fg=MUTED, bg=BG, font=(FONT, 9))
    delta_label.pack(anchor='w')
    tiles = tk.Frame(root, bg=BG)
    tiles.pack(fill=tk.X, pady=10)
    tile_values = []
    for i, name in enumerate(('WINS / LOSSES', 'UNKNOWN', 'BASE LOSS', 'NEXT TIER', 'HOLD / SKIP', '3+ RATE')):
        card = tk.Frame(tiles, bg=CARD, padx=10, pady=6)
        card.grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky='nsew')
        tiles.columnconfigure(i % 3, weight=1)
        tk.Label(card, text=name, fg=MUTED, bg=CARD, font=(FONT, 7, 'bold')).pack()
        value = tk.Label(card, text='', fg=FG, bg=CARD, font=(FONT, 13))
        value.pack()
        tile_values.append(value)
    tk.Label(root, text='CRASH PATTERN', fg=MUTED, bg=BG, font=(FONT, 7, 'bold')).pack(anchor='w', pady=(0, 2))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('TCombobox', fieldbackground=CARD, background=CARD, foreground=FG, arrowcolor=FG, bordercolor=CARD, lightcolor=CARD, darkcolor=CARD, arrowsize=16, padding=(8, 5))
    style.map('TCombobox', fieldbackground=[('readonly', CARD)], foreground=[('disabled', MUTED), ('readonly', FG)], arrowcolor=[('disabled', MUTED)], selectbackground=[('readonly', CARD)], selectforeground=[('readonly', FG)], background=[('active', '#3b4250')])
    for option, value in (('background', CARD), ('foreground', FG), ('selectBackground', '#3b4250'), ('selectForeground', FG), ('font', (FONT, 10))):
        root.option_add(f'*TCombobox*Listbox.{option}', value)
    strategy_box = ttk.Combobox(root, values=['Random'] + [strategy.label for strategy in app.strategies], font=(FONT, 10), height=len(app.strategies) + 1)
    strategy_box.current(0 if app.flow.random_mode else app.strategies.index(app.flow.strategy) + 1)
    strategy_box.bind('<<ComboboxSelected>>', strategy_selected)
    strategy_box.pack(fill=tk.X, padx=3, pady=(0, 6))
    tk.Label(root, text='FEATURES', fg=MUTED, bg=BG, font=(FONT, 7, 'bold')).pack(anchor='w', pady=(0, 2))
    row = tk.Frame(root, bg=BG)
    row.pack(fill=tk.X, padx=3, pady=(0, 4))
    labels = (('bet_holding', f'Hold ({app.cfg.hold_range})'), ('max_loss_skipping', f'Skip ({app.cfg.skip_range})'), ('crashpoint_rate_enabled', f'3+ Rate ({app.cfg.crashpoint_rate_window})'), ('randomize_cashout', f'Cashout ±{app.cfg.cashout_range:g}%'))
    feature_checks = {}
    for key, text in labels:
        variable = tk.IntVar(value=int(app.features[key]))
        feature_checks[key] = tk.Checkbutton(row, text=text, variable=variable, command=lambda k=key, v=variable: app.set_feature(k, v.get()), bg=BG, fg=FG, selectcolor=BG, activebackground=BG, activeforeground=FG, disabledforeground=MUTED, font=(FONT, 9))
        feature_checks[key].pack(side=tk.LEFT, padx=(0, 10))
    grid = tk.Frame(root, bg=BG)
    grid.pack(fill=tk.X, pady=(4, 8))
    buttons = {}
    spec = (('start', 'Start', app.start_game, '#2f6f3e'), ('stop', 'Stop', app.stop_game, '#b45309'), ('toggle', 'Hide overlays', toggle_overlays, '#3b4250'),
            ('save', 'Save', app.save_changes, '#1d4ed8'), ('clear', 'Clear images', clear_images_clicked, '#6b5537'), ('exit', 'Exit', app.exit_program, '#991b1b'))
    for i, (key, text, command, background) in enumerate(spec):
        button = tk.Button(grid, text=text, command=command, bg=background, fg='white', disabledforeground='#7c8591', activebackground=background, activeforeground='white', relief='flat', font=(FONT, 10, 'bold'), width=13, pady=6)
        button.grid(row=i // 3, column=i % 3, padx=3, pady=3, sticky='ew')
        grid.columnconfigure(i % 3, weight=1)
        buttons[key] = button
    buttons['stop'].config(state='disabled')
    bottom = tk.Frame(root, bg=BG)
    bottom.pack(fill=tk.X)
    modes = tk.Frame(bottom, bg=BG)
    modes.pack(side=tk.LEFT, anchor='n')
    tk.Label(modes, text='MODES', fg=MUTED, bg=BG, font=(FONT, 7, 'bold')).pack(anchor='w', padx=3, pady=(0, 2))
    watch_var, autoplay_var, best_var = tk.IntVar(value=app.cfg.watch_mode), tk.IntVar(value=app.cfg.autoplay_mode), tk.IntVar(value=int(app.flow.best_mode))
    mode_checks = []
    for text, variable, command in (('Watch mode (no bets)', watch_var, None), ('Autoplay mode (click start)', autoplay_var, None), (f'Best pattern ({app.cfg.best_strategy_window})', best_var, best_toggled)):
        check = tk.Checkbutton(modes, text=text, variable=variable, command=command, bg=BG, fg=FG, selectcolor=BG, activebackground=BG, activeforeground=FG, disabledforeground=MUTED, font=(FONT, 9))
        check.pack(anchor='w')
        mode_checks.append(check)
    apply_best()
    table = tk.Frame(bottom, bg=BG)
    table.pack(side=tk.RIGHT, anchor='n', padx=(12, 0))
    tk.Label(table, text='OVERLAY REGIONS', fg=MUTED, bg=BG, font=(FONT, 7, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 2))
    for i, button in enumerate(app.inplay_objects + app.restart_objects, 1):
        tk.Label(table, text=button['name'], fg=FG, bg=BG, font=('Consolas', 9), width=17, anchor='w').grid(row=i, column=0)
        size_labels[button['name']] = tk.Label(table, text=f"{button['width']} x {button['height']}", fg=MUTED, bg=BG, font=('Consolas', 9), width=10, anchor='w')
        size_labels[button['name']].grid(row=i, column=1)
    notice_label = tk.Label(root, text='', fg=MUTED, bg=BG, font=(FONT, 8))
    notice_label.pack(anchor='e', pady=(8, 0))
    root.protocol('WM_DELETE_WINDOW', app.exit_program)
    root.update_idletasks()
    root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())
    if app.window_start is not None:
        root.geometry(f"+{app.window_start['x']}+{app.window_start['y']}")
    root.after(500, update_status)
    root.deiconify()
