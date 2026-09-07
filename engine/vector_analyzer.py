"""Vector Analyzer - classifies drawing paths by CAD color layers"""
import fitz
from collections import defaultdict


class VectorAnalyzer:
    def __init__(self, page):
        self.page = page
        self.drawings = page.get_drawings()
    
    def analyze(self):
        """Classify all drawing paths by color layer with line filtering."""
        layer_stats = defaultdict(lambda: {
            "paths": 0, "lines": 0, "filled": 0,
            "line_length_pts": 0, "filled_symbols": [],
            "long_lines": 0, "long_line_length_pts": 0,  # lines > 10pts (real runs)
            "short_lines": 0, "short_line_length_pts": 0,  # lines < 10pts (fragments)
        })
        
        MIN_LINE_LENGTH = 10.0  # pts — below this is a fragment, not a real run
        
        for d in self.drawings:
            color = d.get("color")
            layer_name = self._classify_color(color)
            layer_stats[layer_name]["paths"] += 1
            
            has_fill = d.get("fill") is not None
            if has_fill:
                layer_stats[layer_name]["filled"] += 1
                r = d["rect"]
                layer_stats[layer_name]["filled_symbols"].append({
                    "x": round(r.x0, 1), "y": round(r.y0, 1),
                    "w": round(r.width, 2), "h": round(r.height, 2)
                })
            
            for item in d["items"]:
                if item[0] == "l":
                    layer_stats[layer_name]["lines"] += 1
                    p1, p2 = item[1], item[2]
                    length_pts = ((p2.x - p1.x)**2 + (p2.y - p1.y)**2)**0.5
                    layer_stats[layer_name]["line_length_pts"] += length_pts
                    
                    # Separate real runs from fragments
                    if length_pts >= MIN_LINE_LENGTH:
                        layer_stats[layer_name]["long_lines"] += 1
                        layer_stats[layer_name]["long_line_length_pts"] += length_pts
                    else:
                        layer_stats[layer_name]["short_lines"] += 1
                        layer_stats[layer_name]["short_line_length_pts"] += length_pts
        
        return dict(layer_stats)
    
    def _classify_color(self, color):
        """Map color tuple to layer name."""
        if color is None:
            return "none"
        
        r, g, b = color[0], color[1], color[2]
        
        if r > 0.9 and g < 0.1 and b > 0.9:
            return "magenta_duct"
        elif r < 0.1 and g < 0.1 and b > 0.9:
            return "blue_pipe"
        elif r < 0.1 and g > 0.9 and b > 0.9:
            return "cyan_piping"
        elif r < 0.1 and g > 0.9 and b < 0.1:
            return "green_supply"
        elif r > 0.9 and g < 0.1 and b < 0.1:
            return "red_fire"
        elif r > 0.9 and 0.4 < g < 0.6 and b < 0.1:
            return "orange_equipment"
        elif abs(r - 0.502) < 0.01 and abs(g - 0.502) < 0.01 and abs(b - 0.502) < 0.01:
            return "gray_architectural"
        elif r < 0.1 and g < 0.1 and b < 0.1:
            return "black_structural"
        elif r > 0.9 and g > 0.9 and b < 0.1:
            return "yellow_electrical"
        elif r > 0.7 and g < 0.1 and b > 0.7:
            return "purple_communication"
        else:
            return f"other_{r:.1f}_{g:.1f}_{b:.1f}"
    
    def measure_parallel_widths(self, scale, color_filter="magenta"):
        """Measure duct/pipe widths from parallel line pairs."""
        pt_to_mm_paper = 420.1 / 1191.0
        
        # Collect vertical lines grouped by x-coordinate
        target_color = None
        if color_filter == "magenta":
            target_color = (1.0, 0.0, 1.0)
        elif color_filter == "blue":
            target_color = (0.0, 0.0, 1.0)
        
        if not target_color:
            return {}
        
        x_groups = defaultdict(list)
        for d in self.drawings:
            if d.get("color") == target_color:
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if abs(p2.x - p1.x) < 1:  # vertical line
                            x_groups[round(p1.x)].append(1)
        
        # Find pairs of x-values close together
        x_vals = sorted(x_groups.keys())
        widths = []
        for i, x1 in enumerate(x_vals):
            for x2 in x_vals[i+1:]:
                spacing = x2 - x1
                if spacing > 10:
                    break
                if spacing >= 1 and len(x_groups[x1]) > 2 and len(x_groups[x2]) > 2:
                    width_mm = spacing * pt_to_mm_paper * scale
                    widths.append(width_mm)
        
        if not widths:
            return {"count": 0, "avg_width_mm": 0, "widths": []}
        
        return {
            "count": len(widths),
            "avg_width_mm": sum(widths) / len(widths),
            "widths": sorted(widths)
        }
    
    def get_layer_extent(self, color_filter):
        """Get bounding box of a specific color layer."""
        target_color = None
        if color_filter == "magenta":
            target_color = (1.0, 0.0, 1.0)
        elif color_filter == "blue":
            target_color = (0.0, 0.0, 1.0)
        
        if not target_color:
            return None
        
        rects = []
        for d in self.drawings:
            if d.get("color") == target_color:
                rects.append(d["rect"])
        
        if not rects:
            return None
        
        return {
            "x": (min(r.x0 for r in rects), max(r.x1 for r in rects)),
            "y": (min(r.y0 for r in rects), max(r.y1 for r in rects))
        }