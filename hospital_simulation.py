"""
Hospital Emergency Management System - Patient Flow Simulation
==============================================================
Python + Tkinter implementation of the project flowchart.

Flowchart step                     -> Where it lives in the code
------------------------------------------------------------------
Patient Arrives / Emergency?       -> Hospital.arrive()
Registration + Normal Queue (FIFO) -> collections.deque
Triage Check / Attendant Present?  -> Hospital.arrive()
Temporary / Unknown Record         -> Hospital.arrive()
Assign Emergency Priority          -> PRIORITY dictionary
Add to Priority Queue              -> heapq (min-heap)
Check Resource Availability        -> Hospital.allocate() / _try_admit()
ICU Bed / Doctor / Ambulance       -> lists of resources
Begin Treatment                    -> Hospital._try_admit()
Patient Recovered? (loop)          -> Hospital.treat()
Discharge + Store Record           -> Hospital.discharge() -> history list
"""

import heapq
import itertools
import random
from collections import deque
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk, messagebox

# ----------------------------------------------------------------------
# DATA
# ----------------------------------------------------------------------
PRIORITY = {"Critical": 1, "Serious": 2, "Normal": 3}   # lower = served first

DOCTORS = [
    ("Dr. Sharma", "Emergency"),
    ("Dr. Rawat", "Cardiology"),
    ("Dr. Negi", "General Medicine"),
    ("Dr. Bisht", "Orthopaedics"),
]

SAMPLE_NAMES = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Anjali", "Karan",
                "Meera", "Arjun", "Pooja", "Rahul", "Neha", "Amit", "Divya",
                "Suresh", "Kavita", "Manish", "Ritu", "Deepak", "Sunita"]

AMBULANCE_TRIP_TICKS = 3    # how long an ambulance stays busy


@dataclass
class Patient:
    pid: int
    name: str
    age: object
    emergency: bool
    attendant: bool = True
    severity: str = "Normal"
    needs_ambulance: bool = False
    temp_record: bool = False
    status: str = "Arrived"
    doctor: str = ""
    department: str = ""
    bed: object = None          # ICU bed index or None
    progress: int = 0           # recovery 0..100
    arrived_tick: int = 0
    discharged_tick: int = 0

    @property
    def kind(self):
        return "Emergency" if self.emergency else "Normal"


# ----------------------------------------------------------------------
# LOGIC (no GUI code here - this class is the flowchart)
# ----------------------------------------------------------------------
class Hospital:
    def __init__(self, icu_beds=3, ambulances=2, log=print):
        self.log = log
        self.tick_no = 0
        self._ids = itertools.count(1)
        self._seq = itertools.count()          # tie-breaker keeps heap stable

        self.records = {}                      # dictionary: pid -> Patient
        self.normal_queue = deque()            # FIFO queue of pids
        self.priority_queue = []               # heap of (priority, seq, pid)
        self.in_treatment = []                 # list of pids
        self.history = []                      # stack/list of discharged pids

        self.icu = [None] * icu_beds           # None = free, else pid
        self.doctors = [{"name": n, "dept": d, "patient": None} for n, d in DOCTORS]
        self.ambulances = [{"id": i + 1, "patient": None, "free_at": 0}
                           for i in range(ambulances)]

    # ---------------- START -> Patient Arrives -> Emergency? ----------
    def arrive(self, name="", age="", emergency=False, attendant=True,
               severity="Normal", needs_ambulance=False):
        pid = next(self._ids)
        p = Patient(pid, name or f"Patient-{pid}", age or "?", emergency,
                    arrived_tick=self.tick_no)
        self.records[pid] = p

        if not emergency:
            # NO branch: Normal Patient -> Registration -> Normal Queue (FIFO)
            p.status = "In normal queue"
            self.normal_queue.append(pid)
            self.log(f"P{pid} {p.name}: normal patient registered, "
                     f"added to FIFO queue (position {len(self.normal_queue)})")
            return p

        # YES branch: Emergency Patient -> Triage Check -> Attendant Present?
        p.attendant = attendant
        if attendant:
            self.log(f"P{pid} {p.name}: EMERGENCY, attendant present, details collected")
        else:
            p.name, p.age, p.temp_record = f"Unknown-{pid}", "?", True
            self.log(f"P{pid}: EMERGENCY, no attendant -> temporary/unknown record created")

        # Assign Emergency Priority -> Add to Priority Queue
        p.severity = severity
        p.needs_ambulance = needs_ambulance
        p.status = "In priority queue"
        heapq.heappush(self.priority_queue, (PRIORITY[severity], next(self._seq), pid))
        self.log(f"P{pid} {p.name}: priority = {severity}, added to priority queue")
        return p

    def random_arrival(self):
        if random.random() < 0.40:
            return self.arrive(
                name=random.choice(SAMPLE_NAMES), age=random.randint(1, 90),
                emergency=True, attendant=random.random() > 0.25,
                severity=random.choices(list(PRIORITY), weights=[3, 4, 3])[0],
                needs_ambulance=random.random() < 0.40)
        return self.arrive(name=random.choice(SAMPLE_NAMES),
                           age=random.randint(1, 90))

    # ---------------- Check Resource Availability ---------------------
    def _try_admit(self, p):
        """ICU Bed Available? / Doctor Available? / Ambulance Required?"""
        need_bed = p.emergency and p.severity == "Critical"
        doc = next((d for d in self.doctors if d["patient"] is None), None)
        bed = next((i for i, b in enumerate(self.icu) if b is None), None)
        amb = next((a for a in self.ambulances if a["patient"] is None), None)

        missing = []
        if doc is None:
            missing.append("doctor")
        if need_bed and bed is None:
            missing.append("ICU bed")
        if p.needs_ambulance and amb is None:
            missing.append("ambulance")
        if missing:
            reason = "Waiting for " + ", ".join(missing)
            if p.status != reason:
                p.status = reason
                self.log(f"P{p.pid} {p.name}: {reason.lower()}")
            return False

        parts = []
        if need_bed:                                   # Assign ICU Bed
            self.icu[bed] = p.pid
            p.bed = bed
            parts.append(f"ICU bed {bed + 1}")
        doc["patient"] = p.pid                         # Assign Doctor & Department
        p.doctor, p.department = doc["name"], doc["dept"]
        parts.append(f"{doc['name']} ({doc['dept']})")
        if p.needs_ambulance:                          # Allocate Ambulance
            amb["patient"] = p.pid
            amb["free_at"] = self.tick_no + AMBULANCE_TRIP_TICKS
            parts.append(f"ambulance {amb['id']}")

        p.status = "Under treatment"                   # Begin Treatment
        self.in_treatment.append(p.pid)
        self.log(f"P{p.pid} {p.name}: assigned {', '.join(parts)} -> treatment begins")
        return True

    def allocate(self):
        # Emergency patients first, in priority order. A patient who cannot
        # be served (e.g. no ICU bed) does not block the ones behind them.
        still_waiting = []
        while self.priority_queue:
            item = heapq.heappop(self.priority_queue)
            if not self._try_admit(self.records[item[2]]):
                still_waiting.append(item)
        for item in still_waiting:
            heapq.heappush(self.priority_queue, item)

        # Then normal patients, strictly first-in first-out.
        while self.normal_queue:
            if self._try_admit(self.records[self.normal_queue[0]]):
                self.normal_queue.popleft()
            else:
                break

    # ---------------- Patient Recovered? loop -------------------------
    def treat(self):
        for pid in list(self.in_treatment):
            p = self.records[pid]
            if p.emergency and p.severity == "Critical":
                gain = random.randint(8, 18)
            elif p.emergency and p.severity == "Serious":
                gain = random.randint(12, 25)
            else:
                gain = random.randint(20, 40)
            p.progress = min(100, p.progress + gain)   # Check Patient Status Again
            if p.progress >= 100:                      # Recovered? YES
                self.discharge(p)
            else:                                      # Recovered? NO
                p.status = "Continue treatment"

    # ---------------- Discharge -> Store Record -> END ----------------
    def discharge(self, p):
        self.in_treatment.remove(p.pid)
        if p.bed is not None:
            self.icu[p.bed] = None
        for d in self.doctors:
            if d["patient"] == p.pid:
                d["patient"] = None
        p.status = "Discharged"
        p.discharged_tick = self.tick_no
        self.history.append(p.pid)
        self.log(f"P{p.pid} {p.name}: recovered -> discharged, record stored in history")

    def _release_ambulances(self):
        for a in self.ambulances:
            if a["patient"] is not None and self.tick_no >= a["free_at"]:
                a["patient"] = None

    # ---------------- One simulation step -----------------------------
    def tick(self, auto_arrivals=True, arrival_rate=0.6):
        self.tick_no += 1
        self._release_ambulances()
        if auto_arrivals and random.random() < arrival_rate:
            self.random_arrival()
        self.treat()
        self.allocate()


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------
class App:
    FREE, BUSY = "#8fd9a8", "#f28b82"

    def __init__(self, root):
        self.root = root
        root.title("Hospital Emergency Management - Patient Flow Simulation")
        root.geometry("1250x760")
        root.minsize(1050, 650)
        self.running = False
        self.after_id = None
        self._build()
        self.reset()

    # ---------------- layout ------------------------------------------
    def _build(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=22)
        style.configure("Head.TLabel", font=("Segoe UI", 10, "bold"))

        left = ttk.Frame(self.root, padding=8)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self.root, padding=(0, 8, 8, 8))
        right.pack(side="left", fill="both", expand=True)

        # ---- New patient form ----
        form = ttk.LabelFrame(left, text="Patient Arrives", padding=8)
        form.pack(fill="x")
        self.v_name = tk.StringVar()
        self.v_age = tk.StringVar()
        self.v_emerg = tk.BooleanVar(value=False)
        self.v_attend = tk.BooleanVar(value=True)
        self.v_sev = tk.StringVar(value="Serious")
        self.v_amb = tk.BooleanVar(value=False)

        ttk.Label(form, text="Name").grid(row=0, column=0, sticky="w")
        self.e_name = ttk.Entry(form, textvariable=self.v_name, width=20)
        self.e_name.grid(row=0, column=1, pady=2)
        ttk.Label(form, text="Age").grid(row=1, column=0, sticky="w")
        self.e_age = ttk.Entry(form, textvariable=self.v_age, width=20)
        self.e_age.grid(row=1, column=1, pady=2)
        ttk.Checkbutton(form, text="Emergency?", variable=self.v_emerg,
                        command=self._toggle_form).grid(row=2, column=0, columnspan=2, sticky="w")
        self.c_attend = ttk.Checkbutton(form, text="Attendant present?",
                                        variable=self.v_attend, command=self._toggle_form)
        self.c_attend.grid(row=3, column=0, columnspan=2, sticky="w", padx=(16, 0))
        ttk.Label(form, text="Priority").grid(row=4, column=0, sticky="w", padx=(16, 0))
        self.c_sev = ttk.Combobox(form, textvariable=self.v_sev, values=list(PRIORITY),
                                  state="readonly", width=17)
        self.c_sev.grid(row=4, column=1, pady=2)
        self.c_amb = ttk.Checkbutton(form, text="Ambulance required?", variable=self.v_amb)
        self.c_amb.grid(row=5, column=0, columnspan=2, sticky="w", padx=(16, 0))
        ttk.Button(form, text="Add Patient", command=self.add_patient).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(6, 2))
        ttk.Button(form, text="Add Random Patient", command=self.add_random).grid(
            row=7, column=0, columnspan=2, sticky="ew")

        # ---- Simulation controls ----
        sim = ttk.LabelFrame(left, text="Simulation", padding=8)
        sim.pack(fill="x", pady=8)
        self.b_run = ttk.Button(sim, text="Start", command=self.toggle_run)
        self.b_run.pack(fill="x")
        ttk.Button(sim, text="Step (1 tick)", command=self.step).pack(fill="x", pady=2)
        self.v_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(sim, text="Automatic random arrivals",
                        variable=self.v_auto).pack(anchor="w")
        ttk.Label(sim, text="Speed (ms per tick)").pack(anchor="w", pady=(6, 0))
        self.v_speed = tk.IntVar(value=900)
        ttk.Scale(sim, from_=200, to=2000, variable=self.v_speed,
                  orient="horizontal").pack(fill="x")
        ttk.Label(sim, text="Arrival rate").pack(anchor="w", pady=(6, 0))
        self.v_rate = tk.DoubleVar(value=0.6)
        ttk.Scale(sim, from_=0.1, to=1.0, variable=self.v_rate,
                  orient="horizontal").pack(fill="x")

        setup = ttk.LabelFrame(left, text="Setup (applied on Reset)", padding=8)
        setup.pack(fill="x")
        self.v_beds = tk.IntVar(value=3)
        self.v_ambs = tk.IntVar(value=2)
        ttk.Label(setup, text="ICU beds").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(setup, from_=1, to=8, textvariable=self.v_beds, width=5).grid(row=0, column=1, padx=6)
        ttk.Label(setup, text="Ambulances").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(setup, from_=1, to=6, textvariable=self.v_ambs, width=5).grid(row=1, column=1, padx=6, pady=2)
        ttk.Button(setup, text="Reset", command=self.reset).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))

        self.l_stats = ttk.Label(left, justify="left", padding=(2, 10))
        self.l_stats.pack(fill="x")

        # ---- Resources ----
        res = ttk.LabelFrame(right, text="Resource Availability", padding=6)
        res.pack(fill="x")
        self.canvas = tk.Canvas(res, height=118, bg="white", highlightthickness=0)
        self.canvas.pack(fill="x")

        # ---- Tables ----
        tables = ttk.Frame(right)
        tables.pack(fill="both", expand=True, pady=6)
        tables.columnconfigure(0, weight=1)
        tables.columnconfigure(1, weight=1)
        tables.rowconfigure(1, weight=1)
        tables.rowconfigure(3, weight=1)

        self.t_prio = self._table(tables, 0, 0, "Priority Queue (Emergency)",
                                  [("ID", 45), ("Name", 110), ("Priority", 70), ("Status", 190)])
        self.t_norm = self._table(tables, 0, 1, "Normal Queue (FIFO)",
                                  [("ID", 45), ("Name", 110), ("Age", 50), ("Status", 190)])
        self.t_treat = self._table(tables, 2, 0, "Under Treatment",
                                   [("ID", 45), ("Name", 100), ("Type", 75), ("Doctor", 90),
                                    ("Dept", 110), ("ICU", 40), ("Recovery", 70)])
        self.t_hist = self._table(tables, 2, 1, "Discharged - History",
                                  [("ID", 45), ("Name", 110), ("Type", 75),
                                   ("Priority", 70), ("Ticks in hospital", 110)])
        for t in (self.t_prio, self.t_treat):
            t.tag_configure("Critical", background="#fde0dd")
            t.tag_configure("Serious", background="#fff3cd")

        # ---- Log ----
        logf = ttk.LabelFrame(right, text="Event Log", padding=4)
        logf.pack(fill="x")
        self.t_log = tk.Text(logf, height=8, state="disabled", wrap="word",
                             font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.t_log.yview)
        self.t_log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.t_log.pack(fill="x")

        self._toggle_form()

    def _table(self, parent, row, col, title, cols):
        ttk.Label(parent, text=title, style="Head.TLabel").grid(
            row=row, column=col, sticky="w", padx=4)
        tree = ttk.Treeview(parent, columns=[c for c, _ in cols], show="headings", height=6)
        for c, w in cols:
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        tree.grid(row=row + 1, column=col, sticky="nsew", padx=4, pady=(0, 6))
        return tree

    def _toggle_form(self):
        emerg = self.v_emerg.get()
        for w in (self.c_attend, self.c_amb):
            w.configure(state="normal" if emerg else "disabled")
        self.c_sev.configure(state="readonly" if emerg else "disabled")
        known = not (emerg and not self.v_attend.get())
        for w in (self.e_name, self.e_age):
            w.configure(state="normal" if known else "disabled")

    # ---------------- actions -----------------------------------------
    def reset(self):
        self.pause()
        try:
            beds, ambs = int(self.v_beds.get()), int(self.v_ambs.get())
        except (tk.TclError, ValueError):
            beds, ambs = 3, 2
        self.hospital = Hospital(max(1, beds), max(1, ambs), log=self.log)
        self.t_log.configure(state="normal")
        self.t_log.delete("1.0", "end")
        self.t_log.configure(state="disabled")
        self.log("System ready. Press Start, or add patients manually.")
        self.refresh()

    def add_patient(self):
        emerg = self.v_emerg.get()
        attend = self.v_attend.get()
        name, age = self.v_name.get().strip(), self.v_age.get().strip()
        if not (emerg and not attend):
            if not name:
                messagebox.showwarning("Missing details", "Please enter the patient's name.")
                return
            if age and not age.isdigit():
                messagebox.showwarning("Invalid age", "Age must be a number.")
                return
        self.hospital.arrive(name, age, emerg, attend, self.v_sev.get(),
                             self.v_amb.get() if emerg else False)
        self.hospital.allocate()
        self.v_name.set("")
        self.v_age.set("")
        self.refresh()

    def add_random(self):
        self.hospital.random_arrival()
        self.hospital.allocate()
        self.refresh()

    def step(self):
        self.hospital.tick(self.v_auto.get(), self.v_rate.get())
        self.refresh()

    def toggle_run(self):
        if self.running:
            self.pause()
        else:
            self.running = True
            self.b_run.configure(text="Pause")
            self._loop()

    def pause(self):
        self.running = False
        if self.after_id:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.b_run.configure(text="Start")

    def _loop(self):
        if not self.running:
            return
        self.step()
        self.after_id = self.root.after(int(self.v_speed.get()), self._loop)

    def log(self, msg):
        tick = self.hospital.tick_no if hasattr(self, "hospital") else 0
        self.t_log.configure(state="normal")
        self.t_log.insert("end", f"[t={tick:03d}] {msg}\n")
        self.t_log.see("end")
        self.t_log.configure(state="disabled")

    # ---------------- drawing -----------------------------------------
    def refresh(self):
        h = self.hospital
        rec = h.records

        def fill(tree, rows):
            tree.delete(*tree.get_children())
            for values, tag in rows:
                tree.insert("", "end", values=values, tags=(tag,))

        fill(self.t_prio, [((f"P{p.pid}", p.name, p.severity, p.status), p.severity)
                           for p in (rec[i[2]] for i in sorted(h.priority_queue))])
        fill(self.t_norm, [((f"P{p.pid}", p.name, p.age, p.status), "")
                           for p in (rec[i] for i in h.normal_queue)])
        fill(self.t_treat, [((f"P{p.pid}", p.name, p.kind, p.doctor, p.department,
                              "-" if p.bed is None else p.bed + 1, f"{p.progress}%"),
                             p.severity if p.emergency else "")
                            for p in (rec[i] for i in h.in_treatment)])
        fill(self.t_hist, [((f"P{p.pid}", p.name, p.kind,
                             p.severity if p.emergency else "-",
                             p.discharged_tick - p.arrived_tick), "")
                           for p in (rec[i] for i in reversed(h.history))])

        self.l_stats.configure(text=(
            f"Tick: {h.tick_no}\n"
            f"Total arrived: {len(rec)}\n"
            f"Emergency waiting: {len(h.priority_queue)}\n"
            f"Normal waiting: {len(h.normal_queue)}\n"
            f"Under treatment: {len(h.in_treatment)}\n"
            f"Discharged: {len(h.history)}"))
        self._draw_resources()

    def _draw_resources(self):
        c, h = self.canvas, self.hospital
        c.delete("all")

        def row(y, label, items):
            c.create_text(8, y + 15, text=label, anchor="w", font=("Segoe UI", 9, "bold"))
            x = 95
            for text, busy, width in items:
                c.create_rectangle(x, y, x + width, y + 30, outline="#555",
                                   fill=self.BUSY if busy else self.FREE)
                c.create_text(x + width / 2, y + 15, text=text, font=("Segoe UI", 8))
                x += width + 8

        row(6, "ICU Beds", [(f"Bed {i + 1}" + (f": P{b}" if b else ""), b is not None, 80)
                            for i, b in enumerate(h.icu)])
        row(44, "Doctors", [(d["name"] + (f": P{d['patient']}" if d["patient"] else ""),
                             d["patient"] is not None, 125) for d in h.doctors])
        row(82, "Ambulances", [(f"Amb {a['id']}" + (f": P{a['patient']}" if a["patient"] else ""),
                                a["patient"] is not None, 95) for a in h.ambulances])


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
