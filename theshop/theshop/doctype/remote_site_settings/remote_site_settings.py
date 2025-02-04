# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
import pymysql
from frappe.model.document import Document
from contextlib import contextmanager
import traceback


class RemoteSiteSettings(Document):
	def validate(self):
		self.validate_db_connection()
		if not any([
			self.sync_item_groups,
			self.sync_items,
			self.sync_prices,
			self.sync_stock,
			self.sync_website_items
		]):
			frappe.throw("At least one sync option must be enabled")
	
	def validate_db_connection(self):
		"""Validate database connection settings"""
		if not self.db_host or not self.db_name or not self.db_user or not self.db_password:
			frappe.throw('All database connection fields are required')

		# Debug log the connection details
		frappe.logger().debug(f"Attempting connection with:\nHost: {self.db_host}\nPort: {self.db_port}\nDB: {self.db_name}\nUser: {self.db_user}")
		
		try:
			# Test the connection with explicit SSL disabled for local network
			conn = pymysql.connect(
				host=self.db_host,
				port=self.db_port or 3306,
				user=self.db_user,
				password=self.db_password,
				database=self.db_name,
				cursorclass=pymysql.cursors.DictCursor,
				ssl_disabled=True  # Disable SSL for local network connection
			)
			
			# Test if we can actually query the database
			with conn.cursor() as cursor:
				cursor.execute("SELECT 1")
				result = cursor.fetchone()
				if result:
					frappe.logger().debug("Database connection and query successful")
			
			conn.close()
		except pymysql.Error as e:
			error_msg = str(e)
			frappe.logger().error(f"MySQL Error: {error_msg}")
			
			# Provide more specific error messages
			if "Access denied" in error_msg:
				frappe.throw(
					f'Database access denied. Please verify:\n'
					f'1. Username: {self.db_user} is correct\n'
					f'2. Password is correct\n'
					f'3. The user has permissions to access database {self.db_name}\n'
					f'4. The user is allowed to connect from this server'
				)
			elif "Can't connect" in error_msg:
				frappe.throw(
					f'Cannot connect to database server. Please verify:\n'
					f'1. The host ({self.db_host}) is accessible\n'
					f'2. Port {self.db_port or 3306} is open\n'
					f'3. Any firewalls or security groups allow the connection'
				)
			else:
				frappe.throw(f'Database connection failed: {error_msg}')

	def sync_selected_functions(self):
		"""Run selected sync functions"""
		try:
			with self.get_db_connection() as conn:
				if self.sync_item_groups:
					self.sync_remote_item_groups(conn)
				
				if self.sync_items:
					self.sync_remote_items(conn)
				
				if self.sync_prices:
					self.sync_remote_prices(conn)
				
				if self.sync_stock:
					self.sync_remote_stock(conn)
				
				if self.sync_website_items:
					self.sync_remote_website_items()
					
		except Exception as e:
			frappe.log_error(f"Sync failed for {self.name}: {str(e)}\n{traceback.format_exc()}")
			raise

	@contextmanager
	def get_db_connection(self):
		"""Get database connection with context management"""
		conn = None
		try:
			conn = pymysql.connect(
				host=self.db_host,
				port=self.db_port or 3306,
				user=self.db_user,
				password=self.db_password,
				database=self.db_name,
				cursorclass=pymysql.cursors.DictCursor
			)
			yield conn
		finally:
			if conn:
				conn.close()

	def sync_remote_item_groups(self, conn):
		"""Sync item groups from remote site"""
		with conn.cursor() as cursor:
			# Get all item groups from remote
			cursor.execute("""
				SELECT name, item_group_name, parent_item_group, 
					   is_group, description
				FROM `tabItem Group`
				WHERE parent_item_group != ''
			""")
			remote_groups = cursor.fetchall()

			for group in remote_groups:
				try:
					if not frappe.db.exists("Item Group", group['name']):
						if self.auto_create_item_groups:
							self.create_item_group(group)
					else:
						if self.auto_create_item_groups:
							self.update_item_group(group)
				except Exception as e:
					frappe.log_error(f"Failed to sync item group {group['name']}: {str(e)}")

	def create_item_group(self, group_data):
		"""Create new item group"""
		group = frappe.get_doc({
			"doctype": "Item Group",
			"item_group_name": group_data['item_group_name'],
			"parent_item_group": group_data['parent_item_group'],
			"is_group": group_data['is_group'],
			"description": group_data['description']
		})
		group.insert(ignore_permissions=True)
		frappe.db.commit()

	def update_item_group(self, group_data):
		"""Update existing item group"""
		group = frappe.get_doc("Item Group", group_data['name'])
		group.parent_item_group = group_data['parent_item_group']
		group.is_group = group_data['is_group']
		group.description = group_data['description']
		group.save(ignore_permissions=True)
		frappe.db.commit()

	def sync_remote_items(self, conn):
		"""Sync items from remote site"""
		with conn.cursor() as cursor:
			cursor.execute("""
				SELECT i.name, i.item_name, i.item_group, i.description,
					   i.stock_uom, i.disabled, i.brand, i.image
				FROM tabItem i
				WHERE i.disabled = 0
			""")
			remote_items = cursor.fetchall()

			for item in remote_items:
				try:
					if not frappe.db.exists("Item", item['name']):
						if self.auto_create_items:
							self.create_item(item)
					else:
						if self.auto_create_items:
							self.update_item(item)
				except Exception as e:
					frappe.log_error(f"Failed to sync item {item['name']}: {str(e)}")

	def create_item(self, item_data):
		"""Create new item"""
		item = frappe.get_doc({
			"doctype": "Item",
			"item_code": item_data['name'],
			"item_name": item_data['item_name'],
			"item_group": item_data['item_group'],
			"description": item_data['description'],
			"stock_uom": item_data['stock_uom'],
			"disabled": item_data['disabled'],
			"brand": item_data['brand'],
			"image": item_data['image']
		})
		item.insert(ignore_permissions=True)
		frappe.db.commit()

	def update_item(self, item_data):
		"""Update existing item"""
		item = frappe.get_doc("Item", item_data['name'])
		item.item_name = item_data['item_name']
		item.item_group = item_data['item_group']
		item.description = item_data['description']
		item.stock_uom = item_data['stock_uom']
		item.brand = item_data['brand']
		item.image = item_data['image']
		item.save(ignore_permissions=True)
		frappe.db.commit()

	def sync_remote_prices(self, conn):
		"""Sync prices from remote site"""
		with conn.cursor() as cursor:
			cursor.execute("""
				SELECT ip.item_code, ip.price_list_rate, ip.price_list,
					   ip.valid_from, ip.valid_upto
				FROM `tabItem Price` ip
				JOIN tabItem i ON ip.item_code = i.name
				WHERE i.disabled = 0
				  AND ip.selling = 1
			""")
			remote_prices = cursor.fetchall()

			for price in remote_prices:
				try:
					if self.auto_update_prices:
						self.update_price(price)
				except Exception as e:
					frappe.log_error(f"Failed to sync price for {price['item_code']}: {str(e)}")

	def update_price(self, price_data):
		"""Update item price"""
		# Check if price list exists
		if not frappe.db.exists("Price List", price_data['price_list']):
			return

		# Get existing price
		existing_price = frappe.db.get_value(
			"Item Price",
			{
				"item_code": price_data['item_code'],
				"price_list": price_data['price_list']
			},
			"name"
		)

		if existing_price:
			price = frappe.get_doc("Item Price", existing_price)
			price.price_list_rate = price_data['price_list_rate']
			price.valid_from = price_data['valid_from']
			price.valid_upto = price_data['valid_upto']
			price.save(ignore_permissions=True)
		else:
			price = frappe.get_doc({
				"doctype": "Item Price",
				"item_code": price_data['item_code'],
				"price_list": price_data['price_list'],
				"price_list_rate": price_data['price_list_rate'],
				"valid_from": price_data['valid_from'],
				"valid_upto": price_data['valid_upto']
			})
			price.insert(ignore_permissions=True)
		
		frappe.db.commit()

	def sync_remote_stock(self, conn):
		"""Sync stock from remote site"""
		with conn.cursor() as cursor:
			cursor.execute("""
				SELECT b.item_code, b.actual_qty
				FROM tabBin b
				JOIN tabItem i ON b.item_code = i.name
				WHERE b.warehouse = %s
				  AND i.disabled = 0
			""", (self.remote_warehouse,))
			remote_stock = cursor.fetchall()

			for stock in remote_stock:
				try:
					self.update_stock(stock)
				except Exception as e:
					frappe.log_error(f"Failed to sync stock for {stock['item_code']}: {str(e)}")

	def update_stock(self, stock_data):
		"""Update stock levels"""
		bin_name = frappe.db.get_value(
			"Bin",
			{
				"item_code": stock_data['item_code'],
				"warehouse": self.local_warehouse
			},
			"name"
		)

		if bin_name:
			bin_doc = frappe.get_doc("Bin", bin_name)
			if bin_doc.actual_qty != stock_data['actual_qty']:
				bin_doc.actual_qty = stock_data['actual_qty']
				bin_doc.save(ignore_permissions=True)
		else:
			bin_doc = frappe.get_doc({
				"doctype": "Bin",
				"item_code": stock_data['item_code'],
				"warehouse": self.local_warehouse,
				"actual_qty": stock_data['actual_qty']
			})
			bin_doc.insert(ignore_permissions=True)
		
		frappe.db.commit()

	def sync_remote_website_items(self):
		"""Sync website items"""
		if not self.auto_publish_items:
			return
			
		from theshop.theshop.stock_sync.website_item_handler import WebsiteItemHandler
		handler = WebsiteItemHandler()
		handler.sync_website_items()
