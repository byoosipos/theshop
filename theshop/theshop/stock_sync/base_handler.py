# New base class for common functionality
from datetime import datetime
import frappe
from .db_utils import get_remote_connection

class BaseSyncHandler:
    def __init__(self):
        self.processed = 0
        self.failed = 0
        self.start_time = datetime.now()
        self.company_filters = {}
        self.item_groups_cache = {}
        self.price_lists_cache = set()
        self.default_company = frappe.defaults.get_user_default("company")

    def setup_company_filters(self, remote_company=None, local_company=None):
        """Setup company filtering"""
        self.company_filters = {
            'remote_company': remote_company,
            'local_company': local_company,
            'is_enabled': bool(remote_company and local_company)
        }

    def validate_company_access(self, item_code, company):
        """Validate company access for item"""
        if not self.company_filters.get('is_enabled'):
            return True

        # Check Item Defaults
        has_default = frappe.db.exists({
            "doctype": "Item Default",
            "parent": item_code,
            "company": company
        })
        if has_default:
            return True

        # Check Stock Ledger through Warehouse
        has_stock = frappe.db.sql("""
            SELECT 1 FROM `tabStock Ledger Entry` sle
            JOIN `tabWarehouse` w ON sle.warehouse = w.name
            WHERE sle.item_code = %s AND w.company = %s
            LIMIT 1
        """, (item_code, company))
        if has_stock:
            return True

        # Check Item Price
        has_price = frappe.db.exists({
            "doctype": "Item Price",
            "item_code": item_code,
            "company": company
        })
        return bool(has_price)

    def get_company_filtered_query(self, base_query, table_alias='w'):
        """Add company filter to a query"""
        if not self.company_filters.get('is_enabled'):
            return base_query
            
        company_filter = f" AND {table_alias}.company = %(company)s"
        if 'WHERE' in base_query:
            return base_query + company_filter
        return base_query + " WHERE 1=1" + company_filter

    def get_company_query_params(self):
        """Get query parameters for company filtering"""
        return {'company': self.company_filters.get('remote_company')} if self.company_filters.get('is_enabled') else {}

    def ensure_uom_exists(self, uom_name):
        """Common UOM handling"""
        if not uom_name:
            return False
            
        if not frappe.db.exists("UOM", uom_name):
            try:
                uom = frappe.get_doc({
                    "doctype": "UOM",
                    "uom_name": uom_name,
                    "enabled": 1
                })
                uom.insert(ignore_permissions=True)
                frappe.db.commit()
                return True
            except Exception as e:
                frappe.logger().error(f"Failed to create UOM {uom_name}: {str(e)}")
                return False
        return True

    def ensure_item_group_exists(self, item_group, parent_group="All Item Groups"):
        """Ensure item group exists in local system"""
        if item_group in self.item_groups_cache:
            return self.item_groups_cache[item_group]

        if not frappe.db.exists("Item Group", item_group):
            try:
                group_doc = frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": item_group,
                    "parent_item_group": parent_group
                })
                group_doc.insert(ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.logger().error(f"Failed to create item group {item_group}: {str(e)}")
                return "Products"  # Fallback to default group
        
        self.item_groups_cache[item_group] = item_group
        return item_group

    def ensure_price_list_exists(self, price_list_name, currency="NGN", selling=1):
        """Ensure price list exists in local system"""
        if price_list_name in self.price_lists_cache:
            return True

        if not frappe.db.exists("Price List", price_list_name):
            try:
                price_list = frappe.get_doc({
                    "doctype": "Price List",
                    "price_list_name": price_list_name,
                    "currency": currency,
                    "selling": selling
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

    def create_sync_summary(self, doctype, total_items):
        """Create sync summary with company context"""
        try:
            duration = (datetime.now() - self.start_time).total_seconds()
            company_info = (
                f" for company {self.company_filters.get('remote_company')}"
                if self.company_filters.get('is_enabled')
                else ""
            )
            
            summary = frappe.get_doc({
                "doctype": doctype,
                "start_time": self.start_time,
                "duration": duration,
                "total_items": total_items,
                "processed_items": self.processed,
                "failed_items": self.failed,
                "company": self.company_filters.get('local_company'),
                "status": "Success" if self.failed == 0 else "Failed",
                "error_message": f"Processed: {self.processed}, Failed: {self.failed}{company_info}"
            })
            summary.insert(ignore_permissions=True)
            frappe.db.commit()
            
        except Exception as e:
            frappe.logger().error(f"Failed to create sync summary: {str(e)}")

    def remove_item_and_dependencies(self, item_code):
        """Remove item and its dependencies with company context"""
        try:
            company = self.company_filters.get('local_company')
            
            if company:
                self._remove_company_specific_data(item_code, company)
            else:
                self._remove_all_company_data(item_code)
                
        except Exception as e:
            frappe.logger().error(f"Failed to remove item {item_code}: {str(e)}")
            raise

    def _remove_company_specific_data(self, item_code, company):
        """Remove company-specific item data"""
        frappe.db.begin()
        try:
            # Remove Item Defaults for company
            frappe.db.delete("Item Default", {
                "parent": item_code,
                "company": company
            })
            
            # Remove Item Prices for company
            frappe.db.delete("Item Price", {
                "item_code": item_code,
                "company": company
            })
            
            # Remove Bins in company warehouses
            frappe.db.sql("""
                DELETE FROM `tabBin` b
                USING `tabBin` b
                JOIN `tabWarehouse` w ON b.warehouse = w.name
                WHERE b.item_code = %s AND w.company = %s
            """, (item_code, company))
            
            # Check if item should be fully removed
            if not self._has_other_company_data(item_code, company):
                self._remove_all_company_data(item_code)
                
            frappe.db.commit()
            
        except Exception:
            frappe.db.rollback()
            raise

    def _remove_all_company_data(self, item_code):
        """Remove all item data across companies"""
        frappe.db.begin()
        try:
            # Remove Website Items
            frappe.db.delete("Website Item", {"item_code": item_code})
            
            # Remove Item Prices
            frappe.db.delete("Item Price", {"item_code": item_code})
            
            # Remove Bins
            frappe.db.delete("Bin", {"item_code": item_code})
            
            # Remove Item Barcodes
            frappe.db.delete("Item Barcode", {"parent": item_code})
            
            # Remove Item
            frappe.delete_doc("Item", item_code, force=1, ignore_permissions=True)
            
            frappe.db.commit()
            
        except Exception:
            frappe.db.rollback()
            raise

    def _has_other_company_data(self, item_code, exclude_company):
        """Check if item has data in other companies"""
        checks = [
            # Check Item Defaults
            frappe.db.exists("Item Default", {
                "parent": item_code,
                "company": ["!=", exclude_company]
            }),
            
            # Check Stock Ledger
            bool(frappe.db.sql("""
                SELECT 1 FROM `tabStock Ledger Entry` sle
                JOIN `tabWarehouse` w ON sle.warehouse = w.name
                WHERE sle.item_code = %s AND w.company != %s
                LIMIT 1
            """, (item_code, exclude_company))),
            
            # Check Item Prices
            frappe.db.exists("Item Price", {
                "item_code": item_code,
                "company": ["!=", exclude_company]
            })
        ]
        
        return any(checks)

    def has_local_modifications(self, item_code):
        """Check if item has local modifications"""
        if not self.company_filters.get('is_enabled'):
            return self._check_all_companies_modifications(item_code)
            
        return self._check_company_specific_modifications(
            item_code, 
            self.company_filters.get('local_company')
        )

    def _check_company_specific_modifications(self, item_code, company):
        """Check for modifications within specific company"""
        try:
            # Check company-specific transactions
            checks = [
                ("Sales Order Item", "item_code", "parent", "Sales Order", "company"),
                ("Purchase Order Item", "item_code", "parent", "Purchase Order", "company"),
                ("Sales Invoice Item", "item_code", "parent", "Sales Invoice", "company"),
                ("Purchase Invoice Item", "item_code", "parent", "Purchase Invoice", "company"),
                ("Delivery Note Item", "item_code", "parent", "Delivery Note", "company"),
                ("Stock Entry Detail", "item_code", "parent", "Stock Entry", "company"),
                ("Material Request Item", "item_code", "parent", "Material Request", "company")
            ]
            
            for child_dt, item_field, parent_field, parent_dt, company_field in checks:
                if frappe.db.sql(f"""
                    SELECT 1 FROM `tab{child_dt}` child
                    JOIN `tab{parent_dt}` parent ON child.{parent_field} = parent.name
                    WHERE child.{item_field} = %s AND parent.{company_field} = %s
                    LIMIT 1
                """, (item_code, company)):
                    return True
                    
            return False
            
        except Exception as e:
            frappe.logger().error(f"Error checking modifications for {item_code}: {str(e)}")
            return True  # Err on the side of caution

    def _check_all_companies_modifications(self, item_code):
        """Check for modifications across all companies"""
        try:
            # Check standard transaction tables
            standard_checks = [
                "Sales Order Item",
                "Purchase Order Item",
                "Sales Invoice Item",
                "Purchase Invoice Item",
                "Delivery Note Item",
                "Stock Entry Detail",
                "Material Request Item"
            ]
            
            for doctype in standard_checks:
                if frappe.db.exists(doctype, {"item_code": item_code}):
                    return True
                    
            return False
            
        except Exception as e:
            frappe.logger().error(f"Error checking modifications for {item_code}: {str(e)}")
            return True  # Err on the side of caution 

    def update_sync_status(self, status, error_message=None):
        """Update sync status in database"""
        try:
            frappe.db.set_value("Stock Sync Status", "Stock Sync Status", {
                "status": status,
                "last_run": frappe.utils.now_datetime(),
                "error_message": error_message
            })
            frappe.db.commit()
        except Exception as e:
            frappe.logger().error(f"Failed to update sync status: {str(e)}") 

    def can_sync(self):
        """Check if sync can proceed based on rate limits"""
        last_run = frappe.db.get_value("Stock Sync Status", "Stock Sync Status", "last_run")
        if not last_run:
            return True
        
        time_since_last = (frappe.utils.now_datetime() - last_run).total_seconds()
        return time_since_last > 300  # 5 minutes 

    def validate_sync_config(self, site_config):
        """Validate sync configuration"""
        required_fields = [
            'remote_warehouse', 'local_warehouse',
            'db_host', 'db_name', 'db_user', 'db_password'
        ]
        
        for field in required_fields:
            if not getattr(site_config, field, None):
                raise ValueError(f"Missing required field: {field}") 