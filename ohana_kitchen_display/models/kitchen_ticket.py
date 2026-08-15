from odoo import _, fields, models
from odoo.exceptions import AccessError, UserError


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
    opened_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    updated_at = fields.Datetime(default=fields.Datetime.now, required=True)
    pos_order_write_date = fields.Datetime(
        readonly=True,
        index=True,
        help="Last POS order revision synchronized to this kitchen ticket.",
    )
    display_write_date = fields.Datetime(
        readonly=True,
        help="Last Kitchen Display configuration revision used for routing.",
    )
    ready_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    is_open = fields.Boolean(string="Open", default=True, required=True, index=True)
    close_reason = fields.Selection(
        [
            ("completed", "Completed in Kitchen"),
            ("dismissed", "Dismissed in Kitchen"),
            ("pos_cancelled", "POS Order Cancelled"),
            ("routing", "No Longer Routed"),
        ],
        readonly=True,
        index=True,
    )
    has_changes = fields.Boolean(string="Order Updated", default=False, index=True)
    revision_count = fields.Integer(default=1, readonly=True)
    last_change_at = fields.Datetime(readonly=True)
    stage_changed_by_id = fields.Many2one("res.users", readonly=True)
    stage_changed_at = fields.Datetime(readonly=True)
    line_ids = fields.One2many("ohana.kitchen.ticket.line", "ticket_id", string="Items")
    customer_note = fields.Text()
    internal_note = fields.Text()

    _order_display_unique = models.Constraint(
        "UNIQUE(pos_order_id, display_id)",
        "This POS order is already connected to the kitchen display.",
    )

    def _ohana_check_action_access(self):
        if not (
            self.env.user.has_group("base.group_system")
            or self.env.user.has_group(
                "ohana_kitchen_display.group_ohana_kitchen_user"
            )
        ):
            raise AccessError(_("Ohana Kitchen access is required."))
        if any(ticket.company_id not in self.env.companies for ticket in self):
            raise AccessError(_("This kitchen ticket belongs to another company."))

    def action_set_stage(self, stage):
        self._ohana_check_action_access()
        if isinstance(stage, int):
            stage = self.env["ohana.kitchen.stage"].browse(stage).exists()
        if not stage:
            raise UserError(_("Kitchen stage was not found."))
        stage.ensure_one()
        now = fields.Datetime.now()
        for ticket in self:
            if stage not in ticket.display_id.stage_ids:
                raise UserError(_("This stage is not enabled for the kitchen display."))
            values = {
                "stage_id": stage.id,
                "updated_at": now,
                "stage_changed_by_id": self.env.user.id,
                "stage_changed_at": now,
            }
            if stage.code == "ready":
                values["ready_at"] = ticket.ready_at or now
            if stage.is_done or stage.is_cancelled:
                values.update(
                    {
                        "completed_at": now,
                        "is_open": False,
                        "close_reason": (
                            "completed" if stage.is_done else "dismissed"
                        ),
                    }
                )
            else:
                values.update(
                    {
                        "completed_at": False,
                        "is_open": True,
                        "close_reason": False,
                    }
                )
            if ticket.has_changes:
                values["has_changes"] = False
                ticket.line_ids.filtered("is_changed").sudo().write(
                    {"is_changed": False}
                )
            ticket.sudo().write(values)
        return True

    def action_next_stage(self):
        self._ohana_check_action_access()
        for ticket in self:
            stages = ticket.display_id.stage_ids.filtered(
                lambda stage: not stage.is_cancelled
            ).sorted("sequence")
            if ticket.stage_id not in stages:
                continue
            current_index = stages.ids.index(ticket.stage_id.id)
            if current_index + 1 < len(stages):
                ticket.action_set_stage(stages[current_index + 1])
        return True

    def action_recall(self):
        self._ohana_check_action_access()
        for ticket in self:
            stages = ticket.display_id.stage_ids.filtered(
                lambda stage: not stage.is_done and not stage.is_cancelled
            ).sorted("sequence")
            if not stages:
                continue
            if not ticket.is_open or ticket.stage_id not in stages:
                target = stages[-1]
            else:
                current_index = stages.ids.index(ticket.stage_id.id)
                target = stages[max(current_index - 1, 0)]
            ticket.action_set_stage(target)
        return True

    def _ohana_close_from_pos_cancel(self, reason="pos_cancelled"):
        """Close tickets when the native POS order is cancelled or removed."""
        now = fields.Datetime.now()
        for ticket in self.sudo():
            cancelled_stage = ticket.display_id.stage_ids.filtered("is_cancelled")[:1]
            values = {
                "is_open": False,
                "completed_at": now,
                "updated_at": now,
                "pos_order_write_date": (
                    ticket.pos_order_id.write_date if ticket.pos_order_id else now
                ),
                "display_write_date": ticket.display_id.write_date,
                "close_reason": reason,
            }
            if cancelled_stage:
                values["stage_id"] = cancelled_stage.id
            ticket.write(values)
            ticket.line_ids.filtered("is_active").write({"is_active": False})
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
            "customer_note": self.customer_note or "",
            "internal_note": self.internal_note or "",
            "opened_at": fields.Datetime.to_string(self.opened_at),
            "updated_at": fields.Datetime.to_string(self.updated_at),
            "has_changes": self.has_changes,
            "revision_count": self.revision_count,
            "last_change_at": (
                fields.Datetime.to_string(self.last_change_at)
                if self.last_change_at
                else False
            ),
            "lines": [
                line._ohana_payload() for line in self.line_ids.filtered("is_active")
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
    is_active = fields.Boolean(default=True, required=True, index=True)
    is_changed = fields.Boolean(default=False, index=True)

    _ticket_order_line_unique = models.Constraint(
        "UNIQUE(ticket_id, pos_order_line_id)",
        "This POS item is already present on the kitchen ticket.",
    )

    def _ohana_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "product_name": self.product_name,
            "product_image_url": (
                f"/web/image/product.product/{self.product_id.id}/image_128"
                if self.product_id
                else False
            ),
            "quantity": self.quantity,
            "notes": self.notes or "",
            "course_name": self.course_name or "",
            "is_changed": self.is_changed,
        }
