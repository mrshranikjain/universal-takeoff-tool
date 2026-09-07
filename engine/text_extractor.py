"""Text Extractor - extracts all text annotations from PDF pages"""
import re
from collections import Counter


class TextExtractor:
    def __init__(self, page):
        self.page = page
    
    def extract(self):
        """Extract all text with coordinates, font, color."""
        blocks = self.page.get_text("dict")
        texts = []
        for block in blocks.get("blocks", []):
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            r = (span["color"] >> 16) & 0xFF
                            g = (span["color"] >> 8) & 0xFF
                            b = span["color"] & 0xFF
                            texts.append({
                                "text": text,
                                "x": round(span["bbox"][0], 1),
                                "y": round(span["bbox"][1], 1),
                                "x1": round(span["bbox"][2], 1),
                                "y1": round(span["bbox"][3], 1),
                                "size": round(span["size"], 2),
                                "color": span["color"],
                                "r": r, "g": g, "b": b,
                                "font": span.get("font", "")
                            })
        return texts
    
    def extract_components(self, disc_config):
        """Extract HVAC/plumbing/electrical/etc components based on discipline config."""
        texts = self.extract()
        tag_patterns = disc_config.get("tag_patterns", {})
        components = {}
        
        for tag_name, tag_info in tag_patterns.items():
            regex = tag_info["regex"]
            comp_type = tag_info["type"]
            unit = tag_info.get("unit", "No")
            variants = tag_info.get("variants")
            
            if variants:
                # Count each variant separately
                counts = {}
                for v in variants:
                    matches = [t for t in texts if t["text"].upper() == v]
                    counts[v] = len(matches)
                components[tag_name] = counts
            else:
                matches = [t for t in texts if re.match(f"^{regex}$", t["text"], re.IGNORECASE)]
                if matches:
                    components[tag_name] = {
                        "count": len(matches),
                        "type": comp_type,
                        "unit": unit,
                        "locations": [{"x": m["x"], "y": m["y"], "x1": m["x1"], "y1": m["y1"], "text": m["text"]} for m in matches]
                    }
        
        # Extract room dimensions
        dim_pattern = disc_config.get("dimension_patterns", {}).get("room_size", "")
        if dim_pattern:
            rooms = []
            for t in texts:
                m = re.match(f"^{dim_pattern}$", t["text"], re.IGNORECASE)
                if m:
                    rooms.append({
                        "text": t["text"],
                        "x": t["x"], "y": t["y"],
                        "w_mm": int(m.group(1)),
                        "h_mm": int(m.group(2))
                    })
            components["room_dimensions"] = rooms
        
        # Extract rooms by keyword
        room_keywords = disc_config.get("room_keywords", [])
        if room_keywords:
            rooms_found = []
            for t in texts:
                text_upper = t["text"].upper()
                for kw in room_keywords:
                    if kw in text_upper and len(t["text"]) < 40:
                        # Find nearby dimension
                        nearby_dim = None
                        for d in components.get("room_dimensions", []):
                            if abs(d["x"] - t["x"]) < 50 and abs(d["y"] - t["y"]) < 25:
                                nearby_dim = d["text"]
                                break
                        rooms_found.append({
                            "name": t["text"],
                            "x": t["x"], "y": t["y"],
                            "dimension": nearby_dim
                        })
                        break
            components["rooms"] = rooms_found
        
        return components
    
    def extract_title_block(self):
        """Extract title block info (project name, drawing no, scale, consultant)."""
        texts = self.extract()
        info = {}
        
        for t in texts:
            text = t["text"]
            text_upper = text.upper()
            if "TENDER" in text_upper and "DRAW" in text_upper:
                info["drawing_type"] = text
            if re.match(r"KCEPL|CONSULTING|ENGINEERS", text_upper):
                info["consultant"] = text
            if re.match(r"\d{4}/\d{2}/\d+", text) or "/" in text and len(text) > 10:
                info.get("drawing_numbers", []).append(text) if "drawing_numbers" in info else info.update({"drawing_numbers": [text]})
            if "SCALE" in text_upper:
                m = re.search(r"1[:\s]*(\d+)", text)
                if m:
                    info["title_block_scale"] = int(m.group(1))
            if "SPORTS" in text_upper or "COMPLEX" in text_upper or "BUILDING" in text_upper:
                info["project"] = text
            if re.match(r"PROPOSED|LAYOUT|FIRST|GROUND", text_upper):
                info["drawing_title"] = text
        
        return info
    
    def cross_reference_symbols(self, components, vector_symbols, max_distance=25):
        """
        Cross-reference filled vector symbols with text tag locations.
        
        Returns:
            matched: [{tag, x, y, symbol_x, symbol_y, distance}]
            unmatched: [{x, y, w, h, layer}]
        """
        # Collect all text tag locations with their tags
        tag_locations = []
        for tag, data in components.items():
            if tag in ("room_dimensions", "rooms"):
                continue
            if isinstance(data, dict):
                if data.get("locations"):
                    for loc in data["locations"]:
                        tag_locations.append({
                            "tag": loc.get("text", tag),
                            "tag_type": tag,
                            "x": loc.get("x", 0),
                            "y": loc.get("y", 0),
                        })
        
        matched = []
        matched_symbol_indices = set()
        
        for vs in vector_symbols:
            best_match = None
            best_dist = max_distance
            
            for tl in tag_locations:
                dist = ((vs["x"] - tl["x"])**2 + (vs["y"] - tl["y"])**2)**0.5
                if dist < best_dist:
                    best_dist = dist
                    best_match = tl
            
            if best_match:
                matched.append({
                    "tag": best_match["tag"],
                    "tag_type": best_match["tag_type"],
                    "x": best_match["x"],
                    "y": best_match["y"],
                    "symbol_x": vs["x"],
                    "symbol_y": vs["y"],
                    "symbol_w": vs.get("w", 0),
                    "symbol_h": vs.get("h", 0),
                    "distance": round(best_dist, 1),
                    "layer": vs.get("layer", ""),
                })
                matched_symbol_indices.add(id(vs))
        
        unmatched = [vs for vs in vector_symbols if id(vs) not in matched_symbol_indices]
        
        return matched, unmatched