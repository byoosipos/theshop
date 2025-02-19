import pymysql
import frappe
import time
from contextlib import contextmanager

MAX_RETRIES = 3
RETRY_DELAY = 5
CONNECT_TIMEOUT = 30

@contextmanager
def get_remote_connection(config):
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