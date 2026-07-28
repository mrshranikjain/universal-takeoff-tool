# Universal AI Quantity Takeoff Tool

Multi-discipline AI quantity takeoff tool that reads engineering tender drawings (PDF) and produces bid-ready quantity takeoffs across disciplines — HVAC, plumbing, electrical, structural, civil, P&ID, fire protection.

## Architecture — The Waterfall Engine

```
Layer 1: STRUCTURED DATA (highest confidence)
  ↓
Layer 2: TEXT ANNOTATION EXTRACTION (high confidence)
  ↓
Layer 3: VECTOR GRAPHICS ANALYSIS (medium confidence)
  ↓
Layer 4: VL MODEL VISUAL DETECTION (low confidence — backstop only)
  ↓
Layer 5: PARAMETRIC RULES (inference from known standards)
```

## Installation

```bash
pip3 install --break-system-packages pymupdf openpyxl Pillow requests
```

## Usage

```bash
# Auto-detect discipline and auto-calibrate scale
python3 takeoff.py drawing.pdf output.xlsx

# Force discipline with manual scale reference
python3 takeoff.py drawing.pdf output.xlsx --discipline hvac --scale-ref "AHU ROOM - 04" "4950X7450"

# All pages with VL model verification
python3 takeoff.py drawing.pdf output.xlsx --pages all --vl-verify --verbose

# Specific pages
python3 takeoff.py drawing.pdf output.xlsx --pages 1,3,5
```

## Supported Disciplines

| Discipline | Key Tags | CAD Colors | Output Units |
|---|---|---|---|
| HVAC | AHU, FD1-5, FDA, FHC, SPD, GL2-3 | Magenta, Blue, Green, Cyan | SQMT (ducts), RMT (pipes) |
| Plumbing | WP, CW, HW, WC, WB, SH | Blue, Green, Brown | RMT (pipes), No (fixtures) |
| Electrical | LT, DB, MCC, DG, TR, UPS | Red, Yellow, Blue | RMT (cables), No (panels) |
| Fire Protection | FD, FHC, SPD, SPK, HCV | Red, Green, Orange | RMT (pipes), No (devices) |
| Structural | C1-44, BEAM, ST, SEC | Black, Gray | No (counts) |
| Civil | ROOM, SEC, ELE, SSL | Gray, Black | SQMT (areas) |
| P&ID | VALVE, PI, TI, FI, LI, LINE | Blue, Green, Red | RMT (pipes), No (valves) |

## File Structure

```
takeoff-tool/
├── takeoff.py                    # CLI entry point
├── engine/
│   ├── pdf_parser.py             # Multi-page PDF handling
│   ├── text_extractor.py         # Layer 2: text tag extraction
│   ├── vector_analyzer.py        # Layer 3: CAD color classification
│   ├── scale_calibrator.py       # Auto + manual scale calibration
│   ├── measurement_engine.py     # Length/area calculations
│   ├── vl_verifier.py            # Layer 4: Qwen3-VL-8B backstop
│   └── output_formatter.py       # Excel BOQ output
├── disciplines/
│   └── base.py                   # Auto-discipline detection
├── config/
│   ├── config.json               # Duct/pipe sizes, VL model config
│   └── disciplines.json          # 7 discipline configs
```

## License

MIT