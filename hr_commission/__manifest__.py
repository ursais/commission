# Copyright 2015-2020 Tecnativa - Pedro M. Baeza
# License AGPL-3 - See https://www.gnu.org/licenses/agpl-3.0.html

{
    'name': 'HR commissions',
    'version': '12.0.2.0.0',
    'author': 'Tecnativa,'
              'Odoo Community Association (OCA)',
    "category": "Commissions",
    'summary': 'HR Commissions with approval workflow and payment tracking',
    'depends': [
        'sale_commission',
        'hr',
    ],
    'license': 'AGPL-3',
    "data": [
        "views/res_partner_view.xml",
        "views/sale_commission_settlement_views.xml",
    ],
    "installable": True,
}
