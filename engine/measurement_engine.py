"""Measurement Engine - calculates lengths, areas, and counts from vector data"""
PT_TO_MM_PAPER = 420.1 / 1191.0


class MeasurementEngine:
    def __init__(self, layers, scale, config, disc_config):
        self.layers = layers
        self.scale = scale
        self.config = config
        self.disc_config = disc_config
        self.pt_to_m = PT_TO_MM_PAPER * scale / 1000
    
    def calculate(self):
        """Calculate all measurements based on discipline config."""
        measurements = {}
        disc = self.disc_config
        meas_config = disc.get("measurements", {})
        
        # Ductwork measurements (HVAC)
        if "magenta_duct" in self.layers or "ductwork" in self.layers:
            layer = self.layers.get("magenta_duct", self.layers.get("ductwork", {}))
            duct_len = layer.get("line_length_pts", 0) * self.pt_to_m
            measurements["duct_length_rmt"] = round(duct_len, 1)
            measurements["duct_filled_symbols"] = layer.get("filled", 0)
            
            # Sheet metal area scenarios
            for std in self.config.get("standard_duct_sizes", []):
                area = duct_len * std["perimeter_m"]
                measurements[f"duct_sm_{std['size']}"] = round(area, 1)
        
        # Pipe measurements (CHW, plumbing, fire)
        pipe_layers = ["blue_pipe", "blue_chw_pipe", "cold_water", "hot_water", 
                       "soil_waste", "fire_pipe", "process_pipe"]
        for layer_name in pipe_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                pipe_len = layer.get("line_length_pts", 0) * self.pt_to_m
                key_prefix = layer_name.replace("_pipe", "").replace("_", "")
                
                measurements[f"{key_prefix}_pipe_single_rmt"] = round(pipe_len, 1)
                
                # Apply supply+return multiplier if configured
                multiplier = meas_config.get("pipe_multiplier", 1)
                if multiplier > 1:
                    measurements[f"{key_prefix}_pipe_total_rmt"] = round(pipe_len * multiplier, 1)
                
                measurements[f"{key_prefix}_filled_segments"] = layer.get("filled", 0)
        
        # Supply air (green)
        green_layers = ["green_supply", "green_supply_air", "supply_air"]
        for layer_name in green_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                measurements["supply_air_rmt"] = round(
                    layer.get("line_length_pts", 0) * self.pt_to_m, 1)
                measurements["supply_air_symbols"] = layer.get("filled", 0)
                break
        
        # HVAC piping (cyan)
        cyan_layers = ["cyan_piping", "cyan_hvac_piping", "condensate", "gas_pipe"]
        for layer_name in cyan_layers:
            if layer_name in self.layers:
                layer = self.layers[layer_name]
                measurements["hvac_piping_rmt"] = round(
                    layer.get("line_length_pts", 0) * self.pt_to_m, 1)
                measurements["hvac_piping_symbols"] = layer.get("filled", 0)
                break
        
        # Fire protection (red)
        if "red_fire" in self.layers:
            layer = self.layers["red_fire"]
            measurements["fire_pipe_rmt"] = round(
                layer.get("line_length_pts", 0) * self.pt_to_m, 1)
            measurements["fire_filled_symbols"] = layer.get("filled", 0)
        
        # Equipment (orange)
        if "orange_equipment" in self.layers:
            layer = self.layers["orange_equipment"]
            measurements["equipment_symbols"] = layer.get("filled", 0)
            measurements["equipment_line_rmt"] = round(
                layer.get("line_length_pts", 0) * self.pt_to_m, 1)
        
        # Electrical (yellow)
        if "yellow_electrical" in self.layers:
            layer = self.layers["yellow_electrical"]
            measurements["cable_rmt"] = round(
                layer.get("line_length_pts", 0) * self.pt_to_m, 1)
        
        # Building dimensions
        if "gray_architectural" in self.layers:
            measurements["architectural_paths"] = self.layers["gray_architectural"]["paths"]
        
        if "black_structural" in self.layers:
            measurements["structural_paths"] = self.layers["black_structural"]["paths"]
        
        return measurements