"""
MeasureBook - FastAPI Backend
Serves the web UI and exposes the takeoff engine as an API.
"""
import os
import sys
import uuid
import json
import tempfile
import asyncio
from pathlib import Path

# Add parent dirs to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from engine.pdf_parser import PDFParser
from engine.text_extractor import TextExtractor
from engine.vector_analyzer import VectorAnalyzer
from engine.scale_calibrator import ScaleCalibrator
from engine.measurement_engine import MeasurementEngine
from engine.output_formatter import OutputFormatter
from engine.batch_processor import BatchProcessor
from engine.pid_line_decoder import LineNumberDecoder, SERVICE_CODES, MATERIAL_CODES, INSULATION_CODES
from engine.pid_classifiers import ValveClassifier, SpecBreakDetector, TieInDetector, InstrumentLoopDetector, ASMEEngine
from engine.iso_analyzer import IsometricAnalyzer
from engine.dwg_parser import DWGParser
from engine.ifc_extractor import IFCExtractor
from engine.rate_database import RateDatabase
from engine.cost_estimator import CostEstimator
from engine.revision_tracker import RevisionTracker
from engine.ocr_text_extractor import HybridTextExtractor
from disciplines.base import DisciplineRouter

# Load configs (defined after imports)
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"

# Load configs
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
with open(CONFIG_DIR / "config.json") as f:
    CONFIG = json.load(f)
with open(CONFIG_DIR / "disciplines.json") as f:
    DISCIPLINE_CONFIGS = json.load(f)

# Load rate database
RATE_DB = RateDatabase(str(CONFIG_DIR / "rate_database.json"))

app = FastAPI(title="MeasureBook", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Storage for jobs
JOBS = {}
BATCH_JOBS = {}
JOB_DIR = Path(tempfile.gettempdir()) / "takeoff_jobs"
JOB_DIR.mkdir(exist_ok=True)


class AnalyzeRequest(BaseModel):
    discipline: str = "auto"
    scale_ref_room: str | None = None
    scale_ref_dim: str | None = None
    vl_verify: bool = False


@app.post("/api/analyze")
async def analyze_drawing(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    discipline: str = "auto",
    scale_ref_room: str | None = None,
    scale_ref_dim: str | None = None,
    vl_verify: bool = False,
):
    """Upload a PDF and start analysis. Returns job_id."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported")

    job_id = str(uuid.uuid4())[:8]
    job_dir = JOB_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    pdf_path = job_dir / file.filename
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "filename": file.filename,
        "discipline": discipline,
        "pdf_path": str(pdf_path),
        "scale_ref_room": scale_ref_room,
        "scale_ref_dim": scale_ref_dim,
        "vl_verify": vl_verify,
        "results": None,
        "error": None,
    }

    # Run analysis in background
    background_tasks.add_task(run_analysis, job_id)

    return {"job_id": job_id, "status": "processing"}


def run_analysis(job_id: str):
    """Background task to run the takeoff analysis."""
    job = JOBS[job_id]
    try:
        pdf_path = job["pdf_path"]
        parser = PDFParser(pdf_path)
        pages = parser.get_pages("all")

        all_results = []
        for page_num, page in pages:
            # Layer 2: Text extraction (hybrid — PDF text first, OCR fallback for ZWCAD/scanned)
            hybrid_extractor = HybridTextExtractor(page, render_scale=3.0)
            texts = hybrid_extractor.extract()
            extraction_mode = hybrid_extractor.extraction_mode
            text_extractor = TextExtractor(page)  # keep for extract_components/extract_title_block
            
            # If OCR was used, get components from hybrid extractor
            if extraction_mode == 'ocr':
                # Auto-detect discipline from OCR text
                discipline = job["discipline"]
                if discipline == "auto":
                    router = DisciplineRouter(DISCIPLINE_CONFIGS)
                    discipline = router.detect(texts) or "pid"  # default to P&ID for OCR drawings
                disc_config = DISCIPLINE_CONFIGS[discipline]
                components = hybrid_extractor.extract_components(disc_config)
            else:
                # Normal PDF text extraction
                # Auto-detect discipline
                discipline = job["discipline"]
                if discipline == "auto":
                    router = DisciplineRouter(DISCIPLINE_CONFIGS)
                    discipline = router.detect(texts) or "civil"
                disc_config = DISCIPLINE_CONFIGS[discipline]
                components = text_extractor.extract_components(disc_config)

            # Layer 3: Vector analysis
            vector_analyzer = VectorAnalyzer(page)
            layers = vector_analyzer.analyze()

            # Scale calibration
            calibrator = ScaleCalibrator(texts, page.get_drawings())
            if job["scale_ref_room"] and job["scale_ref_dim"]:
                scale, scale_info = calibrator.calibrate_from_room(
                    job["scale_ref_room"], job["scale_ref_dim"])
            else:
                scale, scale_info = calibrator.auto_calibrate(disc_config)

            if not scale:
                scale = 100
                scale_info = "Default scale 1:100 (calibration failed)"

            # Measurements
            meas_engine = MeasurementEngine(layers, scale, CONFIG, disc_config, drawings=page.get_drawings(), texts=texts)
            measurements, measurement_confidence = meas_engine.get_confidence_map()
            widths = vector_analyzer.measure_parallel_widths(scale)

            # Render page image for UI
            import fitz
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = JOB_DIR / job_id / f"page_{page_num}.png"
            pix.save(str(img_path))

            # Collect filled symbol positions for annotation overlay
            vector_symbols = []
            for layer_name, layer_data in layers.items():
                for sym in layer_data.get("filled_symbols", []):
                    vector_symbols.append({
                        "layer": layer_name,
                        "x": sym["x"], "y": sym["y"],
                        "w": sym["w"], "h": sym["h"]
                    })

            # Get page dimensions for coordinate mapping
            page_rect = page.rect
            page_width = page_rect.width
            page_height = page_rect.height

            result = {
                "page": page_num,
                "discipline": discipline,
                "discipline_name": disc_config["name"],
                "scale": round(scale, 0),
                "scale_info": scale_info,
                "components": components,
                "measurements": measurements,
                "measurement_confidence": measurement_confidence,
                "widths": widths,
                "texts_count": len(texts),
                "title_block": text_extractor.extract_title_block(),
                "vector_summary": {
                    k: {"paths": v["paths"], "lines": v["lines"], "filled": v["filled"]}
                    for k, v in layers.items() if v["paths"] > 0
                },
                "vector_symbols": vector_symbols,
                "page_width": round(page_width, 1),
                "page_height": round(page_height, 1),
            }
            all_results.append(result)

        # Generate Excel
        output_path = JOB_DIR / job_id / "takeoff_output.xlsx"
        formatter = OutputFormatter(str(output_path))
        formatter.build(all_results, disc_config, CONFIG)

        job["status"] = "complete"
        job["results"] = all_results
        job["excel_path"] = str(output_path)
        parser.close()

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()


@app.get("/api/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Get job status and results."""
    if job_id not in JOBS:
        raise HTTPException(404, "Job not found")

    job = JOBS[job_id]
    response = {
        "id": job["id"],
        "status": job["status"],
        "filename": job["filename"],
    }

    if job["status"] == "complete":
        response["results"] = job["results"]
    elif job["status"] == "error":
        response["error"] = job["error"]

    return response


@app.get("/api/jobs/{job_id}/download")
async def download_excel(job_id: str):
    """Download the Excel output."""
    if job_id not in JOBS or JOBS[job_id]["status"] != "complete":
        raise HTTPException(404, "Excel not ready")

    excel_path = JOBS[job_id].get("excel_path")
    if not excel_path or not os.path.exists(excel_path):
        raise HTTPException(404, "Excel file not found")

    return FileResponse(excel_path, filename="takeoff_output.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/jobs/{job_id}/image/{page_num}")
async def get_page_image(job_id: str, page_num: int):
    """Get rendered page image."""
    img_path = JOB_DIR / job_id / f"page_{page_num}.png"
    if not img_path.exists():
        raise HTTPException(404, "Image not found")
    return FileResponse(str(img_path), media_type="image/png")


@app.post("/api/analyze-batch")
async def analyze_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Upload multiple PDFs for batch processing. Returns batch_job_id."""
    if not files:
        raise HTTPException(400, "No files provided")
    
    for f in files:
        if not f.filename.endswith(".pdf"):
            raise HTTPException(400, f"Only PDF files supported: {f.filename}")
    
    batch_id = str(uuid.uuid4())[:8]
    batch_dir = JOB_DIR / f"batch_{batch_id}"
    batch_dir.mkdir(exist_ok=True)
    
    # Save all files
    pdf_files = []
    for f in files:
        file_path = batch_dir / f.filename
        with open(file_path, "wb") as fp:
            content = await f.read()
            fp.write(content)
        pdf_files.append({"path": str(file_path), "filename": f.filename})
    
    BATCH_JOBS[batch_id] = {
        "id": batch_id,
        "status": "processing",
        "total_files": len(pdf_files),
        "processed": 0,
        "current_file": "",
        "progress_message": "Starting batch processing...",
        "files": [],
        "summary": None,
        "unified_boq": None,
        "excel_path": None,
        "batch_dir": str(batch_dir),
    }
    
    background_tasks.add_task(run_batch_analysis, batch_id, pdf_files)
    
    return {"batch_job_id": batch_id, "status": "processing", "total_files": len(pdf_files)}


def run_batch_analysis(batch_id, pdf_files):
    """Background task for batch processing."""
    job = BATCH_JOBS[batch_id]
    batch_dir = Path(job["batch_dir"])
    
    def progress_cb(info):
        job["processed"] = info["current"]
        job["current_file"] = info["file_name"]
        job["progress_message"] = info["message"]
    
    try:
        processor = BatchProcessor(CONFIG, DISCIPLINE_CONFIGS, batch_dir, progress_callback=progress_cb)
        result = processor.process_batch(pdf_files)
        
        # Generate unified Excel
        excel_path = batch_dir / "unified_takeoff.xlsx"
        processor.generate_unified_excel(result["unified_boq"], result["summary"], str(excel_path))
        
        job["status"] = "complete"
        job["files"] = result["files"]
        job["summary"] = result["summary"]
        job["unified_boq"] = result["unified_boq"]
        job["excel_path"] = str(excel_path)
        
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()


@app.get("/api/batch/{batch_id}")
async def get_batch_status(batch_id: str):
    """Get batch job status and results."""
    if batch_id not in BATCH_JOBS:
        raise HTTPException(404, "Batch job not found")
    
    job = BATCH_JOBS[batch_id]
    response = {
        "id": job["id"],
        "status": job["status"],
        "total_files": job["total_files"],
        "processed": job.get("processed", 0),
        "current_file": job.get("current_file", ""),
        "progress_message": job.get("progress_message", ""),
    }
    
    if job["status"] == "complete":
        response["files"] = job["files"]
        response["summary"] = job["summary"]
        response["unified_boq"] = job["unified_boq"]
    elif job["status"] == "error":
        response["error"] = job.get("error", "Unknown error")
    
    return response


@app.get("/api/batch/{batch_id}/download")
async def download_batch_excel(batch_id: str):
    """Download the unified Excel output for a batch job."""
    if batch_id not in BATCH_JOBS or BATCH_JOBS[batch_id]["status"] != "complete":
        raise HTTPException(404, "Excel not ready")
    
    excel_path = BATCH_JOBS[batch_id].get("excel_path")
    if not excel_path or not os.path.exists(excel_path):
        raise HTTPException(404, "Excel file not found")
    
    return FileResponse(excel_path, filename="unified_takeoff.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/jobs/batch/{filename}")
async def get_batch_file_image(filename: str):
    """Get rendered image for a batch file."""
    # Search all batch dirs for this file
    for batch_dir in JOB_DIR.glob("batch_*"):
        img_path = batch_dir / filename
        if img_path.exists():
            return FileResponse(str(img_path), media_type="image/png")
    raise HTTPException(404, "Image not found")


@app.post("/api/pid-analyze")
async def pid_analyze(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Deep P&ID analysis: line decoding, valve classification, spec breaks, tie-ins, instrument loops, ASME data."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files supported")

    job_id = str(uuid.uuid4())[:8]
    job_dir = JOB_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    pdf_path = job_dir / file.filename
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "filename": file.filename,
        "pdf_path": str(pdf_path),
        "results": None,
        "error": None,
        "analysis_type": "pid_deep",
    }

    background_tasks.add_task(run_pid_analysis, job_id)
    return {"job_id": job_id, "status": "processing"}


def run_pid_analysis(job_id):
    """Run deep P&ID analysis on a drawing."""
    job = JOBS[job_id]
    try:
        import fitz
        pdf_path = job["pdf_path"]
        doc = fitz.open(pdf_path)

        line_decoder = LineNumberDecoder()
        valve_classifier = ValveClassifier()
        spec_break_detector = SpecBreakDetector()
        tie_in_detector = TieInDetector()
        instrument_detector = InstrumentLoopDetector()
        asme_engine = ASMEEngine()
        iso_analyzer = IsometricAnalyzer()

        all_page_results = []

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1

            # Extract text
            blocks = page.get_text("dict")
            texts = []
            for block in blocks.get("blocks", []):
                if "lines" in block:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            text = span["text"].strip()
                            if text:
                                texts.append({
                                    "text": text,
                                    "x": round(span["bbox"][0], 1),
                                    "y": round(span["bbox"][1], 1),
                                    "x1": round(span["bbox"][2], 1),
                                    "y1": round(span["bbox"][3], 1),
                                    "size": round(span["size"], 2),
                                    "color": span["color"],
                                })

            # Render page image
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = JOB_DIR / job_id / f"page_{page_num}.png"
            pix.save(str(img_path))

            # 1. Decode line numbers
            line_numbers = line_decoder.decode_from_texts(texts)

            # Enrich with ASME data
            for ln in line_numbers:
                if ln.get("size_mm") and ln.get("material"):
                    ln["asme"] = asme_engine.get_line_info(type('LN', (), ln)())

            # 2. Classify valves
            valves = valve_classifier.classify_with_lines(texts, line_numbers)

            # 3. Detect spec breaks
            spec_breaks = spec_break_detector.detect(line_numbers, valves)

            # 4. Detect tie-ins and battery limits
            tie_ins = tie_in_detector.detect(texts, line_numbers)

            # 5. Detect instrument loops
            loops, instruments = instrument_detector.detect(texts, valves)

            # 6. Iso analysis (welds, fittings, pipe runs)
            iso_data = iso_analyzer.analyze(texts, line_numbers)

            # Render page image for UI
            page_rect = page.rect

            result = {
                "page": page_num,
                "page_width": round(page_rect.width, 1),
                "page_height": round(page_rect.height, 1),
                "extraction_mode": extraction_mode,
                "line_numbers": line_numbers,
                "valves": [v.to_dict() for v in valves],
                "spec_breaks": [sb.to_dict() for sb in spec_breaks],
                "tie_ins": [ti.to_dict() for ti in tie_ins],
                "instruments": instruments,
                "instrument_loops": [loop.to_dict() for loop in loops],
                "iso_data": iso_data,
                "texts_count": len(texts),
            }
            all_page_results.append(result)

        # Summary across all pages
        summary = {
            "total_pages": len(all_page_results),
            "total_lines": sum(len(p["line_numbers"]) for p in all_page_results),
            "total_valves": sum(len(p["valves"]) for p in all_page_results),
            "total_spec_breaks": sum(len(p["spec_breaks"]) for p in all_page_results),
            "total_tie_ins": sum(len(p["tie_ins"]) for p in all_page_results),
            "total_instruments": sum(len(p["instruments"]) for p in all_page_results),
            "total_loops": sum(len(p["instrument_loops"]) for p in all_page_results),
            "total_welds": sum(p["iso_data"]["weld_count"] for p in all_page_results),
            "total_fittings": sum(p["iso_data"]["fitting_count"] for p in all_page_results),
            "total_pipe_length_mm": sum(p["iso_data"]["total_pipe_length_mm"] for p in all_page_results),
            "valve_breakdown": {},
            "fitting_breakdown": {},
            "service_breakdown": {},
            "material_breakdown": {},
        }

        # Aggregate breakdowns
        for p in all_page_results:
            for v in p["valves"]:
                summary["valve_breakdown"][v["valve_type"]] = summary["valve_breakdown"].get(v["valve_type"], 0) + 1
            for f in p["iso_data"]["fittings"]:
                summary["fitting_breakdown"][f["fitting_type"]] = summary["fitting_breakdown"].get(f["fitting_type"], 0) + 1
            for ln in p["line_numbers"]:
                if ln.get("service"):
                    summary["service_breakdown"][ln["service"]] = summary["service_breakdown"].get(ln["service"], 0) + 1
                if ln.get("material"):
                    summary["material_breakdown"][ln["material"]] = summary["material_breakdown"].get(ln["material"], 0) + 1

        job["status"] = "complete"
        job["results"] = {"pages": all_page_results, "summary": summary}
        doc.close()

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()


@app.get("/api/pid-codes")
async def get_pid_codes():
    """Return reference code tables for P&ID display."""
    return {
        "services": SERVICE_CODES,
        "materials": MATERIAL_CODES,
        "insulation": INSULATION_CODES,
    }


@app.post("/api/analyze-dwg")
async def analyze_dwg(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    discipline: str = "auto",
):
    """Upload a DWG/DXF file and start analysis. Returns job_id."""
    if not (file.filename.endswith(".dwg") or file.filename.endswith(".dxf")):
        raise HTTPException(400, "Only DWG/DXF files supported")

    job_id = str(uuid.uuid4())[:8]
    job_dir = JOB_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    dwg_path = job_dir / file.filename
    with open(dwg_path, "wb") as f:
        content = await file.read()
        f.write(content)

    JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "filename": file.filename,
        "discipline": discipline,
        "file_path": str(dwg_path),
        "file_type": "dwg",
        "results": None,
        "error": None,
    }

    background_tasks.add_task(run_dwg_analysis, job_id)
    return {"job_id": job_id, "status": "processing"}


def run_dwg_analysis(job_id):
    """Run takeoff analysis on a DWG/DXF file."""
    job = JOBS[job_id]
    try:
        dwg_path = job["file_path"]
        parser = DWGParser(dwg_path)
        layouts = parser.get_pages()

        all_results = []
        for page_num, layout in layouts:
            texts = parser.extract_texts(layout)
            drawings = parser.extract_drawings(layout)
            blocks = parser.extract_blocks(layout)

            # Auto-detect discipline
            discipline = job["discipline"]
            if discipline == "auto":
                router = DisciplineRouter(DISCIPLINE_CONFIGS)
                discipline = router.detect(texts) or "civil"

            disc_config = DISCIPLINE_CONFIGS[discipline]

            # Use text extractor logic with DWG texts
            from engine.text_extractor import TextExtractor
            # Create a mock page object for TextExtractor
            class MockPage:
                def __init__(self, texts_data, drawings_data):
                    self._texts = texts_data
                    self._drawings = drawings_data
                    self.rect = type('R', (), {'width': 842, 'height': 595})()
                def get_text(self, mode):
                    if mode == "dict":
                        blocks = []
                        for t in self._texts:
                            blocks.append({"lines": [{"spans": [{"text": t["text"], "bbox": [t["x"], t["y"], t["x1"], t["y1"]], "size": t["size"], "color": t["color"], "font": t.get("font", "")}]}]})
                        return {"blocks": blocks}
                def get_drawings(self):
                    return self._drawings
                def get_pixmap(self, matrix=None):
                    return None
                def get_drawings(self):
                    return self._drawings
                def get_pixmap(self, matrix=None):
                    return None

            mock_page = MockPage(texts, drawings)
            text_extractor = TextExtractor(mock_page)
            components = text_extractor.extract_components(disc_config)

            # Vector analysis
            from engine.vector_analyzer import VectorAnalyzer
            vector_analyzer = VectorAnalyzer(mock_page)
            layers = vector_analyzer.analyze()

            # Scale (DWG usually 1:1)
            scale = 1
            scale_info = "DWG native scale (1:1)"

            # Measurements
            meas_engine = MeasurementEngine(layers, scale, CONFIG, disc_config, drawings=page.get_drawings(), texts=texts)
            measurements, measurement_confidence = meas_engine.get_confidence_map()

            result = {
                "page": page_num,
                "discipline": discipline,
                "discipline_name": disc_config["name"],
                "scale": scale,
                "scale_info": scale_info,
                "components": components,
                "measurements": measurements,
                "measurement_confidence": measurement_confidence,
                "texts_count": len(texts),
                "blocks_count": len(blocks),
                "title_block": {},
                "vector_summary": {
                    k: {"paths": v["paths"], "lines": v["lines"], "filled": v["filled"]}
                    for k, v in layers.items() if v["paths"] > 0
                },
                "vector_symbols": [],
                "page_width": 842,
                "page_height": 595,
            }
            all_results.append(result)

        job["status"] = "complete"
        job["results"] = all_results
        parser.close()

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()


@app.post("/api/analyze-ifc")
async def analyze_ifc(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Upload an IFC file and extract quantities. Returns job_id."""
    if not file.filename.endswith(".ifc"):
        raise HTTPException(400, "Only IFC files supported")

    job_id = str(uuid.uuid4())[:8]
    job_dir = JOB_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    ifc_path = job_dir / file.filename
    with open(ifc_path, "wb") as f:
        content = await file.read()
        f.write(content)

    JOBS[job_id] = {
        "id": job_id,
        "status": "processing",
        "filename": file.filename,
        "file_path": str(ifc_path),
        "file_type": "ifc",
        "results": None,
        "error": None,
    }

    background_tasks.add_task(run_ifc_analysis, job_id)
    return {"job_id": job_id, "status": "processing"}


def run_ifc_analysis(job_id):
    """Run IFC extraction."""
    job = JOBS[job_id]
    try:
        extractor = IFCExtractor(job["file_path"])
        results = extractor.extract_all()
        job["status"] = "complete"
        job["results"] = results
        extractor.close()
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        import traceback
        traceback.print_exc()


@app.post("/api/estimate")
async def estimate_costs(request: dict):
    """Generate priced BOQ from takeoff results."""
    job_id = request.get("job_id")
    rate_book = request.get("rate_book", "cpwd_2024")

    if job_id not in JOBS or JOBS[job_id]["status"] != "complete":
        raise HTTPException(404, "Job not found or not complete")

    job = JOBS[job_id]
    results = job.get("results", [])

    estimator = CostEstimator(RATE_DB)
    estimate = estimator.estimate_from_results(results, rate_book)
    return estimate


@app.get("/api/rate-books")
async def list_rate_books():
    """List available rate books."""
    return RATE_DB.list_rate_books()


@app.post("/api/compare")
async def compare_revisions(request: dict):
    """Compare two takeoff results for revision tracking."""
    old_id = request.get("old_job_id")
    new_id = request.get("new_job_id")

    if old_id not in JOBS or new_id not in JOBS:
        raise HTTPException(404, "One or both jobs not found")
    if JOBS[old_id]["status"] != "complete" or JOBS[new_id]["status"] != "complete":
        raise HTTPException(400, "Both jobs must be complete")

    tracker = RevisionTracker()
    comparison = tracker.compare(JOBS[old_id].get("results", []), JOBS[new_id].get("results", []))
    return comparison


@app.get("/api/disciplines")
async def list_disciplines():
    """List available disciplines."""
    return {
        disc: {
            "name": cfg["name"],
            "title_keywords": cfg.get("title_keywords", []),
        }
        for disc, cfg in DISCIPLINE_CONFIGS.items()
    }


# Serve frontend static files (must be last - catch-all)
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    # Mount on /app to avoid catching /api routes
    app.mount("/app", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
    
    # Serve index.html at root
    @app.get("/")
    async def root():
        return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)