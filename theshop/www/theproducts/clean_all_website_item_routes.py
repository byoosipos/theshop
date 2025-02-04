import frappe

def clean_all_website_item_routes():
    # Get all website items
    website_items = frappe.get_all(
        "Website Item",
        fields=['name', 'route', 'item_name', 'item_code', 'item_group']
    )
    
    count = 0
    errors = []
    
    for item in website_items:
        try:
            if item.item_name:
                # Convert item name to lowercase and replace spaces with hyphens
                cleaned_name = item.item_name.lower()
                
                # Replace special characters and spaces
                cleaned_name = cleaned_name.replace(' ', '-')
                cleaned_name = cleaned_name.replace('/', '-')
                cleaned_name = cleaned_name.replace('\\', '-')
                cleaned_name = cleaned_name.replace('&', 'and')
                cleaned_name = cleaned_name.replace('%', '')
                cleaned_name = cleaned_name.replace('(', '')
                cleaned_name = cleaned_name.replace(')', '')
                cleaned_name = cleaned_name.replace('[', '')
                cleaned_name = cleaned_name.replace(']', '')
                cleaned_name = cleaned_name.replace('{', '')
                cleaned_name = cleaned_name.replace('}', '')
                cleaned_name = cleaned_name.replace('?', '')
                cleaned_name = cleaned_name.replace('!', '')
                cleaned_name = cleaned_name.replace(':', '')
                cleaned_name = cleaned_name.replace(';', '')
                cleaned_name = cleaned_name.replace('@', '-at-')
                cleaned_name = cleaned_name.replace('#', '')
                cleaned_name = cleaned_name.replace('$', '')
                cleaned_name = cleaned_name.replace('*', '')
                cleaned_name = cleaned_name.replace('+', '-plus-')
                cleaned_name = cleaned_name.replace('=', '-equals-')
                cleaned_name = cleaned_name.replace(',', '')
                cleaned_name = cleaned_name.replace('.', '')
                cleaned_name = cleaned_name.replace('"', '')
                cleaned_name = cleaned_name.replace("'", '')
                
                # Remove any multiple hyphens
                while '--' in cleaned_name:
                    cleaned_name = cleaned_name.replace('--', '-')
                
                # Remove leading and trailing hyphens
                cleaned_name = cleaned_name.strip('-')
                
                # Create the new route
                new_route = f'product/{cleaned_name}'
                
                # Update only if route is different
                if item.route != new_route:
                    frappe.db.set_value('Website Item', item.name, 'route', new_route)
                    print(f"Updated route for {item.item_name}: {new_route}")
                    count += 1
            
            # Ensure item has a website description
            if not frappe.db.get_value('Website Item', item.name, 'web_item_name'):
                frappe.db.set_value('Website Item', item.name, 'web_item_name', item.item_name)
            
            # Ensure published status
            if not frappe.db.get_value('Website Item', item.name, 'published'):
                frappe.db.set_value('Website Item', item.name, 'published', 1)
                
        except Exception as e:
            error_msg = f"Error processing item {item.name}: {str(e)}"
            errors.append(error_msg)
            print(error_msg)
            continue
    
    if count:
        frappe.db.commit()
        print(f"\nSuccessfully updated {count} Website Items with cleaned routes")
    else:
        print("\nNo Website Items needed route updates")
    
    if errors:
        print("\nErrors encountered:")
        for error in errors:
            print(error)

    # Rebuild sitemap
    try:
        frappe.enqueue('frappe.website.router.rebuild_sitemap')
        print("\nSitemap rebuild queued")
    except Exception as e:
        print(f"\nError queuing sitemap rebuild: {str(e)}")