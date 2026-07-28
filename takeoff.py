"""Universal AI Quantity Takeoff Tool - Phase 1 CLI"""
from engine.pdf_parser import PDFParser
from engine.scale_calibrator import ScaleCalibrator
from engine.vector_analyzer import VectorAnalyzer
from engine.text_extractor import TextExtractor
from engine.vl_verifier import VLVerifier
from engine.measurement_engine import MeasurementEngine
from engine.output_formatter import OutputFormatter
from disciplines.base import DisciplineRouter
import argparse
import os
import json
import time

VERSION = "1.0.0"

def main():
    parser = argparse.ArgumentParser(
        description=f"Universal AI Quantity Takeoff Tool v{VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  takeoff.py drawing.pdf output.xlsx                          # Auto-detect discipline
  takeoff.py drawing.pdf output.xlsx --discipline hvac        # Force HVAC
  takeoff.py drawing.pdf output.xlsx --pages all             # All pages
  takeoff.py drawing.pdf output.xlsx --pages 1,3,5           # Specific pages
  takeoff.py drawing.pdf output.xlsx --vl-verify             # Enable VL verification
  takeoff.py drawing.pdf output.xlsx --scale-ref "AHU ROOM - 04" "4950X7450"  # Manual scale ref
  takeoff.py drawing.pdf output.xlsx --verbose               # Detailed output
        """
    )
    parser.add_argument("pdf_path", help="Path to PDF drawing file")
    parser.add_argument("output_path", help="Path for output Excel file")
    parser.add_argument("--discipline", default="auto", 
                        choices=["auto", "hvac", "plumbing", "electrical", "fire_protection", "structural", "civil", "pid"],
                        help="Drawing discipline (default: auto-detect)")
    parser.add_argument("--pages", default="1", help="Pages to analyze: 'all', '1', '1,3,5', '1-5'")
    parser.add_argument("--vl-verify", action="store_true", help="Enable VL model secondary verification")
    parser.add_argument("--scale-ref", nargs=2, metavar=("ROOM_NAME", "DIMENSION"), 
                        help="Manual scale reference: --scale-ref 'AHU ROOM - 04' '4950X7450'")
    parser.add_argument("--config-dir", default=None, help="Config directory path")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--no-vl", action="store_true", help="Disable VL model entirely")
    
    args = parser.parse_args()
    
    # Setup config
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_dir = args.config_dir or os.path.join(script_dir, "config")
    
    with open(os.path.join(config_dir, "config.json")) as f:
        config = json.load(f)
    with open(os.path.join(config_dir, "disciplines.json")) as f:
        discipline_configs = json.load(f)
    
    if args.verbose:
        print(f"Takeoff Tool v{VERSION}")
        print(f"Input: {args.pdf_path}")
        print(f"Output: {args.output_path}")
        print(f"Config: {config_dir}")
    
    # Step 1: Parse PDF
    if args.verbose:
        print("\n=== Step 1: Parsing PDF ===")
    pdf_parser = PDFParser(args.pdf_path)
    pages = pdf_parser.get_pages(args.pages)
    if args.verbose:
        print(f"  Pages to analyze: {len(pages)}")
    
    all_results = []
    
    for page_num, page in pages:
        if args.verbose:
            print(f"\n--- Page {page_num} ---")
        
        # Step 2: Extract text annotations
        if args.verbose:
            print("  [Layer 2] Extracting text annotations...")
        text_extractor = TextExtractor(page)
        texts = text_extractor.extract()
        if args.verbose:
            print(f"    Found {len(texts)} text items")
        
        # Step 3: Auto-detect discipline if needed
        discipline = args.discipline
        if discipline == "auto":
            router = DisciplineRouter(discipline_configs)
            discipline = router.detect(texts)
            if args.verbose:
                print(f"  Auto-detected discipline: {discipline}")
            if not discipline:
                print(f"  WARNING: Could not auto-detect discipline. Use --discipline to specify.")
                discipline = "civil"  # fallback
        
        disc_config = discipline_configs[discipline]
        
        # Step 4: Extract tagged components
        components = text_extractor.extract_components(disc_config)
        if args.verbose:
            print(f"  Components found:")
            for cat, items in components.items():
                if isinstance(items, list) and len(items) > 0:
                    print(f"    {cat}: {len(items)}")
                elif isinstance(items, dict):
                    for sub, count in items.items():
                        if isinstance(count, int) and count > 0:
                            print(f"    {cat}.{sub}: {count}")
                        elif isinstance(count, dict) and count.get('count', 0) > 0:
                            print(f"    {cat}.{sub}: {count['count']}")
        
        # Step 5: Analyze vector graphics
        if args.verbose:
            print("  [Layer 3] Analyzing vector graphics...")
        vector_analyzer = VectorAnalyzer(page)
        layers = vector_analyzer.analyze()
        if args.verbose:
            for layer_name, stats in layers.items():
                if any(kw in layer_name for kw in ["duct", "pipe", "supply", "equipment", "piping", "fire", "cable", "sprinkler"]):
                    print(f"    {layer_name}: {stats['paths']} paths, {stats['lines']} lines, {stats['filled']} filled")
        
        # Step 6: Calibrate scale
        if args.verbose:
            print("  Calibrating scale...")
        calibrator = ScaleCalibrator(texts, page.get_drawings())
        
        scale = None
        scale_info = "Scale not calibrated"
        
        if args.scale_ref:
            scale, scale_info = calibrator.calibrate_from_room(args.scale_ref[0], args.scale_ref[1])
        else:
            scale, scale_info = calibrator.auto_calibrate(disc_config)
        
        if scale:
            if args.verbose:
                print(f"    Scale: 1:{scale:.0f}")
                print(f"    {scale_info}")
        else:
            print(f"    WARNING: {scale_info}. Using default 1:100")
            scale = 100
        
        # Step 7: Calculate measurements
        if args.verbose:
            print("  Calculating measurements...")
        meas_engine = MeasurementEngine(layers, scale, config, disc_config)
        measurements = meas_engine.calculate()
        if args.verbose:
            for key, val in measurements.items():
                if isinstance(val, float):
                    print(f"    {key}: {val:.1f}")
                else:
                    print(f"    {key}: {val}")
        
        # Step 8: Measure duct/pipe widths
        widths = vector_analyzer.measure_parallel_widths(scale)
        if widths and args.verbose:
            print(f"    Measured avg width: {widths['avg_width_mm']:.0f}mm ({widths['count']} pairs)")
        
        # Step 9: VL verification (optional)
        vl_results = []
        if args.vl_verify and not args.no_vl:
            if args.verbose:
                print("  [Layer 4] VL model verification...")
            vl = VLVerifier(config.get("vl_model", {}))
            vl_results = vl.verify_unlabeled(page)
            if args.verbose:
                for r in vl_results:
                    print(f"    {r.get('crop','?')}: {r.get('result','?')[:80]}")
        
        # Step 10: Compile results
        result = {
            "page": page_num,
            "discipline": discipline,
            "discipline_name": disc_config["name"],
            "scale": scale,
            "scale_info": scale_info,
            "components": components,
            "measurements": measurements,
            "vector_layers": {k: {"paths": v["paths"], "lines": v["lines"], "filled": v["filled"]} 
                            for k, v in layers.items() if v["paths"] > 0},
            "widths": widths,
            "vl_results": vl_results,
            "texts_count": len(texts),
            "title_block": text_extractor.extract_title_block(),
        }
        all_results.append(result)
    
    # Step 11: Build Excel output
    if args.verbose:
        print(f"\n=== Building Excel output ===")
    formatter = OutputFormatter(args.output_path)
    formatter.build(all_results, disc_config, config)
    print(f"\n✅ Takeoff complete: {args.output_path}")
    print(f"   Discipline: {discipline_configs[discipline]['name']}")
    print(f"   Pages analyzed: {len(all_results)}")
    total_items = sum(1 for r in all_results for cat in r["components"].values() 
                     for _ in (cat.items() if isinstance(cat, dict) else [cat]))
    print(f"   Total items extracted: {total_items}")
    
    pdf_parser.close()

if __name__ == "__main__":
    main()