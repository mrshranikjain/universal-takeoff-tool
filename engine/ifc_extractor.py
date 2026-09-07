"""
IFC Quantity Extractor — parses IFC files using ifcopenshell.
Extracts element counts, geometric quantities, spatial hierarchy, and materials.
"""
import ifcopenshell
import ifcopenshell.util.element as element_util
from collections import defaultdict


class IFCExtractor:
    """Extract quantities and data from IFC files."""
    
    def __init__(self, ifc_path):
        self.path = ifc_path
        self.model = ifcopenshell.open(ifc_path)
    
    def extract_all(self):
        """Run full extraction and return all results."""
        counts = self.count_by_class()
        quantities = self.extract_all_quantities()
        hierarchy = self.get_spatial_hierarchy()
        materials = self.extract_all_materials()
        
        # Summary
        total_volume = sum(q.get("total_volume_m3", 0) for q in quantities.values())
        total_area = sum(q.get("total_area_m2", 0) for q in quantities.values())
        total_length = sum(q.get("total_length_m", 0) for q in quantities.values())
        total_elements = sum(counts.values())
        
        return {
            "element_counts": counts,
            "quantities": quantities,
            "spatial_hierarchy": hierarchy,
            "materials": materials,
            "summary": {
                "total_elements": total_elements,
                "total_volume_m3": round(total_volume, 2),
                "total_area_m2": round(total_area, 2),
                "total_length_m": round(total_length, 2),
                "ifc_classes": len(counts),
            },
        }
    
    def count_by_class(self):
        """Count elements by IFC class."""
        counts = defaultdict(int)
        for element in self.model:
            if element.is_a("IfcBuiltElement") or element.is_a("IfcBuildingElement"):
                counts[element.is_a()] += 1
            elif element.is_a("IfcFlowSegment") or element.is_a("IfcFlowFitting"):
                counts[element.is_a()] += 1
            elif element.is_a("IfcDistributionElement"):
                counts[element.is_a()] += 1
        return dict(counts)
    
    def extract_all_quantities(self):
        """Extract quantities for all element classes."""
        results = {}
        class_elements = defaultdict(list)
        
        for element in self.model:
            if element.is_a("IfcBuiltElement") or element.is_a("IfcFlowSegment"):
                class_elements[element.is_a()].append(element)
        
        for ifc_class, elements in class_elements.items():
            total_volume = 0
            total_area = 0
            total_length = 0
            count = len(elements)
            
            for elem in elements:
                qty = self.get_quantities(elem)
                total_volume += qty.get("volume_m3", 0)
                total_area += qty.get("area_m2", 0)
                total_length += qty.get("length_m", 0)
            
            result = {"count": count}
            if total_volume > 0:
                result["total_volume_m3"] = round(total_volume, 3)
            if total_area > 0:
                result["total_area_m2"] = round(total_area, 2)
            if total_length > 0:
                result["total_length_m"] = round(total_length, 2)
            
            results[ifc_class] = result
        
        return results
    
    def get_quantities(self, element):
        """Extract quantity properties from a single element."""
        result = {}
        
        # Try to get base quantities
        for rel in getattr(element, "IsDefinedBy", []):
            if rel.is_a("IfcRelDefinesByProperties"):
                prop_set = rel.RelatingPropertyDefinition
                if prop_set.is_a("IfcElementQuantity"):
                    for qty in prop_set.Quantities:
                        if qty.is_a("IfcQuantityVolume"):
                            result["volume_m3"] = result.get("volume_m3", 0) + qty.VolumeValue
                        elif qty.is_a("IfcQuantityArea"):
                            result["area_m2"] = result.get("area_m2", 0) + qty.AreaValue
                        elif qty.is_a("IfcQuantityLength"):
                            result["length_m"] = result.get("length_m", 0) + qty.LengthValue
                        elif qty.is_a("IfcQuantityCount"):
                            result["count"] = qty.CountValue
        
        # Try ifcopenshell utility
        try:
            psets = element_util.get_psets(element)
            for pset_name, pset_data in psets.items():
                if "Qto_" in pset_name or "BaseQty" in pset_name:
                    for key, val in pset_data.items():
                        if "Volume" in key and isinstance(val, (int, float)):
                            result["volume_m3"] = result.get("volume_m3", 0) + val
                        elif "Area" in key and isinstance(val, (int, float)):
                            result["area_m2"] = result.get("area_m2", 0) + val
                        elif "Length" in key and isinstance(val, (int, float)):
                            result["length_m"] = result.get("length_m", 0) + val
        except Exception:
            pass
        
        return result
    
    def get_spatial_hierarchy(self):
        """Extract building > storey > space hierarchy."""
        hierarchy = {}
        
        # Find all buildings
        buildings = [e for e in self.model if e.is_a("IfcBuilding")]
        if not buildings:
            # Try IfcSpatialStructureElement
            buildings = [e for e in self.model if e.is_a("IfcSpatialStructureElement") and not e.is_a("IfcBuildingStorey")]
        
        for building in buildings:
            building_name = building.Name or "Unnamed Building"
            storeys = {}
            
            # Find storeys in this building
            for rel in getattr(building, "ContainsElements", []):
                for elem in rel.RelatedElements:
                    if elem.is_a("IfcBuildingStorey"):
                        storey_name = elem.Name or f"Storey {elem.id()}"
                        spaces = []
                        
                        # Find spaces in this storey
                        for srel in getattr(elem, "ContainsElements", []):
                            for selem in srel.RelatedElements:
                                if selem.is_a("IfcSpace"):
                                    spaces.append(selem.Name or f"Space {selem.id()}")
                        
                        storeys[storey_name] = spaces
            
            # Also try IfcRelAggregates
            for rel in self.model:
                if rel.is_a("IfcRelAggregates") and rel.RelatingObject == building:
                    for storey in rel.RelatedObjects:
                        if storey.is_a("IfcBuildingStorey"):
                            storey_name = storey.Name or f"Storey {storey.id()}"
                            if storey_name not in storeys:
                                spaces = []
                                for srel in getattr(storey, "ContainsElements", []):
                                    for selem in srel.RelatedElements:
                                        if selem.is_a("IfcSpace"):
                                            spaces.append(selem.Name or f"Space {selem.id()}")
                                storeys[storey_name] = spaces
            
            hierarchy[building_name] = storeys
        
        return hierarchy
    
    def extract_all_materials(self):
        """Extract material info for all element classes."""
        results = defaultdict(lambda: defaultdict(float))
        
        for element in self.model:
            if not (element.is_a("IfcBuiltElement") or element.is_a("IfcFlowSegment")):
                continue
            
            ifc_class = element.is_a()
            material = self.get_materials(element)
            if material:
                for mat_name, pct in material.items():
                    results[ifc_class][mat_name] += pct
        
        return {k: dict(v) for k, v in results.items()}
    
    def get_materials(self, element):
        """Get material info for a single element."""
        materials = {}
        
        try:
            material = element_util.get_material(element)
            if material:
                if isinstance(material, (list, tuple)):
                    for i, mat in enumerate(material):
                        name = mat.Name if hasattr(mat, 'Name') and mat.Name else f"Layer {i+1}"
                        materials[name] = 100.0 / len(material)
                elif hasattr(material, 'Name'):
                    materials[material.Name or "Unknown"] = 100.0
                elif hasattr(material, 'MaterialConstituents'):
                    total = len(material.MaterialConstituents)
                    for const in material.MaterialConstituents:
                        name = const.Material.Name if hasattr(const.Material, 'Name') else "Unknown"
                        frac = const.Fraction or (100.0 / total if total > 0 else 0)
                        materials[name] = frac
        except Exception:
            pass
        
        return materials
    
    def close(self):
        if self.model:
            self.model = None