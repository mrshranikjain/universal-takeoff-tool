"""
Rate Database — CPWD/MES Indian construction rate database.
Loads rates from JSON and provides pricing lookup.
"""
import json
from pathlib import Path


class RateDatabase:
    """Load and query construction rate databases."""
    
    def __init__(self, config_path):
        self.path = Path(config_path)
        with open(self.path) as f:
            self.data = json.load(f)
    
    def list_rate_books(self):
        """Return available rate books."""
        return {
            key: {"name": val["name"], "currency": val["currency"]}
            for key, val in self.data.items()
        }
    
    def get_rate(self, discipline, item_key, rate_book="cpwd_2024"):
        """Get rate for a specific item."""
        book = self.data.get(rate_book)
        if not book:
            return None
        
        rates = book.get("rates", {}).get(discipline, {})
        rate_info = rates.get(item_key)
        if not rate_info:
            return None
        
        return {
            "rate": rate_info["rate"],
            "unit": rate_info["unit"],
            "description": rate_info.get("description", ""),
        }
    
    def estimate_item(self, discipline, item_key, quantity, rate_book="cpwd_2024"):
        """Estimate a single line item."""
        rate_info = self.get_rate(discipline, item_key, rate_book)
        if not rate_info:
            return None
        
        total = rate_info["rate"] * quantity
        return {
            "discipline": discipline,
            "key": item_key,
            "description": rate_info["description"],
            "quantity": quantity,
            "unit": rate_info["unit"],
            "rate": rate_info["rate"],
            "amount": round(total, 2),
        }
    
    def estimate_boq(self, boq_items, rate_book="cpwd_2024"):
        """Estimate a full BOQ from list of items."""
        book = self.data.get(rate_book, {})
        currency = book.get("currency", "INR")
        
        line_items = []
        discipline_totals = {}
        grand_total = 0
        
        for item in boq_items:
            est = self.estimate_item(item["discipline"], item["key"], item["quantity"], rate_book)
            if est:
                est["sno"] = len(line_items) + 1
                line_items.append(est)
                disc = item["discipline"].title()
                discipline_totals[disc] = discipline_totals.get(disc, 0) + est["amount"]
                grand_total += est["amount"]
        
        contingency = round(grand_total * 0.03, 2)
        
        return {
            "rate_book": book.get("name", rate_book),
            "currency": currency,
            "line_items": line_items,
            "discipline_totals": discipline_totals,
            "grand_total": round(grand_total, 2),
            "contingency_3pct": contingency,
            "total_with_contingency": round(grand_total + contingency, 2),
        }