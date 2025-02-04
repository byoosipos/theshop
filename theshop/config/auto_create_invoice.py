import frappe
from frappe import _
import json

@frappe.whitelist()
def create_sales_invoice_from_delivery(delivery_note):
    """
    Create Sales Invoice automatically on Delivery Note submission
    Args:
        delivery_note: Delivery Note object or string
    """
    try:
        if isinstance(delivery_note, str):
            if delivery_note.startswith('{'):
                delivery_note = json.loads(delivery_note)
                delivery_note = frappe.get_doc("Delivery Note", delivery_note.get("name"))
            else:
                delivery_note = frappe.get_doc("Delivery Note", delivery_note)
        
        # Check if Sales Invoice already exists
        existing_invoice = frappe.get_all("Sales Invoice", 
            filters={"delivery_note": delivery_note.name, "docstatus": ["!=", 2]})
        
        if existing_invoice:
            frappe.throw(_("Sales Invoice already exists for this Delivery Note"))
        
        if not delivery_note.items:
            frappe.throw(_("No items found in the Delivery Note"))

        # Get the sales order references
        sales_orders = list(set([item.against_sales_order for item in delivery_note.items if item.against_sales_order]))
        
        if not sales_orders:
            frappe.throw(_("No Sales Order references found in Delivery Note items"))
        
        # Validate Delivery Note is submitted
        if delivery_note.docstatus != 1:
            frappe.throw(_("Please submit the Delivery Note first"))
        
        # Create new Sales Invoice
        sales_invoice = frappe.new_doc("Sales Invoice")
        sales_invoice.customer = delivery_note.customer
        sales_invoice.posting_date = frappe.utils.today()
        
        # Copy shipping details
        if hasattr(delivery_note, 'shipping_address_name'):
            sales_invoice.shipping_address_name = delivery_note.shipping_address_name
            sales_invoice.shipping_address = delivery_note.shipping_address
        
        # Link to Delivery Note
        sales_invoice.update({
            "is_pos": 0,
            "delivery_note": delivery_note.name,
        })
        
        # Add items from Delivery Note
        for item in delivery_note.items:
            si_item = sales_invoice.append("items", {})
            si_item.item_code = item.item_code
            si_item.qty = item.qty
            si_item.rate = item.rate
            si_item.delivery_note = delivery_note.name
            si_item.dn_detail = item.name
            si_item.cost_center = item.cost_center
            
            # Link to original Sales Order
            if item.against_sales_order:
                si_item.sales_order = item.against_sales_order
                si_item.so_detail = item.so_detail
        
        sales_invoice.set_missing_values()
        sales_invoice.calculate_taxes_and_totals()
        
        # Apply advances from Sales Orders
        for sales_order in sales_orders:
            so_doc = frappe.get_doc("Sales Order", sales_order)
            advances = so_doc.get("advances") or []
            if so_doc.advance_paid and advances:
                for payment in advances:
                    sales_invoice.append("advances", {
                        "reference_type": payment.reference_type,
                        "reference_name": payment.reference_name,
                        "reference_row": payment.reference_row,
                        "remarks": payment.remarks,
                        "advance_amount": payment.advance_amount,
                        "allocated_amount": payment.allocated_amount
                    })
        
        sales_invoice.insert()
        sales_invoice.submit()
        
        frappe.msgprint(_("Sales Invoice {0} created").format(sales_invoice.name))
        return sales_invoice.name
        
    except Exception as e:
        frappe.log_error(title="Failed to create Sales Invoice", message=str(e))
        frappe.throw(_("Failed to create Sales Invoice: {0}").format(str(e)))
