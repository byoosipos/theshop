import frappe
from frappe import _
from frappe.utils import flt, cint, get_url
from erpnext.stock.doctype.item.item import Item
from erpnext.stock.doctype.bin.bin import Bin

@frappe.whitelist(allow_guest=True)
def get_item_categories():
    """Get main item categories/groups"""
    categories = frappe.get_all(
        "Item Group",
        filters={
            "show_in_website": 1,
            "parent_item_group": "All Item Groups",
            "is_group": 0
        },
        fields=[
            "name", "route", "image", "item_group_name",
            "description", "website_title"
        ],
        order_by="weightage desc, item_group_name asc"
    )
    
    # Add full URL to image paths
    for category in categories:
        if category.image:
            category.image = get_url(category.image)
    
    return categories

@frappe.whitelist(allow_guest=True)
def get_item_details(item_code):
    """Get comprehensive item details including price and stock"""
    item_details = {}
    
    # Get Website Item information
    web_item = frappe.get_all(
        "Website Item",
        filters={"item_code": item_code, "published": 1},
        fields=[
            "name", "item_code", "item_name", "item_group",
            "description", "website_image", "route",
            "thumbnail"
        ],
        limit=1
    )
    
    if not web_item:
        return None
        
    web_item = web_item[0]
    item_details.update(web_item)
    
    # Get price information
    price_list_rate = frappe.get_all(
        "Item Price",
        filters={
            "item_code": item_code,
            "selling": 1
        },
        fields=[
            "price_list_rate", "currency"
        ],
        order_by="valid_from desc",
        limit=1
    )
    
    if price_list_rate:
        price_info = price_list_rate[0]
        item_details.update({
            "price": flt(price_info.price_list_rate),
            "currency": price_info.currency,
            "formatted_price": frappe.format_value(
                flt(price_info.price_list_rate),
                {"fieldtype": "Currency", "currency": price_info.currency}
            )
        })
    
    # Get stock information
    bin_data = frappe.get_all(
        "Bin",
        filters={"item_code": item_code},
        fields=[
            "actual_qty", "reserved_qty"
        ]
    )
    
    if bin_data:
        total_actual_qty = sum(flt(d.actual_qty) for d in bin_data)
        total_reserved_qty = sum(flt(d.reserved_qty) for d in bin_data)
        available_qty = total_actual_qty - total_reserved_qty
        
        item_details.update({
            "in_stock": available_qty > 0,
            "stock_qty": total_actual_qty,
            "available_qty": available_qty
        })
    
    return item_details

@frappe.whitelist(allow_guest=True)
def get_items_by_category(category, start=0, limit=12):
    """Get items by category with pagination"""
    items = []
    
    item_list = frappe.get_all(
        "Website Item",
        filters={
            "published": 1,
            "item_group": category
        },
        fields=[
            "route", "published", "item_code", "item_name",
            "item_group", "stock_uom", "description", 
            "thumbnail"
        ],
        order_by="item_name asc",
        start=cint(start),
        limit=cint(limit)
    )
    
    for item in item_list:
        item_details = get_item_details(item.item_code)
        if item_details:
            items.append(item_details)
    
    return items

@frappe.whitelist(allow_guest=True)
def search_items(query, start=0, limit=12):
    """Search items by name, code, or description"""
    items = []
    
    # Search in Website Items
    item_list = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        or_filters={
            "item_name": ["like", f"%{query}%"],
            "item_code": ["like", f"%{query}%"],
            "description": ["like", f"%{query}%"]
        },
        fields=[
            "route", "published", "item_code", "item_name",
            "item_group", "stock_uom", "description",
            "thumbnail"
        ],
        order_by="item_name asc",
        start=cint(start),
        limit=cint(limit)
    )
    
    for item in item_list:
        item_details = get_item_details(item.item_code)
        if item_details:
            items.append(item_details)
    
    return items

@frappe.whitelist(allow_guest=True)
def get_all_items(start=0, limit=12):
    """Get all published items with pagination"""
    items = []
    
    # Convert parameters to integers
    start = cint(start)
    limit = cint(limit)
    
    # Get all published items
    item_list = frappe.get_all(
        "Website Item",
        filters={"published": 1},
        fields=[
            "route", "published", "item_code", "item_name",
            "item_group", "stock_uom", "description",
            "thumbnail"
        ],
        order_by="item_name asc",
        start=start,
        limit=limit
    )
    
    for item in item_list:
        item_details = get_item_details(item.item_code)
        if item_details:
            items.append(item_details)
    
    return items 