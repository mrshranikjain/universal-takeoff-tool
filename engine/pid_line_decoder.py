"""
P&ID Line Number Decoder — parses line tags into engineering attributes.

Line number formats found in real P&IDs:
  8"-150-A53-B-003          → size=8", rating=150#, material=A53, service=B, line=003
  6"-300-A106-GAS-001       → size=6", rating=300#, material=A106, service=GAS, line=001
  10"-A106B-CS-201          → size=10", material=A106B, service=CS (cold service), line=201
  4"-SS316-PS-005           → size=4", material=SS316, service=PS (pump suction), line=005
  12"-A53-S-1001            → size=12", material=A53, service=S (steam), line=1001
  2"-A106-BFW-002           → size=2", material=A106, service=BFW (boiler feed water), line=002

Common service codes:
  BFW = Boiler Feed Water
  CW  = Cooling Water
  CHW = Chilled Water
  CS  = Cold Service
  GAS = Gas/Fuel Gas
  HS  = Hot Service
  OS  = Oil Service
  PS  = Pump Suction
  PD  = Pump Discharge
  S   = Steam
  SA  = Steam Auxiliary
  SC  = Steam Condensate
  WS  = Water Service
  FG  = Fuel Gas
  FO  = Fuel Oil
  LO  = Lube Oil
  Air/IA = Instrument Air
  UA  = Utility Air
  N2  = Nitrogen
  DW  = Drinking Water
  FW  = Fire Water
  RW  = Raw Water
  SW  = Sea Water
  TW  = Treated Water
  V   = Vent
  DR  = Drain
  FG  = Flare Gas

Common material codes:
  A53    = Carbon Steel (ASTM A53)
  A106   = Carbon Steel (ASTM A106, high temp)
  A106B  = Carbon Steel Grade B
  SS316  = Stainless Steel 316
  SS304  = Stainless Steel 304
  A335   = Alloy Steel (Chrome-Moly)
  A333   = Low Temp Carbon Steel
  PVC    = Polyvinyl Chloride
  HDPE   = High Density Polyethylene
  FRP    = Fiber Reinforced Plastic
  Cu     = Copper
  DBB    = Double Block and Bleed

Common insulation codes:
  H   = Hot Insulation
  C   = Cold Insulation
  P   = Personnel Protection
  AC  = Acoustic Insulation
  HT  = Heat Tracing (electrical)
  ST  = Steam Tracing
  N   = No Insulation
"""
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LineNumber:
    """Decoded P&ID line number."""
    raw: str
    size: Optional[str] = None        # e.g. "8\"", "6\"", "10\""
    size_mm: Optional[float] = None   # e.g. 200, 150, 250
    rating: Optional[str] = None      # e.g. "150#", "300#", "600#"
    rating_class: Optional[int] = None  # e.g. 150, 300, 600
    material: Optional[str] = None    # e.g. A53, A106, SS316
    service: Optional[str] = None     # e.g. BFW, CW, GAS, S
    service_desc: Optional[str] = None  # e.g. "Boiler Feed Water"
    insulation: Optional[str] = None  # e.g. H, C, P, HT
    insulation_desc: Optional[str] = None
    line_number: Optional[str] = None  # e.g. 003, 001, 1001
    area: Optional[str] = None        # e.g. area/unit code if present
    spec_break: bool = False          # True if this line has a spec break

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}


# Service code lookup
SERVICE_CODES = {
    "BFW": "Boiler Feed Water",
    "CW": "Cooling Water",
    "CHW": "Chilled Water",
    "CS": "Cold Service",
    "GAS": "Gas / Fuel Gas",
    "HS": "Hot Service",
    "OS": "Oil Service",
    "PS": "Pump Suction",
    "PD": "Pump Discharge",
    "S": "Steam",
    "SA": "Steam Auxiliary",
    "SC": "Steam Condensate",
    "WS": "Water Service",
    "FG": "Fuel Gas",
    "FO": "Fuel Oil",
    "LO": "Lube Oil",
    "IA": "Instrument Air",
    "AIR": "Instrument Air",
    "UA": "Utility Air",
    "N2": "Nitrogen",
    "DW": "Drinking Water",
    "FW": "Fire Water",
    "RW": "Raw Water",
    "SW": "Sea Water",
    "TW": "Treated Water",
    "V": "Vent",
    "DR": "Drain",
    "HC": "Hydrocarbon",
    "LPG": "LPG",
    "NG": "Natural Gas",
    "O2": "Oxygen",
    "H2": "Hydrogen",
    "CO2": "Carbon Dioxide",
    "AM": "Amine",
    "GLY": "Glycol",
    "CA": "Caustic",
    "AC": "Acid",
    "SO": "Sodium Hydroxide",
}

# Insulation codes
INSULATION_CODES = {
    "H": "Hot Insulation",
    "C": "Cold Insulation",
    "P": "Personnel Protection",
    "AC": "Acoustic Insulation",
    "HT": "Heat Tracing (Electrical)",
    "ST": "Steam Tracing",
    "N": "No Insulation",
    "None": "No Insulation",
}

# Material codes
MATERIAL_CODES = {
    "A53": "Carbon Steel (ASTM A53)",
    "A106": "Carbon Steel (ASTM A106, high temp)",
    "A106B": "Carbon Steel Grade B",
    "A106C": "Carbon Steel Grade C",
    "SS316": "Stainless Steel 316",
    "SS316L": "Stainless Steel 316L",
    "SS304": "Stainless Steel 304",
    "SS304L": "Stainless Steel 304L",
    "A335": "Alloy Steel (Chrome-Moly P11/P22/P91)",
    "A333": "Low Temp Carbon Steel",
    "A312": "Stainless Steel Pipe (ASTM A312)",
    "A790": "Duplex Stainless Steel",
    "PVC": "Polyvinyl Chloride",
    "HDPE": "High Density Polyethylene",
    "FRP": "Fiber Reinforced Plastic",
    "CU": "Copper",
    "GRE": "Glass Reinforced Epoxy",
}

# Nominal pipe size mapping (inch → mm NPS)
NPS_INCH_TO_MM = {
    '0.5': 15, '1/2': 15,
    '0.75': 20, '3/4': 20,
    '1': 25,
    '1.25': 32, '1-1/4': 32,
    '1.5': 40, '1-1/2': 40,
    '2': 50,
    '2.5': 65, '2-1/2': 65,
    '3': 80,
    '4': 100,
    '6': 150,
    '8': 200,
    '10': 250,
    '12': 300,
    '14': 350,
    '16': 400,
    '18': 450,
    '20': 500,
    '24': 600,
    '30': 750,
    '36': 900,
    '42': 1050,
    '48': 1200,
}


class LineNumberDecoder:
    """Decode P&ID line number strings into structured engineering data."""

    # Regex patterns for line numbers — ordered by specificity
    PATTERNS = [
        # Full format: 8"-150-A53-B-003 or 8"-150#-A53-BFW-001-H
        re.compile(
            r'(\d{1,2}(?:[/-]\d{1,2})?)\s*["\u201d]?[-\s]'  # size
            r'(\d{1,4})\s*#?[-\s]'                          # rating
            r'([A-Z][A-Z0-9]{1,5})[-\s]'                    # material
            r'([A-Z][A-Z0-9]{0,5})[-\s]'                    # service
            r'(\d{1,5})'                                    # line number
            r'(?:[-\s]([A-Z]{1,3}))?'                       # insulation (optional)
            r'(?:[-\s]([A-Z0-9]{1,4}))?'                    # area (optional)
        , re.IGNORECASE),

        # No rating: 10"-A106B-CS-201 or 10"-A106B-CS-201-H
        re.compile(
            r'(\d{1,2}(?:[/-]\d{1,2})?)\s*["\u201d]?[-\s]'
            r'([A-Z][A-Z0-9]{1,5})[-\s]'
            r'([A-Z][A-Z0-9]{0,5})[-\s]'
            r'(\d{1,5})'
            r'(?:[-\s]([A-Z]{1,3}))?'
        , re.IGNORECASE),

        # Size only with tag: 4"-SS316-PS-005
        re.compile(
            r'(\d{1,2}(?:[/-]\d{1,2})?)\s*["\u201d]?[-\s]'
            r'([A-Z][A-Z0-9]{1,5})[-\s]'
            r'([A-Z][A-Z0-9]{0,5})[-\s]'
            r'(\d{1,4})'
        , re.IGNORECASE),

        # Simple: 12"-A53-S-1001
        re.compile(
            r'(\d{1,2}(?:[/-]\d{1,2})?)\s*["\u201d]?[-\s]'
            r'([A-Z][A-Z0-9]{0,5})[-\s]'
            r'([A-Z])-?(\d{1,5})'
        , re.IGNORECASE),

        # DN format: DN100-A106-CW-002
        re.compile(
            r'DN(\d{2,3})[-\s]'
            r'([A-Z][A-Z0-9]{1,5})[-\s]'
            r'([A-Z][A-Z0-9]{0,5})[-\s]'
            r'(\d{1,4})'
        , re.IGNORECASE),

        # NPS format: NPS6-A53-GAS-001
        re.compile(
            r'NPS(\d{1,2})[-\s]'
            r'([A-Z][A-Z0-9]{1,5})[-\s]'
            r'([A-Z][A-Z0-9]{0,5})[-\s]'
            r'(\d{1,4})'
        , re.IGNORECASE),
    ]

    def decode(self, raw_text):
        """Decode a line number string into a LineNumber object."""
        text = raw_text.strip()
        result = LineNumber(raw=text)

        for i, pattern in enumerate(self.PATTERNS):
            m = pattern.match(text)
            if not m:
                continue

            groups = m.groups()

            if i == 0:
                # Full: size, rating, material, service, line, insulation?, area?
                result.size = self._normalize_size(groups[0])
                result.size_mm = self._size_to_mm(groups[0])
                result.rating = f"{groups[1]}#"
                result.rating_class = int(groups[1]) if groups[1].isdigit() else None
                result.material = groups[2].upper()
                result.service = groups[3].upper()
                result.service_desc = SERVICE_CODES.get(groups[3].upper())
                result.line_number = groups[4]
                if groups[5]:
                    result.insulation = groups[5].upper()
                    result.insulation_desc = INSULATION_CODES.get(groups[5].upper())
                if groups[6]:
                    result.area = groups[6].upper()
            elif i == 1:
                # No rating: size, material, service, line, insulation?
                result.size = self._normalize_size(groups[0])
                result.size_mm = self._size_to_mm(groups[0])
                result.material = groups[1].upper()
                result.service = groups[2].upper()
                result.service_desc = SERVICE_CODES.get(groups[2].upper())
                result.line_number = groups[3]
                if groups[4]:
                    result.insulation = groups[4].upper()
                    result.insulation_desc = INSULATION_CODES.get(groups[4].upper())
            elif i == 2:
                # size, material, service, line
                result.size = self._normalize_size(groups[0])
                result.size_mm = self._size_to_mm(groups[0])
                result.material = groups[1].upper()
                result.service = groups[2].upper()
                result.service_desc = SERVICE_CODES.get(groups[2].upper())
                result.line_number = groups[3]
            elif i == 3:
                # Simple: size, material, service, line
                result.size = self._normalize_size(groups[0])
                result.size_mm = self._size_to_mm(groups[0])
                result.material = groups[1].upper()
                result.service = groups[2].upper()
                result.service_desc = SERVICE_CODES.get(groups[2].upper())
                result.line_number = groups[3]
            elif i == 4:
                # DN format
                result.size = f"DN{groups[0]}"
                result.size_mm = int(groups[0])
                result.material = groups[1].upper()
                result.service = groups[2].upper()
                result.service_desc = SERVICE_CODES.get(groups[2].upper())
                result.line_number = groups[3]
            elif i == 5:
                # NPS format
                result.size = f'NPS{groups[0]}"'
                result.size_mm = NPS_INCH_TO_MM.get(groups[0])
                result.material = groups[1].upper()
                result.service = groups[2].upper()
                result.service_desc = SERVICE_CODES.get(groups[2].upper())
                result.line_number = groups[3]

            return result

        # Couldn't parse with any pattern — try to at least extract size
        size_match = re.match(r'(\d{1,2}(?:[/-]\d{1,2})?)\s*["\u201d]', text)
        if size_match:
            result.size = self._normalize_size(size_match.group(1))
            result.size_mm = self._size_to_mm(size_match.group(1))

        return result

    def _normalize_size(self, size_str):
        """Normalize size string to standard format."""
        s = size_str.strip()
        if '/' in s or '-' in s:
            # Fraction like 1-1/2 or 1/2
            s = s.replace('-', '/')
        return f'{s}"'

    def _size_to_mm(self, size_str):
        """Convert inch size to mm NPS."""
        s = size_str.strip().replace('-', '/')
        return NPS_INCH_TO_MM.get(s)

    def decode_from_texts(self, texts):
        """Find and decode all line numbers from extracted text annotations."""
        line_numbers = []
        seen = set()

        for t in texts:
            text = t["text"].strip()
            # Skip very short or very long text
            if len(text) < 5 or len(text) > 40:
                continue
            # Must contain a digit and a dash or quote
            if not re.search(r'\d', text):
                continue
            if not re.search(r'[-\u2013\u2014"\u201d]', text):
                continue

            decoded = self.decode(text)
            if decoded.size and decoded.line_number:
                key = f"{decoded.size}_{decoded.material}_{decoded.service}_{decoded.line_number}"
                if key not in seen:
                    seen.add(key)
                    decoded.raw = text
                    line_numbers.append({
                        **decoded.to_dict(),
                        "x": t.get("x"),
                        "y": t.get("y"),
                        "x1": t.get("x1"),
                        "y1": t.get("y1"),
                    })

        return line_numbers