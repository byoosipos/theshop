def get_remote_items(cursor, warehouse, with_prices=True):
    """Common query for getting remote items"""
    query = """
        SELECT DISTINCT i.name, i.item_name...
        FROM tabItem i
        LEFT JOIN...
        WHERE...
    """
    return cursor.execute(query, (warehouse,))

def validate_remote_conditions(cursor):
    """Common remote validation checks"""
    pass 