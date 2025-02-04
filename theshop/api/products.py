import frappe
from frappe import _
from frappe.utils import flt, cint, get_url

class ProductAPI:
    @staticmethod
    @frappe.whitelist(allow_guest=True)
    def get_products(
        page=1, 
        items_per_page=12, 
        category=None, 
        search=None, 
        sort_by="name_asc",
        filters=None
    ):
        """Get products with pagination, filtering, and sorting"""
        try:
            start = (cint(page) - 1) * cint(items_per_page)
            
            # Base query for Website Items
            query_filters = {
                "published": 1,
            }
            
            # Add category filter
            if category and category != "All Categories":
                query_filters["item_group"] = category
                
            # Add search filter
            if search:
                query_filters.update([
                    "|",
                    ["item_name", "like", f"%{search}%"],
                    ["description", "like", f"%{search}%"]
                ])
                
            # Add custom filters
            if filters:
                query_filters.update(filters)
                
            # Get total count for pagination
            total_items = frappe.db.count("Website Item", filters=query_filters)
            
            # Determine sort field and order
            sort_field, sort_order = ProductAPI._get_sort_params(sort_by)
            
            # Get items with minimal fields
            items = frappe.get_all(
                "Website Item",
                filters=query_filters,
                fields=[
                    "item_code",
                    "description",
                    "thumbnail",
                    "route"
                ],
                order_by=f"{sort_field} {sort_order}",
                start=start,
                limit=cint(items_per_page)
            )
            
            # Efficiently get prices and stock in bulk
            if items:
                item_codes = [item.item_code for item in items]
                prices = ProductAPI._get_bulk_prices(item_codes)
                stock = ProductAPI._get_bulk_stock(item_codes)
                
                # Enhance items with price and stock info
                for item in items:
                    item.update({
                        "price_info": prices.get(item.item_code),
                        "stock_info": stock.get(item.item_code),
                        "image_url": get_url(item.thumbnail) if item.thumbnail else None
                    })
            
            return {
                "items": items,
                "total_items": total_items,
                "total_pages": (total_items + items_per_page - 1) // items_per_page,
                "current_page": cint(page)
            }
            
        except Exception as e:
            frappe.log_error(f"Error in get_products: {str(e)}")
            return {
                "items": [],
                "total_items": 0,
                "total_pages": 0,
                "current_page": 1,
                "error": str(e)
            }

    @staticmethod
    def _get_bulk_prices(item_codes):
        """Get prices for multiple items efficiently"""
        prices = {}
        price_list = frappe.get_all(
            "Item Price",
            fields=["item_code", "price_list_rate", "currency"],
            filters={
                "item_code": ["in", item_codes],
                "selling": 1,
                "price_list": frappe.db.get_single_value('Shopping Cart Settings', 'price_list')
            }
        )
        
        for price in price_list:
            prices[price.item_code] = {
                "price": flt(price.price_list_rate),
                "currency": price.currency,
                "formatted_price": frappe.format_value(
                    price.price_list_rate,
                    {"fieldtype": "Currency", "currency": price.currency}
                )
            }
            
        return prices

    @staticmethod
    def _get_bulk_stock(item_codes):
        """Get stock info for multiple items efficiently"""
        stock = {}
        bin_data = frappe.db.sql("""
            SELECT 
                item_code,
                SUM(actual_qty) as total_qty,
                SUM(reserved_qty) as reserved_qty
            FROM `tabBin`
            WHERE item_code IN %s
            GROUP BY item_code
        """, [tuple(item_codes)], as_dict=1)
        
        for item in bin_data:
            available_qty = flt(item.total_qty) - flt(item.reserved_qty)
            stock[item.item_code] = {
                "in_stock": available_qty > 0,
                "available_qty": available_qty,
                "total_qty": item.total_qty
            }
            
        return stock

    @staticmethod
    def _get_sort_params(sort_by):
        """Get sort field and order based on sort parameter"""
        sort_mapping = {
            "price_asc": ("price_list_rate", "asc"),
            "price_desc": ("price_list_rate", "desc"),
            "name_asc": ("item_name", "asc"),
            "name_desc": ("item_name", "desc"),
            "newest": ("creation", "desc"),
            "ranking": ("ranking", "desc")
        }
        return sort_mapping.get(sort_by, ("item_name", "asc"))

    @staticmethod
    @frappe.whitelist(allow_guest=True)
    def get_item_details(item_code):
        """Get detailed information for a single item"""
        try:
            # Get Website Item information
            web_item = frappe.get_all(
                "Website Item",
                filters={"item_code": item_code, "published": 1},
                fields=[
                    "name", "item_code", "item_name", "item_group",
                    "description", "website_image", "route",
                    "website_description", "ranking", "thumbnail"
                ],
                limit=1
            )
            
            if not web_item:
                return None
                
            item_details = web_item[0]
            
            # Get price information
            prices = ProductAPI._get_bulk_prices([item_code])
            if item_code in prices:
                item_details["price_info"] = prices[item_code]
            
            # Get stock information
            stock = ProductAPI._get_bulk_stock([item_code])
            if item_code in stock:
                item_details["stock_info"] = stock[item_code]
            
            # Add full URLs to images
            item_details["image_url"] = get_url(item_details.get("website_image") or item_details.get("thumbnail"))
            
            return item_details
            
        except Exception as e:
            frappe.log_error(f"Error in get_item_details: {str(e)}")
            return None 