from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OhanaKitchenTicket(models.Model):
    _name = "ohana.kitchen.ticket"
    _description = "Ohana Kitchen Ticket"
    _order = "opened_at desc, id desc"

    name = fields.Char(required=True, index=True)
    display_id = fields.Many2one(
        "ohana.kitchen.display",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(related="display_id.company_id", store=True, index=True)
    pos_order_id = fields.Many2one("pos.order", ondelete="set null", index=True)
    pos_reference = fields.Char(index=True)
    order_uuid = fields.Char(index=True)
    pos_config_id = fields.Many2one("pos.config", index=True)
    session_id = fields.Many2one("pos.session", index=True)
    stage_id = fields.Many2one("ohana.kitchen.stage", required=True, index=True)
    table_name = fields.Char(index=True)
    order_type = fields.Char()
    customer_name = fields.Char()
    waiter_name = fields.Char()
    guest_count = fields.Integer()
    notes = fields.Text()
    opened_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    updated_at = fields.Datetime(default=fields.Datetime.now, required=True)
    pos_order_write_date = fields.Datetime(
        readonly=True,
        index=True,
        help="Last POS order revision synchronized to this kitchen ticket.",
    )
    ready_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True, index=True)
    line_ids = fields.One2many("ohana.kitchen.ticket.line", "ticket_id", string="Items")
    alert_ids = fields.One2many("ohana.kitchen.alert", "ticket_id", string="Alerts")
    unacknowledged_alert_count = fields.Integer(
        compute="_compute_unacknowledged_alert_count",
        store=True,
    )

    _sql_constraints = [
        (
            "order_display_unique",
            "unique(pos_order_id, display_id)",
            "This POS order is already connected to the kitchen display.",
        ),
    ]

    @api.depends("alert_ids.acknowledged")
    def _compute_unacknowledged_alert_count(self):
        for ticket in self:
            ticket.unacknowledged_alert_count = len(
                ticket.alert_ids.filtered(lambda alert: not alert.acknowledged)
            )

    @api.model
    def _ohana_default_stage(self):
        return self.env["ohana.kitchen.stage"].search(
            [("code", "=", "to_cook"), ("active", "=", True)], limit=1
        ) or self.env["ohana.kitchen.stage"].search([("active", "=", True)], order="sequence", limit=1)

    def action_set_stage(self, stage):
        stage.ensure_one()
        for ticket in self:
            if stage not in ticket.display_id.stage_ids:
                raise UserError(_("This stage is not enabled for the kitchen display."))
            values = {"stage_id": stage.id, "updated_at": fields.Datetime.now()}
            if stage.code == "ready":
                values["ready_at"] = fields.Datetime.now()
            if stage.is_done:
                values.update(
                    {"completed_at": fields.Datetime.now(), "active": False}
                )
            elif stage.is_cancelled:
                values.update(
                    {"completed_at": fields.Datetime.now(), "active": False}
                )
            else:
                values["active"] = True
            ticket.sudo().write(values)
        return True

    def action_next_stage(self):
        for ticket in self:
            stages = ticket.display_id.stage_ids.filtered(
                lambda stage: not stage.is_cancelled
            ).sorted("sequence")
            current_index = list(stages.ids).index(ticket.stage_id.id)
            if current_index + 1 < len(stages):
                ticket.action_set_stage(stages[current_index + 1])
        return True

    def action_recall(self):
        for ticket in self:
            stages = ticket.display_id.stage_ids.filtered(
                lambda stage: not stage.is_done and not stage.is_cancelled
            ).sorted("sequence")
            if stages:
                target = stages[-1] if not ticket.active else stages[max(stages.ids.index(ticket.stage_id.id) - 1, 0)]
                ticket.sudo().write(
                    {
                        "stage_id": target.id,
                        "active": True,
                        "completed_at": False,
                        "updated_at": fields.Datetime.now(),
                    }
                )
        return True

    def _ohana_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "reference": self.pos_reference,
            "stage_id": self.stage_id.id,
            "table_name": self.table_name or "Counter",
            "order_type": self.order_type or "Restaurant",
            "customer_name": self.customer_name or "",
            "waiter_name": self.waiter_name or "",
            "guest_count": self.guest_count,
            "notes": self.notes or "",
            "opened_at": fields.Datetime.to_string(self.opened_at),
            "updated_at": fields.Datetime.to_string(self.updated_at),
            "lines": [line._ohana_payload() for line in self.line_ids.filtered("active")],
            "alerts": [
                alert._ohana_payload()
                for alert in self.alert_ids.filtered(lambda item: not item.acknowledged)
            ],
        }


class OhanaKitchenTicketLine(models.Model):
    _name = "ohana.kitchen.ticket.line"
    _description = "Ohana Kitchen Ticket Item"
    _order = "sequence, id"

    ticket_id = fields.Many2one(
        "ohana.kitchen.ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    pos_order_line_id = fields.Many2one("pos.order.line", ondelete="set null", index=True)
    product_id = fields.Many2one("product.product", index=True)
    product_name = fields.Char(required=True)
    quantity = fields.Float(required=True)
    notes = fields.Text()
    course_name = fields.Char()
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "ticket_order_line_unique",
            "unique(ticket_id, pos_order_line_id)",
            "This POS item is already present on the kitchen ticket.",
        ),
    ]

    def _ohana_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "notes": self.notes or "",
            "course_name": self.course_name or "",
        }
