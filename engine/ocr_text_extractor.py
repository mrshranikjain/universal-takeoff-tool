"""
OCR Text Extractor — for PDFs where text is rendered as vector outlines (ZWCAD, scanned drawings).
Uses Tesseract OCR via pytesseract to extract text from rendered page images.
"""
import fitz
import pytesseract
from PIL import Image
import io
import re


class OCRTextExtractor:
    """Extract text from PDFs where PyMuPDF can't find text objects."""
    
    def __init__(self, page, render_scale=3.0):
        """
        Args:
            page: fitz.Page object
            render_scale: resolution multiplier (higher = better OCR, slower)
        """
        self.page = page
        self.render_scale = render_scale
        self._image = None
        self._texts = None
    
    def _render_image(self):
        """Render the page to a PIL Image at high resolution."""
        if self._image is not None:
            return self._image
        
        pix = self.page.get_pixmap(matrix=fitz.Matrix(self.render_scale, self.render_scale))
        img_data = pix.tobytes('png')
        self._image = Image.open(io.BytesIO(img_data))
        return self._image
    
    def extract(self, psm_mode=11):
        """
        Extract all text with coordinates using OCR.
        
        Args:
            psm_mode: Tesseract page segmentation mode
                3 = full page (default)
                6 = uniform block of text
                11 = sparse text (best for engineering drawings)
                12 = sparse text with OSD
        
        Returns:
            List of text dicts compatible with TextExtractor format:
            [{text, x, y, x1, y1, size, color, r, g, b, font, conf}]
        """
        if self._texts is not None:
            return self._texts
        
        img = self._render_image()
        
        # Run OCR with bounding box data
        config = f'--psm {psm_mode}'
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=config)
        
        texts = []
        for i in range(len(data['text'])):
            text = data['text'][i].strip()
            if not text or text == '':
                continue
            
            # OCR post-processing corrections (common misreads in engineering drawings)
            text = self._correct_ocr_text(text)
            if not text:
                continue
            
            # Convert pixel coords back to PDF points
            scale = self.render_scale
            x = int(data['left'][i]) / scale
            y = int(data['top'][i]) / scale
            w = int(data['width'][i]) / scale
            h = int(data['height'][i]) / scale
            conf = int(data['conf'][i]) if str(data['conf'][i]).lstrip('-').isdigit() else 0
            
            # Skip very low confidence items (likely noise)
            if conf < 10:
                continue
            
            # Try to get text color from the image at the text location
            r, g, b = self._get_pixel_color(int(data['left'][i] + data['width'][i] / 2),
                                             int(data['top'][i] + data['height'][i] / 2))
            
            texts.append({
                'text': text,
                'x': round(x, 1),
                'y': round(y, 1),
                'x1': round(x + w, 1),
                'y1': round(y + h, 1),
                'size': round(h, 2),
                'color': (r << 16) | (g << 8) | b,
                'r': r, 'g': g, 'b': b,
                'font': 'OCR',
                'conf': conf,
            })
        
        self._texts = texts
        return texts
    
    def _correct_ocr_text(self, text):
        """Apply common OCR corrections for engineering drawings."""
        import re
        
        # Common OCR misreads in engineering drawings
        corrections = [
            # Pipe size misreads: B0NB → 80NB, BONE → 80NB, 'B0NB → 80NB
            (r"['`]?B0?NB", '80NB', re.IGNORECASE),
            (r"BONE\b", '80NB', re.IGNORECASE),
            # B followed by digits + NB → digit + NB (B8 → 8, B6 → 6)
            (r'\bB(\d{2})NB\b', r'\1NB', re.IGNORECASE),
            # Remove sequences of zeros (OCR noise from line patterns)
            (r'\b0{5,}\b', '', 0),
            (r'0{4,}o+', '', re.IGNORECASE),
            # Fix common character confusion in pipe materials
            (r'\buPVC\.?\b', 'uPVC', re.IGNORECASE),
            (r'\bUPVC\.?\b', 'uPVC', re.IGNORECASE),
            # Fix valve/instrument tag misreads
            (r"['`](\w+)", r'\1', 0),  # Remove leading quote/apostrophe
            # Clean up dashes and underscores noise
            (r'^[_-]{2,}$', '', 0),
            (r'^[|]{2,}$', '', 0),
            # Fix 'FT' → 'FT' (often a fragment)
            (r'\bFT\b', 'FT', 0),
        ]
        
        result = text
        for pattern, replacement, flags in corrections:
            result = re.sub(pattern, replacement, result, flags=flags)
        
        return result.strip() if result.strip() else None
    
    def _get_pixel_color(self, px, py):
        """Get the average color of text pixels at a location."""
        img = self._render_image()
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Sample a small region around the point
        try:
            # Get the darkest pixel in a 3x3 region (text is usually darker than background)
            min_brightness = 255
            darkest = (0, 0, 0)
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    x, y = px + dx, py + dy
                    if 0 <= x < img.width and 0 <= y < img.height:
                        pixel = img.getpixel((x, y))
                        brightness = sum(pixel[:3]) / 3
                        if brightness < min_brightness:
                            min_brightness = brightness
                            darkest = pixel[:3]
            return darkest
        except Exception:
            return (0, 0, 0)
    
    def extract_high_confidence(self, min_conf=50):
        """Return only high-confidence OCR results."""
        texts = self.extract()
        return [t for t in texts if t.get('conf', 0) >= min_conf]
    
    def extract_with_patterns(self, patterns, min_conf=30):
        """
        Extract text matching specific regex patterns.
        Useful for P&ID tag extraction where OCR confidence may be low.
        """
        texts = self.extract()
        results = []
        
        for t in texts:
            if t.get('conf', 0) < min_conf:
                continue
            for pattern, label in patterns:
                if re.search(pattern, t['text'], re.IGNORECASE):
                    t['pattern_match'] = label
                    results.append(t)
                    break
        
        return results
    
    def detect_drawing_type(self):
        """Detect the type of drawing from OCR text."""
        texts = self.extract()
        all_text = ' '.join(t['text'].upper() for t in texts)
        
        types = {
            'pid': ['P&I', 'P&ID', 'PIPING AND INSTRUMENTATION', 'PFD', 'PROCESS FLOW'],
            'hvac': ['HVAC', 'AIR CONDITIONING', 'VENTILATION', 'AHU', 'DUCT'],
            'plumbing': ['PLUMBING', 'WATER SUPPLY', 'DRAINAGE', 'SANITARY'],
            'electrical': ['ELECTRICAL', 'POWER', 'LIGHTING', 'CABLE', 'SINGLE LINE'],
            'fire': ['FIRE', 'FIRE FIGHTING', 'SPRINKLER', 'FIRE ALARM'],
            'structural': ['STRUCTURAL', 'STEEL', 'CONCRETE', 'FOUNDATION'],
            'civil': ['ARCHITECTURAL', 'FLOOR PLAN', 'LAYOUT', 'GENERAL ARRANGEMENT'],
            'iso': ['ISOMETRIC', 'ISO'],
        }
        
        scores = {}
        for dtype, keywords in types.items():
            score = sum(1 for kw in keywords if kw in all_text)
            if score > 0:
                scores[dtype] = score
        
        if not scores:
            return None, 0
        
        best = max(scores, key=scores.get)
        return best, scores[best]


class HybridTextExtractor:
    """
    Try PyMuPDF text extraction first. If no text found, fall back to OCR.
    This handles both normal PDFs (with text objects) and ZWCAD/scanned PDFs.
    """
    
    def __init__(self, page, render_scale=3.0):
        self.page = page
        self.render_scale = render_scale
        self._mode = None  # 'pdf' or 'ocr'
        self._texts = None
    
    def extract(self):
        """Extract text using PyMuPDF first, OCR as fallback."""
        if self._texts is not None:
            return self._texts
        
        # Try PyMuPDF first
        from engine.text_extractor import TextExtractor
        pdf_extractor = TextExtractor(self.page)
        texts = pdf_extractor.extract()
        
        if len(texts) > 5:
            # PyMuPDF found enough text — use it
            self._mode = 'pdf'
            self._texts = texts
            return texts
        
        # Not enough text — use OCR
        self._mode = 'ocr'
        ocr_extractor = OCRTextExtractor(self.page, self.render_scale)
        texts = ocr_extractor.extract()
        
        # Add conf field to PDF texts for consistency (if any)
        for t in texts:
            if 'conf' not in t:
                t['conf'] = 90 if self._mode == 'pdf' else 50
        
        self._texts = texts
        return texts
    
    @property
    def extraction_mode(self):
        """Return how text was extracted: 'pdf' or 'ocr'."""
        if self._mode is None:
            self.extract()
        return self._mode
    
    def extract_components(self, disc_config):
        """Extract components using the appropriate method."""
        texts = self.extract()
        
        if self._mode == 'pdf':
            # Use normal TextExtractor
            from engine.text_extractor import TextExtractor
            return TextExtractor(self.page).extract_components(disc_config)
        else:
            # OCR mode — extract components from OCR text
            # First try the standard tag pattern matching
            from engine.text_extractor import TextExtractor
            class OCRMockPage:
                def __init__(self, ocr_texts, real_page):
                    self._ocr_texts = ocr_texts
                    self._real_page = real_page
                    self.rect = real_page.rect
                def get_text(self, mode):
                    if mode == 'dict':
                        blocks = []
                        for t in self._ocr_texts:
                            blocks.append({
                                'lines': [{
                                    'spans': [{
                                        'text': t['text'],
                                        'bbox': [t['x'], t['y'], t['x1'], t['y1']],
                                        'size': t['size'],
                                        'color': t['color'],
                                        'font': 'OCR',
                                    }]
                                }]
                            })
                        return {'blocks': blocks}
                def get_drawings(self):
                    return self._real_page.get_drawings()
                def get_pixmap(self, matrix=None):
                    return self._real_page.get_pixmap(matrix=matrix)
            
            mock = OCRMockPage(texts, self.page)
            components = TextExtractor(mock).extract_components(disc_config)
            
            # Also extract OCR-specific components (equipment labels, pipe sizes)
            import re
            ocr_components = self._extract_ocr_components(texts)
            
            # Merge: add OCR-specific components that weren't found by tag patterns
            for key, val in ocr_components.items():
                if key not in components:
                    components[key] = val
            
            return components
    
    def _extract_ocr_components(self, texts):
        """Extract P&ID components from OCR text using label-based detection."""
        import re
        from collections import Counter
        
        components = {}
        
        # Equipment by label (PUMP, TANK, VALVE, FILTER, BLOWER, etc.)
        equipment_labels = {
            'PUMP': {'type': 'pump', 'unit': 'No'},
            'TANK': {'type': 'tank', 'unit': 'No'},
            'VALVE': {'type': 'valve', 'unit': 'No'},
            'FILTER': {'type': 'filter', 'unit': 'No'},
            'BLOWER': {'type': 'blower', 'unit': 'No'},
            'DOSING': {'type': 'dosing_system', 'unit': 'No'},
            'ROTAMETER': {'type': 'rotameter', 'unit': 'No'},
            'COMPRESSOR': {'type': 'compressor', 'unit': 'No'},
            'HEAT_EXCHANGER': {'type': 'heat_exchanger', 'unit': 'No'},
        }
        
        for label, info in equipment_labels.items():
            matches = [t for t in texts if label in t['text'].upper() and t.get('conf', 0) >= 30]
            if matches:
                # Deduplicate by location (items within 10pts are likely the same)
                unique = []
                for m in matches:
                    is_dup = any(abs(m['x'] - u['x']) < 10 and abs(m['y'] - u['y']) < 10 for u in unique)
                    if not is_dup:
                        unique.append(m)
                components[label] = {
                    'count': len(unique),
                    'type': info['type'],
                    'unit': info['unit'],
                    'locations': [{'x': u['x'], 'y': u['y'], 'text': u['text']} for u in unique],
                    'source': 'ocr_label',
                }
        
        # Pipe sizes by NB/DN pattern
        pipe_sizes = []
        for t in texts:
            text = t['text'].strip()
            # Match 80NB, 100NB, 150NB, 200NB, 65NB, 25NB, 50NB (with optional leading quote)
            m = re.search(r'(\d{2,3})NB', text, re.IGNORECASE)
            if m and t.get('conf', 0) >= 25:
                pipe_sizes.append({'size': f'{m.group(1)}NB', 'text': text, 'x': t['x'], 'y': t['y'], 'conf': t.get('conf', 0)})
            # Also match DN format
            m = re.search(r'DN(\d{2,3})', text, re.IGNORECASE)
            if m and t.get('conf', 0) >= 25:
                pipe_sizes.append({'size': f'DN{m.group(1)}', 'text': text, 'x': t['x'], 'y': t['y'], 'conf': t.get('conf', 0)})
        
        if pipe_sizes:
            # Deduplicate
            unique_sizes = []
            for ps in pipe_sizes:
                is_dup = any(abs(ps['x'] - u['x']) < 15 and abs(ps['y'] - u['y']) < 15 for u in unique_sizes)
                if not is_dup:
                    unique_sizes.append(ps)
            
            # Count by size
            size_counts = Counter(ps['size'] for ps in unique_sizes)
            components['pipe_sizes'] = {
                'count': len(unique_sizes),
                'type': 'pipe_segment',
                'unit': 'No',
                'size_breakdown': dict(size_counts),
                'locations': [{'x': ps['x'], 'y': ps['y'], 'text': ps['text']} for ps in unique_sizes],
                'source': 'ocr_pipe_size',
            }
        
        # Instruments by label
        instrument_labels = {
            'PRESSURE INDICATOR': {'type': 'pressure_indicator', 'unit': 'No'},
            'FLOW INDICATOR': {'type': 'flow_indicator', 'unit': 'No'},
            'TEMPERATURE INDICATOR': {'type': 'temperature_indicator', 'unit': 'No'},
            'LEVEL INDICATOR': {'type': 'level_indicator', 'unit': 'No'},
            'PI': {'type': 'pressure_indicator', 'unit': 'No'},
            'TI': {'type': 'temperature_indicator', 'unit': 'No'},
            'FI': {'type': 'flow_indicator', 'unit': 'No'},
            'LI': {'type': 'level_indicator', 'unit': 'No'},
            'ROTAMETER': {'type': 'rotameter', 'unit': 'No'},
        }
        
        for label, info in instrument_labels.items():
            # For short labels like PI, TI — match as standalone tags
            if len(label) <= 3:
                matches = [t for t in texts if re.match(rf'^{label}[- ]?\d*$', t['text'], re.IGNORECASE) and t.get('conf', 0) >= 30]
            else:
                # For longer labels — search within text
                matches = [t for t in texts if label in t['text'].upper() and t.get('conf', 0) >= 30]
            if matches:
                unique = []
                for m in matches:
                    is_dup = any(abs(m['x'] - u['x']) < 15 and abs(m['y'] - u['y']) < 15 for u in unique)
                    if not is_dup:
                        unique.append(m)
                if len(label) <= 3:
                    components[f'inst_{label}'] = {
                        'count': len(unique),
                        'type': info['type'],
                        'unit': info['unit'],
                        'locations': [{'x': u['x'], 'y': u['y'], 'text': u['text']} for u in unique],
                        'source': 'ocr_instrument',
                    }
        
        # Pipe materials
        material_labels = {'uPVC': 'uPVC', 'MS': 'Mild Steel', 'SS': 'Stainless Steel', 'CI': 'Cast Iron', 'HDPE': 'HDPE'}
        for label, full_name in material_labels.items():
            matches = [t for t in texts if re.search(rf'\b{re.escape(label)}\b', t['text'], re.IGNORECASE) and t.get('conf', 0) >= 30]
            if matches:
                unique = []
                for m in matches:
                    is_dup = any(abs(m['x'] - u['x']) < 10 and abs(m['y'] - u['y']) < 10 for u in unique)
                    if not is_dup:
                        unique.append(m)
                if len(unique) > 0:
                    components[f'mat_{label}'] = {
                        'count': len(unique),
                        'type': f'pipe_material_{full_name}',
                        'unit': 'No',
                        'locations': [{'x': u['x'], 'y': u['y'], 'text': u['text']} for u in unique],
                        'source': 'ocr_material',
                    }
        
        return components