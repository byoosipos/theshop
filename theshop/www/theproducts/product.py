import frappe
from frappe import _
from frappe.utils import flt, cint, get_url

def get_context(context):
    """Get product context for the template"""
    try:
        # Get item code from URL
        item_code = frappe.form_dict.get('item_code')
        if not item_code:
            frappe.throw(_('Item Code is required'))

        # Get Website Item
        website_item = frappe.get_doc('Website Item', {'item_code': item_code})
        if not website_item or not website_item.published:
            frappe.throw(_('Product not found'))

        # Get price information
        price_list = frappe.db.get_single_value('Webshop Settings', 'price_list')
        if price_list:
            price_info = frappe.get_all(
                'Item Price',
                filters={
                    'item_code': item_code,
                    'price_list': price_list,
                    'selling': 1
                },
                fields=['price_list_rate', 'currency'],
                order_by='valid_from desc',
                limit=1
            )
            if price_info:
                website_item.price = flt(price_info[0].price_list_rate)
                website_item.currency = price_info[0].currency
                website_item.formatted_price = frappe.format_value(
                    website_item.price,
                    dict(fieldtype='Currency', currency=website_item.currency)
                )

        # Get stock information
        bin_data = frappe.db.sql("""
            SELECT SUM(actual_qty) as actual_qty
            FROM tabBin
            WHERE item_code = %s
        """, (item_code,), as_dict=1)
        
        website_item.actual_qty = flt(bin_data[0].actual_qty if bin_data else 0)

        # Get additional images
        website_item.images = []
        if website_item.website_image:
            website_item.images.append(website_item.website_image)
        if website_item.image:
            website_item.images.append(website_item.image)
        
        # Get reviews
        website_item.reviews = frappe.get_all(
            'Item Review',
            filters={'item_code': item_code, 'published': 1},
            fields=['reviewer_name', 'rating', 'comment', 'creation'],
            order_by='creation desc'
        )

        # Get related products
        related_products = frappe.get_all(
            'Website Item',
            filters={
                'published': 1,
                'item_group': website_item.item_group,
                'name': ['!=', website_item.name]
            },
            fields=[
                'item_code', 'item_name', 'website_image',
                'route', 'item_group', 'brand'
            ],
            limit=4
        )

        # Add price and stock info to related products
        for product in related_products:
            # Get price
            if price_list:
                price = frappe.get_all(
                    'Item Price',
                    filters={
                        'item_code': product.item_code,
                        'price_list': price_list,
                        'selling': 1
                    },
                    fields=['price_list_rate', 'currency'],
                    order_by='valid_from desc',
                    limit=1
                )
                if price:
                    product.price = flt(price[0].price_list_rate)
                    product.currency = price[0].currency
                    product.formatted_price = frappe.format_value(
                        product.price,
                        dict(fieldtype='Currency', currency=product.currency)
                    )

            # Get stock
            bin_qty = frappe.db.sql("""
                SELECT SUM(actual_qty) as qty
                FROM tabBin
                WHERE item_code = %s
            """, (product.item_code,), as_dict=1)
            product.actual_qty = flt(bin_qty[0].qty if bin_qty else 0)

        context.product = website_item
        context.related_products = related_products
        
        # SEO
        context.metatags = {
            "title": website_item.item_name,
            "description": website_item.description or website_item.item_name,
            "image": website_item.website_image or website_item.image
        }

    except Exception as e:
        frappe.log_error(f"Error in product page: {str(e)}")
        context.error = _("Unable to load product details") 