"""
Isometric Drawing Analyzer — extracts 3D coordinates and quantities from isometric drawings.

Isometric drawings use a 30° projection with dimension annotations along pipe runs.
This module parses text annotations for dimensions, coordinates, weld symbols, and fitting markers.
"""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IsoSegment:
    """A pipe segment on an isometric drawing."""
    start_coord: tuple  # (x, y, z) in mm
    end_coord: tuple
    length_mm: float
    direction: str  # "N-S", "E-W", "UP", "DOWN"
    pipe_size: Optional[str] = None
    line_number: Optional[str] = None

    def to_dict(self):
        return {
            "start": self.start_coord,
            "end": self.end_coord,
            "length_mm": round(self.length_mm, 1),
            "direction": self.direction,
            "pipe_size": self.pipe_size,
            "line_number": self.line_number,
        }


@dataclass
class IsoWeld:
    """A weld point on an isometric drawing."""
    x: float
    y: float
    weld_type: str = "butt weld"  # butt, socket, fillet
    weld_id: Optional[str] = None
    line_number: Optional[str] = None

    def to_dict(self):
        return self.__dict__


@dataclass
class IsoFitting:
    """A fitting on an isometric drawing."""
    x: float
    y: float
    fitting_type: str  # elbow_90, elbow_45, tee, reducer, cap, flange
    tag: Optional[str] = None
    line_number: Optional[str] = None

    def to_dict(self):
        return self.__dict__


class IsometricAnalyzer:
    """Analyze isometric drawings for pipe runs, welds, and fittings."""

    # Dimension patterns found on isometrics
    DIM_PATTERNS = [
        # "500 mm" or "500mm"
        re.compile(r'(\d{1,5})\s*(?:mm|MM|m\b)', re.IGNORECASE),
        # "1.5 m" or "2.0M"
        re.compile(r'(\d{1,3}\.\d)\s*(?:m\b|M\b)', re.IGNORECASE),
        # Coordinate: "EL +3500" or "EL+3500" (elevation)
        re.compile(r'EL\s*\+?\s*(\d{1,5})', re.IGNORECASE),
        # Coordinate: "N 2500" or "S 1200" (north/south)
        re.compile(r'[NS]\s*(\d{1,5})', re.IGNORECASE),
        # Coordinate: "E 3000" or "W 1800" (east/west)
        re.compile(r'[EW]\s*(\d{1,5})', re.IGNORECASE),
    ]

    # Weld symbol patterns
    WELD_PATTERNS = [
        re.compile(r'W[- ]?\d+', re.IGNORECASE),          # W1, W2, W-001
        re.compile(r'BW[- ]?\d+', re.IGNORECASE),         # Butt weld
        re.compile(r'SW[- ]?\d+', re.IGNORECASE),         # Socket weld
        re.compile(r'FW[- ]?\d+', re.IGNORECASE),         # Fillet weld
        re.compile(r'FIELD[- ]?WELD', re.IGNORECASE),     # Field weld
        re.compile(r'SHOP[- ]?WELD', re.IGNORECASE),      # Shop weld
    ]

    # Fitting tag patterns
    FITTING_PATTERNS = {
        "elbow_90": [re.compile(r'EL[- ]?90[- ]?\d*', re.IGNORECASE), re.compile(r'90[- ]?EL', re.IGNORECASE)],
        "elbow_45": [re.compile(r'EL[- ]?45[- ]?\d*', re.IGNORECASE), re.compile(r'45[- ]?EL', re.IGNORECASE)],
        "elbow_30": [re.compile(r'EL[- ]?30[- ]?\d*', re.IGNORECASE)],
        "tee": [re.compile(r'TEE[- ]?\d*', re.IGNORECASE), re.compile(r'T[- ]?\d{3,}', re.IGNORECASE)],
        "reducer": [re.compile(r'RED[- ]?\d*', re.IGNORECASE), re.compile(r'CONC[- ]?RED', re.IGNORECASE), re.compile(r'ECC[- ]?RED', re.IGNORECASE)],
        "cap": [re.compile(r'CAP[- ]?\d*', re.IGNORECASE)],
        "flange": [re.compile(r'FLG[- ]?\d*', re.IGNORECASE), re.compile(r'FLANGE', re.IGNORECASE)],
        "orifice": [re.compile(r'ORF[- ]?\d*', re.IGNORECASE), re.compile(r'ORIFICE', re.IGNORECASE)],
    }

    def analyze(self, texts, line_numbers=None):
        """
        Full analysis of an isometric drawing.

        Returns:
            {
                "segments": [IsoSegment],
                "welds": [IsoWeld],
                "fitting": [IsoFitting],
                "coordinates": [{x, y, z, tag}],
                "total_pipe_length_mm": float,
                "weld_count": int,
                "fitting_count": int,
            }
        """
        dimensions = self._extract_dimensions(texts)
        welds = self._extract_welds(texts, line_numbers)
        fitting = self._extract_fittings(texts, line_numbers)
        coords = self._extract_coordinates(texts)
        segments = self._build_segments(dimensions, coords, line_numbers)

        total_length = sum(s.length_mm for s in segments)

        return {
            "segments": [s.to_dict() for s in segments],
            "welds": [w.to_dict() for w in welds],
            "fittings": [f.to_dict() for f in fitting],
            "coordinates": coords,
            "total_pipe_length_mm": round(total_length, 1),
            "weld_count": len(welds),
            "fitting_count": len(fitting),
            "fitting_breakdown": dict(defaultdict(int, {
                f["fitting_type"]: sum(1 for ff in fitting if ff.fitting_type == f["fitting_type"])
                for f in [ft.to_dict() for ft in fitting]
            })),
        }

    def _extract_dimensions(self, texts):
        """Extract dimension annotations from text."""
        dims = []
        seen = set()

        for t in texts:
            text = t["text"].strip()
            for pattern in self.DIM_PATTERNS[:2]:  # First two patterns for mm/m
                m = pattern.search(text)
                if m:
                    val = float(m.group(1))
                    # Convert meters to mm if needed
                    if 'm' in text.lower() and 'mm' not in text.lower():
                        val *= 1000
                    key = f"{val}_{t.get('x', 0)}_{t.get('y', 0)}"
                    if key not in seen and 10 < val < 100000:  # Reasonable range
                        seen.add(key)
                        dims.append({
                            "value_mm": val,
                            "text": text,
                            "x": t.get("x", 0),
                            "y": t.get("y", 0),
                        })
                    break

        return dims

    def _extract_welds(self, texts, line_numbers=None):
        """Extract weld symbols from text."""
        welds = []
        seen = set()

        for t in texts:
            text = t["text"].strip()

            for pattern in self.WELD_PATTERNS:
                if pattern.search(text) and text not in seen:
                    seen.add(text)

                    # Determine weld type
                    weld_type = "butt weld"
                    text_upper = text.upper()
                    if "SW" in text_upper and "FIELD" not in text_upper:
                        weld_type = "socket weld"
                    elif "FW" in text_upper:
                        weld_type = "fillet weld"
                    elif "BW" in text_upper:
                        weld_type = "butt weld"
                    elif "FIELD" in text_upper:
                        weld_type = "field weld"
                    elif "SHOP" in text_upper:
                        weld_type = "shop weld"

                    # Find nearby line number
                    nearby_line = None
                    if line_numbers:
                        for ln in line_numbers:
                            if ln.get("x") and t.get("x"):
                                dist = ((ln["x"] - t["x"]) ** 2 + (ln["y"] - t["y"]) ** 2) ** 0.5
                                if dist < 60:
                                    nearby_line = ln.get("raw", "")
                                    break

                    welds.append(IsoWeld(
                        x=t.get("x", 0),
                        y=t.get("y", 0),
                        weld_type=weld_type,
                        weld_id=text,
                        line_number=nearby_line,
                    ))
                    break

        return welds

    def _extract_fittings(self, texts, line_numbers=None):
        """Extract fitting tags from text."""
        fitting = []
        seen = set()

        for t in texts:
            text = t["text"].strip()

            for ftype, patterns in self.FITTING_PATTERNS.items():
                for pattern in patterns:
                    if pattern.search(text) and text not in seen:
                        seen.add(text)

                        nearby_line = None
                        if line_numbers:
                            for ln in line_numbers:
                                if ln.get("x") and t.get("x"):
                                    dist = ((ln["x"] - t["x"]) ** 2 + (ln["y"] - t["y"]) ** 2) ** 0.5
                                    if dist < 60:
                                        nearby_line = ln.get("raw", "")
                                        break

                        fitting.append(IsoFitting(
                            x=t.get("x", 0),
                            y=t.get("y", 0),
                            fitting_type=ftype,
                            tag=text,
                            line_number=nearby_line,
                        ))
                        break

        return fitting

    def _extract_coordinates(self, texts):
        """Extract coordinate annotations (elevation, north/south, east/west)."""
        coords = []

        for t in texts:
            text = t["text"].strip()

            # Elevation
            m = re.search(r'EL\s*\+?\s*(\d{1,5})', text, re.IGNORECASE)
            if m:
                coords.append({
                    "type": "elevation",
                    "value_mm": int(m.group(1)),
                    "text": text,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })
                continue

            # North/South
            m = re.match(r'^N\s*(\d{1,5})$', text, re.IGNORECASE)
            if m:
                coords.append({
                    "type": "north",
                    "value_mm": int(m.group(1)),
                    "text": text,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })
                continue

            m = re.match(r'^S\s*(\d{1,5})$', text, re.IGNORECASE)
            if m:
                coords.append({
                    "type": "south",
                    "value_mm": int(m.group(1)),
                    "text": text,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })
                continue

            # East/West
            m = re.match(r'^E\s*(\d{1,5})$', text, re.IGNORECASE)
            if m:
                coords.append({
                    "type": "east",
                    "value_mm": int(m.group(1)),
                    "text": text,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })
                continue

            m = re.match(r'^W\s*(\d{1,5})$', text, re.IGNORECASE)
            if m:
                coords.append({
                    "type": "west",
                    "value_mm": int(m.group(1)),
                    "text": text,
                    "x": t.get("x", 0),
                    "y": t.get("y", 0),
                })
                continue

        return coords

    def _build_segments(self, dimensions, coords, line_numbers=None):
        """Build pipe segments from dimensions and coordinates."""
        segments = []

        if not dimensions:
            return segments

        # Simple approach: each dimension is a pipe segment
        current_pos = (0, 0, 0)

        for dim in dimensions:
            length = dim["value_mm"]

            # Try to determine direction from nearby coordinate annotations
            direction = "N-S"  # default
            # Check for nearby coordinate type
            for coord in coords:
                if abs(coord["x"] - dim["x"]) < 30 and abs(coord["y"] - dim["y"]) < 30:
                    if coord["type"] == "elevation":
                        direction = "UP"
                    elif coord["type"] in ("north", "south"):
                        direction = "N-S"
                    elif coord["type"] in ("east", "west"):
                        direction = "E-W"
                    break

            # Update position
            if direction == "N-S":
                end_pos = (current_pos[0], current_pos[1] + length, current_pos[2])
            elif direction == "E-W":
                end_pos = (current_pos[0] + length, current_pos[1], current_pos[2])
            elif direction == "UP":
                end_pos = (current_pos[0], current_pos[1], current_pos[2] + length)
            else:
                end_pos = (current_pos[0] + length, current_pos[1], current_pos[2])

            pipe_size = None
            line_num = None
            if line_numbers:
                for ln in line_numbers:
                    if ln.get("x") and dim.get("x"):
                        dist = ((ln["x"] - dim["x"]) ** 2 + (ln["y"] - dim["y"]) ** 2) ** 0.5
                        if dist < 80:
                            pipe_size = ln.get("size")
                            line_num = ln.get("raw")
                            break

            segments.append(IsoSegment(
                start_coord=current_pos,
                end_coord=end_pos,
                length_mm=length,
                direction=direction,
                pipe_size=pipe_size,
                line_number=line_num,
            ))

            current_pos = end_pos

        return segments