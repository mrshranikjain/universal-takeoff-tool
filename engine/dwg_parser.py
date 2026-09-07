"""
DWG/DXF Parser — extracts text, blocks, and drawing entities from CAD files.
Returns data compatible with the existing takeoff engine (TextExtractor/VectorAnalyzer format).
"""
import ezdxf
from ezdxf import recover
from collections import defaultdict


class DWGParser:
    """Parse DWG/DXF files and return data in the same format as PyMuPDF."""
    
    def __init__(self, file_path):
        self.path = file_path
        try:
            self.doc = ezdxf.readfile(file_path)
        except Exception:
            try:
                self.doc, auditor = recover.readfile(file_path)
                auditor.fix_and_write(self.doc, file_path + ".recovered.dxf")
            except Exception as e:
                raise FileNotFoundError(f"Cannot read DWG/DXF file: {e}")
        
        self.metadata = self.doc.metadata
        self._layer_colors = None
    
    def get_pages(self):
        """Return list of (page_num, layout) tuples."""
        layouts = []
        for i, layout_name in enumerate(self.doc.layout_names()):
            layout = self.doc.layouts.get(layout_name)
            layouts.append((i + 1, layout))
        if not layouts:
            ms = self.doc.modelspace()
            layouts = [(1, ms)]
        return layouts
    
    def extract_texts(self, layout):
        """Extract all text entities in PyMuPDF-compatible format."""
        texts = []
        msp = layout if hasattr(layout, 'entities') else layout
        
        for entity in msp:
            etype = entity.dxftype()
            
            if etype == "TEXT":
                text = entity.dxf.text.strip()
                if text:
                    insert = entity.dxf.insert
                    height = entity.dxf.height if entity.dxf.hasattr('height') else 2.5
                    color = self._get_entity_color(entity)
                    r, g, b = self._color_to_rgb(color)
                    texts.append({
                        "text": text,
                        "x": round(insert.x, 1),
                        "y": round(insert.y, 1),
                        "x1": round(insert.x + len(text) * height * 0.6, 1),
                        "y1": round(insert.y + height, 1),
                        "size": round(height, 2),
                        "color": (r << 16) | (g << 8) | b,
                        "r": r, "g": g, "b": b,
                        "font": entity.dxf.style if entity.dxf.hasattr('style') else "Standard",
                        "layer": entity.dxf.layer,
                    })
            
            elif etype == "MTEXT":
                text = entity.text.strip()
                if text:
                    insert = entity.dxf.insert
                    char_height = entity.dxf.char_height if entity.dxf.hasattr('char_height') else 2.5
                    color = self._get_entity_color(entity)
                    r, g, b = self._color_to_rgb(color)
                    # MTEXT may have multiple lines
                    for line_idx, line in enumerate(text.split('\n')):
                        line = line.strip()
                        if line:
                            texts.append({
                                "text": line,
                                "x": round(insert.x, 1),
                                "y": round(insert.y - line_idx * char_height * 1.5, 1),
                                "x1": round(insert.x + len(line) * char_height * 0.6, 1),
                                "y1": round(insert.y - line_idx * char_height * 1.5 + char_height, 1),
                                "size": round(char_height, 2),
                                "color": (r << 16) | (g << 8) | b,
                                "r": r, "g": g, "b": b,
                                "font": entity.dxf.style if entity.dxf.hasattr('style') else "Standard",
                                "layer": entity.dxf.layer,
                            })
        
        return texts
    
    def extract_drawings(self, layout):
        """Extract drawing entities in PyMuPDF-compatible format."""
        drawings = []
        msp = layout if hasattr(layout, 'entities') else layout
        
        for entity in msp:
            etype = entity.dxftype()
            color = self._get_entity_color(entity)
            
            if etype == "LINE":
                start = entity.dxf.start
                end = entity.dxf.end
                drawings.append({
                    "color": self._color_to_tuple(color),
                    "fill": None,
                    "rect": self._rect_from_points([start, end]),
                    "items": [("l", start, end)],
                    "layer": entity.dxf.layer,
                })
            
            elif etype == "LWPOLYLINE":
                points = list(entity.get_points(format='xy'))
                if len(points) >= 2:
                    items = []
                    for i in range(len(points) - 1):
                        items.append(("l", type('P', (), {'x': points[i][0], 'y': points[i][1]})(),
                                      type('P', (), {'x': points[i+1][0], 'y': points[i+1][1]})()))
                    fill = self._color_to_tuple(color) if entity.closed else None
                    drawings.append({
                        "color": self._color_to_tuple(color),
                        "fill": fill,
                        "rect": self._rect_from_points([type('P', (), {'x': p[0], 'y': p[1]})() for p in points]),
                        "items": items,
                        "layer": entity.dxf.layer,
                    })
            
            elif etype == "CIRCLE":
                center = entity.dxf.center
                radius = entity.dxf.radius
                # Approximate circle with 36 segments
                import math
                items = []
                for i in range(36):
                    a1 = 2 * math.pi * i / 36
                    a2 = 2 * math.pi * (i + 1) / 36
                    p1 = type('P', (), {'x': center.x + radius * math.cos(a1), 'y': center.y + radius * math.sin(a1)})()
                    p2 = type('P', (), {'x': center.x + radius * math.cos(a2), 'y': center.y + radius * math.sin(a2)})()
                    items.append(("l", p1, p2))
                drawings.append({
                    "color": self._color_to_tuple(color),
                    "fill": None,
                    "rect": type('R', (), {'x0': center.x - radius, 'y0': center.y - radius,
                                            'x1': center.x + radius, 'y1': center.y + radius,
                                            'width': 2 * radius, 'height': 2 * radius})(),
                    "items": items,
                    "layer": entity.dxf.layer,
                })
            
            elif etype == "ARC":
                center = entity.dxf.center
                radius = entity.dxf.radius
                start_angle = math.radians(entity.dxf.start_angle)
                end_angle = math.radians(entity.dxf.end_angle)
                import math
                items = []
                steps = max(4, int(abs(end_angle - start_angle) / (math.pi / 18)))
                for i in range(steps):
                    a1 = start_angle + (end_angle - start_angle) * i / steps
                    a2 = start_angle + (end_angle - start_angle) * (i + 1) / steps
                    p1 = type('P', (), {'x': center.x + radius * math.cos(a1), 'y': center.y + radius * math.sin(a1)})()
                    p2 = type('P', (), {'x': center.x + radius * math.cos(a2), 'y': center.y + radius * math.sin(a2)})()
                    items.append(("l", p1, p2))
                drawings.append({
                    "color": self._color_to_tuple(color),
                    "fill": None,
                    "rect": self._rect_from_points([p1, p2]),
                    "items": items,
                    "layer": entity.dxf.layer,
                })
            
            elif etype == "INSERT":
                # Block reference — extract as filled symbol
                insert = entity.dxf.insert
                scale = entity.dxf.scale if entity.dxf.hasattr('scale') else (1, 1, 1)
                block = self.doc.blocks.get(entity.dxf.name)
                if block:
                    # Estimate block bounding box
                    min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
                    for e in block:
                        if e.dxftype() == "LINE":
                            min_x = min(min_x, e.dxf.start.x, e.dxf.end.x)
                            min_y = min(min_y, e.dxf.start.y, e.dxf.end.y)
                            max_x = max(max_x, e.dxf.start.x, e.dxf.end.x)
                            max_y = max(max_y, e.dxf.start.y, e.dxf.end.y)
                    if min_x != float('inf'):
                        w = (max_x - min_x) * scale[0]
                        h = (max_y - min_y) * scale[1]
                        drawings.append({
                            "color": self._color_to_tuple(color),
                            "fill": self._color_to_tuple(color),
                            "rect": type('R', (), {'x0': insert.x, 'y0': insert.y,
                                                    'x1': insert.x + w, 'y1': insert.y + h,
                                                    'width': w, 'height': h})(),
                            "items": [],
                            "layer": entity.dxf.layer,
                            "block_name": entity.dxf.name,
                        })
        
        return drawings
    
    def extract_blocks(self, layout):
        """Extract block insertions with block names and positions."""
        blocks = []
        msp = layout if hasattr(layout, 'entities') else layout
        
        for entity in msp:
            if entity.dxftype() == "INSERT":
                insert = entity.dxf.insert
                scale = entity.dxf.scale if entity.dxf.hasattr('scale') else (1, 1, 1)
                rotation = entity.dxf.rotation if entity.dxf.hasattr('rotation') else 0
                blocks.append({
                    "block_name": entity.dxf.name,
                    "x": round(insert.x, 1),
                    "y": round(insert.y, 1),
                    "scale_x": scale[0],
                    "scale_y": scale[1],
                    "rotation": rotation,
                    "layer": entity.dxf.layer,
                })
        
        return blocks
    
    def get_layer_colors(self):
        """Return {layer_name: (r, g, b)} mapping."""
        if self._layer_colors is not None:
            return self._layer_colors
        
        colors = {}
        for layer in self.doc.layers:
            color_idx = layer.color
            r, g, b = self._aci_to_rgb(color_idx)
            colors[layer.dxf.name] = (r, g, b)
        
        self._layer_colors = colors
        return colors
    
    def get_page_rect(self, layout):
        """Get the bounding rectangle of a layout."""
        min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
        
        for entity in layout if hasattr(layout, 'entities') else layout:
            etype = entity.dxftype()
            if etype == "LINE":
                min_x = min(min_x, entity.dxf.start.x, entity.dxf.end.x)
                min_y = min(min_y, entity.dxf.start.y, entity.dxf.end.y)
                max_x = max(max_x, entity.dxf.start.x, entity.dxf.end.x)
                max_y = max(max_y, entity.dxf.start.y, entity.dxf.end.y)
            elif etype in ("TEXT", "MTEXT"):
                insert = entity.dxf.insert
                min_x = min(min_x, insert.x)
                min_y = min(min_y, insert.y)
                max_x = max(max_x, insert.x + 100)
                max_y = max(max_y, insert.y + 10)
            elif etype == "INSERT":
                insert = entity.dxf.insert
                min_x = min(min_x, insert.x)
                min_y = min(min_y, insert.y)
                max_x = max(max_x, insert.x + 100)
                max_y = max(max_y, insert.y + 100)
        
        if min_x == float('inf'):
            return {'width': 842, 'height': 595}  # A3 default
        
        return {
            'width': round(max_x - min_x, 1),
            'height': round(max_y - min_y, 1),
        }
    
    def close(self):
        self.doc = None
    
    def _get_entity_color(self, entity):
        """Get entity color index."""
        if entity.dxf.hasattr('color') and entity.dxf.color != 256:  # 256 = BYLAYER
            return entity.dxf.color
        # Get from layer
        layer = self.doc.layers.get(entity.dxf.layer)
        if layer:
            return layer.color
        return 7  # White/black default
    
    def _color_to_rgb(self, aci_color):
        """Convert ACI color index to RGB."""
        r, g, b = self._aci_to_rgb(aci_color)
        return r, g, b
    
    def _color_to_tuple(self, aci_color):
        """Convert ACI color to (r, g, b) tuple normalized 0-1."""
        r, g, b = self._aci_to_rgb(aci_color)
        return (r / 255.0, g / 255.0, b / 255.0)
    
    def _aci_to_rgb(self, aci):
        """AutoCAD Color Index to RGB."""
        aci_map = {
            0: (0, 0, 0), 1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0),
            4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255),
            8: (128, 128, 128), 9: (192, 192, 192),
            10: (255, 0, 0), 11: (255, 127, 127), 12: (165, 0, 0),
            20: (255, 255, 0), 30: (0, 255, 0), 40: (0, 255, 255),
            50: (0, 0, 255), 60: (255, 0, 255),
            251: (63, 63, 63), 252: (95, 95, 95), 253: (127, 127, 127),
            254: (159, 159, 159), 255: (191, 191, 191),
        }
        return aci_map.get(aci, (0, 0, 0))
    
    def _rect_from_points(self, points):
        """Create a rect-like object from points."""
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        return type('R', (), {
            'x0': min(xs), 'y0': min(ys),
            'x1': max(xs), 'y1': max(ys),
            'width': max(xs) - min(xs),
            'height': max(ys) - min(ys),
        })()