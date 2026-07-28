"""VL Verifier - secondary visual detection using VL model API"""
import base64
import requests
import fitz
import os
import time
import tempfile


class VLVerifier:
    def __init__(self, vl_config):
        self.api_url = vl_config.get("api_url", "")
        self.tenant_id = vl_config.get("tenant_id", "")
        self.model = vl_config.get("model", "Qwen/Qwen3-VL-8B-Instruct")
        self.max_image_kb = vl_config.get("max_image_kb", 50)
        self.max_tokens = vl_config.get("max_tokens", 500)
        self.timeout = vl_config.get("timeout_seconds", 85)
        self.sleep = vl_config.get("sleep_between_calls", 3)
    
    def verify_unlabeled(self, page, max_crops=4):
        """Check for unlabeled symbols (diffusers, VAVs, valves) that text extraction misses."""
        if not self.api_url:
            return [{"crop": "none", "result": "VL model not configured"}]
        
        results = []
        rect = page.rect
        w, h = rect.width, rect.height
        
        # Create 6 crops (3x2 grid)
        crops = [
            ("c1", fitz.Rect(0, 0, w/3, h/2)),
            ("c2", fitz.Rect(w/3, 0, 2*w/3, h/2)),
            ("c3", fitz.Rect(2*w/3, 0, w, h/2)),
            ("c4", fitz.Rect(0, h/2, w/3, h)),
            ("c5", fitz.Rect(w/3, h/2, 2*w/3, h)),
            ("c6", fitz.Rect(2*w/3, h/2, w, h)),
        ]
        
        prompt = ("Look ONLY for unlabeled HVAC/mechanical symbols in this drawing section: "
                  "1) Small square/rectangular symbols on duct lines (diffusers) - count "
                  "2) Circular symbols (round diffusers) - count "
                  "3) Any VAV box symbols - count "
                  "4) Any valve symbols - count. Just give counts.")
        
        for name, clip in crops[:max_crops]:
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2.5, 2.5), clip=clip)
                
                # Save to temp file, optimize size
                tmp_path = os.path.join(tempfile.gettempdir(), f"vl_{name}.jpg")
                quality = 35
                pix.pil_save(tmp_path, quality=quality)
                
                size = os.path.getsize(tmp_path)
                if size > self.max_image_kb * 1024:
                    pix.pil_save(tmp_path, quality=20)
                    size = os.path.getsize(tmp_path)
                
                if size > self.max_image_kb * 1024:
                    results.append({"crop": name, "result": "Image too large, skipped"})
                    continue
                
                with open(tmp_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                    ]}],
                    "max_tokens": self.max_tokens,
                    "temperature": 0
                }
                
                resp = requests.post(self.api_url, json=payload,
                    headers={"Content-Type": "application/json", "x-tenant-id": self.tenant_id},
                    timeout=self.timeout)
                
                if resp.status_code == 200:
                    data = resp.json()
                    text = data['choices'][0]['message']['content']
                    results.append({"crop": name, "size_kb": size // 1024, "result": text})
                else:
                    results.append({"crop": name, "size_kb": size // 1024, "result": f"Error {resp.status_code}"})
                
                os.remove(tmp_path)
            except Exception as e:
                results.append({"crop": name, "result": f"Error: {e}"})
            
            time.sleep(self.sleep)
        
        return results