# Copyright 2021 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class CommissionSettlement(models.Model):
    _inherit = "commission.settlement"

    invoice_partner_id = fields.Many2one(
        "res.partner", compute="_compute_invoice_partner_id"
    )

    @api.depends("agent_id.delegated_agent_id")
    def _compute_invoice_partner_id(self):
        for record in self:
            record.invoice_partner_id = record._get_invoice_partner()

    def _get_invoice_grouping_keys(self):
        res = super()._get_invoice_grouping_keys()
        new_res = []
        for key in res:
            if key == "agent_id":
                new_res.append("invoice_partner_id")
            else:
                new_res.append(key)
        return new_res

    def _get_invoice_partner(self):
        agent = self[0].agent_id
        if agent.delegated_agent_id:
            return agent.delegated_agent_id
        return super()._get_invoice_partner()

    def _prepare_invoice(self, journal, product, date=False):
        vals = super()._prepare_invoice(journal, product, date=date)
        for line_command in vals["invoice_line_ids"]:
            line_vals = line_command[2]
            settlement = self.browse(line_vals["settlement_id"])
            if settlement.agent_id.delegated_agent_id:
                line_vals["name"] += "\n" + self.env._(
                    "Agent: %s", settlement.agent_id.display_name
                )
        return vals
