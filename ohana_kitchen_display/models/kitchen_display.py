import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class OhanaKitchenDisplay(models.Model):
    _name = "ohana.kitchen.display"
    _description = "Ohana Kitchen Display"
    _order = "sequence, name"

    name = fields.Char(required=True, default="Ohana Main Kitchen")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    pos_config_ids = fields.Many2many(
        "pos.config",
        "ohana_kitchen_display_pos_config_rel",
        "display_id",
        "config_id",
        string="Restaurant Point of Sale",
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    category_ids = fields.Many2many(
        "pos.category",
        "ohana_kitchen_display_pos_category_rel",
        "display_id",
        "category_id",
        string="Kitchen Categories",
        help="Leave empty to show every ordered product.",
    )
    stage_ids = fields.Many2many(
        "ohana.kitchen.stage",
        "ohana_kitchen_display_stage_rel",
        "display_id",
        "stage_id",
        string="Stages",
        required=True,
        default=lambda self: self.env["ohana.kitchen.stage"].search(
            [("active", "=", True)], order="sequence"
        ),
    )
    refresh_seconds = fields.Integer(default=3, required=True)
    alert_minutes = fields.Integer(
        string="Late Order Alert (Minutes)",
        default=15,
        required=True,
    )
    sound_enabled = fields.Boolean(default=True)
    ticket_count = fields.Integer(compute="_compute_ticket_count")

    @api.constrains("refresh_seconds", "alert_minutes")
    def _check_positive_intervals(self):
        for display in self:
            if display.refresh_seconds < 1 or display.alert_minutes < 1:
                raise ValidationError(_("Kitchen timing values must be at least one minute/second."))

    def _compute_ticket_count(self):
        for display in self:
            display.ticket_count = self.env["ohana.kitchen.ticket"].search_count(
                [("display_id", "=", display.id)]
            )

    def action_open_screen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/ohana/kitchen?display_id={self.id}",
            "target": "self",
        }

    def action_open_tickets(self):
        self.ensure_one()
        action = self.env.ref("ohana_kitchen_display.action_ohana_kitchen_ticket").read()[0]
        action["domain"] = [("display_id", "=", self.id)]
        return action

    def _ohana_sync_pos_orders(self):
        """Synchronize outside the cashier's POS create/write transaction.

        A savepoint per order ensures malformed or unexpected order data can
        affect only that kitchen synchronization attempt, never the POS screen.
        """
        Ticket = self.env["ohana.kitchen.ticket"].sudo()
        PosOrder = self.env["pos.order"].sudo()
        cutoff = fields.Datetime.now() - timedelta(days=2)

        for display in self.sudo():
            if not display.active or not display.pos_config_ids:
                continue
            orders = PosOrder.search(
                [
                    ("config_id", "in", display.pos_config_ids.ids),
                    ("company_id", "=", display.company_id.id),
                    ("state", "!=", "cancel"),
                    ("date_order", ">=", cutoff),
                ],
                order="date_order desc, id desc",
                limit=500,
            )
            existing_tickets = Ticket.search(
                [
                    ("display_id", "=", display.id),
                    ("pos_order_id", "in", orders.ids),
                ]
            )
            ticket_by_order = {
                ticket.pos_order_id.id: ticket
                for ticket in existing_tickets
                if ticket.pos_order_id
            }

            for order in orders:
                ticket = ticket_by_order.get(order.id)
                if (
                    ticket
                    and ticket.pos_order_write_date
                    and order.write_date
                    and ticket.pos_order_write_date >= order.write_date
                ):
                    continue
                try:
                    with self.env.cr.savepoint():
                        order._ohana_sync_kitchen_tickets(target_displays=display)
                except Exception:
                    _logger.exception(
                        "Ohana Kitchen could not synchronize POS order %s to display %s",
                        order.id,
                        display.id,
                    )
        return True

    def ohana_screen_payload(self):
        self.ensure_one()
        self._ohana_sync_pos_orders()
        tickets = self.env["ohana.kitchen.ticket"].sudo().search(
            [("display_id", "=", self.id), ("active", "=", True)],
            order="opened_at, id",
        )
        return {
            "ok": True,
            "server_time": fields.Datetime.now().isoformat(),
            "display": {
                "id": self.id,
                "name": self.name,
                "refresh_seconds": self.refresh_seconds,
                "alert_minutes": self.alert_minutes,
                "sound_enabled": self.sound_enabled,
            },
            "stages": [stage._ohana_payload() for stage in self.stage_ids.sorted("sequence")],
            "tickets": [ticket._ohana_payload() for ticket in tickets],
        }
