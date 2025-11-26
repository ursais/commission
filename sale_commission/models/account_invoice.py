# Copyright 2014-2018 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import _, api, exceptions, fields, models


class AccountInvoice(models.Model):
    _inherit = "account.invoice"

    @api.depends('invoice_line_ids.agents.amount')
    def _compute_commission_total(self):
        for record in self:
            record.commission_total = 0.0
            for line in record.invoice_line_ids:
                record.commission_total += sum(x.amount for x in line.agents)

    commission_total = fields.Float(
        string="Commissions",
        compute="_compute_commission_total",
        store=True,
    )

    def action_cancel(self):
        """Put settlements associated to the invoices in exception."""
        settlements = self.env['sale.commission.settlement'].search(
            [('invoice', 'in', self.ids)])
        settlements.write({'state': 'except_invoice'})
        return super(AccountInvoice, self).action_cancel()

    def invoice_validate(self):
        """Put settlements associated to the invoices in invoiced state."""
        self.env['sale.commission.settlement'].search(
            [('invoice', 'in', self.ids)]
        ).write({'state': 'invoiced'})
        return super(AccountInvoice, self).invoice_validate()

    @api.model
    def create(self, vals):
        """Create commission agents when invoice is paid for payment-based commissions."""
        invoice = super(AccountInvoice, self).create(vals)
        # If invoice is already paid, create commission agents for payment-based commissions
        if invoice.state == 'paid':
            invoice._create_payment_based_commissions()
        return invoice

    def write(self, vals):
        """Create commission agents when invoice becomes paid for payment-based commissions."""
        result = super(AccountInvoice, self).write(vals)
        # Check if state changed to 'paid'
        if 'state' in vals and vals['state'] == 'paid':
            for invoice in self:
                if invoice.state == 'paid':
                    invoice._create_payment_based_commissions()
        return result

    def _create_payment_based_commissions(self):
        """Create commission agents for payment-based commissions when invoice is paid.
        
        This method ensures that commission records are only created for payment-based
        commissions after the invoice is fully paid, preventing premature commission
        creation when using job queues.
        """
        for invoice in self:
            # Only process customer invoices
            if invoice.type[:3] != "out":
                continue
            # Check if invoice is actually paid
            if invoice.state != 'paid':
                continue
            # Create agents for lines that don't have them yet for payment-based commissions
            for line in invoice.invoice_line_ids:
                # Check if line already has payment-based commission agents
                has_payment_based = any(
                    agent.commission.invoice_state == 'paid'
                    for agent in line.agents
                )
                if not has_payment_based:
                    # Get partner agents for payment-based commissions
                    partner = invoice.partner_id
                    agents_to_create = []
                    for agent in partner.agents:
                        # Only create agents for payment-based commissions
                        if agent.commission.invoice_state == 'paid':
                            agents_to_create.append((0, 0, {
                                'agent': agent.id,
                                'commission': agent.commission.id,
                            }))
                    if agents_to_create:
                        # Preserve existing agents and add payment-based ones
                        existing_agent_ids = [(4, agent.id) for agent in line.agents]
                        line.agents = existing_agent_ids + agents_to_create

    def _refund_cleanup_lines(self, lines):
        """ugly function to map all fields of account.invoice.line
        when creates refund invoice"""
        res = super(AccountInvoice, self)._refund_cleanup_lines(lines)
        if lines and lines[0]._name != 'account.invoice.line':
            return res
        for i, line in enumerate(lines):
            vals = res[i][2]
            agents = super(AccountInvoice, self)._refund_cleanup_lines(
                line['agents'])
            # Remove old reference to source invoice
            for agent in agents:
                agent_vals = agent[2]
                del agent_vals['invoice']
                del agent_vals['object_id']
            vals['agents'] = agents
        return res

    def recompute_lines_agents(self):
        """Recompute agents for invoice lines, respecting payment status for payment-based commissions."""
        for invoice in self:
            # For payment-based commissions, only recompute if invoice is paid
            if invoice.state == 'paid':
                invoice.mapped('invoice_line_ids').recompute_agents()
            else:
                # For non-paid invoices, only recompute non-payment-based commissions
                for line in invoice.invoice_line_ids:
                    line._recompute_agents_skip_payment_based()


class AccountInvoiceLine(models.Model):
    _inherit = [
        "account.invoice.line",
        "sale.commission.mixin",
    ]
    _name = "account.invoice.line"

    agents = fields.One2many(
        comodel_name="account.invoice.line.agent",
    )
    any_settled = fields.Boolean(
        compute="_compute_any_settled",
    )

    @api.model
    def _default_agents(self):
        """Don't populate agents for supplier invoices."""
        if self.env.context.get('type', '')[:2] == 'in':
            return []
        return super()._default_agents()

    @api.depends('agents', 'agents.settled')
    def _compute_any_settled(self):
        for record in self:
            record.any_settled = any(record.mapped('agents.settled'))

    @api.model
    def create(self, vals):
        """Add agents for records created from automations instead of UI.
        
        For payment-based commissions, agents are only created when the invoice
        is paid. This prevents premature commission creation when using job queues.
        """
        # We use this form as this is the way it's returned when no real vals
        agents_vals = vals.get('agents', [(6, 0, [])])
        invoice_id = vals.get('invoice_id', False)
        if (agents_vals and agents_vals[0][0] == 6 and not
                agents_vals[0][2] and invoice_id):
            invoice = self.env['account.invoice'].browse(invoice_id)
            # Check if invoice is paid and if any commission requires payment
            if invoice.state == 'paid':
                # Invoice is paid, create all agents
                vals['agents'] = self._prepare_agents_vals(vals=vals)
            else:
                # Invoice not paid yet, only create agents for non-payment-based commissions
                vals['agents'] = self._prepare_agents_vals_skip_payment_based(vals=vals)
        return super().create(vals)

    def _prepare_agents_vals(self, vals=None):
        res = super()._prepare_agents_vals(vals=vals)
        if self:
            invoice = self.invoice_id
        else:
            invoice = self.env['account.invoice'].browse(vals['invoice_id'])
        if invoice.type[:3] != "out":
            return [(6, 0, [])]
        return res + self._prepare_agents_vals_partner(invoice.partner_id)

    def _prepare_agents_vals_skip_payment_based(self, vals=None):
        """Prepare agent values but skip payment-based commissions.
        
        This method is used when invoice is not yet paid to prevent creating
        commission records for payment-based commissions prematurely.
        """
        res = super()._prepare_agents_vals(vals=vals)
        if self:
            invoice = self.invoice_id
        else:
            invoice = self.env['account.invoice'].browse(vals['invoice_id'])
        if invoice.type[:3] != "out":
            return [(6, 0, [])]
        # Only include agents with non-payment-based commissions
        partner = invoice.partner_id
        agents_vals = []
        for agent in partner.agents:
            if agent.commission.invoice_state != 'paid':
                agents_vals.append((0, 0, {
                    'agent': agent.id,
                    'commission': agent.commission.id,
                }))
        return res + agents_vals

    def _recompute_agents_skip_payment_based(self):
        """Recompute agents but skip payment-based commissions if invoice is not paid.
        
        This ensures that payment-based commissions are only created when
        the invoice is actually paid, even when recompute is called.
        """
        self.ensure_one()
        invoice = self.invoice_id
        if invoice.state == 'paid':
            # Invoice is paid, recompute all agents
            self.recompute_agents()
        else:
            # Invoice not paid, only keep/recompute non-payment-based commissions
            # Get existing non-payment-based agent IDs
            existing_agent_ids = {
                agent.agent.id for agent in self.agents
                if agent.commission.invoice_state != 'paid'
            }
            # Prepare agents list: keep existing non-payment-based ones
            agents_to_keep = [
                (4, agent.id) for agent in self.agents
                if agent.commission.invoice_state != 'paid'
            ]
            # Add non-payment-based commission agents from partner that don't exist yet
            partner = invoice.partner_id
            for agent in partner.agents:
                if (agent.commission.invoice_state != 'paid' and
                        agent.id not in existing_agent_ids):
                    agents_to_keep.append((0, 0, {
                        'agent': agent.id,
                        'commission': agent.commission.id,
                    }))
            # Remove payment-based commission agents and set the new list
            self.agents = [(5, 0, 0)] + agents_to_keep


class AccountInvoiceLineAgent(models.Model):
    _inherit = "sale.commission.line.mixin"
    _name = "account.invoice.line.agent"

    object_id = fields.Many2one(
        comodel_name="account.invoice.line",
        oldname='invoice_line',
    )
    invoice = fields.Many2one(
        string="Invoice",
        comodel_name="account.invoice",
        related="object_id.invoice_id",
        store=True,
    )
    invoice_date = fields.Date(
        string="Invoice date",
        related="invoice.date_invoice",
        store=True,
        readonly=True,
    )
    agent_line = fields.Many2many(
        comodel_name='sale.commission.settlement.line',
        relation='settlement_agent_line_rel',
        column1='agent_line_id',
        column2='settlement_id',
        copy=False,
    )
    settled = fields.Boolean(
        compute="_compute_settled",
        store=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        compute="_compute_company",
        store=True,
    )
    currency_id = fields.Many2one(
        related="object_id.currency_id",
        readonly=True,
    )

    @api.depends('object_id.price_subtotal')
    def _compute_amount(self):
        for line in self:
            inv_line = line.object_id
            line.amount = line._get_commission_amount(
                line.commission, inv_line.price_subtotal,
                inv_line.product_id, inv_line.quantity,
            )
            # Refunds commissions are negative
            if 'refund' in line.invoice.type:
                line.amount = -line.amount

    @api.depends('agent_line', 'agent_line.settlement.state', 'invoice',
                 'invoice.state')
    def _compute_settled(self):
        # Count lines of not open or paid invoices as settled for not
        # being included in settlements
        for line in self:
            line.settled = (any(x.settlement.state != 'cancel'
                                for x in line.agent_line))

    @api.depends('object_id', 'object_id.company_id')
    def _compute_company(self):
        for line in self:
            line.company_id = line.object_id.company_id

    @api.constrains('agent', 'amount')
    def _check_settle_integrity(self):
        for record in self:
            if any(record.mapped('settled')):
                raise exceptions.ValidationError(
                    _("You can't modify a settled line"),
                )

    def _skip_settlement(self):
        """This function should return if the commission can be payed.

        :return: bool
        """
        self.ensure_one()
        return (
            self.commission.invoice_state == 'paid' and
            self.invoice.state != 'paid'
        ) or (self.invoice.state not in ('open', 'paid'))
