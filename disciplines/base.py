"""Discipline Router - auto-detects drawing discipline from text content"""
import re


class DisciplineRouter:
    def __init__(self, discipline_configs):
        self.configs = discipline_configs
    
    def detect(self, texts):
        """Auto-detect discipline from text annotations.
        
        Returns discipline key (e.g., 'hvac', 'plumbing') or None.
        """
        # Combine all text into one string for keyword matching
        all_text = " ".join(t["text"].upper() for t in texts)
        
        scores = {}
        for disc_key, disc_config in self.configs.items():
            keywords = disc_config.get("title_keywords", [])
            score = 0
            for kw in keywords:
                if kw in all_text:
                    score += 1
            
            # Also check tag patterns
            tag_patterns = disc_config.get("tag_patterns", {})
            for tag_name, tag_info in tag_patterns.items():
                regex = tag_info.get("regex", "")
                variants = tag_info.get("variants", [])
                if variants:
                    for v in variants:
                        if v in all_text:
                            score += 2
                elif regex:
                    try:
                        if re.search(regex, all_text):
                            score += 1
                    except re.error:
                        pass
            
            if score > 0:
                scores[disc_key] = score
        
        if not scores:
            return None
        
        # Return highest scoring discipline
        best = max(scores, key=scores.get)
        return best if scores[best] >= 2 else None