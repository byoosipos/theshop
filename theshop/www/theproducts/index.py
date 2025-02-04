import frappe
from frappe.utils import flt

@frappe.whitelist(allow_guest=True)
def get_actual_qty(item_code):
    """Get total actual quantity of an item from all warehouses."""
    try:
        # Get sum of quantities from all warehouses
        actual_qty = frappe.db.sql("""
            SELECT IFNULL(SUM(actual_qty), 0) as qty
            FROM tabBin 
            WHERE item_code=%s
        """, (item_code), as_dict=1)
        
        return actual_qty[0].qty if actual_qty else 0
        
    except Exception as e:
        frappe.log_error(f"Error getting actual quantity for item {item_code}: {str(e)}")
        return 0

@frappe.whitelist(allow_guest=True)
def get_published_Item_group():
    """Get all published item groups"""
    try:
        item_groups = frappe.db.sql("""
            SELECT 
                name,
                route,
                image
            FROM `tabItem Group`
            WHERE show_in_website = 1
                                    
        """, as_dict=True)
        
        for group in item_groups:
            # Get item count for each group
            item_count = frappe.db.count('Website Item', 
                filters={'item_group': group['name']})
            
            if item_count > 0:  # Only include groups with items
                group['item_count'] = item_count
            
            # Add default image if none exists
            if not group.get('image'):
                group['image'] = '/files/default-category.png'  # Make sure this default image exists
        
        return item_groups

    except Exception as e:
        frappe.log_error(f"Error getting item groups: {str(e)}")
        return []

@frappe.whitelist(allow_guest=True)
def search_items(query, limit=8):
    """Search items with essential fields"""
    try:
        # Get website items
        items = frappe.db.get_list('Website Item',
            filters={
                'published': 1,
                'item_name': ['like', f'%{query}%']
            },
            fields=[
                'item_name',
                'item_code',
                'stock_qty',
                'route',
                'item_group',
                'thumbnail'
            ],
            limit=limit
        )

        # Get price list
        price_list = frappe.db.get_single_value('Webshop Settings', 'price_list')

        # Get prices for these items using direct SQL query to bypass permission check
        prices = frappe.db.sql("""
            SELECT item_code, price_list_rate 
            FROM `tabItem Price`
            WHERE price_list = %s 
            AND selling = 1
            AND item_code IN %s
        """, (price_list, [item.item_code for item in items]), as_dict=1)

        # Create price lookup
        price_dict = {p.item_code: p.price_list_rate for p in prices}

        # Format results
        formatted_items = []
        for item in items:
            # Add actual quantity from all warehouses
            item['actual_qty'] = get_actual_qty(item.item_code)
            
            # Add thumbnail default if not exists
            if not item.get('thumbnail'):
                item['thumbnail'] = '/files/b92a1d2cde33efb5bcbd296515a03cb2.jpg'
            
            formatted_items.append({
                'item_name': item.item_name,
                'item_code': item.item_code,
                'quantity': item.stock_qty or 0,
                'actual_qty': item.actual_qty,
                'route': item.route or f'/shop/product/{item.item_code}',
                'item_group': item.item_group,
                'thumbnail': item.thumbnail,
                'price': frappe.format_value(
                    price_dict.get(item.item_code, 0), 
                    dict(fieldtype='Currency', currency='NGN')
                )
            })

        return formatted_items

    except Exception as e:
        frappe.log_error(f"Search Items Error: {str(e)}")
        return []

@frappe.whitelist(allow_guest=True)
def get_website_items(query='', limit=12, item_group=None):
    """Get website items based on search query and category"""
    try:
        # Base filters
        filters = {
            'published': 1,
        }
        
        # Add search condition if query exists
        if query:
            filters['item_name'] = ['like', f'%{query}%']
        
        # Add category filter if item_group is provided
        if item_group:
            filters['item_group'] = ['=', item_group]
        
        # Get website items with essential fields
        items = frappe.get_all('Website Item',
            filters=filters,
            fields=[
                'item_name',
                'item_code',
                'thumbnail',
                'route',
                'item_group'
            ],
            limit=limit,
            order_by='creation desc'
        )
        
        # Log the query for debugging
        frappe.logger().debug(f"Website Items Query - Filters: {filters}, Results: {len(items)}")
        
        # Get price list
        price_list = frappe.db.get_single_value('Webshop Settings', 'price_list')
        
        # Get prices for these items
        prices = frappe.get_all('Item Price',
            filters={
                'price_list': price_list,
                'selling': 1,
                'item_code': ['in', [item.item_code for item in items]]
            },
            fields=['item_code', 'price_list_rate']
        )
        
        # Create price lookup
        price_dict = {p.item_code: p.price_list_rate for p in prices}
        
        # Format the response
        for item in items:
            # Add actual quantity from all warehouses
            item['actual_qty'] = get_actual_qty(item.item_code)
            
            # Add price information
            item['price'] = price_dict.get(item.item_code, 0)
            item['formatted_price'] = frappe.format_value(
                item['price'],
                dict(fieldtype='Currency', currency='NGN')
            )
            
            # Ensure image exists
            if not item.get('thumbnail'):
                item['thumbnail'] = '/files/b92a1d2cde33efb5bcbd296515a03cb2.jpg'
            
            # Format the route
            if not item.get('route'):
                item['route'] = f'/shop/product/{item.item_code}'
        
        return items

    except Exception as e:
        frappe.log_error(f"Error fetching website items: {str(e)}")
        return []