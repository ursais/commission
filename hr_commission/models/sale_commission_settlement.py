# Copyright 2020 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleCommissionSettlement(models.Model):
    _inherit = "sale.commission.settlement"

    # Approval tracking fields
    approval_state = fields.Selection(
        selection=[
            ('pending', 'Pending Approval'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string="Approval Status",
        default='pending',
        tracking=True,
        help="Tracks the approval status of this commission settlement.",
    )
    approved_by = fields.Many2one(
        comodel_name='res.users',
        string="Approved By",
        readonly=True,
        help="User who approved or rejected this settlement.",
    )
    approval_date = fields.Datetime(
        string="Approval Date",
        readonly=True,
        help="Date and time when the settlement was approved or rejected.",
    )
    approval_notes = fields.Text(
        string="Approval Notes",
        help="Notes or comments regarding the approval decision.",
    )

    # Payment status tracking fields
    payment_state = fields.Selection(
        selection=[
            ('not_paid', 'Not Paid'),
            ('partial', 'Partially Paid'),
            ('paid', 'Fully Paid'),
        ],
        string="Payment Status",
        default='not_paid',
        tracking=True,
        help="Tracks the payment status of the commission to the agent.",
    )
    payment_date = fields.Date(
        string="Payment Date",
        help="Date when the commission was paid to the agent.",
    )
    payment_reference = fields.Char(
        string="Payment Reference",
        help="Reference number for the payment (check number, transfer ID, etc.).",
    )
    amount_paid = fields.Float(
        string="Amount Paid",
        default=0.0,
        help="Total amount that has been paid to the agent for this settlement.",
    )
    amount_due = fields.Float(
        string="Amount Due",
        compute='_compute_amount_due',
        store=True,
        help="Remaining amount to be paid to the agent.",
    )

    # Sales order total value tracking
    sale_order_total = fields.Float(
        string="Sales Order Total",
        compute='_compute_sale_order_total',
        store=True,
        help="Total value of sales orders related to this settlement.",
    )
    sale_order_count = fields.Integer(
        string="Sales Order Count",
        compute='_compute_sale_order_total',
        store=True,
        help="Number of sales orders related to this settlement.",
    )

    @api.depends('total', 'amount_paid')
    def _compute_amount_due(self):
        """Compute the remaining amount due to the agent."""
        for record in self:
            record.amount_due = record.total - record.amount_paid

    @api.depends('lines', 'lines.invoice', 'lines.invoice.invoice_line_ids.sale_line_ids')
    def _compute_sale_order_total(self):
        """Compute total sales order value from settlement lines.
        
        This traverses from settlement lines to invoices, then to invoice lines,
        and finally to the related sale order lines to calculate the total
        sales order value that generated these commissions.
        """
        for record in self:
            sale_orders = self.env['sale.order']
            for line in record.lines:
                if line.invoice and line.invoice.invoice_line_ids:
                    for inv_line in line.invoice.invoice_line_ids:
                        if hasattr(inv_line, 'sale_line_ids') and inv_line.sale_line_ids:
                            sale_orders |= inv_line.sale_line_ids.mapped('order_id')
            record.sale_order_total = sum(sale_orders.mapped('amount_total'))
            record.sale_order_count = len(sale_orders)

    def mark_as_invoiced(self):
        """Mark settlement as invoiced (for salesman type agents)."""
        self.write({"state": "invoiced"})

    def action_approve(self):
        """Approve the commission settlement."""
        for record in self:
            if record.approval_state == 'approved':
                raise UserError(_("This settlement is already approved."))
            if record.state == 'cancel':
                raise UserError(_("Cannot approve a cancelled settlement."))
        self.write({
            'approval_state': 'approved',
            'approved_by': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })

    def action_reject(self):
        """Reject the commission settlement."""
        for record in self:
            if record.approval_state == 'rejected':
                raise UserError(_("This settlement is already rejected."))
            if record.state == 'cancel':
                raise UserError(_("Cannot reject a cancelled settlement."))
        self.write({
            'approval_state': 'rejected',
            'approved_by': self.env.user.id,
            'approval_date': fields.Datetime.now(),
        })

    def action_reset_approval(self):
        """Reset approval status back to pending."""
        for record in self:
            if record.state == 'invoiced':
                raise UserError(
                    _("Cannot reset approval for an invoiced settlement.")
                )
        self.write({
            'approval_state': 'pending',
            'approved_by': False,
            'approval_date': False,
            'approval_notes': False,
        })

    def action_mark_paid(self):
        """Mark the settlement as fully paid."""
        for record in self:
            if record.approval_state != 'approved':
                raise UserError(
                    _("Cannot mark as paid. Settlement must be approved first.")
                )
        self.write({
            'payment_state': 'paid',
            'amount_paid': self.total,
            'payment_date': fields.Date.today(),
        })

    def action_view_sale_orders(self):
        """Open a list of related sale orders."""
        self.ensure_one()
        sale_orders = self.env['sale.order']
        for line in self.lines:
            if line.invoice and line.invoice.invoice_line_ids:
                for inv_line in line.invoice.invoice_line_ids:
                    if hasattr(inv_line, 'sale_line_ids') and inv_line.sale_line_ids:
                        sale_orders |= inv_line.sale_line_ids.mapped('order_id')
        
        action = {
            'name': _('Related Sales Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', sale_orders.ids)],
            'context': {'create': False},
        }
        if len(sale_orders) == 1:
            action['view_mode'] = 'form'
            action['res_id'] = sale_orders.id
        return action
