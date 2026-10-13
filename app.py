import streamlit as st
import json
import time
import math
import random
import base64
import os
import subprocess
from PIL import Image, ImageFile

# Ensure TraCI dependencies are correctly mapped from the local system paths
if "SUMO_HOME" not in os.environ:
    os.environ["SUMO_HOME"] = "/usr/share/sumo" if os.path.exists("/usr/share/sumo") else "/usr/local/share/sumo"
import traci

ImageFile.LOAD_TRUNCATED_IMAGES = True

    
# ==============================================================================
# PAGE CONFIG + THEME
# ==============================================================================
st.set_page_config(
    page_title="Cognitive Traffic Digital Twin",
    page_icon="🚦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

BG          = "#0B0E14"
PANEL       = "#131721"
PANEL_ALT   = "#171C28"
BORDER      = "#232838"
TEXT        = "#E6E9F0"
TEXT_DIM    = "#8590A6"
ACCENT      = "#F5A623"
GOOD        = "#3DDC84"
WARN        = "#F5A623"
BAD         = "#FF5C5C"
MONO_FONT   = "'JetBrains Mono', 'SF Mono', 'Consolas', monospace"
SANS_FONT   = "'Inter', -apple-system, 'Segoe UI', sans-serif"

CUSTOM_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"] {{ font-family: {SANS_FONT}; }}
.stApp {{ background: {BG}; color: {TEXT}; }}
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1440px; }}

/* ---- Masthead ---- */
.twin-header {{ display: flex; align-items: center; justify-content: space-between; padding: 0 0 1.1rem 0; border-bottom: 1px solid {BORDER}; margin-bottom: 1.4rem; }}
.twin-title {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; color: {TEXT}; margin: 0; display: flex; align-items: center; gap: 0.55rem; }}
.twin-subtitle {{ font-size: 0.82rem; color: {TEXT_DIM}; font-family: {MONO_FONT}; margin-top: 0.2rem; letter-spacing: 0.01em; }}
.status-pill {{ display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.85rem; border-radius: 999px; border: 1px solid {BORDER}; background: {PANEL}; font-family: {MONO_FONT}; font-size: 0.78rem; color: {TEXT_DIM}; }}
.status-dot {{ width: 8px; height: 8px; border-radius: 50%; background: {GOOD}; box-shadow: 0 0 8px {GOOD}; }}
.status-dot.offline {{ background: {BAD}; box-shadow: 0 0 8px {BAD}; }}

/* ---- Panel shell ---- */
.panel-heading {{ font-size: 0.78rem; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase; color: {TEXT_DIM}; margin-bottom: 0.6rem; display: flex; align-items: center; gap: 0.4rem; }}

/* ---- Metric cards ---- */
div[data-testid="stMetric"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; padding: 0.75rem 0.9rem 0.65rem 0.9rem; }}
div[data-testid="stMetric"] label {{ font-family: {MONO_FONT}; font-size: 0.68rem !important; letter-spacing: 0.06em; text-transform: uppercase; color: {TEXT_DIM} !important; }}
div[data-testid="stMetricValue"] {{ font-family: {MONO_FONT}; font-size: 1.5rem !important; color: {TEXT} !important; font-weight: 600; }}

/* ---- Fixed-height media frames ---- */
.media-frame {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; height: 540px; display: flex; align-items: center; justify-content: center; overflow: hidden; }}
.media-empty {{ color: {TEXT_DIM}; font-family: {MONO_FONT}; font-size: 0.85rem; text-align: center; }}
hr {{ border-color: {BORDER}; }}

/* ---- Digital twin: scrollable viewport ----
   The twin's SVG canvas can legitimately be wider/taller than this panel
   once lane width is increased so vehicle icons fit inside their lanes.
   Rather than clipping (overflow:hidden) or squeezing everything to fit,
   the frame becomes its own scroll container in both axes, with the SVG
   sized to its true rendered dimensions inside it.

   This used to use flexbox centering (display:flex; align-items:center;
   justify-content:center) on .twin-scroll. That has TWO separate problems
   when the child can be larger than the container, both of which combined
   to produce "can only see a little of the intersection, and scrolling
   can't reach the rest":

   1. A flex item's default min-width/min-height is `auto`, which stops
      the flex container from ever shrinking below its content's (the
      SVG's) intrinsic size — so .twin-scroll never actually became a
      540px box in the first place, and never got a chance to scroll.

   2. Even once that's fixed (min-width/height:0), align-items/justify-
      content:center on a flex container CENTERS an overflowing child —
      which in every major browser means the overflow is distributed
      symmetrically on both sides, and scrollLeft/scrollTop can't go
      negative to reach the half of the overflow that got centered
      "before" the visible origin. That silently makes roughly half of
      any oversized content permanently unreachable by scrolling, no
      matter how large min-width:0 or overflow:auto are set.

   The robust standard fix for "centered when it fits, fully scrollable
   when it doesn't" is to stop using flexbox centering here altogether:
   .twin-scroll is plain block layout (so 100% of its scroll range is
   always reachable), and the SVG child centers itself only when there's
   spare room via margin:auto -- which has no effect once the child is
   larger than the container (there's no spare room to distribute), so
   large content just starts flush at (0,0) and scrolls normally over its
   full range in both directions. */
.twin-scroll {{
    width: 100%; height: 100%;
    min-width: 0; min-height: 0;
    overflow: auto;
    border-radius: 10px;
}}
.twin-scroll > svg {{
    display: block;
    margin: auto;
}}
.twin-scroll::-webkit-scrollbar {{ width: 10px; height: 10px; }}
.twin-scroll::-webkit-scrollbar-track {{ background: {PANEL}; }}
.twin-scroll::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 6px; }}
.twin-scroll::-webkit-scrollbar-thumb:hover {{ background: {TEXT_DIM}; }}

/* ---- Digital twin fullscreen wrapper ---- */
.twin-frame-wrap {{ position: relative; height: 100%; }}
.twin-fullscreen-btn {{
    position: absolute; top: 10px; right: 10px; z-index: 20;
    width: 34px; height: 34px; border-radius: 8px;
    background: rgba(19, 23, 33, 0.78); border: 1px solid {BORDER};
    color: {TEXT}; display: flex; align-items: center; justify-content: center;
    cursor: pointer; backdrop-filter: blur(4px); transition: background 0.15s ease, transform 0.1s ease;
}}
.twin-fullscreen-btn:hover {{ background: rgba(35, 40, 56, 0.92); }}
.twin-fullscreen-btn:active {{ transform: scale(0.94); }}
.twin-fullscreen-btn svg {{ width: 16px; height: 16px; stroke: {TEXT}; }}

/* When the wrapper is the browser fullscreen element, let it fill the
   screen AND keep scrolling available — this is the actual fix for
   "enlarge doesn't show the full ROI": previously .media-frame kept a
   fixed max-width/height and overflow:hidden even in fullscreen, clipping
   any ROI too big to fit. Now the fullscreen frame grows to (nearly) the
   whole viewport and still scrolls if the ROI is bigger still. */
.twin-frame-wrap:fullscreen {{
    background: {BG}; display: flex; align-items: center; justify-content: center;
    padding: 24px; box-sizing: border-box; width: 100vw; height: 100vh;
}}
.twin-frame-wrap:fullscreen .media-frame {{ height: 94vh; width: 96vw; max-width: none; }}
.twin-frame-wrap:-webkit-full-screen {{ background: {BG}; display: flex; align-items: center; justify-content: center; padding: 24px; box-sizing: border-box; width: 100vw; height: 100vh; }}
.twin-frame-wrap:-webkit-full-screen .media-frame {{ height: 94vh; width: 96vw; max-width: none; }}

/* ---- Twin legend ---- */
.twin-legend {{ display: flex; gap: 1.1rem; flex-wrap: wrap; margin-top: 0.55rem; font-family: {MONO_FONT}; font-size: 0.7rem; color: {TEXT_DIM}; }}
.twin-legend span.dot {{ display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 5px; vertical-align: middle; }}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ==============================================================================
# VEHICLE ICON MAPPING (non-car/truck classes keep emoji rendering)
# ==============================================================================
VEHICLE_ICONS = {
    "car":            "🚘",
    "truck":          "🚛",
    "bus":            "🚌",
    "motorcycle":     "🏍️",
    "bicycle":        "🚲",
    "person":         "🚶",
    "van":            "🚐",
    "ambulance":      "🚑",
    "fire truck":     "🚒",
    "fire_truck":     "🚒",
    "police vehicle": "🚓",
    "police_vehicle": "🚓",
}
DEFAULT_ICON = "🚘"
EMERGENCY_TYPES = {"ambulance", "fire truck", "fire_truck", "police vehicle", "police_vehicle"}
IMAGE_CLASSES = {"car", "truck", "fire truck", "fire_truck", "bus"}  
def resolve_icon(vehicle_class: str) -> str:
    return VEHICLE_ICONS.get(str(vehicle_class).strip().lower(), DEFAULT_ICON)

def is_emergency(vehicle_class: str) -> bool:
    return str(vehicle_class).strip().lower() in EMERGENCY_TYPES

def uses_image(vehicle_class: str) -> bool:
    return str(vehicle_class).strip().lower() in IMAGE_CLASSES

# ==============================================================================
# IMAGE ASSETS (base64-embedded)
# ==============================================================================
_ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Press 'C' in the browser to clear this cache if you hot-swap image files
@st.cache_resource
def load_vehicle_images_b64():
    def get_b64(filename):
        path = os.path.join(_ASSET_DIR, filename)
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except FileNotFoundError:
            return ""

    # Check for PNGs first (preferred for transparency), fallback to JPGs
    car_filenames = ["car_icon.png", "car_icon_1.png", "car_icon_2.png", "car_icon_3.png", "car_icon_4.png"]
    cars_list = [get_b64(name) for name in car_filenames if get_b64(name) != ""]
    
    # Load all Truck assets
    truck_filenames = ["truck_icon.png", "truck_icon_1.png", "truck_icon_2.png"]
    trucks_list = [get_b64(name) for name in truck_filenames if get_b64(name) != ""]
    
    # Load Firetruck and new Bus assets
    firetruck_b64 = get_b64("firetruck_icon.png") or get_b64("firetruck_icon.jpg")
    bus_b64 = get_b64("bus_icon.png") or get_b64("bus_icon.jpg")
    
    return cars_list, trucks_list, firetruck_b64, bus_b64

CARS_POOL, TRUCKS_POOL, FIRETRUCK_IMG_B64, BUS_IMG_B64 = load_vehicle_images_b64()

# ==============================================================================
# SESSION STATE
# ==============================================================================
defaults = {
    "cached_fig": None,
    "cached_image": None,
    "sumo_started": False,
    "sumo_error": None,
    "last_good_state": None,
    "vehicle_prev_pos": {},   
    "vehicle_heading": {},    
}
for k, v in defaults.items():
    st.session_state.setdefault(k, v)

# ==============================================================================
# SUMO ASSET + ENGINE BOOTSTRAP
# ==============================================================================
def _read_roi_from_live_state():
    """Pull roi_width/roi_height from the monitor's live state file so the
    placeholder SUMO network matches the actual calibrated ROI instead of a
    fixed assumption. Returns None if the file isn't available yet (e.g. the
    monitor process hasn't started) — the SUMO net is only a bootstrap
    scaffold for TraCI and isn't what renders the visible twin, so a modest
    generic size is used solely to get the engine running until real data
    arrives.
    """
    try:
        with open("/dev/shm/live_state.json", "r") as f:
            state = json.load(f)
        roi_w = state.get("roi_width")
        roi_h = state.get("roi_height")
        if roi_w and roi_h:
            return float(roi_w), float(roi_h)
    except Exception:
        pass
    return None


def verify_sumo_assets():
    if not os.path.exists("twin.net.xml"):
        roi = _read_roi_from_live_state()
        roi_w, roi_h = roi if roi else (42.0, 210.0)
        center_x = roi_w / 2.0
        with open("twin.nod.xml", "w") as f:
            f.write(f'<nodes><node id="bottom" x="{center_x:.2f}" y="0"/>'
                     f'<node id="top" x="{center_x:.2f}" y="{roi_h:.2f}"/></nodes>')
        with open("twin.edg.xml", "w") as f:
            f.write('<edges><edge id="main_road" from="bottom" to="top" numLanes="6" speed="22.22"/></edges>')

        subprocess.run(
            ["netconvert", "--node-files=twin.nod.xml", "--edge-files=twin.edg.xml", "--output-file=twin.net.xml"],
            stdout=subprocess.DEVNULL,
        )

        with open("twin.sumocfg", "w") as f:
            f.write('<configuration><input><net-file value="twin.net.xml"/></input>'
                    '<processing><lateral-resolution value="0.8"/></processing></configuration>')

if not st.session_state.sumo_started:
    verify_sumo_assets()
    try:
        try:
            traci.close()
        except Exception:
            pass
        sumo_cmd = ["sumo", "-c", "twin.sumocfg", "--num-clients", "1"]
        traci.start(sumo_cmd)
        st.session_state.sumo_started = True
        st.session_state.sumo_error = None
    except Exception as e:
        st.session_state.sumo_error = str(e)

# ==============================================================================
# HEADER
# ==============================================================================
dot_class = "" if st.session_state.sumo_started else "offline"
status_label = "SUMO ENGINE ONLINE" if st.session_state.sumo_started else "FALLBACK PLOT MODE"

st.markdown(f"""
<div class="twin-header">
    <div>
        <p class="twin-title">🚦 Cognitive Traffic Digital Twin</p>
        <p class="twin-subtitle">MICROSCOPIC PHYSICS SIMULATION · TraCI BIDIRECTIONAL SYNC LAYER</p>
    </div>
    <div class="status-pill">
        <span class="status-dot {dot_class}"></span>
        {status_label}
    </div>
</div>
""", unsafe_allow_html=True)

if st.session_state.sumo_error and not st.session_state.sumo_started:
    st.warning(f"SUMO connection offline — running visualizer in fallback plot mode. ({st.session_state.sumo_error})")

# ==============================================================================
# LAYOUT SKELETON
# ==============================================================================
# 1. Metrics placeholder AT THE TOP
metrics_placeholder = st.empty()

st.markdown("<br>", unsafe_allow_html=True)

# 2. Main columns BELOW metrics
col_real, col_twin = st.columns(2, gap="medium")

with col_real:
    st.markdown('<div class="panel-heading">📷 Real-World Feed</div>', unsafe_allow_html=True)
    video_placeholder = st.empty()

with col_twin:
    st.markdown('<div class="panel-heading">🌐 Digital Twin — Simulated View</div>', unsafe_allow_html=True)
    map_placeholder = st.empty()
    # NOTE: the fullscreen wrapper + button are emitted inside build_twin_html()
    # on every fragment refresh so the control stays present and functional
    # across live updates, rather than being drawn once outside the fragment.
    st.markdown(f"""
    <div class="twin-legend">
        <div><span class="dot" style="background:{BAD}; box-shadow:0 0 6px {BAD};"></span>Overspeeding</div>
        <div><span class="dot" style="background:#C061FF; box-shadow:0 0 6px #C061FF;"></span>Lane Crossing</div>
        <div><span class="dot" style="background:{BAD};"></span>Emergency Vehicle</div>
        <div><span class="dot" style="background:{GOOD};"></span>Nominal</div>
    </div>
    """, unsafe_allow_html=True)


# ==============================================================================
# HEADING ESTIMATION
# ==============================================================================
def update_and_get_heading(v_id: str, x: float, y: float, speed: float) -> float:
    prev = st.session_state.vehicle_prev_pos.get(v_id)
    st.session_state.vehicle_prev_pos[v_id] = (x, y)

    if prev is None:
        return st.session_state.vehicle_heading.get(v_id, 0.0)

    dx = x - prev[0]
    dy = y - prev[1]
    dist = math.hypot(dx, dy)

    if dist < 0.15:
        return st.session_state.vehicle_heading.get(v_id, 0.0)

    heading = math.degrees(math.atan2(dx, -dy))
    st.session_state.vehicle_heading[v_id] = heading
    return heading


# ==============================================================================
# SVG DIGITAL TWIN RENDERER
# ==============================================================================
def build_road_defs():
    return """
    <defs>
        <linearGradient id="asphalt" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%"  stop-color="#181c26"/>
            <stop offset="8%"  stop-color="#20242f"/>
            <stop offset="50%" stop-color="#262b38"/>
            <stop offset="92%" stop-color="#20242f"/>
            <stop offset="100%" stop-color="#181c26"/>
        </linearGradient>
        <linearGradient id="asphaltSheen" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stop-color="#ffffff" stop-opacity="0.05"/>
            <stop offset="12%"  stop-color="#ffffff" stop-opacity="0"/>
            <stop offset="88%"  stop-color="#000000" stop-opacity="0"/>
            <stop offset="100%" stop-color="#000000" stop-opacity="0.18"/>
        </linearGradient>
        <linearGradient id="shoulder" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stop-color="#2b3040"/>
            <stop offset="100%" stop-color="#12151d"/>
        </linearGradient>
        <filter id="softGlow" x="-60%" y="-60%" width="220%" height="220%">
            <feGaussianBlur stdDeviation="3.2" result="blur"/>
            <feMerge>
                <feMergeNode in="blur"/>
                <feMergeNode in="SourceGraphic"/>
            </feMerge>
        </filter>
        <radialGradient id="overspeedGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stop-color="#FF5C5C" stop-opacity="0.85"/>
            <stop offset="55%" stop-color="#FF5C5C" stop-opacity="0.50"/>
            <stop offset="100%" stop-color="#FF5C5C" stop-opacity="0"/>
        </radialGradient>
        <radialGradient id="emergencyGlow" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stop-color="#FF3B3B" stop-opacity="0.95"/>
            <stop offset="60%" stop-color="#FF3B3B" stop-opacity="0.50"/>
            <stop offset="100%" stop-color="#FF3B3B" stop-opacity="0"/>
        </radialGradient>
        <pattern id="noiseTexture" width="6" height="6" patternUnits="userSpaceOnUse">
            <rect width="6" height="6" fill="transparent"/>
            <circle cx="1" cy="1" r="0.35" fill="#ffffff" opacity="0.03"/>
            <circle cx="4" cy="3" r="0.3" fill="#000000" opacity="0.05"/>
            <circle cx="2.5" cy="5" r="0.3" fill="#ffffff" opacity="0.025"/>
        </pattern>
        <!-- Fine asphalt aggregate grain, layered on top of noiseTexture at a
             different scale so the two patterns don't visibly repeat in sync -->
        <pattern id="asphaltGrain" width="3.2" height="3.2" patternUnits="userSpaceOnUse" patternTransform="rotate(12)">
            <rect width="3.2" height="3.2" fill="transparent"/>
            <circle cx="0.6" cy="0.5" r="0.22" fill="#000000" opacity="0.08"/>
            <circle cx="2.1" cy="1.4" r="0.18" fill="#ffffff" opacity="0.02"/>
            <circle cx="1.4" cy="2.6" r="0.20" fill="#000000" opacity="0.06"/>
            <circle cx="2.8" cy="2.9" r="0.15" fill="#ffffff" opacity="0.015"/>
        </pattern>
        <!-- Faint tire-wear streaks: two darker bands per lane where tires
             typically track, giving the asphalt a used, driven-on look -->
        <linearGradient id="tireWear" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%"   stop-color="#000000" stop-opacity="0"/>
            <stop offset="22%"  stop-color="#000000" stop-opacity="0.16"/>
            <stop offset="32%"  stop-color="#000000" stop-opacity="0"/>
            <stop offset="68%"  stop-color="#000000" stop-opacity="0"/>
            <stop offset="78%"  stop-color="#000000" stop-opacity="0.16"/>
            <stop offset="100%" stop-color="#000000" stop-opacity="0"/>
        </linearGradient>
        <linearGradient id="edgeLineFade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stop-color="#f4f6fa" stop-opacity="0.55"/>
            <stop offset="50%"  stop-color="#f4f6fa" stop-opacity="0.85"/>
            <stop offset="100%" stop-color="#f4f6fa" stop-opacity="0.55"/>
        </linearGradient>
    </defs>
    """

def render_digital_twin_svg(vehicles, roi_w, roi_h, lanes, view_w=600, view_h=760, pad=26, zoom=2.2,
                             median_gap=None, median_x=None, roi_type=None, junction_box=None,
                             approaches=None, signal_phases=None, lane_meta=None):
    # --------------------------------------------------------------------
    # UNIFORM (ISOTROPIC) SCALING — true top-down, undistorted ROI mapping
    # --------------------------------------------------------------------
    # The perspective-transformed ROI (roi_w x roi_h, in real-world units,
    # e.g. metres) must be dropped into the label using a SINGLE scale
    # factor for both axes. Using independent x/y scale factors (the old
    # behaviour) stretches whichever axis has the smaller real-world extent
    # relative to the other, which is exactly why lane polygons and vehicle
    # markers drifted apart from each other in the rendered frame.
    #
    # Rule (as specified): the ROI's real-world height is matched to the
    # available vertical pixel height of the label. The ROI's pixel width
    # is then whatever that same scale factor produces for roi_w — i.e.
    # width shrinks/grows *proportionally* to height, never independently.
    #
    # `zoom` is an extra multiplier on top of the base fit-to-height scale,
    # used to make lanes/vehicles visibly bigger (per request) rather than
    # shrinking everything down to whatever bare minimum fits the panel.
    # A zoom > 1 will commonly make the rendered road wider/taller than the
    # panel — that's expected and handled by the scrollable twin frame.
    avail_h = view_h - 2 * pad   # vertical pixel budget of the twin label
    avail_w = view_w - 2 * pad   # horizontal pixel budget of the twin label

    if roi_h:
        scale = (avail_h / roi_h) * zoom
    else:
        scale = 1.0 * zoom

    inner_h = roi_h * scale if roi_h else avail_h        # scaled ROI height (incl. zoom)
    inner_w = roi_w * scale if roi_w else avail_w         # proportional width, NOT stretched to avail_w

    # We do NOT clamp inner_w/inner_h down to the panel's available size —
    # that would fight directly against "enlarge the lanes/vehicles". If the
    # zoomed road is bigger than the panel, the SVG canvas grows to match
    # and the surrounding HTML container (.twin-scroll) scrolls to reveal
    # the rest, instead of shrinking everything back down to fit.

    # Center the road on BOTH axes when it's smaller than the visible
    # panel (the common case, and what was previously left-aligned/off-
    # center per the reported bug). When the zoomed road is larger than the
    # panel on an axis, fall back to starting at `pad` on that axis so the
    # scrollable content starts flush at the edge instead of being
    # (impossibly) centered around a negative offset.
    off_x = pad + max(0.0, (avail_w - inner_w) / 2.0)
    off_y = pad + max(0.0, (avail_h - inner_h) / 2.0)

    # Effective canvas size actually needed to show the full ROI at this
    # scale, without clipping. The caller (build_twin_html) uses this to
    # size the scrollable inner content; view_w/view_h remain the *visible
    # viewport* size when not enlarged.
    canvas_w = max(view_w, inner_w + 2 * pad)
    canvas_h = max(view_h, inner_h + 2 * pad)

    def sx(x):
        return off_x + (x * scale) if roi_w else off_x

    def sy(y):
        return off_y + (y * scale) if roi_h else off_y

    # ------------------------------------------------------------------
    # LANE-WIDTH-AWARE ICON SIZING
    # ------------------------------------------------------------------
    # Vehicle icon/image sizes used to be fixed pixel constants (e.g. a car
    # was always 32x48px) regardless of how wide a rendered lane actually
    # was. When a lane was narrow, icons overflowed it and overlapped
    # neighbouring lanes; when a lane was wide, icons looked comically
    # small. Instead, derive the real rendered lane width directly from the
    # `lanes` polygons (already expressed in the same scaled pixel space
    # via sx/sy), and size every icon as a fraction of that — so an icon is
    # always narrower than the lane it sits in, for ANY ROI/lane count.
    lane_px_width = None
    if lanes:
        widths = []
        for lane in lanes:
            if not lane:
                continue
            pts = [(sx(p[0]), sy(p[1])) for p in lane]
            xs = [p[0] for p in pts]
            widths.append(max(xs) - min(xs))
        if widths:
            lane_px_width = sum(widths) / len(widths)  # average lane width in px

    if not lane_px_width or lane_px_width <= 0:
        # Fallback: assume the whole rendered road is one lane's worth of
        # width if we have no lane polygons to measure (e.g. intersection
        # mode or a still-initializing feed).
        lane_px_width = max(inner_w, 24)

    # Cap icon width to a safe fraction of the lane so there's always a
    # visible gap between a vehicle and the lane edge/neighbouring traffic.
    ICON_WIDTH_FRACTION = 0.62
    max_icon_w = max(10.0, lane_px_width * ICON_WIDTH_FRACTION)

    def sized(base_w, base_h, cap_w):
        """Scale an icon's (w,h) down to fit cap_w while preserving its
        aspect ratio; never scales up beyond the icon's own design size."""
        if base_w <= cap_w:
            return base_w, base_h
        f = cap_w / base_w
        return base_w * f, base_h * f

    svg_parts = [f'<svg viewBox="0 0 {canvas_w:.0f} {canvas_h:.0f}" xmlns="http://www.w3.org/2000/svg" '
                 f'style="width:{canvas_w:.0f}px;height:{canvas_h:.0f}px;display:block;">']
    svg_parts.append(build_road_defs())

    is_intersection = (roi_type == "intersection")

    if is_intersection:
        # ------------------------------------------------------------
        # INTERSECTION BACKDROP — cross/plus (4-way) or T (3-way) shape
        # ------------------------------------------------------------
        # A junction isn't one solid rectangle of pavement: it's several
        # approach "arms" meeting at a shared box, with open (non-road)
        # corners between the arms. Drawing one big filled rect (the
        # straight/divided approach) would paint pavement into those empty
        # corners, which don't exist in the real intersection. Instead the
        # backdrop is built from each approach's own lane-polygon bounding
        # box plus the junction box, unioned together, so the twin's shape
        # actually matches whichever approaches (3 or 4) are configured.
        # `lanes` is a FLAT list with one polygon per LANE — a 2+2+1+1
        # four-way intersection has 6 entries here, not 4. Painting /
        # positioning per-approach elements (the arm backdrop, and later
        # the traffic lights) from this flat list directly, one rect per
        # entry, silently assumed "one entry per approach", which is why
        # arms and lights ended up misplaced/duplicated whenever an
        # approach had more than one lane. Instead, group lane polygons by
        # their approach first (via `lane_meta`, a parallel array telling
        # us which approach each `lanes[i]` belongs to), then take ONE
        # bounding box per approach — that's what an "arm" actually is.
        arm_rects = []          # (x, y, w, h) in scaled pixel space, one per approach
        arm_names = []          # parallel list: approach name for each arm_rects entry
        if lane_meta and len(lane_meta) == len(lanes):
            _by_approach = {}
            _order = []
            for lane, meta in zip(lanes, lane_meta):
                if not lane:
                    continue
                name = meta.get("approach") if meta else None
                if name not in _by_approach:
                    _by_approach[name] = []
                    _order.append(name)
                _by_approach[name].append(lane)
            for name in _order:
                pts = [(sx(p[0]), sy(p[1])) for lane in _by_approach[name] for p in lane]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                arm_rects.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
                arm_names.append(name)
        else:
            # Older state file without lane_meta — fall back to the
            # previous per-lane-polygon behaviour (approach name unknown
            # per arm; the traffic-light block below re-derives it from
            # geometry instead).
            for lane in lanes:
                if not lane:
                    continue
                pts = [(sx(p[0]), sy(p[1])) for p in lane]
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                arm_rects.append((min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
                arm_names.append(None)

        jbox_pts = None
        if junction_box:
            jbox_pts = [(sx(p[0]), sy(p[1])) for p in junction_box]

        def _paint_rect(x, y, w, h):
            svg_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#asphalt)"/>')
            svg_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#noiseTexture)"/>')
            svg_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#asphaltGrain)"/>')
            svg_parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="url(#asphaltSheen)"/>')

        for (rx, ry, rw, rh) in arm_rects:
            _paint_rect(rx, ry, rw, rh)

        if jbox_pts:
            jx = [p[0] for p in jbox_pts]
            jy = [p[1] for p in jbox_pts]
            _paint_rect(min(jx), min(jy), max(jx) - min(jx), max(jy) - min(jy))
            # Distinguish the junction box slightly from the approach arms —
            # a faint amber-tinted overlay reads as "shared crossing area"
            # (where turning/queued vehicles have no single lane) without
            # hiding the asphalt texture underneath.
            jpath = "M " + " L ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in jbox_pts) + " Z"
            svg_parts.append(f'<path d="{jpath}" fill="{ACCENT}" opacity="0.05"/>')
            svg_parts.append(f'<path d="{jpath}" fill="none" stroke="{ACCENT}" stroke-width="1.4" '
                              f'stroke-dasharray="5 4" opacity="0.5"/>')

    else:
        # Draw Road Backdrop — layered asphalt: base color, coarse noise, fine
        # grain, and a soft top-to-bottom sheen, in that order, so the surface
        # reads as textured pavement rather than a flat fill. The rect is sized
        # to the proportionally-scaled ROI (inner_w x inner_h), not the full
        # label, and offset (off_x/off_y) so it's centered in the frame.
        svg_parts.append(f'<rect x="{off_x:.1f}" y="{off_y:.1f}" width="{inner_w:.1f}" height="{inner_h:.1f}" rx="10" fill="url(#asphalt)"/>')
        svg_parts.append(f'<rect x="{off_x:.1f}" y="{off_y:.1f}" width="{inner_w:.1f}" height="{inner_h:.1f}" rx="10" fill="url(#noiseTexture)"/>')
        svg_parts.append(f'<rect x="{off_x:.1f}" y="{off_y:.1f}" width="{inner_w:.1f}" height="{inner_h:.1f}" rx="10" fill="url(#asphaltGrain)"/>')
        svg_parts.append(f'<rect x="{off_x:.1f}" y="{off_y:.1f}" width="{inner_w:.1f}" height="{inner_h:.1f}" rx="10" fill="url(#asphaltSheen)"/>')

        # Draw Shoulders — anchored to the centered/offset road rect (off_x/off_y),
        # not the raw label padding, so they hug the actual proportionally-scaled
        # ROI instead of the full label edge.
        strip_w = 5
        svg_parts.append(f'<rect x="{off_x:.1f}" y="{off_y:.1f}" width="{strip_w}" height="{inner_h:.1f}" fill="url(#shoulder)"/>')
        svg_parts.append(f'<rect x="{off_x + inner_w - strip_w:.1f}" y="{off_y:.1f}" width="{strip_w}" height="{inner_h:.1f}" fill="url(#shoulder)"/>')

        # Solid white edge lines along the outer shoulders, like real carriageway
        # markings, using a soft top/bottom fade so they don't look like a hard
        # SVG stroke pasted on top of the road.
        edge_x_left = off_x + strip_w + 1.5
        edge_x_right = off_x + inner_w - strip_w - 1.5
        svg_parts.append(f'<line x1="{edge_x_left:.1f}" y1="{off_y:.1f}" x2="{edge_x_left:.1f}" y2="{off_y + inner_h:.1f}" '
                          f'stroke="url(#edgeLineFade)" stroke-width="1.6"/>')
        svg_parts.append(f'<line x1="{edge_x_right:.1f}" y1="{off_y:.1f}" x2="{edge_x_right:.1f}" y2="{off_y + inner_h:.1f}" '
                          f'stroke="url(#edgeLineFade)" stroke-width="1.6"/>')

        # Median / barrier band — only drawn for ROI_MODE == "divided" (the
        # monitor sends median_x/median_gap in that case; both are None
        # otherwise). This is what visually separates the left and right
        # carriageways instead of letting their lanes run together as if it
        # were one continuous road, matching how the physical barrier splits
        # the two sides in the source footage.
        if median_gap is not None and median_x is not None and roi_w:
            band_x0 = sx(median_x)
            band_x1 = sx(median_x + median_gap)
            band_w = max(2.0, band_x1 - band_x0)
            svg_parts.append(
                f'<rect x="{band_x0:.1f}" y="{off_y:.1f}" width="{band_w:.1f}" height="{inner_h:.1f}" '
                f'fill="#3a4152"/>'
            )
            # A row of small reflective posts down the middle of the median,
            # reading as a crash barrier rather than a flat gap.
            if inner_h > 0:
                post_count = max(4, int(inner_h / 45))
                for i in range(post_count):
                    py_ = off_y + (i + 0.5) * (inner_h / post_count)
                    svg_parts.append(
                        f'<rect x="{band_x0 + band_w/2 - 1.2:.1f}" y="{py_ - 4:.1f}" width="2.4" height="8" '
                        f'rx="1" fill="#c7cbd6" opacity="0.85"/>'
                    )

    # Draw Lanes
    for lane in lanes:
        if not lane:
            continue
        pts = [(sx(p[0]), sy(p[1])) for p in lane]
        pts.append(pts[0])
        path_d = "M " + " L ".join(f"{px:.1f},{py:.1f}" for px, py in pts) + " Z"

        # Subtle tire-wear streaks inside each lane cell, oriented along the
        # lane's own bounding box so they follow the road's perspective.
        lane_xs = [p[0] for p in pts]
        lane_ys = [p[1] for p in pts]
        lx0, lx1 = min(lane_xs), max(lane_xs)
        ly0, ly1 = min(lane_ys), max(lane_ys)
        svg_parts.append(
            f'<clipPath id="clip_{id(lane)}_{ly0:.0f}"><path d="{path_d}"/></clipPath>'
        )
        svg_parts.append(
            f'<rect x="{lx0:.1f}" y="{ly0:.1f}" width="{max(lx1-lx0,1):.1f}" height="{max(ly1-ly0,1):.1f}" '
            f'fill="url(#tireWear)" opacity="0.55" clip-path="url(#clip_{id(lane)}_{ly0:.0f})"/>'
        )

        svg_parts.append(f'<path d="{path_d}" fill="#ffffff" opacity="0.015"/>')
        svg_parts.append(f'<path d="{path_d}" fill="none" stroke="#f4f6fa" stroke-width="2.2" '
                          f'stroke-dasharray="14 10" stroke-linejoin="round" opacity="0.75" filter="url(#softGlow)"/>')
        svg_parts.append(f'<path d="{path_d}" fill="none" stroke="#ffffff" stroke-width="0.8" '
                          f'stroke-dasharray="14 10" stroke-linejoin="round" opacity="0.9"/>')

    if is_intersection:
        # Stop-lines: a short bright bar across each approach's lane group
        # right where it meets the junction box, standing in for the real
        # painted stop-line drivers wait behind. Drawn from each approach
        # arm's own bounding box (computed above, now correctly ONE rect
        # per approach) rather than a single inner_w/inner_h center-line,
        # since that center-line assumption only holds for a single
        # straight carriageway.
        #
        # Each arm's stop-line edge (side + coordinate) is also recorded
        # into approach_edges, keyed by approach name, so the traffic-light
        # renderer below can place one signal head per approach at exactly
        # this same edge without recomputing the geometry a second time.
        approach_edges = {}
        for arm_i, (rx, ry, rw, rh) in enumerate(arm_rects):
            if jbox_pts:
                jcx = sum(p[0] for p in jbox_pts) / len(jbox_pts)
                jcy = sum(p[1] for p in jbox_pts) / len(jbox_pts)
            else:
                jcx, jcy = off_x + inner_w / 2, off_y + inner_h / 2
            arm_cx, arm_cy = rx + rw / 2, ry + rh / 2

            arm_name = arm_names[arm_i] if arm_i < len(arm_names) else None

            if rw >= rh:
                # Horizontal arm (east/west): stop-line is vertical, at
                # whichever x-edge faces the junction.
                stop_x = rx + rw if arm_cx < jcx else rx
                svg_parts.append(f'<line x1="{stop_x:.1f}" y1="{ry:.1f}" x2="{stop_x:.1f}" y2="{ry+rh:.1f}" '
                                  f'stroke="#f4f6fa" stroke-width="2.4" opacity="0.85"/>')
                side = "W" if arm_cx < jcx else "E"
                if arm_name is None:
                    arm_name = "west" if side == "W" else "east"
                approach_edges[arm_name] = {
                    "orientation": "vertical_line",
                    "stop_x": stop_x, "ry": ry, "rh": rh, "rx": rx, "rw": rw,
                    "faces": "E" if side == "W" else "W",
                }
            else:
                # Vertical arm (north/south): stop-line is horizontal, at
                # whichever y-edge faces the junction.
                stop_y = ry + rh if arm_cy < jcy else ry
                svg_parts.append(f'<line x1="{rx:.1f}" y1="{stop_y:.1f}" x2="{rx+rw:.1f}" y2="{stop_y:.1f}" '
                                  f'stroke="#f4f6fa" stroke-width="2.4" opacity="0.85"/>')
                side = "N" if arm_cy < jcy else "S"
                if arm_name is None:
                    arm_name = "north" if side == "N" else "south"
                approach_edges[arm_name] = {
                    "orientation": "horizontal_line",
                    "stop_y": stop_y, "rx": rx, "rw": rw, "ry": ry, "rh": rh,
                    "faces": "S" if side == "N" else "N",
                }

        # ------------------------------------------------------------
        # TRAFFIC LIGHTS — one signal head per approach, planted just
        # behind the stop-line on the right-hand shoulder of that arm
        # (matching real-world placement: a driver waiting at the line
        # sees the light ahead, slightly to their right).
        # ------------------------------------------------------------
        # `signal_phases` (from IntersectionSignalController.get_display_
        # status()) is keyed directly by approach NAME — "north" / "south"
        # / "east" / "west" — each pointing at {"color", "remaining", ...}
        # for that whole approach (every lane on an approach shares one
        # physical head). `approaches` entries also carry this same color/
        # remaining redundantly (signal_color/signal_remaining) as a
        # convenience; signal_phases is used here since it's always
        # present whenever the monitor is running in intersection mode.
        if signal_phases:
            LIGHT_COLORS = {"RED": "#FF4B4B", "YELLOW": "#F5C518", "GREEN": "#3DDC84"}

            def _approach_color(name):
                info = signal_phases.get(name)
                if not info:
                    # Approach not found in signal_phases (e.g. stale/
                    # mismatched state) — fall back to the per-approach
                    # fields on `approaches` rather than defaulting to RED,
                    # so a naming mismatch doesn't read as "stuck red".
                    for a in (approaches or []):
                        if a.get("name") == name:
                            return a.get("signal_color", "RED"), a.get("signal_remaining", 0.0)
                    return "RED", 0.0
                return info.get("color", "RED"), info.get("remaining", 0.0)

            head_w = max(14.0, min(26.0, lane_px_width * 0.42))
            head_h = head_w * 2.35
            lamp_r = head_w * 0.26
            pole_h = head_h * 0.65
            setback = head_w * 0.9

            for name, edge in approach_edges.items():
                color, remaining = _approach_color(name)

                if edge["orientation"] == "vertical_line":
                    stop_x = edge["stop_x"]
                    ry, rh = edge["ry"], edge["rh"]
                    dir_sign = 1 if edge["faces"] == "E" else -1
                    pole_x = stop_x - dir_sign * setback
                    right_sign = 1 if edge["faces"] == "E" else -1
                    pole_y = (ry + rh / 2) + right_sign * (rh / 2 + head_w * 0.9)
                    head_x = pole_x - head_w / 2
                    head_y = pole_y - head_h
                    lamp_cx = pole_x
                    lamp_top_y = head_y + head_h * 0.22
                    lamp_gap = head_h * 0.28
                else:
                    stop_y = edge["stop_y"]
                    rx, rw = edge["rx"], edge["rw"]
                    dir_sign = 1 if edge["faces"] == "S" else -1
                    pole_y = stop_y - dir_sign * setback
                    right_sign = -1 if edge["faces"] == "S" else 1
                    pole_x = (rx + rw / 2) + right_sign * (rw / 2 + head_w * 0.9)
                    head_x = pole_x - head_w / 2
                    head_y = pole_y - head_h
                    lamp_cx = pole_x
                    lamp_top_y = head_y + head_h * 0.22
                    lamp_gap = head_h * 0.28

                glow_color = LIGHT_COLORS.get(color, LIGHT_COLORS["RED"])

                svg_parts.append(
                    f'<line x1="{pole_x:.1f}" y1="{head_y+head_h:.1f}" x2="{pole_x:.1f}" y2="{head_y+head_h+pole_h:.1f}" '
                    f'stroke="#4a5064" stroke-width="{max(2.0, head_w*0.12):.1f}" stroke-linecap="round"/>'
                )
                svg_parts.append(
                    f'<rect x="{head_x:.1f}" y="{head_y:.1f}" width="{head_w:.1f}" height="{head_h:.1f}" '
                    f'rx="{head_w*0.22:.1f}" fill="#14161d" stroke="#31374a" stroke-width="1.2"/>'
                )

                lamp_order = [("RED", LIGHT_COLORS["RED"]), ("YELLOW", LIGHT_COLORS["YELLOW"]), ("GREEN", LIGHT_COLORS["GREEN"])]
                for li, (lamp_name, lamp_color) in enumerate(lamp_order):
                    lcy = lamp_top_y + li * lamp_gap
                    is_active = (lamp_name == color)
                    if is_active:
                        svg_parts.append(
                            f'<circle cx="{lamp_cx:.1f}" cy="{lcy:.1f}" r="{lamp_r*2.1:.1f}" fill="{lamp_color}" opacity="0.32">'
                            f'<animate attributeName="opacity" values="0.32;0.08;0.32" dur="1.4s" repeatCount="indefinite"/>'
                            f'</circle>'
                        )
                        svg_parts.append(
                            f'<circle cx="{lamp_cx:.1f}" cy="{lcy:.1f}" r="{lamp_r:.1f}" fill="{lamp_color}" filter="url(#softGlow)"/>'
                        )
                    else:
                        svg_parts.append(
                            f'<circle cx="{lamp_cx:.1f}" cy="{lcy:.1f}" r="{lamp_r:.1f}" fill="{lamp_color}" opacity="0.16"/>'
                        )

                label_y = head_y + head_h + head_w * 0.14
                svg_parts.append(
                    f'<text x="{pole_x:.1f}" y="{label_y:.1f}" font-size="{max(9.0, head_w*0.5):.1f}" '
                    f'text-anchor="middle" fill="{glow_color}" font-family="{MONO_FONT}" '
                    f'font-weight="600">{remaining:.0f}s</text>'
                )
    else:
        # Draw Road Studs (Reflectors) — spacing derived from the rendered
        # pixel height only, so it scales correctly regardless of the
        # source ROI's real-world width/height (no hardcoded ROI unit
        # assumptions). Only meaningful for a single straight carriageway.
        if inner_h > 0:
            stud_count = max(4, int(inner_h / 60))
            for i in range(stud_count):
                cy_ = off_y + (i + 0.5) * (inner_h / stud_count)
                svg_parts.append(f'<circle cx="{off_x + inner_w / 2:.1f}" cy="{cy_:.1f}" r="1.4" '
                                  f'fill="#ffd166" opacity="0.35"/>')

    # Render Vehicles
    for v in vehicles:
        v_id = str(v.get("id"))
        v_class = str(v.get("class", "car")).lower().strip()
        speed = float(v.get("speed", 0.0))
        emergency = is_emergency(v_class)
        overspeeding = bool(v.get("overspeeding", False))
        lane_crossing = bool(v.get("lane_crossing", False))

        raw_x = float(v.get("x", 0.0))
        raw_y = float(v.get("y", 0.0))
        px, py = sx(raw_x), sy(raw_y)

        heading = update_and_get_heading(v_id, raw_x, raw_y, speed)

        status = "EMERGENCY" if emergency else ("OVERSPEED" if overspeeding else ("LANE CROSS" if lane_crossing else "Normal"))
        title = f"ID {v_id} · {v_class.capitalize()} · {speed:.0f} km/h · {status}"

        halo_r = 38 

        # 1. EMERGENCY
        if emergency:
            svg_parts.append(
                f'<g transform="translate({px:.1f},{py:.1f})">'
                f'<circle r="34" fill="none" stroke="#FF3B3B" stroke-width="4.5" '
                f'stroke-dasharray="10 8" opacity="1.0">'
                f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="0.6s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values="1.0;0.5;1.0" dur="0.5s" repeatCount="indefinite"/>'
                f'</circle>'
                f'</g>'
            )
            
        # 2. OVERSPEED
        elif overspeeding:
            svg_parts.append(
                f'<g transform="translate({px:.1f},{py:.1f})">'
                f'<circle r="30" fill="none" stroke="#FF5C5C" stroke-width="3.5" '
                f'stroke-dasharray="8 6" opacity="1.0">'
                f'<animateTransform attributeName="transform" type="rotate" from="0" to="360" dur="1.2s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values="1.0;0.5;1.0" dur="1.0s" repeatCount="indefinite"/>'
                f'</circle>'
                f'</g>'
            )

        # 3. LANE CROSSING
        if lane_crossing:
            svg_parts.append(
                f'<g transform="translate({px:.1f},{py:.1f})">'
                f'<circle r="26" fill="none" stroke="#C061FF" stroke-width="3.5" '
                f'stroke-dasharray="6 5" opacity="1.0">'
                f'<animateTransform attributeName="transform" type="rotate" from="0" to="-360" dur="1.8s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values="1.0;0.6;1.0" dur="0.9s" repeatCount="indefinite"/>'
                f'</circle>'
                f'</g>'
            )

        # 4. DRAW VEHICLE (Handles Car pools, Truck pools, Firetrucks, and Buses)
        is_firetruck = v_class in ["fire truck", "fire_truck"]
        is_bus = (v_class == "bus")
        is_truck = (v_class == "truck")
        is_car = (v_class == "car")
        
        has_firetruck_img = is_firetruck and FIRETRUCK_IMG_B64
        has_bus_img = is_bus and BUS_IMG_B64
        has_truck_img = is_truck and len(TRUCKS_POOL) > 0
        has_car_img = is_car and len(CARS_POOL) > 0

        if has_firetruck_img or has_bus_img or has_truck_img or has_car_img:
            # Deterministic random picking based on Vehicle Tracker ID 
            # This prevents vehicles from flickering to different colors on every frame refresh
            random.seed(int(v_id)) 
            
            if has_firetruck_img:
                b64_src = FIRETRUCK_IMG_B64
                base_w, base_h = 36, 105  # Firetruck structural limits
            elif has_bus_img:
                b64_src = BUS_IMG_B64
                base_w, base_h = 38, 110  # Buses are typically long and broad
            elif has_truck_img:
                b64_src = random.choice(TRUCKS_POOL)
                base_w, base_h = 34, 85   
            else:
                b64_src = random.choice(CARS_POOL)
                base_w, base_h = 32, 48   

            img_w, img_h = sized(base_w, base_h, max_icon_w)

            svg_parts.append(
                f'<g transform="translate({px:.1f},{py:.1f}) rotate({heading:.1f})">'
                f'<title>{title}</title>'
                f'<image href="data:image/png;base64,{b64_src}" '
                f'x="{-img_w/2:.1f}" y="{-img_h/2:.1f}" width="{img_w:.1f}" height="{img_h:.1f}" '
                f'preserveAspectRatio="xMidYMid meet"/>'
                f'</g>'
            )
        else:
            # Fallback for buses, motorcycles, bicycles, or if images are missing
            icon = resolve_icon(v_class)
            base_font = 30 if not emergency else 34
            # Emoji glyphs render roughly square; cap the font-size so the
            # glyph's approximate width (~0.9 * font-size) stays under the
            # same lane-width budget as the image-based icons.
            font_size = min(base_font, max(10.0, max_icon_w / 0.9))
            svg_parts.append(
                f'<text x="{px:.1f}" y="{py + font_size*0.35:.1f}" font-size="{font_size:.1f}" '
                f'text-anchor="middle">{icon}<title>{title}</title></text>'
            )

    svg_parts.append('</svg>')
    return "".join(svg_parts)


def build_twin_html(svg_markup, panel_bg=PANEL_ALT, frame_id="twin-frame-wrap"):
    """Wraps the SVG twin in a container with a fullscreen toggle button.

    Uses the standard browser Fullscreen API (requestFullscreen /
    exitFullscreen) on the wrapper div itself, so the digital twin — including
    its live updates — can be expanded to fill the screen and shrunk back
    without navigating away or reloading the fragment.
    """
    return f"""
    <div class="twin-frame-wrap" id="{frame_id}">
        <div class="media-frame" style="background:{panel_bg}; width:100%; padding:0; border-radius:10px;">
            <div class="twin-scroll">
                {svg_markup}
            </div>
            <button class="twin-fullscreen-btn" id="{frame_id}-btn" title="Toggle fullscreen" aria-label="Toggle fullscreen">
                <svg id="{frame_id}-icon-expand" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="15 3 21 3 21 9"></polyline>
                    <polyline points="9 21 3 21 3 15"></polyline>
                    <line x1="21" y1="3" x2="14" y2="10"></line>
                    <line x1="3" y1="21" x2="10" y2="14"></line>
                </svg>
                <svg id="{frame_id}-icon-collapse" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none;">
                    <polyline points="4 14 10 14 10 20"></polyline>
                    <polyline points="20 10 14 10 14 4"></polyline>
                    <line x1="14" y1="10" x2="21" y2="3"></line>
                    <line x1="3" y1="21" x2="10" y2="14"></line>
                </svg>
            </button>
        </div>
    </div>
    <script>
    (function() {{
        var wrap = document.getElementById("{frame_id}");
        var btn = document.getElementById("{frame_id}-btn");
        var expandIcon = document.getElementById("{frame_id}-icon-expand");
        var collapseIcon = document.getElementById("{frame_id}-icon-collapse");
        if (!wrap || !btn) return;

        function isFs() {{
            return document.fullscreenElement === wrap || document.webkitFullscreenElement === wrap;
        }}

        function syncIcon() {{
            var fs = isFs();
            expandIcon.style.display = fs ? "none" : "block";
            collapseIcon.style.display = fs ? "block" : "none";
        }}

        btn.onclick = function(e) {{
            e.stopPropagation();
            if (isFs()) {{
                if (document.exitFullscreen) document.exitFullscreen();
                else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
            }} else {{
                if (wrap.requestFullscreen) wrap.requestFullscreen();
                else if (wrap.webkitRequestFullscreen) wrap.webkitRequestFullscreen();
            }}
        }};

        document.addEventListener("fullscreenchange", syncIcon);
        document.addEventListener("webkitfullscreenchange", syncIcon);
        syncIcon();
    }})();
    </script>
    """


# ==============================================================================
# LIVE-UPDATING FRAGMENT
# ==============================================================================
@st.fragment(run_every=1.0)
def live_twin_fragment():
    state = st.session_state.last_good_state

    try:
        with open("/dev/shm/live_state.json", "r") as f:
            state = json.load(f)
        st.session_state.last_good_state = state
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # --- Render Metrics ---
    with metrics_placeholder.container():
        st.markdown('<div class="panel-heading">📊 Live Metrics</div>', unsafe_allow_html=True)
        m1, m2, m3, m4 = st.columns(4)

        if state is None:
            m1.metric("Live Vehicles", "—")
            m2.metric("Congestion Index", "—")
            m3.metric("Risk Level", "—")
            m4.metric("Emergency Status", "—")
        else:
            m1.metric("Live Vehicles", state.get("vehicle_count", 0))
            m2.metric("Congestion Index", state.get("congestion", "Low"))
            m3.metric("Risk Level", f"{state.get('risk_level', 0.0)}")
            em_status = state.get("emergency_status", "None")
            m4.metric("Emergency Status", em_status, delta=None if em_status == "None" else "active", delta_color="inverse")

    # --- Halt rendering map/video if no state is available yet ---
    if state is None:
        video_placeholder.markdown(
            '<div class="media-frame"><div class="media-empty">Waiting for live feed…<br>no data at /dev/shm/live_state.json yet</div></div>',
            unsafe_allow_html=True,
        )
        map_placeholder.markdown(
            '<div class="media-frame"><div class="media-empty">Waiting for telemetry…</div></div>',
            unsafe_allow_html=True,
        )
        return

    # --- Digital twin SVG scene ---
    # ROI dimensions come exclusively from the live state file (produced by the
    # monitor's own perspective-transform target size). No hardcoded fallback
    # is used here, since a fixed value would misrepresent any video whose
    # ROI was calibrated to a different width/height.
    roi_w = state.get("roi_width")
    roi_h = state.get("roi_height")

    if not roi_w or not roi_h:
        # The monitor hasn't published valid ROI dimensions yet — render a
        # clear waiting state instead of guessing at a scale.
        map_placeholder.markdown(
            '<div class="media-frame"><div class="media-empty">'
            'Waiting for ROI calibration (roi_width / roi_height) from live feed…'
            '</div></div>',
            unsafe_allow_html=True,
        )
        return

    svg_markup = render_digital_twin_svg(
        state.get("vehicles", []),
        roi_w,
        roi_h,
        state.get("lanes", []),
        median_gap=state.get("median_gap"),
        median_x=state.get("median_x"),
        roi_type=state.get("roi_type"),
        junction_box=state.get("junction_box"),
        approaches=state.get("approaches"),
        signal_phases=state.get("signal_phases"),
        lane_meta=state.get("lane_meta"),
    )
    st.session_state.cached_fig = svg_markup

    # --- Safe byte-level Camera frame read to prevent Streamlit layout crashing ---
    if os.path.exists("current_frame.jpg"):
        try:
            with open("current_frame.jpg", "rb") as img_file:
                img_data = img_file.read()
                # Ensure the file isn't empty/corrupted from a mid-process OpenCV write
                if len(img_data) > 100: 
                    st.session_state.cached_image = img_data
        except Exception:
            pass

    # --- Render Camera Frame via raw HTML ---
    if st.session_state.cached_image:
        b64_img = base64.b64encode(st.session_state.cached_image).decode('utf-8')
        img_html = f'''
        <div class="media-frame" style="padding:0; background:#000;">
            <img src="data:image/jpeg;base64,{b64_img}" style="width:100%; height:100%; object-fit:contain; border-radius:10px;"/>
        </div>
        '''
        video_placeholder.markdown(img_html, unsafe_allow_html=True)
    else:
        video_placeholder.markdown(
            '<div class="media-frame"><div class="media-empty">No camera frame available yet</div></div>',
            unsafe_allow_html=True,
        )

    # --- Render the SVG directly into the DOM ---
    map_placeholder.markdown(build_twin_html(svg_markup), unsafe_allow_html=True)


live_twin_fragment()