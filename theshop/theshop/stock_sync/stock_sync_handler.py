import frappe
import pymysql
from frappe.utils.data import now_datetime, cint
import traceback
import time
from contextlib import contextmanager

MAX_RETRIES = 3
RETRY_DELAY = 5
CONNECT_TIMEOUT = 30

@contextmanager
def database_connection(config):
    """Context manager for database connections with retry logic"""
    retries = 0
    last_error = None
    
    while retries < MAX_RETRIES:
        try:
            conn = pymysql.connect(
                host=config.db_host,
                port=config.db_port or 3306,
                user=config.db_user,
                password=config.db_password,
                database=config.db_name,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=CONNECT_TIMEOUT,
                read_timeout=300,
                write_timeout=300,
                ssl_disabled=True  # Disable SSL for local network
            )
            try:
                yield conn
                return  # Connection successful, exit the context manager
            finally:
                conn.close()
        except pymysql.Error as e:
            last_error = e
            retries += 1
            if retries < MAX_RETRIES:
                frappe.logger().warning(f"Database connection attempt {retries} failed: {str(e)}. Retrying in {RETRY_DELAY} seconds...")
                time.sleep(RETRY_DELAY)
    
    # If we get here, all retries failed
    raise Exception(f"Failed to connect to database after {MAX_RETRIES} attempts. Last error: {str(last_error)}")

class StockSyncHandler:
    def __init__(self):
        try:
            frappe.logger().info("=== Starting Stock Sync Process ===")
            self.settings = frappe.get_all(
                "Remote Site Settings",
                fields=["name", "remote_warehouse", "local_warehouse", "db_host", 
                       "db_port", "db_name", "db_user", "db_password",
                       "sync_item_groups", "sync_items", "sync_prices", 
                       "sync_stock", "sync_website_items",
                       "auto_create_item_groups", "auto_create_items",
                       "auto_update_prices", "auto_publish_items"],
                filters={"enabled": 1}  # Only get enabled settings
            )
            if not self.settings:
                raise Exception("No enabled remote site settings found")
                
            frappe.logger().info(f"Initialized with {len(self.settings)} remote site settings")
            self.item_groups_cache = {}
            self.price_lists_cache = set()
            self.default_company = frappe.defaults.get_user_default("company")
            frappe.logger().info(f"Using default company: {self.default_company}")
        except Exception as e:
            frappe.logger().error(f"Initialization Error: {str(e)}\n{traceback.format_exc()}")
            raise

    def sync_stock_from_remote(self):
        """Sync stock from all configured remote sites"""
        if not self.settings:
            frappe.logger().error("No remote site settings found. Aborting sync.")
            return

        total_sites = len(self.settings)
        processed_sites = 0
        failed_sites = []

        frappe.logger().info(f"Starting sync for {total_sites} remote sites")
        
        for site in self.settings:
            try:
                site_doc = frappe.get_doc("Remote Site Settings", site.name)
                frappe.logger().info(f"=== Processing Site {processed_sites + 1}/{total_sites} ===")
                frappe.logger().info(f"Remote Warehouse: {site.remote_warehouse}")
                frappe.logger().info(f"Local Warehouse: {site.local_warehouse}")
                frappe.logger().info(f"DB Host: {site.db_host}")
                
                # Call the site-specific sync function
                site_doc.sync_selected_functions()
                
                self.create_sync_log(site.remote_warehouse, "Success")
                frappe.logger().info(f"Successfully completed sync for warehouse: {site.remote_warehouse}")
                
            except Exception as e:
                error_trace = traceback.format_exc()
                frappe.logger().error(f"Failed to sync warehouse {site.remote_warehouse}:\n{error_trace}")
                self.create_sync_log(site.remote_warehouse, "Failed", f"{str(e)}\n{error_trace}")
                failed_sites.append(site.remote_warehouse)
            
            processed_sites += 1
            
        # Final summary
        success_count = processed_sites - len(failed_sites)
        frappe.logger().info(f"=== Sync Summary ===")
        frappe.logger().info(f"Total Sites: {total_sites}")
        frappe.logger().info(f"Successful: {success_count}")
        frappe.logger().info(f"Failed: {len(failed_sites)}")
        if failed_sites:
            frappe.logger().info(f"Failed Sites: {', '.join(failed_sites)}")

    def ensure_item_group_exists(self, item_group):
        """Ensure item group exists in local system"""
        if item_group in self.item_groups_cache:
            return self.item_groups_cache[item_group]

        if not frappe.db.exists("Item Group", item_group):
            try:
                group_doc = frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": item_group,
                    "parent_item_group": "All Item Groups"
                })
                group_doc.insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.logger().error(f"Failed to create item group {item_group}: {str(e)}")
                return "Products"  # Fallback to default group
        
        self.item_groups_cache[item_group] = item_group
        return item_group

    def ensure_price_list_exists(self, price_list_name):
        """Ensure price list exists in local system"""
        if price_list_name in self.price_lists_cache:
            return True

        if not frappe.db.exists("Price List", price_list_name):
            try:
                price_list = frappe.get_doc({
                    "doctype": "Price List",
                    "price_list_name": price_list_name,
                    "currency": "NGN",
                    "selling": 1
                })
                price_list.insert(ignore_permissions=True)
                frappe.db.commit()
                self.price_lists_cache.add(price_list_name)
                return True
            except Exception as e:
                frappe.logger().error(f"Failed to create price list {price_list_name}: {str(e)}")
                return False
        
        self.price_lists_cache.add(price_list_name)
        return True

    def sync_single_site(self, site_config):
        """Sync stock from a single remote site using direct database access"""
        try:
            frappe.logger().info(f"Attempting database connection to: {site_config.db_host}")
            
            with database_connection(site_config) as conn:
                with conn.cursor() as cursor:
                    frappe.logger().info("Fetching items data...")
                    query = """
                        SELECT DISTINCT 
                            b.item_code, i.item_name, i.item_group, 
                            i.description, i.stock_uom, b.actual_qty,
                            i.has_batch_no, i.has_serial_no, i.is_stock_item,
                            ig.parent_item_group, ig.is_group
                        FROM tabBin b
                        JOIN tabItem i ON b.item_code = i.name
                        LEFT JOIN `tabItem Group` ig ON i.item_group = ig.name
                        WHERE b.warehouse = %s
                        AND i.disabled = 0  -- Only get active items
                    """
                    cursor.execute(query, (site_config.remote_warehouse,))
                    items_data = cursor.fetchall()
                    
                    if not items_data:
                        frappe.logger().warning(f"No items found in warehouse {site_config.remote_warehouse}")
                        return
                        
                    frappe.logger().info(f"Retrieved {len(items_data)} items from remote")
                    
                    frappe.logger().info("Fetching price data...")
                    price_query = """
                        SELECT DISTINCT 
                            ip.item_code, ip.price_list, ip.price_list_rate,
                            pl.currency
                        FROM `tabItem Price` ip
                        JOIN `tabPrice List` pl ON ip.price_list = pl.name
                        WHERE ip.item_code IN (
                            SELECT DISTINCT b.item_code 
                            FROM tabBin b 
                            WHERE b.warehouse = %s
                        )
                    """
                    cursor.execute(price_query, (site_config.remote_warehouse,))
                    price_data = cursor.fetchall()
                    frappe.logger().info(f"Retrieved {len(price_data)} price records")
                    
                    # Process items and update stock
                    stock_dict = {}
                    price_dict = {}
                    for price in price_data:
                        if price['item_code'] not in price_dict:
                            price_dict[price['item_code']] = []
                        price_dict[price['item_code']].append(price)
                    
                    frappe.logger().info("Processing items and updating stock...")
                    processed_items = 0
                    for item in items_data:
                        if not item['item_code']:
                            continue
                            
                        try:
                            frappe.logger().debug(f"Processing item: {item['item_code']}")
                            item_group = self.process_item_group(item)
                            self.process_single_item(item, item_group, site_config)
                            
                            if item['item_code'] in price_dict:
                                self.sync_item_prices(item['item_code'], price_dict[item['item_code']])
                            
                            stock_dict[item['item_code']] = item['actual_qty']
                            processed_items += 1
                            
                            if processed_items % 10 == 0:  # Log progress every 10 items
                                frappe.logger().info(f"Processed {processed_items}/{len(items_data)} items")
                        except Exception as e:
                            frappe.logger().error(f"Error processing item {item['item_code']}: {str(e)}")
                            continue
                    
                    frappe.logger().info("Updating local stock...")
                    updated_count = self.update_local_stock(
                        site_config.local_warehouse,
                        stock_dict
                    )
                    
                    frappe.logger().info(f"Completed: Updated {updated_count} items in {site_config.local_warehouse}")
                    
        except Exception as e:
            frappe.logger().error(f"Sync failed: {str(e)}\n{traceback.format_exc()}")
            raise Exception(f"Sync failed: {str(e)}")

    def process_item_group(self, item):
        """Process item group hierarchy"""
        item_group = item['item_group']
        if item['parent_item_group']:
            parent_group = self.ensure_item_group_exists(item['parent_item_group'])
            if parent_group != "Products":
                item_group = self.ensure_item_group_exists(item['item_group'])
        else:
            item_group = self.ensure_item_group_exists(item['item_group'])
        return item_group

    def process_single_item(self, item, item_group, site_config):
        """Process a single item"""
        if not frappe.db.exists("Item", item['item_code']):
            try:
                item_defaults = [{"company": self.default_company}]
                item_doc = frappe.get_doc({
                    "doctype": "Item",
                    "item_code": item['item_code'],
                    "item_name": item['item_name'],
                    "item_group": item_group,
                    "description": item['description'] or item['item_name'],
                    "stock_uom": item['stock_uom'] or "Nos",
                    "is_stock_item": item['is_stock_item'] or 1,
                    "has_batch_no": item['has_batch_no'] or 0,
                    "has_serial_no": item['has_serial_no'] or 0,
                    "disabled": 0,
                    "include_item_in_manufacturing": 0,
                    "item_defaults": item_defaults
                })
                item_doc.insert(ignore_permissions=True)
                frappe.logger().info(f"Created new item: {item['item_code']}")
            except Exception as e:
                frappe.logger().error(f"Failed to create item {item['item_code']}: {str(e)}")
                raise
        else:
            try:
                existing_item = frappe.get_doc("Item", item['item_code'])
                if existing_item.item_group != item_group:
                    existing_item.item_group = item_group
                    existing_item.save(ignore_permissions=True)
                    frappe.logger().info(f"Updated item group for {item['item_code']} to {item_group}")
            except Exception as e:
                frappe.logger().error(f"Failed to update item {item['item_code']}: {str(e)}")
                raise

    def sync_item_prices(self, item_code, prices):
        """Sync item prices from remote to local"""
        for price_data in prices:
            try:
                if not self.ensure_price_list_exists(price_data['price_list']):
                    continue

                # Check if price already exists
                existing_price = frappe.db.get_value(
                    "Item Price",
                    {
                        "item_code": item_code,
                        "price_list": price_data['price_list']
                    },
                    "name"
                )

                if existing_price:
                    price_doc = frappe.get_doc("Item Price", existing_price)
                    if price_doc.price_list_rate != price_data['price_list_rate']:
                        price_doc.price_list_rate = price_data['price_list_rate']
                        price_doc.save(ignore_permissions=True)
                        frappe.logger().debug(f"Updated price for {item_code} in {price_data['price_list']}")
                else:
                    price_doc = frappe.get_doc({
                        "doctype": "Item Price",
                        "item_code": item_code,
                        "price_list": price_data['price_list'],
                        "price_list_rate": price_data['price_list_rate']
                    })
                    price_doc.insert(ignore_permissions=True)
                    frappe.logger().debug(f"Created new price for {item_code} in {price_data['price_list']}")

            except Exception as e:
                frappe.logger().error(f"Failed to sync price for {item_code}: {str(e)}")
                continue

    def update_local_stock(self, warehouse, stock_data):
        """Update local bin entries with remote stock data"""
        updated_count = 0
        errors = []
        
        for item_code, qty in stock_data.items():
            try:
                # First ensure item exists
                if not frappe.db.exists("Item", item_code):
                    frappe.logger().error(f"Item {item_code} does not exist in local system")
                    continue

                # Then check warehouse exists
                if not frappe.db.exists("Warehouse", warehouse):
                    frappe.logger().error(f"Warehouse {warehouse} does not exist in local system")
                    continue

                bin_name = frappe.db.get_value(
                    "Bin",
                    {"item_code": item_code, "warehouse": warehouse},
                    "name"
                )
                
                if bin_name:
                    bin_doc = frappe.get_doc("Bin", bin_name)
                    if bin_doc.actual_qty != cint(qty):
                        bin_doc.db_set('actual_qty', cint(qty))
                        updated_count += 1
                        frappe.logger().debug(f"Updated {item_code} in {warehouse} to {qty}")
                else:
                    try:
                        bin_doc = frappe.new_doc("Bin")
                        bin_doc.item_code = item_code
                        bin_doc.warehouse = warehouse
                        bin_doc.actual_qty = cint(qty)
                        bin_doc.insert(ignore_permissions=True)
                        updated_count += 1
                        frappe.logger().debug(f"Created new bin for {item_code} in {warehouse} with qty {qty}")
                    except Exception as bin_error:
                        frappe.logger().error(f"Failed to create bin for {item_code}: {str(bin_error)}")
                        continue

            except Exception as e:
                frappe.logger().error(f"Error updating stock for {item_code}: {str(e)}")
                continue

        try:
            frappe.db.commit()
        except Exception as commit_error:
            frappe.logger().error(f"Failed to commit stock updates: {str(commit_error)}")
            frappe.db.rollback()
            
        return updated_count

    def create_sync_log(self, remote_warehouse, status, error_message=None):
        """Create sync log with full error message"""
        try:
            log = frappe.get_doc({
                "doctype": "Stock Sync Log",
                "timestamp": now_datetime(),
                "remote_warehouse": remote_warehouse,
                "status": status,
                "error_message": error_message if error_message else ""
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Failed to create sync log: {str(e)}")

def sync_all_sites():
    """Function to be called by scheduler"""
    start_time = time.time()
    success = False
    error_message = None
    
    try:
        handler = StockSyncHandler()
        handler.sync_stock_from_remote()
        success = True
    except Exception as e:
        error_message = f"Stock sync failed: {str(e)}\n{traceback.format_exc()}"
        frappe.logger().error(error_message)
    finally:
        end_time = time.time()
        duration = end_time - start_time
        
        # Create a summary log
        try:
            log = frappe.get_doc({
                "doctype": "Stock Sync Summary",
                "start_time": now_datetime(),
                "duration": duration,
                "status": "Success" if success else "Failed",
                "error_message": error_message or "",
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as log_error:
            frappe.logger().error(f"Failed to create sync summary log: {str(log_error)}") 