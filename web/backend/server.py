"""
Takeoff Tool - FastAPI Backend
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
from disciplines.base import DisciplineRouter

# Load configs
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
with open(CONFIG_DIR / "config.json") as f:
    CONFIG = json.load(f)
with open(CONFIG_DIR / "disciplines.json") as f:
    DISCIPLINE_CONFIGS = json.load(f)

app = FastAPI(title="Universal Takeoff Tool", version="1.0.0")

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
            # Layer 2: Text extraction
            text_extractor = TextExtractor(page)
            texts = text_extractor.extract()

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
            meas_engine = MeasurementEngine(layers, scale, CONFIG, disc_config)
            measurements = meas_engine.calculate()
            widths = vector_analyzer.measure_parallel_widths(scale)

            # Render page image for UI
            import fitz
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = JOB_DIR / job_id / f"page_{page_num}.png"
            pix.save(str(img_path))

            result = {
                "page": page_num,
                "discipline": discipline,
                "discipline_name": disc_config["name"],
                "scale": round(scale, 0),
                "scale_info": scale_info,
                "components": components,
                "measurements": measurements,
                "widths": widths,
                "texts_count": len(texts),
                "title_block": text_extractor.extract_title_block(),
                "vector_summary": {
                    k: {"paths": v["paths"], "lines": v["lines"], "filled": v["filled"]}
                    for k, v in layers.items() if v["paths"] > 0
                },
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


# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)