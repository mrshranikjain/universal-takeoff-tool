"""
P&ID Component Classifiers — valve types, instruments, spec breaks, tie-ins.

Works with text annotations extracted from P&ID drawings by PyMuPDF.
Uses tag pattern matching + proximity analysis for classification.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


# ==================== VALVE CLASSIFIER ====================

# Valve tag patterns (standard ISA/ANSI P&ID notation)
VALVE_PATTERNS = {
    # Actuated valves (check BEFORE manual valves for correct priority)
    "safety_relief_valve": {
        "patterns": [r"[A-Z]*[- ]?PSV[- ]?\d+", r"[A-Z]*[- ]?PRV[- ]?\d+", r"[A-Z]*[- ]?RV[- ]?\d+"],
        "label": "Pressure Safety/Relief Valve",
        "actuation": "automatic",
        "symbol_hints": ["spring-loaded", "relief"],
    },
    "control_valve": {
        "patterns": [r"[A-Z]*[- ]?FCV[- ]?\d+", r"[A-Z]*[- ]?TCV[- ]?\d+", r"[A-Z]*[- ]?LCV[- ]?\d+", r"[A-Z]*[- ]?PCV[- ]?\d+", r"[A-Z]*[- ]?CV[- ]?\d+"],
        "label": "Control Valve",
        "actuation": "actuated",
        "symbol_hints": ["control", "globe with actuator"],
        "requires_actuator": True,
    },
    "solenoid_valve": {
        "patterns": [r"[A-Z]*[- ]?SOV[- ]?\d+"],
        "label": "Solenoid Valve",
        "actuation": "solenoid",
        "symbol_hints": ["solenoid"],
    },
    # Manual valves
    "gate_valve": {
        "patterns": [r"[A-Z]*[- ]?GV[- ]?\d+", r"[A-Z]*[- ]?GT[- ]?\d+"],
        "label": "Gate Valve",
        "actuation": "manual",
        "symbol_hints": ["gate", "wedge"],
    },
    "globe_valve": {
        "patterns": [r"[A-Z]*[- ]?GLV[- ]?\d+", r"[A-Z]*[- ]?GB[- ]?\d+"],
        "label": "Globe Valve",
        "actuation": "manual",
        "symbol_hints": ["globe"],
    },
    "check_valve": {
        "patterns": [r"[A-Z]*[- ]?CV[- ]?\d+", r"[A-Z]*[- ]?CK[- ]?\d+", r"[A-Z]*[- ]?CH[- ]?\d+"],
        "label": "Check Valve",
        "actuation": "automatic",
        "symbol_hints": ["check", "non-return", "flapper"],
    },
    "ball_valve": {
        "patterns": [r"[A-Z]*[- ]?BV[- ]?\d+", r"[A-Z]*[- ]?BL[- ]?\d+"],
        "label": "Ball Valve",
        "actuation": "manual",
        "symbol_hints": ["ball"],
    },
    "butterfly_valve": {
        "patterns": [r"[A-Z]*[- ]?BF[- ]?\d+", r"[A-Z]*[- ]?BFV[- ]?\d+"],
        "label": "Butterfly Valve",
        "actuation": "manual",
        "symbol_hints": ["butterfly"],
    },
    "plug_valve": {
        "patterns": [r"[A-Z]*[- ]?PV[- ]?\d+", r"[A-Z]*[- ]?PL[- ]?\d+"],
        "label": "Plug Valve",
        "actuation": "manual",
        "symbol_hints": ["plug"],
    },
    "needle_valve": {
        "patterns": [r"[A-Z]*[- ]?NV[- ]?\d+", r"[A-Z]*[- ]?ND[- ]?\d+"],
        "label": "Needle Valve",
        "actuation": "manual",
        "symbol_hints": ["needle"],
    },
    "diaphragm_valve": {
        "patterns": [r"[A-Z]*[- ]?DV[- ]?\d+", r"[A-Z]*[- ]?DP[- ]?\d+"],
        "label": "Diaphragm Valve",
        "actuation": "manual",
        "symbol_hints": ["diaphragm"],
    },

    # Special
    "double_block_bleed": {
        "patterns": [r"[A-Z]*[- ]?DBB[- ]?\d+", r"[A-Z]*[- ]?DBBV[- ]?\d+"],
        "label": "Double Block and Bleed",
        "actuation": "manual",
        "symbol_hints": ["DBB"],
    },
    "blanking_blind": {
        "patterns": [r"[A-Z]*[- ]?BV[- ]?BLIND", r"[A-Z]*[- ]?SP[- ]?\d+"],
        "label": "Spectacle Blind / Blank",
        "actuation": "manual",
        "symbol_hints": ["spectacle", "figure-8"],
    },
}


@dataclass
class ValveItem:
    tag: str
    valve_type: str
    label: str
    actuation: str
    x: float = 0
    y: float = 0
    line_number: Optional[str] = None  # Associated line if found nearby

    def to_dict(self):
        return self.__dict__


class ValveClassifier:
    """Classify valve tags from P&ID text annotations."""

    def __init__(self):
        self.compiled_patterns = {}
        for vtype, vinfo in VALVE_PATTERNS.items():
            self.compiled_patterns[vtype] = {
                "label": vinfo["label"],
                "actuation": vinfo["actuation"],
                "regexes": [re.compile(p, re.IGNORECASE) for p in vinfo["patterns"]],
            }

    def classify(self, texts):
        """Find and classify all valves from text annotations."""
        valves = []
        seen = set()

        for t in texts:
            text = t["text"].strip()
            if len(text) < 2 or len(text) > 20:
                continue

            for vtype, vinfo in self.compiled_patterns.items():
                for rx in vinfo["regexes"]:
                    if rx.match(text) or rx.search(text):
                        key = f"{text}_{vtype}"
                        if key not in seen:
                            seen.add(key)
                            valves.append(ValveItem(
                                tag=text,
                                valve_type=vtype,
                                label=vinfo["label"],
                                actuation=vinfo["actuation"],
                                x=t.get("x", 0),
                                y=t.get("y", 0),
                            ))
                        break

        return valves

    def classify_with_lines(self, texts, line_numbers):
        """Classify valves and associate with nearby line numbers."""
        valves = self.classify(texts)

        for valve in valves:
            # Find nearest line number
            min_dist = float('inf')
            nearest_line = None
            for ln in line_numbers:
                if ln.get("x") is None or valve.x is None:
                    continue
                dist = ((ln["x"] - valve.x) ** 2 + (ln["y"] - valve.y) ** 2) ** 0.5
                if dist < min_dist and dist < 80:  # within 80 PDF points
                    min_dist = dist
                    nearest_line = ln.get("raw") or f'{ln.get("size", "")}-{ln.get("material", "")}-{ln.get("service", "")}-{ln.get("line_number", "")}'

            valve.line_number = nearest_line

        return valves


# ==================== SPEC BREAK DETECTOR ====================

@dataclass
class SpecBreak:
    """A spec break point on a P&ID where pipe class/rating changes."""
    x: float
    y: float
    from_class: Optional[str] = None
    to_class: Optional[str] = None
    from_rating: Optional[str] = None
    to_rating: Optional[str] = None
    from_material: Optional[str] = None
    to_material: Optional[str] = None
    description: str = ""

    def to_dict(self):
        return self.__dict__


class SpecBreakDetector:
    """Detect spec breaks by finding where line numbers change along pipe runs."""

    def detect(self, line_numbers, valve_items=None):
        """
        Detect spec breaks by comparing adjacent line numbers.

        A spec break occurs when:
        - Two line numbers are close together on the drawing (within 150 pts)
        - They share the same service but have different material or rating
        """
        breaks = []

        if len(line_numbers) < 2:
            return breaks

        # Sort by position (top to bottom, left to right)
        sorted_lines = sorted(line_numbers, key=lambda l: (l.get("y", 0), l.get("x", 0)))

        for i in range(len(sorted_lines) - 1):
            ln1 = sorted_lines[i]
            ln2 = sorted_lines[i + 1]

            x1, y1 = ln1.get("x", 0), ln1.get("y", 0)
            x2, y2 = ln2.get("x", 0), ln2.get("y", 0)

            dist = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5

            if dist > 150:  # Too far apart to be on the same pipe run
                continue

            # Check if same service but different material or rating
            service1 = ln1.get("service", "")
            service2 = ln2.get("service", "")

            if service1 and service2 and service1 == service2:
                mat1 = ln1.get("material", "")
                mat2 = ln2.get("material", "")
                rating1 = ln1.get("rating", "")
                rating2 = ln2.get("rating", "")

                if mat1 != mat2 or rating1 != rating2:
                    desc_parts = []
                    if mat1 != mat2:
                        desc_parts.append(f"Material: {mat1} → {mat2}")
                    if rating1 != rating2:
                        desc_parts.append(f"Rating: {rating1} → {rating2}")

                    breaks.append(SpecBreak(
                        x=(x1 + x2) / 2,
                        y=(y1 + y2) / 2,
                        from_class=rating1,
                        to_class=rating2,
                        from_rating=rating1,
                        to_rating=rating2,
                        from_material=mat1,
                        to_material=mat2,
                        description="; ".join(desc_parts),
                    ))

        return breaks


# ==================== TIE-IN / BATTERY LIMIT DETECTOR ====================

@dataclass
class TieIn:
    """A tie-in or battery limit connection point."""
    x: float
    y: float
    tag: str
    tie_in_type: str  # "tie_in" or "battery_limit"
    direction: Optional[str] = None  # "in" or "out"
    line_number: Optional[str] = None
    description: str = ""

    def to_dict(self):
        return self.__dict__


class TieInDetector:
    """Detect tie-ins and battery limits from P&ID text annotations."""

    TIE_IN_PATTERNS = [
        re.compile(r"TI[- ]?E?IN[- ]?\d*", re.IGNORECASE),
        re.compile(r"TIE[- ]?IN", re.IGNORECASE),
        re.compile(r"TI[- ]?\d+", re.IGNORECASE),
    ]

    BATTERY_LIMIT_PATTERNS = [
        re.compile(r"BL[- ]?\d+", re.IGNORECASE),
        re.compile(r"BATT[- ]?LIM", re.IGNORECASE),
        re.compile(r"BATTERY[- ]?LIM", re.IGNORECASE),
        re.compile(r"BL[- ]?IN[- ]?\d+", re.IGNORECASE),
        re.compile(r"BL[- ]?OUT[- ]?\d+", re.IGNORECASE),
    ]

    def detect(self, texts, line_numbers=None):
        """Find tie-in and battery limit markers."""
        tie_ins = []
        seen = set()

        for t in texts:
            text = t["text"].strip()

            # Check tie-in patterns
            for rx in self.TIE_IN_PATTERNS:
                if rx.search(text) and text not in seen:
                    seen.add(text)
                    direction = "in" if "IN" in text.upper() else "out"
                    # Find nearby line number
                    nearby_line = None
                    if line_numbers:
                        for ln in line_numbers:
                            if ln.get("x") and t.get("x"):
                                dist = ((ln["x"] - t["x"]) ** 2 + (ln["y"] - t["y"]) ** 2) ** 0.5
                                if dist < 60:
                                    nearby_line = ln.get("raw", "")
                                    break

                    tie_ins.append(TieIn(
                        x=t.get("x", 0),
                        y=t.get("y", 0),
                        tag=text,
                        tie_in_type="tie_in",
                        direction=direction,
                        line_number=nearby_line,
                        description=f"Tie-in ({direction})" + (f" on {nearby_line}" if nearby_line else ""),
                    ))
                    break

            # Check battery limit patterns
            for rx in self.BATTERY_LIMIT_PATTERNS:
                if rx.search(text) and text not in seen:
                    seen.add(text)
                    direction = "in" if "IN" in text.upper() else ("out" if "OUT" in text.upper() else None)
                    nearby_line = None
                    if line_numbers:
                        for ln in line_numbers:
                            if ln.get("x") and t.get("x"):
                                dist = ((ln["x"] - t["x"]) ** 2 + (ln["y"] - t["y"]) ** 2) ** 0.5
                                if dist < 60:
                                    nearby_line = ln.get("raw", "")
                                    break

                    tie_ins.append(TieIn(
                        x=t.get("x", 0),
                        y=t.get("y", 0),
                        tag=text,
                        tie_in_type="battery_limit",
                        direction=direction,
                        line_number=nearby_line,
                        description=f"Battery Limit ({direction or 'unspecified'})" + (f" on {nearby_line}" if nearby_line else ""),
                    ))
                    break

        return tie_ins


# ==================== INSTRUMENT LOOP DETECTOR ====================

@dataclass
class InstrumentLoop:
    """A control loop grouping instruments that work together."""
    loop_number: str
    instruments: list = field(default_factory=list)
    loop_type: str = ""  # "TIC" (temp), "FIC" (flow), "LIC" (level), "PIC" (pressure)
    has_control_valve: bool = False
    description: str = ""

    def to_dict(self):
        return {
            "loop_number": self.loop_number,
            "loop_type": self.loop_type,
            "instruments": [i if isinstance(i, dict) else i.__dict__ for i in self.instruments],
            "has_control_valve": self.has_control_valve,
            "description": self.description,
        }


# Instrument tag patterns (ISA-5.1 standard)
# First letter = measured variable, second letter = function
INSTRUMENT_CODES = {
    "T": "Temperature",
    "P": "Pressure",
    "F": "Flow",
    "L": "Level",
    "A": "Analyzer",
    "S": "Speed",
    "V": "Vibration",
    "W": "Weight/Force",
    "D": "Density",
    "H": "Hand (manual)",
}

INSTRUMENT_FUNCTIONS = {
    "I": "Indicator",
    "T": "Transmitter",
    "C": "Controller",
    "R": "Recorder",
    "G": "Gauge",
    "S": "Switch",
    "V": "Valve",
    "A": "Alarm",
    "E": "Element (sensor)",
    "X": "Undefined function",
}


class InstrumentLoopDetector:
    """Group instruments into control loops by shared loop number."""

    INSTRUMENT_PATTERN = re.compile(
        r'^([A-Z])([A-Z])[- ]?(\d{1,5})$', re.IGNORECASE
    )

    def detect(self, texts, valve_items=None):
        """Find instruments and group them into loops."""
        instruments = []
        seen = set()

        for t in texts:
            text = t["text"].strip()
            m = self.INSTRUMENT_PATTERN.match(text)
            if m and text not in seen:
                seen.add(text)
                var_code = m.group(1).upper()
                func_code = m.group(2).upper()
                loop_num = m.group(3)

                var_desc = INSTRUMENT_CODES.get(var_code, "Unknown")
                func_desc = INSTRUMENT_FUNCTIONS.get(func_code, "Unknown")

                instruments.append({
                    "tag": text,
                    "variable": var_code,
                    "variable_desc": var_desc,
                    "function": func_code,
                    "function_desc": func_desc,
                    "loop_number": loop_num,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })

        # Group by loop number
        loops_map = defaultdict(list)
        for inst in instruments:
            loops_map[inst["loop_number"]].append(inst)

        # Build loop objects
        loops = []
        for loop_num, insts in sorted(loops_map.items()):
            # Determine loop type from first variable code
            loop_type = ""
            if insts:
                first_var = insts[0]["variable"]
                loop_type = f"{first_var}IC"

            # Check if there's a control valve for this loop
            has_cv = False
            if valve_items:
                for v in valve_items:
                    if v.valve_type == "control_valve" and v.tag and loop_num in v.tag:
                        has_cv = True
                        break

            # Build description
            tags = [i["tag"] for i in insts]
            desc = f"Loop {loop_num}: {' + '.join(tags)}"
            if has_cv:
                desc += " (with control valve)"

            loops.append(InstrumentLoop(
                loop_number=loop_num,
                loop_type=loop_type,
                instruments=insts,
                has_control_valve=has_cv,
                description=desc,
            ))

        return loops, instruments


# ==================== ASME FITTING DIMENSIONS ====================

# ASME B16.5 flange dimensions (mm) — pressure class to flange OD
ASME_B16_5_FLANGE = {
    150: {15: 90, 20: 100, 25: 110, 40: 125, 50: 150, 80: 190, 100: 230, 150: 280, 200: 345, 250: 405, 300: 485, 350: 535, 400: 600},
    300: {15: 95, 20: 105, 25: 115, 40: 130, 50: 155, 80: 210, 100: 255, 150: 320, 200: 380, 250: 445, 300: 520, 350: 585, 400: 650},
    600: {15: 105, 20: 115, 25: 125, 40: 155, 50: 165, 80: 240, 100: 275, 150: 360, 200: 420, 250: 525, 300: 585, 350: 650, 400: 710},
    900: {15: 120, 20: 130, 25: 150, 40: 180, 50: 195, 80: 265, 100: 320, 150: 445, 200: 520, 250: 640, 300: 705},
    1500: {15: 120, 20: 130, 25: 150, 40: 180, 50: 215, 80: 300, 100: 360, 150: 485, 200: 600, 250: 730},
}

# ASME B31.3 pipe wall thickness formulas (simplified)
# t = (P * D) / (2 * (S * E + P * Y))
# where: P=pressure, D=outside dia, S=allowable stress, E=quality factor, Y=coefficient
ASME_B31_3_PARAMS = {
    "A53": {"S": 137.9, "E": 0.60, "Y": 0.40},   # Carbon steel, API 5L
    "A106B": {"S": 137.9, "E": 1.00, "Y": 0.40},  # Carbon steel, seamless
    "A106C": {"S": 161.3, "E": 1.00, "Y": 0.40},
    "SS316": {"S": 137.9, "E": 1.00, "Y": 0.40},  # SS 316 seamless
    "A335P11": {"S": 172.4, "E": 1.00, "Y": 0.40},  # Chrome-Moly P11
    "A335P22": {"S": 172.4, "E": 1.00, "Y": 0.40},  # Chrome-Moly P22
}

# Pipe outside diameters (mm) — ASME B36.10M
PIPE_OD_MM = {
    15: 21.3, 20: 26.7, 25: 33.4, 32: 42.2, 40: 48.3,
    50: 60.3, 65: 73.0, 80: 88.9, 100: 114.3, 150: 168.3,
    200: 219.1, 250: 273.0, 300: 323.8, 350: 355.6, 400: 406.4,
    450: 457.0, 500: 508.0, 600: 609.6,
}


class ASMEEngine:
    """ASME B31.3 and B16.5 native dimension calculations."""

    def get_flange_od(self, rating_class, nps_mm):
        """Get flange outside diameter (mm) per ASME B16.5."""
        ratings = ASME_B16_5_FLANGE.get(rating_class, {})
        return ratings.get(nps_mm)

    def get_pipe_od(self, nps_mm):
        """Get pipe outside diameter (mm) per ASME B36.10M."""
        return PIPE_OD_MM.get(nps_mm)

    def calc_min_wall_thickness(self, material, nps_mm, pressure_mpa):
        """
        Calculate minimum wall thickness per ASME B31.3.
        t = (P * D) / (2 * (S * E + P * Y))
        """
        params = ASME_B31_3_PARAMS.get(material)
        if not params:
            return None

        od = self.get_pipe_od(nps_mm)
        if not od:
            return None

        S = params["S"]
        E = params["E"]
        Y = params["Y"]

        t = (pressure_mpa * od) / (2 * (S * E + pressure_mpa * Y))
        return round(t, 2)

    def get_fitting_weight(self, fitting_type, nps_mm, rating_class=150):
        """Estimate fitting weight (kg) — simplified lookup."""
        # Approximate weights for common fittings
        od = self.get_pipe_od(nps_mm) or 0
        if fitting_type == "elbow_90":
            return round(od ** 2 * 0.0015 * (rating_class / 150), 2)
        elif fitting_type == "elbow_45":
            return round(od ** 2 * 0.0008 * (rating_class / 150), 2)
        elif fitting_type == "tee":
            return round(od ** 2 * 0.002 * (rating_class / 150), 2)
        elif fitting_type == "reducer":
            return round(od ** 2 * 0.0012 * (rating_class / 150), 2)
        elif fitting_type == "flange":
            flange_od = self.get_flange_od(rating_class, nps_mm) or od * 1.5
            return round(((flange_od ** 2 - od ** 2) * 0.00002 * (rating_class / 150)), 2)
        return None

    def get_line_info(self, line_number):
        """Given a decoded LineNumber, return engineering data."""
        info = {}

        if line_number.size_mm:
            info["pipe_od_mm"] = self.get_pipe_od(line_number.size_mm)

        if line_number.rating_class and line_number.size_mm:
            info["flange_od_mm"] = self.get_flange_od(
                line_number.rating_class, line_number.size_mm
            )

        if line_number.material:
            info["allowable_stress_mpa"] = ASME_B31_3_PARAMS.get(
                line_number.material, {}
            ).get("S")

        return info