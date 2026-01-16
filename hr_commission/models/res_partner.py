# Copyright 2015-2018 Tecnativa - Pedro M. Baeza
# License AGPL-3 - See https://www.gnu.org/licenses/agpl-3.0.html

from odoo import _, api, fields, exceptions, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    agent_type = fields.Selection(
        selection_add=[
            ("salesman", "Salesman (employee)"),
            ("project_manager", "Project Manager"),
        ],
    )
    employee_id = fields.Many2one(
        string="Employee",
        comodel_name="hr.employee",
        compute="_compute_employee_id",
        compute_sudo=True,
    )
    # Project manager specific fields
    pm_commission_rate = fields.Float(
        string="PM Commission Rate (%)",
        default=0.0,
        help="Default commission rate for project manager on project-based sales.",
    )
    managed_projects_count = fields.Integer(
        string="Managed Projects",
        compute="_compute_managed_projects_count",
        help="Number of projects managed by this project manager.",
    )

    @api.depends('user_ids')
    def _compute_employee_id(self):
        """Compute the employee linked to this partner via user."""
        for partner in self:
            if (len(partner.user_ids) == 1 and
                    len(partner.user_ids[0].employee_ids) == 1):
                partner.employee_id = partner.user_ids[0].employee_ids[0]

    def _compute_managed_projects_count(self):
        """Compute the count of projects managed by this partner as PM.
        
        This searches for projects where this partner's user is the 
        project manager.
        """
        Project = self.env.get('project.project')
        for partner in self:
            count = 0
            if Project and partner.user_ids:
                # Check if project module is installed
                count = Project.search_count([
                    ('user_id', 'in', partner.user_ids.ids)
                ])
            partner.managed_projects_count = count

    @api.constrains('agent_type')
    def _check_employee(self):
        """Validate that salesman and project_manager agents have an employee."""
        for partner in self:
            if partner.agent_type in ('salesman', 'project_manager'):
                if not partner.employee_id:
                    raise exceptions.ValidationError(
                        _("There must be one (and only one) employee linked to this "
                          "partner. To do this, go to 'Human Resources' and check "
                          "'Employees'")
                    )

    @api.onchange('agent_type')
    def onchange_agent_type_hr_commission(self):
        """Handle agent type changes for HR-related agent types."""
        if self.agent_type in ('salesman', 'project_manager'):
            self.supplier = False
