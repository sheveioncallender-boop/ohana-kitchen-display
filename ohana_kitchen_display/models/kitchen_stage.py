from odoo import fields, models


class OhanaKitchenStage(models.Model):
    _name = "ohana.kitchen.stage"
    _description = "Ohana Kitchen Stage"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    color = fields.Char(default="#f2a66d")
    is_done = fields.Boolean(string="Completed Stage")
    is_cancelled = fields.Boolean(string="Cancelled Stage")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_unique", "unique(code)", "The kitchen stage code must be unique."),
    ]

    def _ohana_payload(self):
        self.ensure_one()
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "sequence": self.sequence,
            "color": self.color,
            "is_done": self.is_done,
            "is_cancelled": self.is_cancelled,
        }
