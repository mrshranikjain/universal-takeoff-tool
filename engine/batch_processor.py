"""
Batch Processor - handles multi-file tender set processing.
Upload multiple PDFs → auto-classify → process → unified BOQ.
"""
import os
import sys
import json
import fitz
from pathlib import Path
from collections import defaultdict

# Add parent paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.pdf_parser import PDFParser
from engine.text_extractor import TextExtractor
from engine.vector_analyzer import VectorAnalyzer
from engine.scale_calibrator import ScaleCalibrator
from engine.measurement_engine import MeasurementEngine
from engine.output_formatter import OutputFormatter
from disciplines.base import DisciplineRouter


class BatchProcessor:
    """Process multiple PDF drawings as a unified tender set."""

    def __init__(self, config, discipline_configs, job_dir, progress_callback=None):
        self.config = config
        self.discipline_configs = discipline_configs
        self.job_dir = Path(job_dir)
        self.job_dir.mkdir(exist_ok=True)
        self.progress_callback = progress_callback
        self.router = DisciplineRouter(discipline_configs)

    def _report(self, current, total, message, file_name=""):
        if self.progress_callback:
            self.progress_callback({
                "current": current,
                "total": total,
                "message": message,
                "file_name": file_name,
            })

    def process_batch(self, pdf_files):
        """
        Process multiple PDF files.
        
        Args:
            pdf_files: list of {path, filename} dicts
        
        Returns:
            {
                "files": [{filename, discipline, pages, status, results, error}],
                "summary": {total_files, total_pages, by_discipline, total_components, total_measurements},
                "unified_boq": {discipline: [items]},
            }
        """
        total = len(pdf_files)
        file_results = []
        
        for idx, pf in enumerate(pdf_files):
            self._report(idx + 1, total, f"Processing {pf['filename']}...", pf["filename"])
            
            try:
                result = self._process_single_pdf(pf["path"], pf["filename"])
                file_results.append(result)
            except Exception as e:
                file_results.append({
                    "filename": pf["filename"],
                    "discipline": "unknown",
                    "discipline_name": "Unknown",
                    "pages": 0,
                    "status": "error",
                    "error": str(e),
                    "results": [],
                })

        # Build unified BOQ across all files
        unified_boq = self._build_unified_boq(file_results)
        
        # Build summary
        summary = self._build_summary(file_results, unified_boq)
        
        return {
            "files": file_results,
            "summary": summary,
            "unified_boq": unified_boq,
        }

    def _process_single_pdf(self, pdf_path, filename):
        """Process a single PDF and return results."""
        parser = PDFParser(pdf_path)
        pages = parser.get_pages("all")
        page_results = []
        detected_discipline = None

        for page_num, page in pages:
            # Text extraction
            text_extractor = TextExtractor(page)
            texts = text_extractor.extract()

            # Auto-detect discipline (from first page)
            discipline = "auto"
            if not detected_discipline:
                detected_discipline = self.router.detect(texts) or "civil"
            
            disc_config = self.discipline_configs[detected_discipline]
            components = text_extractor.extract_components(disc_config)

            # Vector analysis
            vector_analyzer = VectorAnalyzer(page)
            layers = vector_analyzer.analyze()

            # Scale calibration
            calibrator = ScaleCalibrator(texts, page.get_drawings())
            scale, scale_info = calibrator.auto_calibrate(disc_config)
            if not scale:
                scale = 100
                scale_info = "Default scale 1:100"

            # Measurements
            meas_engine = MeasurementEngine(layers, scale, self.config, disc_config)
            measurements = meas_engine.calculate()

            # Render thumbnail
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            thumb_path = self.job_dir / f"thumb_{filename}_{page_num}.png"
            pix.save(str(thumb_path))

            # Full render for viewer
            pix_full = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img_path = self.job_dir / f"page_{filename}_{page_num}.png"
            pix_full.save(str(img_path))

            # Collect vector symbols
            vector_symbols = []
            for layer_name, layer_data in layers.items():
                for sym in layer_data.get("filled_symbols", []):
                    vector_symbols.append({
                        "layer": layer_name,
                        "x": sym["x"], "y": sym["y"],
                        "w": sym["w"], "h": sym["h"],
                    })

            page_rect = page.rect
            result = {
                "page": page_num,
                "filename": filename,
                "discipline": detected_discipline,
                "discipline_name": disc_config["name"],
                "scale": round(scale, 0),
                "scale_info": scale_info,
                "components": components,
                "measurements": measurements,
                "texts_count": len(texts),
                "title_block": text_extractor.extract_title_block(),
                "vector_summary": {
                    k: {"paths": v["paths"], "lines": v["lines"], "filled": v["filled"]}
                    for k, v in layers.items() if v["paths"] > 0
                },
                "vector_symbols": vector_symbols,
                "page_width": round(page_rect.width, 1),
                "page_height": round(page_rect.height, 1),
                "thumb_url": f"/api/jobs/batch/thumb_{filename}_{page_num}.png",
                "image_url": f"/api/jobs/batch/page_{filename}_{page_num}.png",
            }
            page_results.append(result)

        parser.close()

        return {
            "filename": filename,
            "discipline": detected_discipline,
            "discipline_name": self.discipline_configs[detected_discipline]["name"],
            "pages": len(page_results),
            "status": "complete",
            "error": None,
            "results": page_results,
        }

    def _build_unified_boq(self, file_results):
        """Consolidate all components and measurements across files into a unified BOQ."""
        boq = defaultdict(lambda: {"components": [], "measurements": [], "rooms": []})

        for fr in file_results:
            if fr["status"] != "complete":
                continue

            disc = fr["discipline"]
            disc_name = fr["discipline_name"]

            for page_result in fr["results"]:
                components = page_result.get("components", {})
                measurements = page_result.get("measurements", {})

                # Components
                for tag, data in components.items():
                    if tag in ("room_dimensions", "rooms"):
                        if tag == "rooms":
                            for room in data:
                                boq[disc]["rooms"].append({
                                    "name": room["name"],
                                    "dimension": room.get("dimension", ""),
                                    "source": f"{fr['filename']} - Page {page_result['page']}",
                                })
                        continue

                    if isinstance(data, dict):
                        if "count" in data:
                            boq[disc]["components"].append({
                                "tag": tag,
                                "type": data.get("type", tag),
                                "count": data["count"],
                                "unit": data.get("unit", "No"),
                                "source": f"{fr['filename']} - Page {page_result['page']}",
                            })
                        elif data.get("locations"):
                            boq[disc]["components"].append({
                                "tag": tag,
                                "type": data.get("type", tag),
                                "count": len(data["locations"]),
                                "unit": data.get("unit", "No"),
                                "source": f"{fr['filename']} - Page {page_result['page']}",
                            })
                        else:
                            # Variants (FD1=5, FD2=2, etc.)
                            for variant, count in data.items():
                                if isinstance(count, int) and count > 0:
                                    boq[disc]["components"].append({
                                        "tag": variant,
                                        "type": f"{tag} variant {variant}",
                                        "count": count,
                                        "unit": "No",
                                        "source": f"{fr['filename']} - Page {page_result['page']}",
                                    })

                # Measurements
                for key, val in measurements.items():
                    if isinstance(val, (int, float)) and val != 0:
                        unit = "RMT"
                        if "sqmt" in key or "sm_" in key:
                            unit = "SQMT"
                        elif "symbols" in key or "segments" in key or "paths" in key or "filled" in key:
                            unit = "No"

                        boq[disc]["measurements"].append({
                            "key": key,
                            "value": round(val, 2) if isinstance(val, float) else val,
                            "unit": unit,
                            "source": f"{fr['filename']} - Page {page_result['page']}",
                        })

        # Consolidate: merge same tags across pages
        consolidated = {}
        for disc, data in boq.items():
            # Merge components by tag+type
            comp_map = defaultdict(lambda: {"count": 0, "unit": "", "type": "", "sources": []})
            for c in data["components"]:
                key = f"{c['tag']}_{c['type']}"
                comp_map[key]["count"] += c["count"]
                comp_map[key]["unit"] = c["unit"]
                comp_map[key]["type"] = c["type"]
                comp_map[key]["tag"] = c["tag"]
                comp_map[key]["sources"].append(f"{c['source']} ({c['count']})")

            # Merge measurements by key
            meas_map = defaultdict(lambda: {"value": 0, "unit": "", "sources": []})
            for m in data["measurements"]:
                meas_map[m["key"]]["value"] += m["value"]
                meas_map[m["key"]]["unit"] = m["unit"]
                meas_map[m["key"]]["key"] = m["key"]
                meas_map[m["key"]]["sources"].append(f"{m['source']} ({m['value']})")

            consolidated[disc] = {
                "discipline_name": self.discipline_configs[disc]["name"],
                "components": [
                    {**v, "sources": v["sources"]} for v in comp_map.values()
                ],
                "measurements": [
                    {**v, "sources": v["sources"]} for v in meas_map.values()
                ],
                "rooms": data["rooms"],
            }

        return consolidated

    def _build_summary(self, file_results, unified_boq):
        """Build summary statistics."""
        total_files = len(file_results)
        successful = sum(1 for f in file_results if f["status"] == "complete")
        failed = sum(1 for f in file_results if f["status"] == "error")
        total_pages = sum(f["pages"] for f in file_results if f["status"] == "complete")

        by_discipline = {}
        for disc, data in unified_boq.items():
            by_discipline[disc] = {
                "name": data["discipline_name"],
                "files": sum(1 for f in file_results if f["discipline"] == disc),
                "pages": sum(f["pages"] for f in file_results if f["discipline"] == disc),
                "component_types": len(data["components"]),
                "total_components": sum(c["count"] for c in data["components"]),
                "measurement_types": len(data["measurements"]),
                "rooms": len(data["rooms"]),
            }

        return {
            "total_files": total_files,
            "successful": successful,
            "failed": failed,
            "total_pages": total_pages,
            "by_discipline": by_discipline,
            "disciplines_found": list(by_discipline.keys()),
        }

    def generate_unified_excel(self, unified_boq, summary, output_path):
        """Generate a single Excel workbook with all disciplines as separate sheets."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()

        # Styles
        hf = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        hfill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
        tf = Font(name='Calibri', size=14, bold=True, color='2F5496')
        sf = Font(name='Calibri', size=9, italic=True, color='666666')
        nf = Font(name='Calibri', size=10)
        bf = Font(name='Calibri', size=10, bold=True)
        ca = Alignment(horizontal='center', vertical='center', wrap_text=True)
        la = Alignment(horizontal='left', vertical='center', wrap_text=True)
        tb = Border(left=Side(style='thin'), right=Side(style='thin'),
                    top=Side(style='thin'), bottom=Side(style='thin'))
        hi = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        md = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')

        # Summary sheet
        ws_summary = wb.active
        ws_summary.title = "Summary"
        ws_summary.merge_cells('A1:E1')
        ws_summary['A1'] = 'TENDER SET TAKEOFF — SUMMARY'
        ws_summary['A1'].font = tf
        ws_summary['A1'].alignment = Alignment(horizontal='center')

        row = 3
        summary_data = [
            ("Total Files", summary["total_files"]),
            ("Successful", summary["successful"]),
            ("Failed", summary["failed"]),
            ("Total Pages", summary["total_pages"]),
            ("", ""),
            ("DISCIPLINE BREAKDOWN", ""),
        ]
        for label, val in summary_data:
            ws_summary.cell(row=row, column=1, value=label).font = bf
            ws_summary.cell(row=row, column=2, value=val).font = nf
            row += 1

        # Discipline breakdown
        headers = ["Discipline", "Files", "Pages", "Component Types", "Total Components"]
        for c, h in enumerate(headers, 1):
            cell = ws_summary.cell(row=row, column=c, value=h)
            cell.font = hf; cell.fill = hfill; cell.alignment = ca; cell.border = tb
        row += 1

        for disc, data in summary["by_discipline"].items():
            ws_summary.cell(row=row, column=1, value=data["name"]).border = tb
            ws_summary.cell(row=row, column=2, value=data["files"]).border = tb
            ws_summary.cell(row=row, column=3, value=data["pages"]).border = tb
            ws_summary.cell(row=row, column=4, value=data["component_types"]).border = tb
            ws_summary.cell(row=row, column=5, value=data["total_components"]).border = tb
            row += 1

        # Each discipline as a sheet
        for disc, data in unified_boq.items():
            ws = wb.create_sheet(title=data["discipline_name"][:31])

            ws.merge_cells('A1:F1')
            ws['A1'] = f'{data["discipline_name"].upper()} — QUANTITY TAKEOFF'
            ws['A1'].font = tf
            ws['A1'].alignment = Alignment(horizontal='center')

            row = 3
            # Components section
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
            ws.cell(row=row, column=1, value="COMPONENTS").font = Font(bold=True, color='4472C4')
            row += 1

            headers = ["S.No", "Tag", "Description", "Qty", "Unit", "Sources"]
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=row, column=c, value=h)
                cell.font = hf; cell.fill = hfill; cell.alignment = ca; cell.border = tb
            row += 1

            sno = 1
            for comp in sorted(data["components"], key=lambda x: -x["count"]):
                ws.cell(row=row, column=1, value=sno).border = tb
                ws.cell(row=row, column=2, value=comp["tag"]).border = tb
                ws.cell(row=row, column=3, value=comp["type"]).border = tb
                ws.cell(row=row, column=4, value=comp["count"]).border = tb
                ws.cell(row=row, column=5, value=comp["unit"]).border = tb
                sources_text = "; ".join(comp["sources"][:5])
                if len(comp["sources"]) > 5:
                    sources_text += f" +{len(comp['sources'])-5} more"
                ws.cell(row=row, column=6, value=sources_text).border = tb
                ws.cell(row=row, column=6).font = sf
                row += 1; sno += 1

            # Measurements section
            row += 1
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
            ws.cell(row=row, column=1, value="MEASUREMENTS").font = Font(bold=True, color='4472C4')
            row += 1

            headers = ["S.No", "Measurement", "Value", "Unit", "Sources", ""]
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=row, column=c, value=h)
                cell.font = hf; cell.fill = hfill; cell.alignment = ca; cell.border = tb
            row += 1

            sno = 1
            for meas in data["measurements"]:
                ws.cell(row=row, column=1, value=sno).border = tb
                ws.cell(row=row, column=2, value=meas["key"].replace("_", " ").title()).border = tb
                ws.cell(row=row, column=3, value=meas["value"]).border = tb
                ws.cell(row=row, column=4, value=meas["unit"]).border = tb
                sources_text = "; ".join(meas["sources"][:5])
                if len(meas["sources"]) > 5:
                    sources_text += f" +{len(meas['sources'])-5} more"
                ws.cell(row=row, column=5, value=sources_text).border = tb
                ws.cell(row=row, column=5).font = sf
                # Confidence
                conf = "Medium" if "rmt" in meas["key"] or "sqmt" in meas["key"] else "Low"
                conf_cell = ws.cell(row=row, column=6, value=conf)
                conf_cell.border = tb
                conf_cell.fill = md if conf == "Medium" else PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
                row += 1; sno += 1

            # Rooms section
            if data["rooms"]:
                row += 1
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
                ws.cell(row=row, column=1, value="ROOMS").font = Font(bold=True, color='4472C4')
                row += 1

                headers = ["S.No", "Room Name", "Dimension", "Source", "", ""]
                for c, h in enumerate(headers, 1):
                    cell = ws.cell(row=row, column=c, value=h)
                    cell.font = hf; cell.fill = hfill; cell.alignment = ca; cell.border = tb
                row += 1

                sno = 1
                for room in data["rooms"]:
                    ws.cell(row=row, column=1, value=sno).border = tb
                    ws.cell(row=row, column=2, value=room["name"]).border = tb
                    ws.cell(row=row, column=3, value=room["dimension"]).border = tb
                    ws.cell(row=row, column=4, value=room["source"]).border = tb
                    ws.cell(row=row, column=4).font = sf
                    row += 1; sno += 1

            # Column widths
            for i, w in enumerate([6, 18, 35, 10, 8, 40], 1):
                ws.column_dimensions[get_column_letter(i)].width = w

        # Column widths for summary
        for i, w in enumerate([25, 12, 12, 18, 20], 1):
            ws_summary.column_dimensions[get_column_letter(i)].width = w

        wb.save(output_path)
        return output_path