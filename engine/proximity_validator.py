"""
Proximity Validator — confirms color-based line classifications by checking
for corroborating text labels near the lines.

This upgrades confidence from Medium (color-assumed) to High (text-confirmed).
"""
import re
from collections import defaultdict


class ProximityValidator:
    """Validate color-layer classifications by finding confirming text nearby."""
    
    # What text labels confirm each color layer
    CONFIRM_LABELS = {
        "magenta_duct": {
            "labels": ["DUCT", "SA", "RA", "EA", "AHU", "FCU", "DIFF", "GRILLE", "LOUVER", "VAV", "SPD", "FD1", "FD2", "FD3", "FD4", "FD5", "FDA", "FHC", "GL2", "GL3"],
            "size_labels": [r"\d{2,4}\s*[xX]\s*\d{2,4}"],  # duct size like 600x400
            "confirmed_name": "ductwork",
        },
        "blue_pipe": {
            "labels": ["CHW", "CHILLED", "CW", "COLD WATER", "COOLING", "BRINE", "GLYCOL"],
            "size_labels": [r"DN\d{2,3}", r"\d{2,3}NB", r'\d{1,2}"'],
            "confirmed_name": "chilled_water_pipe",
        },
        "green_supply": {
            "labels": ["SA", "SUPPLY AIR", "SUPPLY", "FRESH AIR", "FA", "OUTDOOR"],
            "size_labels": [r"\d{2,4}\s*[xX]\s*\d{2,4}"],
            "confirmed_name": "supply_air_duct",
        },
        "cyan_piping": {
            "labels": ["CONDENSATE", "COND", "CD", "GAS", "N2", "NITROGEN", "COMPRESSED AIR", "CA"],
            "size_labels": [r"DN\d{2,3}", r"\d{2,3}NB", r'\d{1,2}"'],
            "confirmed_name": "condensate_pipe",
        },
        "red_fire": {
            "labels": ["FIRE", "FIRE FIGHTING", "FP", "SPRINKLER", "HYDRANT", "FIRE PUMP", "HCV", "FIRE DAMPER"],
            "size_labels": [r"DN\d{2,3}", r"\d{2,3}NB", r'\d{1,2}"'],
            "confirmed_name": "fire_fighting_pipe",
        },
        "orange_equipment": {
            "labels": ["AHU", "FCU", "PUMP", "CHILLER", "BOILER", "COOLING TOWER", "COMPRESSOR", "TANK", "HEAT EXCHANGER", "BLOWER", "FILTER"],
            "size_labels": [],
            "confirmed_name": "equipment",
        },
        "yellow_electrical": {
            "labels": ["CABLE", "WIRE", "LT", "HT", "POWER", "DB", "MCC", "PANEL", "UPS", "LIGHT", "LUMINAIRE", "OUTLET", "SOCKET"],
            "size_labels": [r"\d{1,3}\s*(?:mm2|sqmm|Sq\.?mm)", r"\d{1,3}\s*x\s*\d{1,3}\s*C"],
            "confirmed_name": "electrical_cable",
        },
    }
    
    def __init__(self, texts, drawings, max_distance=40):
        """
        Args:
            texts: list of text dicts with x, y, text
            drawings: list of drawing objects from PyMuPDF (or mock)
            max_distance: max distance in PDF points to consider text "near" a line
        """
        self.texts = texts
        self.drawings = drawings
        self.max_distance = max_distance
        self._line_cache = {}  # layer_name -> list of (x, y) line midpoints
    
    def _get_line_midpoints(self, layer_color_key):
        """Get midpoints of all lines on a specific color layer."""
        if layer_color_key in self._line_cache:
            return self._line_cache[layer_color_key]
        
        # Map layer key to color tuple
        color_map = {
            "magenta_duct": (1.0, 0.0, 1.0),
            "blue_pipe": (0.0, 0.0, 1.0),
            "green_supply": (0.0, 1.0, 0.0),
            "cyan_piping": (0.0, 1.0, 1.0),
            "red_fire": (1.0, 0.0, 0.0),
            "orange_equipment": (1.0, 0.498, 0.0),
            "yellow_electrical": (1.0, 1.0, 0.0),
        }
        
        target_color = color_map.get(layer_color_key)
        if not target_color:
            self._line_cache[layer_color_key] = []
            return []
        
        midpoints = []
        for d in self.drawings:
            dc = d.get("color")
            if dc and abs(dc[0] - target_color[0]) < 0.01 and abs(dc[1] - target_color[1]) < 0.01 and abs(dc[2] - target_color[2]) < 0.01:
                for item in d.get("items", []):
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        mx = (p1.x + p2.x) / 2
                        my = (p1.y + p2.y) / 2
                        length = ((p2.x - p1.x)**2 + (p2.y - p1.y)**2)**0.5
                        if length > 10:  # only real lines, not fragments
                            midpoints.append((mx, my, length))
        
        self._line_cache[layer_color_key] = midpoints
        return midpoints
    
    def validate_layer(self, layer_key):
        """
        Check if text labels confirm the color-based classification of a layer.
        
        Returns:
            {
                "confirmed": bool,
                "confidence": "High" | "Medium",
                "confirming_labels": [{text, x, y, distance, label_type}],
                "confirmed_name": str,
                "evidence": str,  # human-readable explanation
            }
        """
        config = self.CONFIRM_LABELS.get(layer_key)
        if not config:
            return {"confirmed": False, "confidence": "Medium", "confirming_labels": [], "evidence": "No validation config"}
        
        midpoints = self._get_line_midpoints(layer_key)
        if not midpoints:
            return {"confirmed": False, "confidence": "Medium", "confirming_labels": [], "evidence": "No lines on this layer"}
        
        confirming_labels = []
        labels_found = set()
        sizes_found = []
        
        for text in self.texts:
            text_upper = text["text"].upper().strip()
            if not text_upper or len(text_upper) > 30:
                continue
            
            tx, ty = text["x"], text["y"]
            
            # Find minimum distance to any line midpoint on this layer
            min_dist = float('inf')
            for mx, my, _ in midpoints:
                dist = ((tx - mx)**2 + (ty - my)**2)**0.5
                if dist < min_dist:
                    min_dist = dist
            
            if min_dist > self.max_distance:
                continue
            
            # Check if text matches a confirming label
            for label in config["labels"]:
                if label in text_upper:
                    if label not in labels_found:
                        labels_found.add(label)
                        confirming_labels.append({
                            "text": text["text"],
                            "x": tx, "y": ty,
                            "distance": round(min_dist, 1),
                            "label_type": "name",
                            "matched_label": label,
                        })
                    break
            
            # Check if text matches a size pattern
            for size_pattern in config["size_labels"]:
                if re.search(size_pattern, text["text"], re.IGNORECASE):
                    sizes_found.append({
                        "text": text["text"],
                        "x": tx, "y": ty,
                        "distance": round(min_dist, 1),
                        "label_type": "size",
                    })
                    break
        
        # Determine confirmation
        has_name = len(labels_found) > 0
        has_size = len(sizes_found) > 0
        
        if has_name and has_size:
            confidence = "High"
            evidence = f"Confirmed by {len(labels_found)} label(s) ({', '.join(list(labels_found)[:3])}) and {len(sizes_found)} size annotation(s)"
        elif has_name:
            confidence = "High"
            evidence = f"Confirmed by {len(labels_found)} label(s): {', '.join(list(labels_found)[:3])}"
        elif has_size:
            confidence = "Medium"  # size only, no name — better than nothing but not fully confirmed
            evidence = f"Size annotations found ({len(sizes_found)}) but no name labels"
        else:
            confidence = "Medium"
            evidence = "No confirming text labels found near lines — classification based on color only"
        
        return {
            "confirmed": has_name,
            "confidence": confidence,
            "confirming_labels": confirming_labels,
            "size_labels": sizes_found,
            "confirmed_name": config["confirmed_name"] if has_name else None,
            "evidence": evidence,
        }
    
    def validate_all(self, layer_keys=None):
        """Validate all configured layers."""
        if layer_keys is None:
            layer_keys = list(self.CONFIRM_LABELS.keys())
        
        results = {}
        for key in layer_keys:
            results[key] = self.validate_layer(key)
        
        return results
    
    def get_confidence_for_measurement(self, measurement_key, layer_key):
        """
        Get the confidence level for a specific measurement.
        
        Args:
            measurement_key: e.g. "duct_length_rmt", "blue_pipe_single_rmt"
            layer_key: e.g. "magenta_duct", "blue_pipe"
        
        Returns:
            "High" if text-confirmed, "Medium" if color-only, "Low" if inferred
        """
        validation = self.validate_layer(layer_key)
        return validation["confidence"]
    
    def get_sizes_for_layer(self, layer_key):
        """Get detected size labels near a layer's lines."""
        validation = self.validate_layer(layer_key)
        return validation.get("size_labels", [])
    
    def get_confirmed_name(self, layer_key):
        """Get the text-confirmed name for a layer, or None."""
        validation = self.validate_layer(layer_key)
        return validation.get("confirmed_name")