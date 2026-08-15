from odoo import fields, models


class OhanaKitchenAlert(models.Model):
    _name = "ohana.kitchen.alert"
    _description = "Ohana Kitchen Alert"
    _order = "created_at desc, id desc"

    ticket_id = fields.Many2one(
        "ohana.kitchen.ticket",
        required=True,
        ondelete="cascade",
        index=True,
    )
    source_reference = fields.Char(
        required=True,
        index=True,
        copy=False,
        help="Unique reference supplied by the module or workflow that created this alert.",
    )
    product_name = fields.Char(required=True)
    quantity = fields.Float(required=True)
    reason = fields.Char()
    notes = fields.Text()
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    acknowledged = fields.Boolean(default=False, index=True)
    acknowledged_by_id = fields.Many2one("res.users", readonly=True)
    acknowledged_at = fields.Datetime(readonly=True)

    _sql_constraints = [
        (
            "ticket_source_reference_unique",
            "unique(ticket_id, source_reference)",
            "This kitchen alert already exists on the ticket.",
        ),
    ]

    def _ohana_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "reason": self.reason or "",
            "notes": self.notes or "",
            "created_at": fields.Datetime.to_string(self.created_at),
        }
