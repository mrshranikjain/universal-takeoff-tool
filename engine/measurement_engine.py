"""Measurement Engine - calculates lengths, areas, and counts from vector data
Uses ProximityValidator to upgrade confidence when text labels confirm color classification."""
from engine.proximity_validator import ProximityValidator

PT_TO_MM_PAPER = 420.1 / 1191.0


class MeasurementEngine:
    def __init__(self, layers, scale, config, disc_config, drawings=None, texts=None):
        self.layers = layers
        self.scale = scale
        self.config = config
        self.disc_config = disc_config
        self.pt_to_m = PT_TO_MM_PAPER * scale / 1000
        self._drawings = drawings or []
        self._texts = texts or []
        self._validator = None
        
        if texts and drawings:
            self._validator = ProximityValidator(texts, drawings)
    
    def _get_confidence(self, layer_key, default="Medium"):
        """Get confidence level for a layer — High if text-confirmed, else default."""
        if self._validator:
            conf = self._validator.get_confidence_for_measurement(None, layer_key)
            return conf
        return default
    
    def calculate(self):
        """Calculate all measurements based on discipline config."""
        measurements = {}
        disc = self.disc_config
        meas_config = disc.get("measurements", {})
        
        # Ductwork measurements (HVAC) — use filtered long lines only
        if "magenta_duct" in self.layers or "ductwork" in self.layers:
            layer = self.layers.get("magenta_duct", self.layers.get("ductwork", {}))
            duct_len = layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m
            duct_conf = self._get_confidence("magenta_duct")
            measurements["duct_length_rmt"] = {"value": round(duct_len, 1), "unit": "RMT", "confidence": duct_conf}
            measurements["duct_filled_symbols"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": "Low"}
            
            # Only generate SM area for DETECTED sizes
            detected_sizes = self._detect_duct_sizes()
            sm_conf = "High" if duct_conf == "High" and len(self._validator.get_sizes_for_layer("magenta_duct") if self._validator else []) > 0 else "Medium"
            for size_info in detected_sizes:
                area = duct_len * size_info["perimeter_m"]
                measurements[f"duct_sm_{size_info['size']}"] = {"value": round(area, 1), "unit": "SQMT", "confidence": sm_conf}
        
        # Pipe measurements (CHW, plumbing, fire) — use filtered long lines
        pipe_layers = ["blue_pipe", "blue_chw_pipe", "cold_water", "hot_water", 
                       "soil_waste", "fire_pipe", "process_pipe"]
        for layer_name in pipe_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                pipe_len = layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m
                key_prefix = layer_name.replace("_pipe", "").replace("_", "")
                pipe_conf = self._get_confidence(layer_name)
                
                measurements[f"{key_prefix}_pipe_single_rmt"] = {"value": round(pipe_len, 1), "unit": "RMT", "confidence": pipe_conf}
                
                multiplier = meas_config.get("pipe_multiplier", 1)
                if multiplier > 1:
                    measurements[f"{key_prefix}_pipe_total_rmt"] = {"value": round(pipe_len * multiplier, 1), "unit": "RMT", "confidence": pipe_conf}
                
                measurements[f"{key_prefix}_filled_segments"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": "Low"}
        
        # Supply air (green) — use filtered
        green_layers = ["green_supply", "green_supply_air", "supply_air"]
        for layer_name in green_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                sa_conf = self._get_confidence("green_supply")
                measurements["supply_air_rmt"] = {"value": round(layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m, 1), "unit": "RMT", "confidence": sa_conf}
                measurements["supply_air_symbols"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": "Low"}
                break
        
        # HVAC piping (cyan) — use filtered
        cyan_layers = ["cyan_piping", "cyan_hvac_piping", "condensate", "gas_pipe"]
        for layer_name in cyan_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                cy_conf = self._get_confidence("cyan_piping")
                measurements["hvac_piping_rmt"] = {"value": round(layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m, 1), "unit": "RMT", "confidence": cy_conf}
                measurements["hvac_piping_symbols"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": "Low"}
                break
        
        # Fire protection (red) — use filtered
        if "red_fire" in self.layers:
            layer = self.layers["red_fire"]
            fr_conf = self._get_confidence("red_fire")
            measurements["fire_pipe_rmt"] = {"value": round(layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m, 1), "unit": "RMT", "confidence": fr_conf}
            measurements["fire_filled_symbols"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": "Low"}
        
        # Equipment (orange) — use filtered
        if "orange_equipment" in self.layers:
            layer = self.layers["orange_equipment"]
            eq_conf = self._get_confidence("orange_equipment")
            measurements["equipment_symbols"] = {"value": layer.get("filled", 0), "unit": "No", "confidence": eq_conf}
            measurements["equipment_line_rmt"] = {"value": round(layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m, 1), "unit": "RMT", "confidence": eq_conf}
        
        # Electrical (yellow) — use filtered
        if "yellow_electrical" in self.layers:
            layer = self.layers["yellow_electrical"]
            el_conf = self._get_confidence("yellow_electrical")
            measurements["cable_rmt"] = {"value": round(layer.get("long_line_length_pts", layer.get("line_length_pts", 0)) * self.pt_to_m, 1), "unit": "RMT", "confidence": el_conf}
        
        # NOTE: architectural_paths and structural_paths are REMOVED from output
        # They are raw path counts, not real BOQ quantities
        
        return measurements
    
    def get_confidence_map(self):
        """Return {measurement_key: confidence_level} for all measurements."""
        measurements = self.calculate()
        conf_map = {}
        flat = {}
        for key, data in measurements.items():
            if isinstance(data, dict) and "value" in data:
                flat[key] = data["value"]
                conf_map[key] = data.get("confidence", "Medium")
            else:
                flat[key] = data
                conf_map[key] = "Medium"
        return flat, conf_map
    
    def _detect_duct_sizes(self):
        """Detect actual duct sizes from parallel line pairs in magenta layer."""
        # Look for widths in the layers data
        # Group magenta vertical lines by x-coordinate to find parallel pairs
        from collections import defaultdict
        
        magenta_color = (1.0, 0.0, 1.0)
        x_groups = defaultdict(list)
        
        for d in getattr(self, '_drawings', []):
            if d.get("color") == magenta_color:
                for item in d.get("items", []):
                    if item[0] == "l":
                        p1, p2 = item[1], item[2]
                        if abs(p2.x - p1.x) < 1:  # vertical line
                            x_groups[round(p1.x)].append(1)
        
        x_vals = sorted(x_groups.keys())
        widths_mm = []
        pt_to_mm = 420.1 / 1191.0
        
        for i, x1 in enumerate(x_vals):
            for x2 in x_vals[i+1:]:
                spacing = x2 - x1
                if spacing > 10:  # skip too-close pairs
                    break
                if 1 <= spacing <= 15 and len(x_groups[x1]) >  2 and len(x_groups[x2]) > 2:
                    width_mm = spacing * pt_to_mm * self.scale
                    widths_mm.append(width_mm)
        
        if not widths_mm:
            # Fallback: return single default size
            return [{"size": "detected", "perimeter_m": 1.2}]  # default 300x300
        
        # Match detected widths to standard sizes
        standard_sizes = self.config.get("standard_duct_sizes", [])
        detected = []
        avg_width = sum(widths_mm) / len(widths_mm)
        
        for std in standard_sizes:
            # Check if any detected width is close to this standard size
            std_width = std["width_mm"]
            if any(abs(w - std_width) / std_width < 0.2 for w in widths_mm):
                detected.append(std)
        
        if not detected:
            # Use the average detected width to estimate a size
            for std in standard_sizes:
                if abs(avg_width - std["width_mm"]) / std["width_mm"] < 0.3:
                    detected.append(std)
                    break
            if not detected:
                detected = [{"size": f"{int(avg_width)}x{int(avg_width)}", "perimeter_m": 4 * avg_width / 1000}]
        
        return detected