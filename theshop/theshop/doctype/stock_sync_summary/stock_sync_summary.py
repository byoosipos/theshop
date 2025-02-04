# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class StockSyncSummary(Document):
    def validate(self):
        if self.duration and self.duration < 0:
            frappe.throw("Duration cannot be negative")
            
        if self.status not in ["Success", "Failed"]:
            frappe.throw("Invalid status value") 