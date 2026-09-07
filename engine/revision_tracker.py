"""
Revision Tracker — compares two takeoff result sets and finds quantity deltas.
"""


class RevisionTracker:
    """Compare two takeoff runs and identify changes."""
    
    def __init__(self):
        pass
    
    def compare(self, old_results, new_results):
        """Compare old and new takeoff results."""
        old_items = self._flatten_results(old_results)
        new_items = self._flatten_results(new_results)
        
        old_keys = set(old_items.keys())
        new_keys = set(new_items.keys())
        
        added = []
        removed = []
        changed = []
        unchanged = []
        
        # Added: in new but not old
        for key in new_keys - old_keys:
            item = new_items[key]
            added.append({
                "tag": item["tag"],
                "description": item["description"],
                "qty": item["qty"],
                "unit": item["unit"],
            })
        
        # Removed: in old but not new
        for key in old_keys - new_keys:
            item = old_items[key]
            removed.append({
                "tag": item["tag"],
                "description": item["description"],
                "qty": item["qty"],
                "unit": item["unit"],
            })
        
        # Changed or unchanged: in both
        for key in old_keys & new_keys:
            old_item = old_items[key]
            new_item = new_items[key]
            
            if old_item["qty"] != new_item["qty"]:
                delta = new_item["qty"] - old_item["qty"]
                pct = round((delta / old_item["qty"]) * 100, 1) if old_item["qty"] != 0 else float('inf')
                changed.append({
                    "tag": new_item["tag"],
                    "description": new_item["description"],
                    "old_qty": old_item["qty"],
                    "new_qty": new_item["qty"],
                    "delta": round(delta, 2),
                    "unit": new_item["unit"],
                    "pct_change": pct,
                })
            else:
                unchanged.append({
                    "tag": new_item["tag"],
                    "description": new_item["description"],
                    "qty": new_item["qty"],
                    "unit": new_item["unit"],
                })
        
        return {
            "added": sorted(added, key=lambda x: -x["qty"]),
            "removed": sorted(removed, key=lambda x: -x["qty"]),
            "changed": sorted(changed, key=lambda x: -abs(x["delta"])),
            "unchanged": sorted(unchanged, key=lambda x: x["tag"]),
            "summary": {
                "total_added": len(added),
                "total_removed": len(removed),
                "total_changed": len(changed),
                "total_unchanged": len(unchanged),
            },
        }
    
    def _flatten_results(self, results):
        """Flatten takeoff results into {key: {tag, description, qty, unit}} dict."""
        items = {}
        
        if isinstance(results, dict) and "results" in results:
            results = results["results"]
        
        for page in results:
            components = page.get("components", {})
            measurements = page.get("measurements", {})
            
            # Components
            for tag, data in components.items():
                if tag in ("room_dimensions", "rooms"):
                    continue
                
                if isinstance(data, dict):
                    if "count" in data:
                        qty = data["count"]
                        unit = data.get("unit", "No")
                        desc = data.get("type", tag)
                        key = f"comp_{tag}"
                        if key in items:
                            items[key]["qty"] += qty
                        else:
                            items[key] = {"tag": tag, "description": desc, "qty": qty, "unit": unit}
                    elif data.get("locations"):
                        qty = len(data["locations"])
                        unit = data.get("unit", "No")
                        desc = data.get("type", tag)
                        key = f"comp_{tag}"
                        if key in items:
                            items[key]["qty"] += qty
                        else:
                            items[key] = {"tag": tag, "description": desc, "qty": qty, "unit": unit}
                    else:
                        for variant, count in data.items():
                            if isinstance(count, int) and count > 0:
                                key = f"comp_{tag}_{variant}"
                                items[key] = {
                                    "tag": variant,
                                    "description": f"{tag} variant {variant}",
                                    "qty": count,
                                    "unit": "No",
                                }
            
            # Measurements
            for key, val in measurements.items():
                if isinstance(val, (int, float)) and val != 0:
                    unit = "RMT"
                    if "sqmt" in key or "sm_" in key:
                        unit = "SQMT"
                    elif "symbols" in key or "paths" in key or "filled" in key:
                        unit = "No"
                    
                    mkey = f"meas_{key}"
                    if mkey in items:
                        items[mkey]["qty"] += val
                    else:
                        items[mkey] = {
                            "tag": key,
                            "description": key.replace("_", " ").title(),
                            "qty": round(val, 2),
                            "unit": unit,
                        }
        
        return items