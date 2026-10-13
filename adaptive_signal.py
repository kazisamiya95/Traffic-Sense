import cv2
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import numpy as np



#  Tunable parameters
BASE_GREEN_SEC   = 10.0   # default green duration (seconds)
BASE_RED_SEC     = 10.0   # default red duration (seconds)
MIN_GREEN_SEC    = 5.0    # never go below this
MAX_GREEN_SEC    = 60.0   # cap to avoid starvation on other lanes
YELLOW_SEC       = 2.0    # fixed yellow phase

# How strongly each factor pulls the green time
DENSITY_WEIGHT   = 0.5    # extra seconds per vehicle above threshold
SPEED_VAR_WEIGHT = 0.2    # extra seconds per unit of speed std-dev
CONGESTION_BONUS = {"low": 0, "medium": 8, "high": 20}   # flat bonus (sec)

# Density thresholds (vehicles in lane)
LOW_DENSITY_THRESH    = 5
MEDIUM_DENSITY_THRESH = 7



#  Data structures
@dataclass
class LaneStats:
    """Per-lane snapshot passed in each frame."""
    lane_id: int
    vehicle_count: int          = 0
    avg_speed_kmh: float        = 0.0
    speed_std_kmh: float        = 0.0
    congestion_level: str       = "low"   # "low" | "medium" | "high"
    lane_crossing_count: int    = 0
    overspeed_count: int        = 0


@dataclass
class SignalPhase:
    """Represents one traffic light phase."""
    color: str          # "GREEN" | "YELLOW" | "RED"
    duration_sec: float
    elapsed_sec: float  = 0.0

    @property
    def remaining_sec(self) -> float:
        return max(0.0, self.duration_sec - self.elapsed_sec)

    @property
    def progress(self) -> float:
        """0.0 → 1.0 fraction of phase completed."""
        if self.duration_sec == 0:
            return 1.0
        return min(1.0, self.elapsed_sec / self.duration_sec)


@dataclass
class LaneSignalState:
    """Full signal state for one lane."""
    lane_id: int
    phase: SignalPhase = field(default_factory=lambda: SignalPhase("RED", BASE_RED_SEC))
    computed_green_sec: float = BASE_GREEN_SEC
    reason: str = ""            # human-readable explanation of last adjustment

    # Stats history (rolling)
    _density_history: List[int]   = field(default_factory=list)
    _speed_var_history: List[float] = field(default_factory=list)

    def update_history(self, stats: LaneStats, window: int = 30) -> None:
        self._density_history.append(stats.vehicle_count)
        self._speed_var_history.append(stats.speed_std_kmh)
        if len(self._density_history) > window:
            self._density_history.pop(0)
            self._speed_var_history.pop(0)

    @property
    def avg_density(self) -> float:
        return float(np.mean(self._density_history)) if self._density_history else 0.0

    @property
    def avg_speed_var(self) -> float:
        return float(np.mean(self._speed_var_history)) if self._speed_var_history else 0.0



#  Controller
class AdaptiveSignalController:

    def __init__(self, num_lanes: int, fps: float, cycle_offset_sec: float = 10.0):

        self.fps = fps
        self.num_lanes = num_lanes
        self.states: Dict[int, LaneSignalState] = {}

        for lane_id in range(num_lanes):
            state = LaneSignalState(lane_id=lane_id)
            # Stagger starting phase so lanes alternate naturally
            offset = lane_id * cycle_offset_sec
            if offset < BASE_GREEN_SEC:
                state.phase = SignalPhase("GREEN", BASE_GREEN_SEC, elapsed_sec=offset)
            else:
                state.phase = SignalPhase("RED",   BASE_RED_SEC,
                                          elapsed_sec=offset - BASE_GREEN_SEC)
            self.states[lane_id] = state

        self._last_frame: int = 0
        self._global_override: Optional[str] = None   # e.g. "EMERGENCY"

    # ── Public API 

    def update(self, frame_idx: int, lane_stats: List[LaneStats]) -> None:

        dt = (frame_idx - self._last_frame) / self.fps   # seconds since last call
        self._last_frame = frame_idx

        stats_by_id = {s.lane_id: s for s in lane_stats}

        for lane_id, state in self.states.items():
            stats = stats_by_id.get(lane_id, LaneStats(lane_id=lane_id))
            state.update_history(stats)

            # Recompute desired green time for this lane
            state.computed_green_sec = self._compute_green(stats, state)

            # Advance phase clock
            state.phase.elapsed_sec += dt

            # Transition phases when time is up
            if state.phase.elapsed_sec >= state.phase.duration_sec:
                self._advance_phase(state)

    def get_display_status(self) -> Dict[int, dict]:

        out = {}
        for lane_id, state in self.states.items():
            phase = state.phase
            color_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(phase.color, "⚪")
            out[lane_id] = {
                "color":     phase.color,
                "remaining": round(phase.remaining_sec, 1),
                "label":     f"{color_emoji} L{lane_id+1} {phase.color} — {phase.remaining_sec:.0f}s left",
                "reason":    state.reason,
                "progress":  phase.progress,
                "computed_green": round(state.computed_green_sec, 1),
            }
        return out

    def get_active_green_lanes(self) -> List[int]:
        """Returns list of lane_ids currently in GREEN phase."""
        return [lid for lid, s in self.states.items() if s.phase.color == "GREEN"]

    def force_green(self, lane_id: int, duration_sec: Optional[float] = None) -> None:
        """Emergency override — immediately give a lane a GREEN phase."""
        if lane_id in self.states:
            dur = duration_sec or self.states[lane_id].computed_green_sec
            self.states[lane_id].phase = SignalPhase("GREEN", dur)
            self.states[lane_id].reason = "FORCED GREEN (override)"

    # ── Internal helpers 
    

    def _compute_green(self, stats: LaneStats, state: LaneSignalState) -> float:

        base = BASE_GREEN_SEC
        reasons = []

        # Density component
        density_excess = max(0, stats.vehicle_count - LOW_DENSITY_THRESH)
        density_add = DENSITY_WEIGHT * density_excess
        if density_add > 0:
            reasons.append(f"+{density_add:.0f}s density({stats.vehicle_count}v)")

        # Speed variation component (chaotic traffic → give more time to clear)
        var_add = SPEED_VAR_WEIGHT * stats.speed_std_kmh
        if var_add > 1:
            reasons.append(f"+{var_add:.0f}s spd-var")

        # Congestion level flat bonus
        cong_add = CONGESTION_BONUS.get(stats.congestion_level, 0)
        if cong_add > 0:
            reasons.append(f"+{cong_add}s {stats.congestion_level}-cong")

        green = base + density_add + var_add + cong_add
        green = float(np.clip(green, MIN_GREEN_SEC, MAX_GREEN_SEC))

        state.reason = ", ".join(reasons) if reasons else "nominal"
        return green

    def _advance_phase(self, state: LaneSignalState) -> None:
        """Cycle GREEN → YELLOW → RED → GREEN with adaptive durations."""
        current = state.phase.color
        overflow = state.phase.elapsed_sec - state.phase.duration_sec  # carry leftover

        if current == "GREEN":
            state.phase = SignalPhase("YELLOW", YELLOW_SEC, elapsed_sec=overflow)
        elif current == "YELLOW":
            state.phase = SignalPhase("RED",    BASE_RED_SEC, elapsed_sec=overflow)
        elif current == "RED":
            # Use the freshly computed adaptive green duration
            state.phase = SignalPhase("GREEN", state.computed_green_sec, elapsed_sec=overflow)



#  FOUR-WAY INTERSECTION CONTROLLER (approach-level right-of-way)
# ============================================================================
# A real intersection does not give each detected *lane* its own
# independent light: every lane belonging to the same approach (e.g. both
# lanes of "west") is physically wired to one signal head and always shows
# the same color at the same time. Exactly one approach has the
# right-of-way (GREEN, then YELLOW) at any moment; every other approach is
# RED. This is a standard single-ring, fixed-sequence phase plan, with the
# GREEN duration for each approach made adaptive — based on that
# approach's own aggregated lane stats — instead of fixed.
#
# The ring always starts with WEST green and every other approach red (per
# spec), then advances clockwise (west -> north -> east -> south -> west
# ...) through whichever approaches are actually calibrated for this
# intersection. A 3-way T-junction simply omits the missing arm from the
# ring — no gaps, no dead phases.
APPROACH_COMPASS_ORDER = ["west", "north", "east", "south"]


def _compute_adaptive_green(stats: "LaneStats"):
    """Shared adaptive-green formula used for both a single lane
    (AdaptiveSignalController) and a whole approach's aggregated stats
    (IntersectionSignalController). Returns (green_seconds, reason_text)."""
    base = BASE_GREEN_SEC
    reasons = []

    density_excess = max(0, stats.vehicle_count - LOW_DENSITY_THRESH)
    density_add = DENSITY_WEIGHT * density_excess
    if density_add > 0:
        reasons.append(f"+{density_add:.0f}s density({stats.vehicle_count}v)")

    var_add = SPEED_VAR_WEIGHT * stats.speed_std_kmh
    if var_add > 1:
        reasons.append(f"+{var_add:.0f}s spd-var")

    cong_add = CONGESTION_BONUS.get(stats.congestion_level, 0)
    if cong_add > 0:
        reasons.append(f"+{cong_add}s {stats.congestion_level}-cong")

    green = base + density_add + var_add + cong_add
    green = float(np.clip(green, MIN_GREEN_SEC, MAX_GREEN_SEC))

    return green, (", ".join(reasons) if reasons else "nominal")


@dataclass
class ApproachSignalState:
    """Aggregated signal state for one intersection approach (i.e. every
    lane on that approach, all sharing one physical signal head)."""
    approach: str
    computed_green_sec: float = BASE_GREEN_SEC
    reason: str = ""

    _density_history: List[int] = field(default_factory=list)
    _speed_var_history: List[float] = field(default_factory=list)

    def update_history(self, stats: LaneStats, window: int = 30) -> None:
        self._density_history.append(stats.vehicle_count)
        self._speed_var_history.append(stats.speed_std_kmh)
        if len(self._density_history) > window:
            self._density_history.pop(0)
            self._speed_var_history.pop(0)


class IntersectionSignalController:
    """
    Adaptive real-world 4-way (or 3-way T-junction) intersection
    controller. Exactly one approach is GREEN -> YELLOW at a time (a
    single-ring, fixed-sequence phase plan); every other approach is RED.

    The cycle always STARTS with the WEST approach GREEN and every other
    approach RED, then advances clockwise through whichever of
    north/east/south are actually calibrated. Missing approaches
    (T-junctions) are skipped in the ring entirely.
    """

    def __init__(self, approaches: Dict[str, int], fps: float):
        """
        approaches: {approach_name: num_lanes} — any subset of
                    "north"/"south"/"east"/"west", as calibrated for this
                    intersection.
        """
        self.fps = fps
        self.approach_lane_counts: Dict[str, int] = dict(approaches)

        order = [a for a in APPROACH_COMPASS_ORDER if a in approaches]
        if not order:
            order = list(approaches.keys())
        if "west" in order:
            i = order.index("west")
            order = order[i:] + order[:i]
        self.cycle_order: List[str] = order

        self.states: Dict[str, ApproachSignalState] = {
            name: ApproachSignalState(approach=name) for name in order
        }

        # Cycle starts at index 0 (west, if present) GREEN; everything
        # else is implicitly RED since only the active index ever holds a
        # non-RED phase object (see get_display_status / _time_until_green).
        self.active_index = 0
        self.active_phase = SignalPhase("GREEN", BASE_GREEN_SEC)

        self._last_frame = 0

    # ── Public API ──

    def update(self, frame_idx: int, approach_stats: List[LaneStats]) -> None:
        dt = (frame_idx - self._last_frame) / self.fps
        self._last_frame = frame_idx

        stats_by_name = {s.lane_id: s for s in approach_stats}

        # Recompute every approach's desired adaptive green so both the
        # currently-waiting approaches' countdowns and whichever approach
        # goes green next reflect the latest traffic, not a stale value
        # from when it last had the right-of-way.
        for name, state in self.states.items():
            stats = stats_by_name.get(name, LaneStats(lane_id=name))
            state.update_history(stats)
            state.computed_green_sec, state.reason = _compute_adaptive_green(stats)

        self.active_phase.elapsed_sec += dt
        if self.active_phase.elapsed_sec >= self.active_phase.duration_sec:
            self._advance(overflow=self.active_phase.elapsed_sec - self.active_phase.duration_sec)

    def get_display_status(self) -> Dict[str, dict]:
        out = {}
        for idx, name in enumerate(self.cycle_order):
            state = self.states[name]
            if idx == self.active_index:
                color = self.active_phase.color
                remaining = self.active_phase.remaining_sec
                progress = self.active_phase.progress
            else:
                color = "RED"
                remaining = self._time_until_green(idx)
                progress = 0.0

            color_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(color, "⚪")
            n_lanes = self.approach_lane_counts.get(name, 0)
            out[name] = {
                "color":          color,
                "remaining":      round(remaining, 1),
                "label":          f"{color_emoji} {name.upper()} {color} — {remaining:.0f}s left",
                "reason":         state.reason,
                "progress":       progress,
                "computed_green": round(state.computed_green_sec, 1),
                "num_lanes":      n_lanes,
            }
        return out

    def get_active_green_approach(self) -> Optional[str]:
        """Returns the approach currently holding GREEN (not YELLOW/RED),
        or None if none is (e.g. mid-yellow)."""
        name = self.cycle_order[self.active_index]
        return name if self.active_phase.color == "GREEN" else None

    def force_green(self, approach_name: str, duration_sec: Optional[float] = None) -> None:
        """Emergency override — immediately give one approach (all its
        lanes) the right-of-way; every other approach is RED until the
        ring resumes from here on its next advance."""
        if approach_name not in self.states:
            return
        self.active_index = self.cycle_order.index(approach_name)
        dur = duration_sec or self.states[approach_name].computed_green_sec
        self.active_phase = SignalPhase("GREEN", dur)
        self.states[approach_name].reason = "FORCED GREEN (override)"

    # ── Internal helpers ──

    def _advance(self, overflow: float) -> None:
        """Cycle the active approach GREEN -> YELLOW -> (next approach) GREEN."""
        if self.active_phase.color == "GREEN":
            self.active_phase = SignalPhase("YELLOW", YELLOW_SEC, elapsed_sec=overflow)
        else:
            # YELLOW just finished: hand the right-of-way to the next
            # approach in the ring; this approach becomes (implicitly) RED.
            self.active_index = (self.active_index + 1) % len(self.cycle_order)
            next_name = self.cycle_order[self.active_index]
            next_green = self.states[next_name].computed_green_sec
            self.active_phase = SignalPhase("GREEN", next_green, elapsed_sec=overflow)

    def _time_until_green(self, idx: int) -> float:
        """Seconds until the approach at cycle_order[idx] gets GREEN,
        given the current active phase and every intervening approach's
        latest adaptive-green estimate."""
        if idx == self.active_index:
            return 0.0

        t = self.active_phase.remaining_sec
        if self.active_phase.color == "GREEN":
            t += YELLOW_SEC  # active approach still has its yellow to run

        n = len(self.cycle_order)
        i = (self.active_index + 1) % n
        while i != idx:
            name = self.cycle_order[i]
            t += self.states[name].computed_green_sec + YELLOW_SEC
            i = (i + 1) % n
        return t


def draw_intersection_signal_hud(frame, signal_status: dict, cycle_order: List[str],
                                  x: int = 0, y: int = 235) -> None:
    """
    OpenCV HUD panel for a 4-way (or 3-way) intersection: one row per
    approach in ring order (west-first), each row drawn as a real-world
    style 3-lamp traffic-light housing (red/yellow/green stacked) with
    only the currently active lamp lit, plus the countdown and the
    approach's adaptive-green reason.
    """
    rows = [name for name in cycle_order if name in signal_status]
    n = len(rows)
    if n == 0:
        return
    panel_w, row_h = 330, 46
    panel_h = n * row_h + 28
    font = cv2.FONT_HERSHEY_SIMPLEX

    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + panel_w, y + panel_h), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.50, frame, 0.50, 0, frame)

    cv2.putText(frame, "INTERSECTION SIGNAL STATUS", (x + 8, y + 17),
                font, 0.42, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.line(frame, (x + 8, y + 22), (x + panel_w - 8, y + 22), (80, 80, 80), 1)

    LAMP_COLORS = {"RED": (0, 0, 220), "YELLOW": (0, 200, 200), "GREEN": (0, 200, 0)}
    DIM = (55, 55, 55)

    for i, name in enumerate(rows):
        info = signal_status[name]
        row_y = y + 28 + i * row_h
        active_color = info["color"]

        # Compact 3-lamp housing standing in for a real traffic-light head.
        hx, hy = x + 14, row_y + 2
        cv2.rectangle(frame, (hx - 7, hy - 4), (hx + 7, hy + 33), (25, 25, 25), -1)
        for j, lamp in enumerate(("RED", "YELLOW", "GREEN")):
            cy_ = hy + 4 + j * 11
            lit = (lamp == active_color)
            cv2.circle(frame, (hx, cy_), 4, LAMP_COLORS[lamp] if lit else DIM, -1, cv2.LINE_AA)

        n_lanes = info.get("num_lanes", 0)
        label = (f"{name.upper()} ({n_lanes} lane{'s' if n_lanes != 1 else ''})  "
                 f"{active_color}  {info['remaining']:.0f}s")
        cv2.putText(frame, label, (x + 30, row_y + 14),
                    font, 0.44, LAMP_COLORS.get(active_color, (200, 200, 200)), 1, cv2.LINE_AA)

        bar_x1, bar_y = x + 30, row_y + 22
        bar_w, bar_h = panel_w - 45, 5
        cv2.rectangle(frame, (bar_x1, bar_y), (bar_x1 + bar_w, bar_y + bar_h), (50, 50, 50), -1)
        filled = int(bar_w * (1.0 - info["progress"])) if active_color != "RED" else 0
        if filled > 0:
            cv2.rectangle(frame, (bar_x1, bar_y), (bar_x1 + filled, bar_y + bar_h),
                          LAMP_COLORS.get(active_color, (150, 150, 150)), -1)

        if info["reason"] and info["reason"] != "nominal" and active_color != "RED":
            cv2.putText(frame, info["reason"][:40], (x + 30, row_y + 40),
                        font, 0.30, (130, 130, 130), 1, cv2.LINE_AA)


#  OpenCV overlay helper (optional)

SIGNAL_COLOR_BGR = {
    "GREEN":  (0,   200,  0),
    "YELLOW": (0,   200, 200),
    "RED":    (0,   0,   220),
}

def draw_signal_hud(frame, signal_status: dict, x: int = 0, y: int = 235) -> None:
    

    n = len(signal_status)
    panel_w, row_h = 310, 42
    panel_h = n * row_h + 28
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Background
    overlay = frame.copy()
    cv2.rectangle(overlay, (x, y), (x + panel_w, y + panel_h), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.50, frame, 0.50, 0, frame)

    # Header
    cv2.putText(frame, "ADAPTIVE SIGNAL STATUS", (x + 8, y + 17),
                font, 0.42, (180, 180, 180), 1, cv2.LINE_AA)
    cv2.line(frame, (x + 8, y + 22), (x + panel_w - 8, y + 22), (80, 80, 80), 1)

    for i, (lane_id, info) in enumerate(sorted(signal_status.items())):
        row_y = y + 28 + i * row_h
        color_bgr = SIGNAL_COLOR_BGR.get(info["color"], (150, 150, 150))

        # Colored circle indicator
        cv2.circle(frame, (x + 16, row_y + 14), 8, color_bgr, -1, cv2.LINE_AA)

        # Lane label + countdown
        main_text = f"Lane {lane_id+1}: {info['color']}  {info['remaining']:.0f}s"
        cv2.putText(frame, main_text, (x + 30, row_y + 18),
                    font, 0.46, color_bgr, 1, cv2.LINE_AA)

        # Progress bar
        bar_x1, bar_y  = x + 30, row_y + 25
        bar_w, bar_h   = panel_w - 45, 5
        cv2.rectangle(frame, (bar_x1, bar_y), (bar_x1 + bar_w, bar_y + bar_h),
                      (50, 50, 50), -1)
        filled = int(bar_w * (1.0 - info["progress"]))   # shrinks as phase progresses
        if filled > 0:
            cv2.rectangle(frame, (bar_x1, bar_y), (bar_x1 + filled, bar_y + bar_h),
                          color_bgr, -1)

        # Reason (small grey text)
        if info["reason"] and info["reason"] != "nominal":
            reason_short = info["reason"][:42]   # truncate for HUD width
            cv2.putText(frame, reason_short, (x + 30, row_y + 38),
                        font, 0.30, (130, 130, 130), 1, cv2.LINE_AA)