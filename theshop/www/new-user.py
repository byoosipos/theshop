import frappe
from frappe import _

def get_context(context, bypass_signup_check=False):
    # Redirect logged in users to home
    if frappe.session.user != "Guest":
        frappe.local.flags.redirect_location = "/"
        raise frappe.Redirect
    
    # Check if signup is enabled, but skip if bypass is True
    if not bypass_signup_check and frappe.utils.cint(frappe.db.get_single_value("Website Settings", "disable_signup")):
        frappe.throw(_("New user registration is disabled"), title=_("Not Allowed"))
    
    # Set page context
    context.no_cache = 1
    context.show_sidebar = False
    context.no_breadcrumbs = True
    context.title = "New User Registration - The Shop"
    
    # Set navigation
    context.parents = [
        {"name": "Home", "route": "/"},
        {"name": "Login", "route": "/login"}
    ]
    
    return context 