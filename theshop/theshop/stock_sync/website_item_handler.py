import frappe
from frappe import _
import traceback
from datetime import datetime
from frappe.utils import now
from .base_handler import BaseSyncHandler

class WebsiteItemHandler(BaseSyncHandler):
    def __init__(self):
        super().__init__()
        # Define required and optional fields
        self.required_fields = {
            "item_code": "name",
            "item_name": "item_name",
            "item_group": "item_group",
            "stock_uom": "stock_uom"  # Added stock_uom as required
        }
        self.optional_fields = {
            "description": "description",
            "brand": "brand",
            "image": "image",
            "web_item_name": "item_name"
        }
        # Common UOM conversions
        self.default_uom_conversions = {
            "tons": 1000,
            "kg": 1,
            "g": 0.001,
            "mg": 0.000001,
            "lb": 0.45359237,
            "oz": 0.0283495231,
            "m": 1,
            "cm": 0.01,
            "mm": 0.001,
            "in": 0.0254,
            "ft": 0.3048,
            "yd": 0.9144,
            "l": 1,
            "ml": 0.001,
            "gal": 3.78541,
            "qt": 0.946353,
            "pt": 0.473176,
            "fl oz": 0.0295735,
            "pc": 1,
            "unit": 1,
            "piece": 1,
            "pieces": 1,
            "nos": 1,
            "numbers": 1,
            "box": 1,
            "boxes": 1,
            "pack": 1,
            "packs": 1,
            "pair": 1,
            "pairs": 1,
            "set": 1,
            "sets": 1,
            "bundle": 1,
            "bundles": 1,
            "roll": 1,
            "rolls": 1,
            "dozen": 12,
            "dozens": 12
        }

    def ensure_uom_exists(self, uom_name):
        """Create UOM if it doesn't exist"""
        if not frappe.db.exists("UOM", uom_name):
            try:
                # Convert to lowercase for comparison
                uom_lower = uom_name.lower()
                
                # Create new UOM
                uom_doc = frappe.new_doc("UOM")
                uom_doc.uom_name = uom_name
                
                # Set conversion factor if known
                if uom_lower in self.default_uom_conversions:
                    uom_doc.must_be_whole_number = 0
                    uom_doc.enabled = 1
                    
                    # Create UOM conversion
                    conversion = frappe.new_doc("UOM Conversion Factor")
                    conversion.category = "Default"
                    conversion.from_uom = uom_name
                    conversion.to_uom = "Nos"  # Base unit
                    conversion.value = self.default_uom_conversions[uom_lower]
                    
                    uom_doc.append("conversion_factors", conversion)
                
                uom_doc.insert(ignore_permissions=True)
                frappe.db.commit()
                
                frappe.logger().info(f"Created new UOM: {uom_name}")
                return True
            except Exception as e:
                frappe.logger().error(f"Failed to create UOM {uom_name}: {str(e)[:100]}")
                return False
        return True

    def sync_website_items(self):
        """Handle only website item sync"""
        # Focus on website item creation/updates
        pass

    def sync_variant_item(self, variant_data):
        """Handle website variants"""
        # Focus on variant website items
        pass

    def sync_template_item(self, template_data):
        """Sync template item to website"""
        try:
            website_item = frappe.get_doc("Website Item", {"item_code": template_data.name})
            is_new = False
        except frappe.DoesNotExistError:
            website_item = frappe.new_doc("Website Item")
            is_new = True

        # Update fields
        website_item.item_code = template_data.name
        website_item.item_name = template_data.item_name
        website_item.item_group = template_data.item_group
        website_item.has_variants = 1
        website_item.show_variant_in_website = 1
        
        if is_new:
            website_item.published = 1

        website_item.save()
        return website_item

    def create_sync_summary(self, total_items):
        """Create sync summary document"""
        try:
            duration = (datetime.now() - self.start_time).total_seconds()
            status = "Success" if self.failed == 0 else "Failed"
            
            summary = frappe.get_doc({
                "doctype": "Website Item Sync Summary",
                "start_time": self.start_time,
                "duration": duration,
                "total_items": total_items,
                "processed_items": self.processed,
                "failed_items": self.failed,
                "status": status,
                "error_message": f"Processed: {self.processed}, Failed: {self.failed}"[:140]
            })
            summary.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Failed to create sync summary: {str(e)[:100]}")

def sync_all_website_items():
    """Wrapper function for scheduler"""
    try:
        handler = WebsiteItemHandler()
        handler.sync_website_items()
    except Exception as e:
        error_msg = f"Website sync failed: {str(e)[:50]}"
        frappe.log_error(message=error_msg, title="Website Sync")

def sync_website_item(item_code):
    """
    Sync individual website item
    """
    # Get item details from Item master
    item = frappe.get_doc("Item", item_code)
    
    # Skip if item is a variant
    if item.variant_of:
        return
    
    # Get or create Website Item
    try:
        website_item = frappe.get_doc("Website Item", {"item_code": item_code})
    except frappe.DoesNotExistError:
        website_item = frappe.new_doc("Website Item")
        website_item.item_code = item_code
        website_item.item_name = item.item_name
        website_item.web_item_name = item.item_name
    
    # Update fields
    website_item.item_group = item.item_group
    website_item.description = item.description
    website_item.brand = item.brand
    
    # Get stock details
    stock_qty = frappe.db.sql("""
        SELECT SUM(actual_qty) as qty
        FROM tabBin 
        WHERE item_code=%s
    """, item_code)[0][0] or 0
    
    website_item.stock_qty = stock_qty
    
    # Save changes
    website_item.save()
    
    return website_item 