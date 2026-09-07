"""
Cost Estimation Engine — links takeoff quantities to rate database.
Maps extracted components and measurements to priced BOQ line items.
"""
from engine.rate_database import RateDatabase


# Mapping: takeoff component tags → rate database keys
TAG_TO_RATE = {
    # HVAC
    "AHU": ("hvac", "ahu"),
    "FD": ("hvac", "fire_damper"),
    "FD1": ("hvac", "fire_damper"),
    "FD2": ("hvac", "fire_damper"),
    "FD3": ("hvac", "fire_damper"),
    "FD4": ("hvac", "fire_damper"),
    "FD5": ("hvac", "fire_damper"),
    "FDA": ("hvac", "fire_damper"),
    "FHC": ("hvac", "fire_damper"),
    "SPD": ("hvac", "fire_damper"),
    "GL2": ("hvac", "grille"),
    "GL3": ("hvac", "grille"),
    "SA": ("hvac", "diffuser"),
    "RA": ("hvac", "grille"),
    "EA": ("hvac", "grille"),
    "VAV": ("hvac", "diffuser"),
    "FCU": ("hvac", "ahu"),
    # Plumbing
    "WC": ("plumbing", "wc"),
    "WB": ("plumbing", "wb"),
    "SH": ("plumbing", "wb"),
    "CH": ("plumbing", "wb"),
    "CW": ("plumbing", "cw_pipe"),
    "HW": ("plumbing", "cw_pipe"),
    "ST": ("plumbing", "soil_pipe"),
    "VP": ("plumbing", "soil_pipe"),
    # Electrical
    "DB": ("electrical", "db"),
    "LT": ("electrical", "lt_fixture"),
    "MCC": ("electrical", "db"),
    "UPS": ("electrical", "db"),
    # Fire
    "SPK": ("fire_protection", "sprinkler"),
    "FP": ("fire_protection", "fire_pump"),
    "SI": ("fire_protection", "sprinkler"),
    "HD": ("fire_protection", "sprinkler"),
    # P&ID
    "gate_valve": ("pid", "gate_valve"),
    "control_valve": ("pid", "control_valve"),
    "safety_relief_valve": ("pid", "psv"),
}

# Mapping: measurement keys → rate database keys
MEASUREMENT_TO_RATE = {
    "duct_length_rmt": ("hvac", "duct_sm", "SQMT", 1.2),  # RMT → SQMT with avg perimeter
    "bluepipe_total_rmt": ("hvac", "chw_pipe", "RMT", 1),
    "bluepipe_single_rmt": ("hvac", "chw_pipe", "RMT", 1),
    "supply_air_rmt": ("hvac", "duct_sm", "SQMT", 0.8),
    "hvac_piping_rmt": ("hvac", "chw_pipe", "RMT", 1),
    "fire_pipe_rmt": ("fire_protection", "fire_pipe", "RMT", 1),
    "cable_rmt": ("electrical", "cable", "RMT", 1),
}


class CostEstimator:
    """Estimate costs from takeoff results using rate database."""
    
    def __init__(self, rate_database):
        self.rate_db = rate_database
    
    def estimate_from_results(self, takeoff_results, rate_book="cpwd_2024"):
        """Generate priced BOQ from takeoff engine results."""
        boq_items = []
        
        for page_result in takeoff_results:
            components = page_result.get("components", {})
            measurements = page_result.get("measurements", {})
            
            # Components → BOQ items
            for tag, data in components.items():
                if tag in ("room_dimensions", "rooms"):
                    continue
                
                if isinstance(data, dict):
                    if "count" in data:
                        count = data["count"]
                        rate_key = TAG_TO_RATE.get(tag) or TAG_TO_RATE.get(tag.upper())
                        if rate_key:
                            boq_items.append({
                                "discipline": rate_key[0],
                                "key": rate_key[1],
                                "quantity": count,
                            })
                    elif data.get("locations"):
                        count = len(data["locations"])
                        rate_key = TAG_TO_RATE.get(tag) or TAG_TO_RATE.get(tag.upper())
                        if rate_key:
                            boq_items.append({
                                "discipline": rate_key[0],
                                "key": rate_key[1],
                                "quantity": count,
                            })
                    else:
                        # Variants
                        for variant, count in data.items():
                            if isinstance(count, int) and count > 0:
                                rate_key = TAG_TO_RATE.get(variant) or TAG_TO_RATE.get(tag)
                                if rate_key:
                                    boq_items.append({
                                        "discipline": rate_key[0],
                                        "key": rate_key[1],
                                        "quantity": count,
                                    })
            
            # Measurements → BOQ items
            for key, val in measurements.items():
                if not isinstance(val, (int, float)) or val == 0:
                    continue
                
                rate_map = MEASUREMENT_TO_RATE.get(key)
                if rate_map:
                    disc, rate_key, expected_unit, multiplier = rate_map
                    # Convert quantity if needed
                    qty = val * multiplier
                    boq_items.append({
                        "discipline": disc,
                        "key": rate_key,
                        "quantity": round(qty, 2),
                    })
        
        # Aggregate same items
        aggregated = {}
        for item in boq_items:
            key = f"{item['discipline']}_{item['key']}"
            if key in aggregated:
                aggregated[key]["quantity"] += item["quantity"]
            else:
                aggregated[key] = item.copy()
        
        return self.rate_db.estimate_boq(list(aggregated.values()), rate_book)