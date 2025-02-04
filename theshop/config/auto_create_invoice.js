frappe.ui.form.on('Delivery Note', {
    before_submit: function(frm) {
        // Allow the Delivery Note to submit first
        frappe.validated = true;
    },
    
    on_submit: function(frm) {
        // Create Sales Invoice after Delivery Note is submitted
        create_sales_invoice(frm);
    },
    
    refresh: function(frm) {
        // Add a custom button to manually trigger invoice creation
        if (frm.doc.docstatus === 1 && !frm.doc.__islocal && !frm.doc.is_return) {
            let btn = frm.add_custom_button(__('Create Invoice'), function() {
                create_sales_invoice(frm);
            }, __('Create'));
            btn.addClass('btn-primary');
        }
    }
});

function create_sales_invoice(frm) {
    frappe.call({
        method: 'theshop.config.auto_create_invoice.create_sales_invoice_from_delivery',
        args: {
            delivery_note: frm.doc.name
        },
        freeze: true,
        freeze_message: `<div class="text-primary">
            <i class="fa fa-spin fa-spinner"></i> Creating Sales Invoice...
        </div>`,
        callback: function(r) {
            if (!r.exc) {
                if (r.message) {
                    // Show success message with prominent styling
                    frappe.show_alert({
                        message: `<div style="color: #28a745; font-weight: bold;">
                            <i class="fa fa-check-circle"></i> Sales Invoice ${r.message} created successfully
                        </div>`,
                        indicator: 'green'
                    }, 5);
                    
                    // Also show a more detailed message
                    frappe.msgprint({
                        title: __('Success'),
                        indicator: 'green',
                        message: __(`
                            <div style="color: #28a745;">
                                <h4><i class="fa fa-check-circle"></i> Sales Invoice Created</h4>
                                <p>Sales Invoice <strong>${r.message}</strong> has been created and submitted.</p>
                            </div>
                        `),
                    });
                    
                    // Reload the document to reflect changes
                    frm.reload_doc();
                }
            } else {
                // Show error message with prominent styling
                frappe.msgprint({
                    title: __('Error'),
                    indicator: 'red',
                    message: `
                        <div style="color: #dc3545;">
                            <h4><i class="fa fa-times-circle"></i> Failed to Create Sales Invoice</h4>
                            <p>The system encountered an error while creating the Sales Invoice.</p>
                            <p>Please try again or contact support if the issue persists.</p>
                        </div>
                    `
                });
            }
        }
    });
}
