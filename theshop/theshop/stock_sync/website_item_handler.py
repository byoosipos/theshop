import frappe
from frappe.utils.data import now_datetime, cint
import traceback
import time

class WebsiteItemHandler:
    def __init__(self):
        try:
            frappe.logger().info("=== Starting Website Item Sync Process ===")
            self.website_warehouse = "All Warehouses - MSO"
            self.default_company = frappe.defaults.get_user_default("company")
            self.processed_items = 0
            self.failed_items = []
            
            # Ensure website warehouse exists
            if not frappe.db.exists("Warehouse", self.website_warehouse):
                frappe.logger().error(f"Website warehouse {self.website_warehouse} does not exist")
                raise Exception(f"Website warehouse {self.website_warehouse} not found")
                
            frappe.logger().info(f"Using website warehouse: {self.website_warehouse}")
        except Exception as e:
            frappe.logger().error(f"Initialization Error: {str(e)}\n{traceback.format_exc()}")
            raise

    def sync_website_items(self):
        """Sync all items to website items"""
        try:
            # Get all active items that should be on website
            items = frappe.get_all(
                "Item",
                fields=[
                    "name", "item_name", "item_group", "description", 
                    "image", "brand", "stock_uom", "weight_per_unit",
                    "weight_uom"
                ],
                filters={
                    "disabled": 0,  # Only active items
                    "show_in_website": 1  # Only items marked for website
                }
            )
            
            if not items:
                frappe.logger().info("No items found for website sync")
                return
            
            total_items = len(items)
            frappe.logger().info(f"Found {total_items} items to process")
            
            for item in items:
                try:
                    self.process_single_item(item)
                    self.processed_items += 1
                    
                    if self.processed_items % 10 == 0:  # Log progress every 10 items
                        frappe.logger().info(f"Processed {self.processed_items}/{total_items} items")
                except Exception as e:
                    error_msg = f"Failed to process website item for {item.name}: {str(e)}"
                    frappe.logger().error(f"{error_msg}\n{traceback.format_exc()}")
                    self.failed_items.append({
                        'item_code': item.name,
                        'error': str(e)
                    })
                    continue
                    
            # Create sync summary
            self.create_sync_summary(total_items)
            
        except Exception as e:
            error_msg = f"Website item sync failed: {str(e)}"
            frappe.logger().error(f"{error_msg}\n{traceback.format_exc()}")
            self.create_sync_summary(0, error_msg)
            raise

    def process_single_item(self, item):
        """Process a single item for website"""
        website_item_exists = frappe.db.exists(
            "Website Item",
            {"item_code": item.name}
        )
        
        # Get stock information
        actual_qty = self.get_item_stock(item.name)
        
        # Get price information
        price_info = self.get_item_price(item.name)
        
        # Create rich product content
        advanced_content = self.create_product_content(item, actual_qty, price_info)
        
        try:
            if website_item_exists:
                # Update existing website item
                website_item = frappe.get_doc("Website Item", {"item_code": item.name})
                self.update_website_item(website_item, item, advanced_content)
                frappe.logger().debug(f"Updated website item for {item.name}")
            else:
                # Create new website item
                self.create_website_item(item, advanced_content)
                frappe.logger().debug(f"Created new website item for {item.name}")
            
            frappe.db.commit()
        except Exception as e:
            frappe.db.rollback()
            raise

    def get_item_stock(self, item_code):
        """Get current stock of item"""
        bin_data = frappe.db.sql("""
            SELECT SUM(actual_qty) as qty
            FROM tabBin
            WHERE item_code = %s
            AND warehouse = %s
        """, (item_code, self.website_warehouse), as_dict=1)
        
        return cint(bin_data[0].qty if bin_data and bin_data[0].qty else 0)

    def get_item_price(self, item_code):
        """Get item price information"""
        price_list = frappe.db.get_single_value('Webshop Settings', 'price_list')
        if not price_list:
            return None
            
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
        
        return price_info[0] if price_info else None

    def create_product_content(self, item, actual_qty, price_info):
        """Create rich HTML content for product display"""
        price_html = ""
        if price_info:
            formatted_price = frappe.format_value(
                price_info.price_list_rate,
                dict(fieldtype='Currency', currency=price_info.currency)
            )
            price_html = f"<p class='product-price'>{formatted_price}</p>"

        return f"""
        <div class="container py-4">
            <div class="row">
                <div class="col-md-12 mb-4">
                    <div class="card">
                        <div class="card-body">
                            <h4 class="card-title">Product Details</h4>
                            <p class="card-text">{item.description or item.item_name}</p>
                            {price_html}
                        </div>
                    </div>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6 mb-4">
                    <div class="card h-100">
                        <div class="card-body">
                            <h4 class="card-title">Features</h4>
                            <ul class="list-unstyled">
                                <li><i class="fa fa-check text-success mr-2"></i>Premium Quality</li>
                                <li><i class="fa fa-check text-success mr-2"></i>Genuine Product</li>
                                <li><i class="fa fa-check text-success mr-2"></i>Best Price Guaranteed</li>
                                <li><i class="fa fa-truck text-success mr-2"></i>Fast Delivery</li>
                            </ul>
                        </div>
                    </div>
                </div>
                <div class="col-md-6 mb-4">
                    <div class="card h-100">
                        <div class="card-body">
                            <h4 class="card-title">Specifications</h4>
                            <table class="table table-sm">
                                <tr>
                                    <th scope="row">Brand</th>
                                    <td>{item.brand or 'Generic'}</td>
                                </tr>
                                <tr>
                                    <th scope="row">Category</th>
                                    <td>{item.item_group}</td>
                                </tr>
                                <tr>
                                    <th scope="row">SKU</th>
                                    <td>{item.name}</td>
                                </tr>
                                <tr>
                                    <th scope="row">Unit</th>
                                    <td>{item.stock_uom}</td>
                                </tr>
                                {f'''<tr>
                                    <th scope="row">Weight</th>
                                    <td>{item.weight_per_unit} {item.weight_uom}</td>
                                </tr>''' if item.weight_per_unit else ''}
                            </table>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """

    def update_website_item(self, website_item, item, content):
        """Update existing website item"""
        website_item.website_warehouse = self.website_warehouse
        website_item.published = 1
        website_item.web_item_name = item.item_name
        website_item.item_name = item.item_name
        website_item.item_group = item.item_group
        website_item.description = item.description
        website_item.brand = item.brand
        website_item.website_content = content
        website_item.save(ignore_permissions=True)

    def create_website_item(self, item, content):
        """Create new website item"""
        website_item = frappe.get_doc({
            "doctype": "Website Item",
            "item_code": item.name,
            "web_item_name": item.item_name,
            "item_name": item.item_name,
            "item_group": item.item_group,
            "description": item.description,
            "brand": item.brand,
            "image": item.image,
            "website_warehouse": self.website_warehouse,
            "website_content": content,
            "published": 1,
            "copy_from_item": 1
        })
        website_item.insert(ignore_permissions=True)

    def create_sync_summary(self, total_items, error_message=None):
        """Create a summary of the sync process"""
        try:
            summary = frappe.get_doc({
                "doctype": "Website Item Sync Summary",
                "start_time": now_datetime(),
                "total_items": total_items,
                "processed_items": self.processed_items,
                "failed_items": len(self.failed_items),
                "status": "Failed" if error_message or self.failed_items else "Success",
                "error_message": error_message or "\n".join([
                    f"Item: {item['item_code']} - Error: {item['error']}"
                    for item in self.failed_items
                ]) if self.failed_items else ""
            })
            summary.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Failed to create sync summary: {str(e)}")

def sync_all_website_items():
    """Function to be called by scheduler"""
    start_time = time.time()
    
    try:
        handler = WebsiteItemHandler()
        handler.sync_website_items()
    except Exception as e:
        frappe.logger().error(f"Website item sync failed: {str(e)}")
    finally:
        end_time = time.time()
        frappe.logger().info(f"Website sync completed in {end_time - start_time:.2f} seconds") 