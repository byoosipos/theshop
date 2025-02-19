import frappe
import traceback
import time
from theshop.theshop.stock_sync.website_item_handler import WebsiteItemHandler
from theshop.theshop.stock_sync.db_utils import get_remote_connection
from .base_handler import BaseSyncHandler

class StockSyncHandler(BaseSyncHandler):
    def __init__(self):
        super().__init__()
        try:
            frappe.logger().info("=== Starting Stock Sync Process ===")
            self.settings = self.get_enabled_settings()
            if not self.settings:
                raise Exception("No enabled remote site settings found")
                
            frappe.logger().info(f"Initialized with {len(self.settings)} remote site settings")
            
            # Initialize company filters
            for setting in self.settings:
                if setting.sync_company_items_only:
                    self.setup_company_filters(
                        remote_company=setting.remote_company,
                        local_company=setting.local_company
                    )
                    break  # Use first enabled company filter
                    
            frappe.logger().info(
                "Company filtering: " + 
                ("Enabled" if self.company_filters.get('is_enabled') else "Disabled")
            )
        except Exception as e:
            frappe.logger().error(f"Initialization Error: {str(e)}\n{traceback.format_exc()}")
            raise

    def get_enabled_settings(self):
        """Get all enabled remote site settings"""
        try:
            settings = frappe.get_all(
                "Remote Site Settings",
                filters={
                    "enabled": 1  # Only check if the site is enabled
                },
                fields=[
                    "name", "remote_warehouse", "local_warehouse",
                    "sync_company_items_only", "remote_company", "local_company",
                    "sync_item_groups", "sync_items", "sync_prices",
                    "sync_stock", "sync_website_items",
                    "auto_create_item_groups", "auto_create_items",
                    "auto_update_prices", "auto_publish_items"
                ]
            )
            
            if not settings:
                frappe.logger().warning("No enabled remote site settings found")
                return []
                
            # Convert to full documents to access all methods
            settings_docs = [frappe.get_doc("Remote Site Settings", s.name) for s in settings]
            
            # Log what we're syncing for each site
            for doc in settings_docs:
                frappe.logger().info(f"""
                    Site {doc.name} sync options:
                    - Item Groups: {doc.sync_item_groups}
                    - Items: {doc.sync_items}
                    - Prices: {doc.sync_prices}
                    - Stock: {doc.sync_stock}
                    - Website Items: {doc.sync_website_items}
                """)
            
            return settings_docs
            
        except Exception as e:
            frappe.logger().error(f"Failed to get enabled settings: {str(e)}")
            return []

    def sync_stock_from_remote(self):
        try:
            self.update_sync_status('In Progress')
            if not self.can_sync():
                frappe.logger().info("Sync skipped - rate limit reached")
                return
            """Handle stock synchronization based on individual site settings"""
            for site_config in self.settings:
                frappe.logger().info(f"Processing site: {site_config.name}")
                
                try:
                    with get_remote_connection(site_config) as conn:
                        # Process based on enabled options
                        if site_config.sync_item_groups and site_config.auto_create_item_groups:
                            frappe.logger().info(f"Syncing item groups for {site_config.name}")
                            self.sync_item_groups(conn, site_config)
                            
                        if site_config.sync_items and site_config.auto_create_items:
                            frappe.logger().info(f"Syncing items for {site_config.name}")
                            self.sync_items(conn, site_config)
                            
                        if site_config.sync_stock:
                            frappe.logger().info(f"Syncing stock for {site_config.name}")
                            self.sync_stock(conn, site_config)
                            
                        if site_config.sync_website_items and site_config.auto_publish_items:
                            frappe.logger().info(f"Syncing website items for {site_config.name}")
                            self.sync_website_items(site_config)
                            
                        frappe.logger().info(f"Completed processing for site: {site_config.name}")
                except Exception as site_error:
                    frappe.logger().error(f"Error processing site {site_config.name}: {str(site_error)}")
                    continue
                
            self.update_sync_status('Completed')
        except Exception as e:
            self.update_sync_status('Failed', str(e))
            raise

    def sync_item_groups(self, conn, site_config):
        """Sync item groups focusing on name, group status, parent group, and company defaults"""
        try:
            with conn.cursor() as cursor:
                # Query including parent item group
                cursor.execute("""
                    SELECT DISTINCT
                        ig.name,
                        ig.item_group_name,
                        ig.is_group,
                        ig.parent_item_group,
                        igd.company
                    FROM `tabItem Group` ig
                    LEFT JOIN `tabItem Group Default` igd ON ig.name = igd.parent
                    WHERE ig.name != 'All Item Groups'
                    AND (
                        igd.company = %(company)s
                        OR igd.company IS NULL
                    )
                    ORDER BY ig.lft ASC  # Ensure parent groups are processed first
                """, {'company': self.company_filters.get('remote_company')})
                
                groups = cursor.fetchall()
                frappe.logger().info(f"Found {len(groups)} company-specific item groups to sync")
                
                # Track renamed groups to update parent references
                renamed_groups = {}
                
                # Process each group
                for group in groups:
                    existing = frappe.db.get_value(
                        "Item Group",
                        {"item_group_name": group['item_group_name']},
                        ["name", "is_group", "item_group_name", "parent_item_group"],
                        as_dict=True
                    )
                    
                    if existing:
                        # Handle existing group updates
                        doc = frappe.get_doc("Item Group", existing.name)
                        needs_update = False
                        
                        # Check for name change
                        if doc.item_group_name != group['item_group_name']:
                            old_name = doc.name
                            renamed_groups[old_name] = group['name']
                            frappe.rename_doc("Item Group", old_name, group['name'], force=True)
                            doc = frappe.get_doc("Item Group", group['name'])  # Get renamed doc
                            frappe.logger().info(f"Renamed item group from {old_name} to {group['name']}")
                        
                        # Update parent if changed
                        parent_group = group['parent_item_group'] or 'All Item Groups'
                        if parent_group in renamed_groups:
                            parent_group = renamed_groups[parent_group]
                        
                        if doc.parent_item_group != parent_group:
                            doc.parent_item_group = parent_group
                            needs_update = True
                            frappe.logger().info(f"Updating parent group for {doc.name} to {parent_group}")
                        
                        # Check for group status change
                        if doc.is_group != group['is_group']:
                            # Validate before changing group status
                            if not group['is_group']:
                                has_children = frappe.db.exists("Item Group", {"parent_item_group": doc.name})
                                if has_children:
                                    frappe.logger().warning(f"Cannot convert {doc.name} to non-group: Has child items/groups")
                                    continue
                            doc.is_group = group['is_group']
                            needs_update = True
                            frappe.logger().info(f"Updating group status for {doc.name} to {group['is_group']}")
                        
                        # Update company defaults if needed
                        if group.get('company'):
                            has_company = False
                            for d in doc.get("item_group_defaults", []):
                                if d.company == group['company']:
                                    has_company = True
                                    break
                            
                            if not has_company:
                                doc.append("item_group_defaults", {
                                    "company": group['company']
                                })
                                needs_update = True
                                frappe.logger().info(f"Adding company default {group['company']} to {doc.name}")
                        
                        if needs_update:
                            doc.save(ignore_permissions=True)
                    
                    else:
                        # Create new group
                        parent_group = group['parent_item_group'] or 'All Item Groups'
                        if parent_group in renamed_groups:
                            parent_group = renamed_groups[parent_group]
                            
                        new_group = frappe.get_doc({
                            "doctype": "Item Group",
                            "item_group_name": group['item_group_name'],
                            "is_group": group['is_group'],
                            "parent_item_group": parent_group,
                            "__islocal": 1
                        })
                        
                        # Add company default if specified
                        if group.get('company'):
                            new_group.append("item_group_defaults", {
                                "company": group['company']
                            })
                        
                        new_group.insert(ignore_permissions=True)
                        frappe.logger().info(f"Created new item group: {group['item_group_name']} under {parent_group}")
                
                frappe.db.commit()
                
        except Exception as e:
            frappe.logger().error(f"Error in sync_item_groups: {str(e)}")
            frappe.db.rollback()
            raise

    def process_group_conversion(self, group_name, new_group_data):
        """Handle conversion between regular group and group container"""
        try:
            group_doc = frappe.get_doc("Item Group", group_name)
            
            if not group_doc.is_group and new_group_data['is_group']:
                # Converting to group container
                group_doc.is_group = 1
                frappe.logger().info(f"Converting {group_name} to group container")
                
            elif group_doc.is_group and not new_group_data['is_group']:
                # Converting from group container to regular group
                # Check for child items/groups first
                has_children = frappe.db.exists("Item Group", {"parent_item_group": group_name})
                if has_children:
                    frappe.logger().warning(
                        f"Cannot convert {group_name} to non-group: Has child items/groups"
                    )
                    return
                
                group_doc.is_group = 0
                frappe.logger().info(f"Converting {group_name} to regular group")
            
            if group_doc.has_changed():
                group_doc.save(ignore_permissions=True)
                
        except Exception as e:
            frappe.logger().error(f"Error in process_group_conversion for {group_name}: {str(e)}")
            raise

    def process_item_group(self, item):
        """Process item group with company validation"""
        try:
            item_group_name = item['item_group']
            
            # Check if item group exists
            existing_group = frappe.db.exists("Item Group", item_group_name)
            
            if existing_group:
                group_doc = frappe.get_doc("Item Group", item_group_name)
                needs_update = False
                
                # Check if parent needs update
                if group_doc.parent_item_group != item['parent_item_group']:
                    group_doc.parent_item_group = item['parent_item_group']
                    needs_update = True
                
                # Check if is_group needs update
                if group_doc.is_group != item['is_group']:
                    group_doc.is_group = item['is_group']
                    needs_update = True
                
                if needs_update:
                    group_doc.save(ignore_permissions=True)
                    frappe.logger().info(f"Updated item group: {item_group_name}")
                
            else:
                # Create new item group
                group_doc = frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": item.get('item_group_name', item_group_name),
                    "parent_item_group": item['parent_item_group'],
                    "is_group": item['is_group'],
                    "__islocal": 1
                })
                
                # Add company default if specified
                if item.get('company'):
                    group_doc.append("item_group_defaults", {
                        "company": item['company']
                    })
                    
                group_doc.insert(ignore_permissions=True)
                frappe.logger().info(f"Created new item group: {item_group_name}")
            
            return item_group_name
            
        except Exception as e:
            frappe.logger().error(f"Error processing item group {item['item_group']}: {str(e)}")
            frappe.db.rollback()
            return "Products"  # Fallback to default group

    def sync_items(self, conn, site_config):
        """Sync items from remote"""
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT name, item_name, item_group, description, 
                       stock_uom, has_batch_no, has_serial_no, is_stock_item
                FROM `tabItem`
                WHERE disabled = 0
            """)
            items = cursor.fetchall()
            
            for item in items:
                self.process_single_item(item, item['item_group'], site_config)

    def sync_stock(self, conn, site_config):
        """Sync stock levels from remote"""
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT item_code, actual_qty 
                    FROM `tabBin`
                    WHERE warehouse = %s
                """, (site_config.remote_warehouse,))
                stock_data = cursor.fetchall()
                
                if not stock_data:
                    frappe.logger().warning(f"No stock data found for warehouse {site_config.remote_warehouse}")
                    return
                    
                stock_dict = {item['item_code']: item['actual_qty'] for item in stock_data}
                self.update_local_stock(site_config.local_warehouse, stock_dict)
                
        except Exception as e:
            frappe.logger().error(f"Stock sync failed: {str(e)}\n{traceback.format_exc()}")
            self.create_sync_log(
                site_config.remote_warehouse, 
                "Failed",
                f"Stock sync error: {str(e)}"
            )
            raise

    def sync_website_items(self, site_config):
        """Sync website items"""
        website_handler = WebsiteItemHandler()
        website_handler.sync_website_items(site_config)

    def update_local_stock(self, warehouse, stock_data):
        """Update bin entries with validation and batching"""
        batch_size = 100  # Process in smaller chunks
        for i in range(0, len(stock_data.items()), batch_size):
            batch = dict(list(stock_data.items())[i:i + batch_size])
            frappe.db.begin()
            try:
                for item_code, qty in batch.items():
                    if not frappe.db.exists("Item", item_code):
                        frappe.logger().error(f"Item {item_code} does not exist locally")
                        self.failed += 1
                        continue
                        
                    if qty < 0:
                        frappe.logger().warning(f"Negative stock quantity for {item_code}: {qty}")
                    
                    bin_name = frappe.db.get_value(
                        "Bin",
                        {"item_code": item_code, "warehouse": warehouse},
                        "name"
                    )

                    if bin_name:
                        bin_doc = frappe.get_doc("Bin", bin_name)
                        if bin_doc.actual_qty != qty:
                            bin_doc.actual_qty = qty
                            bin_doc.save(ignore_permissions=True)
                    else:
                        bin_doc = frappe.get_doc({
                            "doctype": "Bin",
                            "item_code": item_code,
                            "warehouse": warehouse,
                            "actual_qty": qty
                        })
                        bin_doc.insert(ignore_permissions=True)
                    
                    self.processed += 1
                    
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                frappe.logger().error(
                    f"Batch stock update failed: {str(e)}\n{traceback.format_exc()}"
                )
                self.failed += len(batch)

    def sync_single_site(self, site_config):
        """Sync stock from a single remote site using direct database access"""
        try:
            frappe.logger().info(f"Attempting database connection to: {site_config.db_host}")
            
            # Update company filters for this site if needed
            if site_config.sync_company_items_only:
                self.setup_company_filters(
                    remote_company=site_config.remote_company,
                    local_company=site_config.local_company
                )
            
            with get_remote_connection(site_config) as conn:
                with conn.cursor() as cursor:
                    frappe.logger().info("Fetching items data...")
                    
                    # Base query
                    base_query = """
                        SELECT DISTINCT 
                            b.item_code, i.item_name, i.item_group, 
                            i.description, i.stock_uom, b.actual_qty,
                            i.has_batch_no, i.has_serial_no, i.is_stock_item,
                            ig.parent_item_group, ig.is_group,
                            GROUP_CONCAT(
                                CONCAT(ucd.uom, ':', ucd.conversion_factor)
                                SEPARATOR '|'
                            ) as uom_conversions,
                            MAX(CASE WHEN ip.price_list = 'Standard Selling' THEN ip.price_list_rate ELSE NULL END) as selling_price,
                            MAX(CASE WHEN ip.price_list = 'Standard Buying' THEN ip.price_list_rate ELSE NULL END) as buying_price
                        FROM tabBin b
                        JOIN tabItem i ON b.item_code = i.name
                        LEFT JOIN `tabItem Group` ig ON i.item_group = ig.name
                        LEFT JOIN `tabUOM Conversion Detail` ucd ON ucd.parent = i.name
                        LEFT JOIN `tabWarehouse` w ON b.warehouse = w.name
                        LEFT JOIN `tabItem Default` id ON id.parent = i.name
                        LEFT JOIN `tabItem Price` ip ON ip.item_code = i.name 
                            AND ip.price_list IN ('Standard Selling', 'Standard Buying')
                        WHERE b.warehouse = %(warehouse)s
                        AND i.disabled = 0
                    """
                    
                    # Add company filtering if enabled
                    if self.company_filters.get('is_enabled'):
                        base_query += """ 
                        AND (
                            w.company = %(company)s
                            OR id.company = %(company)s
                            OR EXISTS (
                                SELECT 1 FROM `tabItem Price` ip 
                                WHERE ip.item_code = i.name 
                                AND ip.company = %(company)s
                            )
                        )
                        """
                    
                    base_query += " GROUP BY b.item_code"
                    
                    # Prepare query parameters
                    params = {
                        'warehouse': site_config.remote_warehouse,
                        **self.get_company_query_params()
                    }
                    
                    cursor.execute(base_query, params)
                    items_data = cursor.fetchall()
                    
                    if not items_data:
                        frappe.logger().warning(f"No items found in warehouse {site_config.remote_warehouse}")
                        return
                        
                    frappe.logger().info(f"Retrieved {len(items_data)} items from remote")
                    
                    # Process items with UOM conversions
                    for item in items_data:
                        if item.get('uom_conversions'):
                            uom_list = []
                            for conv in item['uom_conversions'].split('|'):
                                if ':' in conv:
                                    uom, factor = conv.split(':')
                                    uom_list.append({
                                        'uom': uom,
                                        'conversion_factor': float(factor)
                                    })
                            item['uom_conversions'] = uom_list

                    # Process items and update stock
                    stock_dict = {}
                    processed_items = 0
                    
                    for item in items_data:
                        if not item['item_code']:
                            continue
                            
                        try:
                            # Validate company access
                            if self.company_filters.get('is_enabled'):
                                if not self.validate_company_access(
                                    item['item_code'], 
                                    self.company_filters['remote_company']
                                ):
                                    frappe.logger().warning(
                                        f"Skipping item {item['item_code']} - No company access"
                                    )
                                    continue
                            
                            frappe.logger().debug(f"Processing item: {item['item_code']}")
                            item_group = self.process_item_group(item)
                            self.process_single_item(item, item_group, site_config)
                            
                            # Handle price syncing with clearer logic
                            if site_config.sync_prices:  # Master switch for price syncing
                                prices = []
                                if item.get('selling_price'):
                                    prices.append({
                                        'price_list': 'Standard Selling',
                                        'price_list_rate': item['selling_price']
                                    })
                                if item.get('buying_price'):
                                    prices.append({
                                        'price_list': 'Standard Buying',
                                        'price_list_rate': item['buying_price']
                                    })
                                    
                                if prices and site_config.auto_update_prices:  # Control automatic updates
                                    frappe.logger().info(f"Auto-updating prices for item {item['item_code']}")
                                    self.sync_item_prices(item['item_code'], prices)
                                elif prices:
                                    frappe.logger().info(f"Prices available for {item['item_code']} but auto-update disabled")
                            
                            stock_dict[item['item_code']] = item['actual_qty']
                            processed_items += 1
                            
                            if processed_items % 10 == 0:
                                frappe.logger().info(f"Processed {processed_items}/{len(items_data)} items")
                        except Exception as e:
                            frappe.logger().error(f"Error processing item {item['item_code']}: {str(e)}")
                            continue
                    
                    frappe.logger().info("Updating local stock...")
                    self.update_local_stock(
                        site_config.local_warehouse,
                        stock_dict
                    )
                    
                    frappe.logger().info(f"Completed: Updated {processed_items} items in {site_config.local_warehouse}")
                    
        except Exception as e:
            frappe.logger().error(f"Sync failed: {str(e)}\n{traceback.format_exc()}")
            raise Exception(f"Sync failed: {str(e)}")

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

                # Prepare common price data
                price_list_data = {
                    "item_code": item_code,
                    "price_list": price_data['price_list'],
                    "price_list_rate": price_data['price_list_rate'],
                    "currency": "NGN",
                    "selling": 1 if price_data['price_list'] == 'Standard Selling' else 0,
                    "buying": 1 if price_data['price_list'] == 'Standard Buying' else 0,
                    "valid_from": frappe.utils.nowdate()
                }

                if existing_price:
                    price_doc = frappe.get_doc("Item Price", existing_price)
                    if price_doc.price_list_rate != price_data['price_list_rate']:
                        # Update only if price has changed
                        price_doc.update(price_list_data)
                        price_doc.save(ignore_permissions=True)
                        frappe.logger().info(
                            f"Updated price for {item_code} in {price_data['price_list']}: "
                            f"Old: {price_doc.price_list_rate} -> New: {price_data['price_list_rate']}"
                        )
                else:
                    price_doc = frappe.get_doc({
                        "doctype": "Item Price",
                        **price_list_data
                    })
                    price_doc.insert(ignore_permissions=True)
                    frappe.logger().info(
                        f"Created new price for {item_code} in {price_data['price_list']}: "
                        f"Rate: {price_data['price_list_rate']}"
                    )

                frappe.db.commit()

            except Exception as e:
                frappe.logger().error(f"Failed to sync price for {item_code}: {str(e)}")
                continue

    def sync_prices_realtime(self, site_config, item_code=None):
        """Real-time price synchronization for specific item or all items"""
        try:
            with get_remote_connection(site_config) as conn:
                with conn.cursor() as cursor:
                    # Query to get latest prices
                    query = """
                        SELECT 
                            ip.item_code,
                            ip.price_list,
                            ip.price_list_rate,
                            ip.modified,
                            i.item_name
                        FROM `tabItem Price` ip
                        JOIN tabItem i ON i.name = ip.item_code
                        WHERE ip.price_list IN ('Standard Selling', 'Standard Buying')
                        AND i.disabled = 0
                    """
                    
                    # Add item filter if specified
                    if item_code:
                        query += " AND ip.item_code = %(item_code)s"
                        
                    # Add company filter if enabled - using item defaults instead of price list
                    if self.company_filters.get('is_enabled'):
                        query += """ 
                        AND EXISTS (
                            SELECT 1 
                            FROM `tabItem Default` id 
                            WHERE id.parent = i.name 
                            AND id.company = %(company)s
                        )
                        """
                    
                    # Order by most recently modified
                    query += " ORDER BY ip.modified DESC"
                    
                    # Prepare parameters
                    params = {
                        'item_code': item_code,
                        **self.get_company_query_params()
                    }
                    
                    cursor.execute(query, params)
                    price_data = cursor.fetchall()
                    
                    if not price_data:
                        frappe.logger().info(f"No prices found to sync{' for ' + item_code if item_code else ''}")
                        return
                    
                    frappe.logger().info(f"Found {len(price_data)} prices to sync")
                    
                    # Process each price
                    for price in price_data:
                        try:
                            prices = [{
                                'price_list': price['price_list'],
                                'price_list_rate': price['price_list_rate']
                            }]
                            self.sync_item_prices(price['item_code'], prices)
                            frappe.db.commit()  # Commit after each price update
                        except Exception as e:
                            frappe.logger().error(
                                f"Failed to sync price for {price['item_code']} in {price['price_list']}: {str(e)}"
                            )
                            continue
                    
                    frappe.logger().info("Real-time price sync completed successfully")
                    
        except Exception as e:
            frappe.logger().error(f"Real-time price sync failed: {str(e)}")
            raise

    def create_sync_log(self, remote_warehouse, status, error_message=None):
        """Create sync log with full error message"""
        try:
            log = frappe.get_doc({
                "doctype": "Stock Sync Log",
                "timestamp": frappe.utils.now_datetime(),
                "remote_warehouse": remote_warehouse,
                "status": status,
                "error_message": error_message if error_message else ""
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Failed to create sync log: {str(e)}")

def validate_site_config(doc, method=None):
    """Validate required fields for Remote Site Settings
    
    Args:
        doc: The document instance being validated
        method: The method being called (e.g., 'on_update', 'on_submit', etc.)
    """
    required_fields = [
        'remote_warehouse', 'local_warehouse',
        'db_host', 'db_name', 'db_user', 'db_password'
    ]
    
    for field in required_fields:
        if not getattr(doc, field, None):
            frappe.throw(f"Missing required field: {field}")

def sync_all_sites():
    """Function to be called by scheduler"""
    start_time = time.time()
    success = False
    error_message = None
    processed_items = 0
    
    try:
        handler = StockSyncHandler()
        if not handler.settings:
            error_message = "No enabled remote site settings found or missing database configuration"
            frappe.logger().error(error_message)
        else:
            handler.sync_stock_from_remote()
            success = True
            processed_items = handler.processed
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
                "start_time": frappe.utils.now_datetime(),
                "duration": duration,
                "total_items": processed_items,
                "status": "Success" if success else "Failed",
                "error_message": error_message or "",
            })
            log.insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception as log_error:
            frappe.logger().error(f"Failed to create sync summary log: {str(log_error)}")

def sync_all_prices():
    """Function to be called by scheduler for frequent price updates"""
    try:
        handler = StockSyncHandler()
        if not handler.settings:
            frappe.logger().error("No enabled remote site settings found")
            return
            
        for site_config in handler.settings:
            if site_config.sync_prices and site_config.auto_update_prices:
                handler.sync_prices_realtime(site_config)
                
    except Exception as e:
        frappe.logger().error(f"Price sync failed: {str(e)}")
        raise 