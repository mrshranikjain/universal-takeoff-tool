"""Output Formatter - generates Excel BOQ output"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


class OutputFormatter:
    def __init__(self, output_path):
        self.path = output_path
    
    def build(self, results, disc_config, config):
        """Build Excel workbook with quantity takeoff."""
        wb = openpyxl.Workbook()
        
        # Styles
        hf = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
        hfill = PatternFill(start_color='2F5496', end_color='2F5496', fill_type='solid')
        tf = Font(name='Calibri', size=14, bold=True, color='2F5496')
        sf = Font(name='Calibri', size=9, italic=True, color='666666')
        cf = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        cfill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        nf = Font(name='Calibri', size=9)
        bf = Font(name='Calibri', size=9, bold=True)
        hi = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        md = PatternFill(start_color='FFEB9C', end_color='FFEB9C', fill_type='solid')
        lo = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
        ca = Alignment(horizontal='center', vertical='center', wrap_text=True)
        la = Alignment(horizontal='left', vertical='center', wrap_text=True)
        tb = Border(left=Side(style='thin'), right=Side(style='thin'),
                    top=Side(style='thin'), bottom=Side(style='thin'))
        
        # Sheet 1: Quantity Takeoff
        ws = wb.active
        ws.title = "Quantity Takeoff"
        
        ws.merge_cells('A1:G1')
        ws['A1'] = f'QUANTITY TAKEOFF - {disc_config["name"].upper()}'
        ws['A1'].font = tf
        ws['A1'].alignment = Alignment(horizontal='center')
        
        # Process each page result
        row = 3
        for result in results:
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
            ws.cell(row=row, column=1, value=f'Page {result["page"]} | Discipline: {result["discipline_name"]} | Scale: 1:{result["scale"]:.0f}').font = sf
            row += 1
            
            # Headers
            headers = ['S.No', 'Tag', 'Description', 'Qty', 'Unit', 'Specification', 'Confidence']
            for c, h in enumerate(headers, 1):
                cell = ws.cell(row=row, column=c, value=h)
                cell.font = hf; cell.fill = hfill; cell.alignment = ca; cell.border = tb
            row += 1
            
            sno = 1
            components = result.get("components", {})
            measurements = result.get("measurements", {})
            
            # Component counts (High confidence - from text tags)
            for tag_name, tag_data in components.items():
                if tag_name in ["room_dimensions", "rooms"]:
                    continue
                
                if isinstance(tag_data, dict) and "count" in tag_data:
                    ws.cell(row=row, column=1, value=sno).border = tb
                    ws.cell(row=row, column=1).alignment = ca; ws.cell(row=row, column=1).font = nf
                    ws.cell(row=row, column=2, value=tag_name).border = tb; ws.cell(row=row, column=2).font = bf; ws.cell(row=row, column=2).alignment = la
                    ws.cell(row=row, column=3, value=tag_data.get("type", tag_name)).border = tb; ws.cell(row=row, column=3).font = nf; ws.cell(row=row, column=3).alignment = la
                    ws.cell(row=row, column=4, value=tag_data["count"]).border = tb; ws.cell(row=row, column=4).font = bf; ws.cell(row=row, column=4).alignment = ca
                    ws.cell(row=row, column=5, value=tag_data.get("unit", "No")).border = tb; ws.cell(row=row, column=5).font = nf; ws.cell(row=row, column=5).alignment = ca
                    ws.cell(row=row, column=6, value="").border = tb; ws.cell(row=row, column=6).font = nf
                    conf_cell = ws.cell(row=row, column=7, value="High")
                    conf_cell.border = tb; conf_cell.fill = hi; conf_cell.alignment = ca; conf_cell.font = nf
                    row += 1; sno += 1
                
                elif isinstance(tag_data, dict):
                    # Variants (e.g., FD1=5, FD2=2)
                    for variant, count in tag_data.items():
                        if count > 0:
                            ws.cell(row=row, column=1, value=sno).border = tb; ws.cell(row=row, column=1).alignment = ca; ws.cell(row=row, column=1).font = nf
                            ws.cell(row=row, column=2, value=variant).border = tb; ws.cell(row=row, column=2).font = bf; ws.cell(row=row, column=2).alignment = la
                            ws.cell(row=row, column=3, value=f"{tag_name} variant {variant}").border = tb; ws.cell(row=row, column=3).font = nf; ws.cell(row=row, column=3).alignment = la
                            ws.cell(row=row, column=4, value=count).border = tb; ws.cell(row=row, column=4).font = bf; ws.cell(row=row, column=4).alignment = ca
                            ws.cell(row=row, column=5, value="No").border = tb; ws.cell(row=row, column=5).font = nf; ws.cell(row=row, column=5).alignment = ca
                            ws.cell(row=row, column=6, value="").border = tb; ws.cell(row=row, column=6).font = nf
                            conf_cell = ws.cell(row=row, column=7, value="High")
                            conf_cell.border = tb; conf_cell.fill = hi; conf_cell.alignment = ca; conf_cell.font = nf
                            row += 1; sno += 1
            
            # Measurements (Medium confidence - from vector analysis)
            for meas_name, meas_val in measurements.items():
                if isinstance(meas_val, (int, float)) and meas_val != 0:
                    unit = "RMT"
                    if "sqmt" in meas_name or "sm_" in meas_name:
                        unit = "SQMT"
                    elif "symbols" in meas_name or "segments" in meas_name or "paths" in meas_name:
                        unit = "No"
                    
                    ws.cell(row=row, column=1, value=sno).border = tb; ws.cell(row=row, column=1).alignment = ca; ws.cell(row=row, column=1).font = nf
                    ws.cell(row=row, column=2, value=meas_name).border = tb; ws.cell(row=row, column=2).font = bf; ws.cell(row=row, column=2).alignment = la
                    ws.cell(row=row, column=3, value=meas_name.replace("_", " ").title()).border = tb; ws.cell(row=row, column=3).font = nf; ws.cell(row=row, column=3).alignment = la
                    ws.cell(row=row, column=4, value=round(meas_val, 1) if isinstance(meas_val, float) else meas_val).border = tb; ws.cell(row=row, column=4).font = bf; ws.cell(row=row, column=4).alignment = ca
                    ws.cell(row=row, column=5, value=unit).border = tb; ws.cell(row=row, column=5).font = nf; ws.cell(row=row, column=5).alignment = ca
                    ws.cell(row=row, column=6, value=f"Scale 1:{result['scale']:.0f}").border = tb; ws.cell(row=row, column=6).font = nf; ws.cell(row=row, column=6).alignment = la
                    
                    conf = "Medium" if "rmt" in meas_name or "sqmt" in meas_name else "Low"
                    conf_cell = ws.cell(row=row, column=7, value=conf)
                    conf_cell.border = tb; conf_cell.alignment = ca; conf_cell.font = nf
                    conf_cell.fill = md if conf == "Medium" else lo
                    row += 1; sno += 1
            
            # Rooms
            rooms = components.get("rooms", [])
            if rooms:
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
                ws.cell(row=row, column=1, value="ROOMS").font = cf; ws.cell(row=row, column=1).fill = cfill
                row += 1
                for room in rooms:
                    ws.cell(row=row, column=1, value=sno).border = tb; ws.cell(row=row, column=1).alignment = ca; ws.cell(row=row, column=1).font = nf
                    ws.cell(row=row, column=2, value="").border = tb; ws.cell(row=row, column=2).font = nf
                    ws.cell(row=row, column=3, value=room["name"]).border = tb; ws.cell(row=row, column=3).font = nf; ws.cell(row=row, column=3).alignment = la
                    ws.cell(row=row, column=4, value=1).border = tb; ws.cell(row=row, column=4).font = bf; ws.cell(row=row, column=4).alignment = ca
                    ws.cell(row=row, column=5, value="Room").border = tb; ws.cell(row=row, column=5).font = nf; ws.cell(row=row, column=5).alignment = ca
                    ws.cell(row=row, column=6, value=room.get("dimension", "")).border = tb; ws.cell(row=row, column=6).font = nf; ws.cell(row=row, column=6).alignment = la
                    conf_cell = ws.cell(row=row, column=7, value="High")
                    conf_cell.border = tb; conf_cell.fill = hi; conf_cell.alignment = ca; conf_cell.font = nf
                    row += 1; sno += 1
            
            row += 1
        
        # Column widths
        for i, w in enumerate([6, 14, 30, 8, 10, 20, 10], 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        
        # Sheet 2: Scale & Methodology
        ws2 = wb.create_sheet("Methodology")
        ws2.merge_cells('A1:B1')
        ws2['A1'] = 'METHODOLOGY & SCALE CALIBRATION'
        ws2['A1'].font = tf
        ws2['A1'].alignment = Alignment(horizontal='center')
        
        method_lines = [
            f"Discipline: {disc_config['name']}",
            f"Scale: 1:{results[0]['scale']:.0f}" if results else "Scale: N/A",
            f"Scale info: {results[0]['scale_info']}" if results else "",
            "",
            "EXTRACTION METHOD - WATERFALL ENGINE:",
            "  Layer 1: Structured data (tables, schedules) - if available",
            "  Layer 2: Text annotation extraction (PyMuPDF) - HIGH confidence",
            "  Layer 3: Vector graphics analysis (CAD color layers) - MEDIUM confidence",
            "  Layer 4: VL model visual detection (Qwen3-VL-8B) - LOW confidence backstop",
            "  Layer 5: Parametric rules (standard sizes, multipliers) - inference",
            "",
            "CONFIDENCE SCORING:",
            "  High (90-100%): Explicitly tagged in PDF text",
            "  Medium (60-89%): Measured from vector graphics at calibrated scale",
            "  Low (30-59%): Inferred from VL model or parametric rules",
            "",
            "MEASUREMENT UNITS:",
            "  Ducting: SQMT (sheet metal area = linear length × cross-section perimeter)",
            "  Piping: RMT (running meters, supply+return = ×2 where applicable)",
            "  Equipment/Fixtures: No (count)",
            "  Rooms: SQMT (floor area from dimension annotations)",
            "",
            "COLOR LAYER MAPPING:",
        ]
        
        for layer_name, use in disc_config.get("color_layers", {}).items():
            method_lines.append(f"  {layer_name} → {use}")
        
        method_lines.extend([
            "",
            f"VL MODEL: {'Enabled' if results and results[0].get('vl_results') else 'Disabled'}",
        ])
        
        if results and results[0].get("vl_results"):
            for vr in results[0]["vl_results"]:
                method_lines.append(f"  {vr.get('crop','?')}: {vr.get('result','?')[:100]}")
        
        row = 3
        for line in method_lines:
            ws2.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
            ws2.cell(row=row, column=1, value=line).font = nf
            ws2.cell(row=row, column=1).alignment = Alignment(horizontal='left', wrap_text=True)
            row += 1
        
        ws2.column_dimensions['A'].width = 80
        ws2.column_dimensions['B'].width = 20
        
        wb.save(self.path)