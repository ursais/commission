# Copyright 2016-2019 Tecnativa - Pedro M. Baeza
# License AGPL-3 - See https://www.gnu.org/licenses/agpl-3.0.html

import dateutil.relativedelta

from odoo import fields
from odoo.fields import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestSaleCommissionDelegatePartner(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.commission_model = cls.env["commission"]
        cls.commission_net_invoice = cls.commission_model.create(
            {
                "name": "10% fixed commission (Net amount) - Invoice Based",
                "fix_qty": 10.0,
                "amount_base_type": "net_amount",
            }
        )
        cls.res_partner_model = cls.env["res.partner"]
        cls.partner = cls.res_partner_model.create({"name": "Test Partner"})
        cls.partner.write({"agent": False})
        cls.settle_model = cls.env["commission.settlement"]
        cls.make_settle_model = cls.env["commission.make.settle"]
        cls.make_inv_model = cls.env["commission.make.invoice"]
        cls.product = cls.env["product.product"].create({"name": "Test Product"})
        cls.journal = cls.env["account.journal"].search(
            [("type", "=", "purchase"), ("company_id", "=", cls.env.company.id)],
            limit=1,
        )
        cls.delegate_agent = cls.res_partner_model.create({"name": "Delegate Agent"})
        cls.agent_monthly = cls.res_partner_model.create(
            {
                "name": "Test Agent - Monthly",
                "agent": True,
                "delegated_agent_id": cls.delegate_agent.id,
                "settlement": "monthly",
                "lang": "en_US",
            }
        )
        cls.agent_monthly_02 = cls.res_partner_model.create(
            {
                "name": "Test Agent 02 - Monthly",
                "agent": True,
                "settlement": "monthly",
                "lang": "en_US",
            }
        )

    def _create_invoice(self, agent, commission, date=None, currency=None):
        vals = {
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "invoice_line_ids": [
                Command.create(
                    {
                        "product_id": self.product.id,
                        "agent_ids": [
                            Command.create(
                                {"agent_id": agent.id, "commission_id": commission.id}
                            )
                        ],
                    }
                )
            ],
        }
        if date:
            vals.update({"invoice_date": date, "date": date})
        if currency:
            vals.update({"currency_id": currency.id})
        move = self.env["account.move"].create([vals])
        move.action_post()
        return move

    def _settle_and_invoice(self, grouped=False):
        wizard = self.make_settle_model.create(
            {
                "date_to": (
                    fields.Datetime.from_string(fields.Datetime.now())
                    + dateutil.relativedelta.relativedelta(months=1)
                ),
                "settlement_type": "sale_invoice",
            }
        )
        wizard.action_settle()
        settlements = self.settle_model.search([("state", "=", "settled")])
        self.make_inv_model.with_context(settlement_ids=settlements.ids).create(
            {
                "journal_id": self.journal.id,
                "product_id": self.product.id,
                "date": fields.Datetime.now(),
                "grouped": grouped,
            }
        ).button_create()
        return settlements

    def test_settlement(self):
        self._create_invoice(
            self.agent_monthly,
            self.commission_net_invoice,
        )
        self._create_invoice(
            self.agent_monthly_02,
            self.commission_net_invoice,
        )
        settlements = self._settle_and_invoice()
        self.assertEqual(len(settlements), 2)
        for settlement in settlements:
            self.assertEqual(settlement.state, "invoiced")
        settlement = settlements.filtered(lambda r: r.agent_id == self.agent_monthly)
        self.assertTrue(settlement)
        self.assertEqual(1, len(settlement))
        self.assertNotEqual(self.agent_monthly, settlement.invoice_id.partner_id)
        self.assertEqual(self.delegate_agent, settlement.invoice_id.partner_id)
        self.assertIn(
            "Agent: Test Agent - Monthly",
            settlement.invoice_id.invoice_line_ids.name,
        )
        settlement = settlements.filtered(lambda r: r.agent_id == self.agent_monthly_02)
        self.assertTrue(settlement)
        self.assertEqual(1, len(settlement))
        self.assertEqual(self.agent_monthly_02, settlement.invoice_id.partner_id)
        self.assertNotIn("Agent:", settlement.invoice_id.invoice_line_ids.name)

    def test_settlement_grouped(self):
        self.agent_monthly_02.delegated_agent_id = self.delegate_agent
        self._create_invoice(
            self.agent_monthly,
            self.commission_net_invoice,
        )
        self._create_invoice(
            self.agent_monthly_02,
            self.commission_net_invoice,
        )
        settlements = self._settle_and_invoice(grouped=True)
        self.assertEqual(len(settlements), 2)
        invoice = settlements.invoice_id
        self.assertEqual(1, len(invoice))
        self.assertEqual(self.delegate_agent, invoice.partner_id)
        line_names = "\n".join(invoice.invoice_line_ids.mapped("name"))
        self.assertIn("Agent: Test Agent - Monthly", line_names)
        self.assertIn("Agent: Test Agent 02 - Monthly", line_names)
