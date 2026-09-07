"""Scale Calibrator - auto-calibrate drawing scale from room dimensions"""
import re
from collections import defaultdict

PT_TO_MM_PAPER = 420.1 / 1191.0  # A3 paper width / PDF points


class ScaleCalibrator:
    def __init__(self, texts, drawings):
        self.texts = texts
        self.drawings = drawings
    
    def auto_calibrate(self, disc_config):
        """Try to auto-calibrate scale from room dimension annotations."""
        # Find dimension annotations matching pattern
        dim_pattern = disc_config.get("dimension_patterns", {}).get("room_size", r"(\d{3,5})\s*[xX]\s*(\d{3,5})")
        
        dim_annotations = []
        for t in self.texts:
            m = re.match(f"^{dim_pattern}$", t["text"], re.IGNORECASE)
            if m:
                w_mm = int(m.group(1))
                h_mm = int(m.group(2))
                if 1000 <= w_mm <= 50000 and 1000 <= h_mm <= 50000:
                    dim_annotations.append({
                        "text": t["text"],
                        "x": t["x"], "y": t["y"],
                        "w_mm": w_mm, "h_mm": h_mm
                    })
        
        if not dim_annotations:
            return None, "No room dimension annotations found"
        
        # Try to find walls near each dimension annotation
        scales = []
        
        for dim in dim_annotations:
            # Find gray walls near this annotation
            sig_h, sig_v = self._find_walls_near(dim["x"], dim["y"])
            
            if sig_v:
                # Try width calibration from vertical walls
                left_walls = sorted([w for w in sig_v if w["x"] < dim["x"]], 
                                   key=lambda w: dim["x"] - w["x"])
                right_walls = sorted([w for w in sig_v if w["x"] > dim["x"]], 
                                    key=lambda w: w["x"] - dim["x"])
                
                if left_walls and right_walls:
                    width_pts = right_walls[0]["x"] - left_walls[0]["x"]
                    if 3 < width_pts < 200:
                        scale_w = dim["w_mm"] / (width_pts * PT_TO_MM_PAPER)
                        if 50 < scale_w < 2000:
                            scales.append(scale_w)
                
                # Try height from wall endpoints
                if len(sig_v) >= 2:
                    y_vals = []
                    for w in sig_v[:5]:
                        y_vals.extend([w["y1"], w["y2"]])
                    height_pts = max(y_vals) - min(y_vals)
                    if 3 < height_pts < 200:
                        scale_h = dim["h_mm"] / (height_pts * PT_TO_MM_PAPER)
                        if 50 < scale_h < 2000:
                            scales.append(scale_h)
        
        if not scales:
            return None, "Could not match walls to dimension annotations"
        
        # Filter outliers (remove >2 std dev from median)
        median_scale = sorted(scales)[len(scales) // 2]
        filtered = [s for s in scales if abs(s - median_scale) / median_scale < 0.3]
        
        if not filtered:
            filtered = scales
        
        avg_scale = sum(filtered) / len(filtered)
        
        # Sanity check: HVAC layouts are typically 1:50 to 1:200
        # If scale is way off, try title block scale
        if avg_scale > 200:
            for t in self.texts:
                text_upper = t["text"].upper()
                if "SCALE" in text_upper:
                    import re as re2
                    m = re2.search(r"1[:\s]*(\d+)", text_upper)
                    if m:
                        tb_scale = int(m.group(1))
                        if 20 < tb_scale < 200:
                            return tb_scale, f"Title block scale 1:{tb_scale} (auto-calib gave 1:{avg_scale:.0f} - out of range)"
            
            # If no title block scale, clamp to reasonable max
            if avg_scale > 300:
                return 100, f"Scale clamped to 1:100 (calib gave 1:{avg_scale:.0f} - likely wall mismatch)"
        
        info = f"Calibrated from {len(filtered)} measurements (median 1:{median_scale:.0f})"
        return avg_scale, info
    
    def calibrate_from_room(self, room_name, expected_dim):
        """Calibrate from a specific room name and dimension."""
        # Parse expected dimensions
        parts = expected_dim.upper().replace(" ", "").split("X")
        w_mm = int(parts[0])
        h_mm = int(parts[1])
        
        # Find room text
        room_texts = [t for t in self.texts if room_name.upper() in t["text"].upper()]
        if not room_texts:
            return None, f"Room '{room_name}' not found"
        
        rx, ry = room_texts[0]["x"], room_texts[0]["y"]
        
        sig_h, sig_v = self._find_walls_near(rx, ry, search_radius=50, min_length=15)
        
        scales = []
        details = []
        
        # Width from vertical walls
        left_walls = sorted([w for w in sig_v if w["x"] < rx], key=lambda w: rx - w["x"])
        right_walls = sorted([w for w in sig_v if w["x"] > rx], key=lambda w: w["x"] - rx)
        
        if left_walls and right_walls:
            width_pts = right_walls[0]["x"] - left_walls[0]["x"]
            if width_pts > 5:
                scale_w = w_mm / (width_pts * PT_TO_MM_PAPER)
                scales.append(scale_w)
                details.append(f"Width: {width_pts:.1f}pts -> {w_mm}mm -> 1:{scale_w:.0f}")
        
        # Height from vertical wall span
        if sig_v:
            v_walls = sorted(sig_v, key=lambda w: -w["len"])
            if len(v_walls) >= 2:
                y_top = min(w["y1"] for w in v_walls[:5])
                y_bot = max(w["y2"] for w in v_walls[:5])
                height_pts = y_bot - y_top
                if height_pts > 5:
                    scale_h = h_mm / (height_pts * PT_TO_MM_PAPER)
                    scales.append(scale_h)
                    details.append(f"Height: {height_pts:.1f}pts -> {h_mm}mm -> 1:{scale_h:.0f}")
        
        if not scales:
            return None, "Could not find walls for calibration"
        
        avg = sum(scales) / len(scales)
        return avg, "\n  ".join(details)
    
    def _find_walls_near(self, x, y, search_radius=40, min_length=10):
        """Find horizontal and vertical walls near a point."""
        sig_h = []
        sig_v = []
        
        for d in self.drawings:
            if d.get("color") == (0.5019599795341492, 0.5019599795341492, 0.5019599795341492):
                for item in d["items"]:
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        length = ((p2.x - p1.x)**2 + (p2.y - p1.y)**2)**0.5
                        if length > min_length:
                            cx = (p1.x + p2.x) / 2
                            cy = (p1.y + p2.y) / 2
                            if abs(cx - x) < search_radius and abs(cy - y) < search_radius:
                                if abs(p2.y - p1.y) < 1.0 and abs(p2.x - p1.x) > min_length:
                                    sig_h.append({"x1": min(p1.x, p2.x), "y": p1.y, "x2": max(p1.x, p2.x), "len": length})
                                elif abs(p2.x - p1.x) < 1.0 and abs(p2.y - p1.y) > min_length:
                                    sig_v.append({"x": p1.x, "y1": min(p1.y, p2.y), "y2": max(p1.y, p2.y), "len": length})
        
        return sig_h, sig_v