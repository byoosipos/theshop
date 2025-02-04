# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class WebsiteItemSyncSummary(Document):
    def validate(self):
        if self.duration and self.duration < 0:
            frappe.throw("Duration cannot be negative")
            
        if self.status not in ["Success", "Failed"]:
            frappe.throw("Invalid status value")
            
        # Ensure counts are non-negative
        for field in ["total_items", "processed_items", "failed_items"]:
            if getattr(self, field, 0) and getattr(self, field) < 0:
                frappe.throw(f"{field.replace('_', ' ').title()} cannot be negative") 