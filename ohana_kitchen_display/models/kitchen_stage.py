import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The kitchen stage code must be unique.",
    )

    @api.constrains("code")
    def _check_code(self):
        for stage in self:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", stage.code or ""):
                raise ValidationError(
                    _("Stage codes must use lowercase letters, numbers, and underscores.")
                )

    @api.constrains("is_done", "is_cancelled")
    def _check_terminal_flags(self):
        if any(stage.is_done and stage.is_cancelled for stage in self):
            raise ValidationError(
                _("A kitchen stage cannot be completed and cancelled at the same time.")
            )

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
