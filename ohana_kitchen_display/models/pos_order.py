from odoo import api, fields, models


def _first_existing(record, field_names, default=False):
    for field_name in field_names:
        if field_name in record._fields:
            value = record[field_name]
            if value:
                return value
    return default


class PosOrder(models.Model):
    _inherit = "pos.order"

    ohana_kitchen_ticket_ids = fields.One2many(
        "ohana.kitchen.ticket",
        "pos_order_id",
        string="Ohana Kitchen Tickets",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders._ohana_sync_kitchen_tickets()
        return orders

    def write(self, values):
        result = super().write(values)
        if not self.env.context.get("skip_ohana_kitchen_sync"):
            self._ohana_sync_kitchen_tickets()
        return result

    @api.model
    def create_from_ui(self, orders, draft=False, **kwargs):
        result = super().create_from_ui(orders, draft=draft, **kwargs)
        references = []
        uuids = []
        for payload in orders:
            data = payload.get("data", payload)
            reference = data.get("pos_reference") or data.get("name")
            order_uuid = data.get("uuid") or data.get("uid")
            if reference:
                references.append(reference)
            if order_uuid:
                uuids.append(order_uuid)
        domain = []
        if references:
            domain.append(("pos_reference", "in", references))
        if uuids and "uuid" in self._fields:
            uuid_domain = [("uuid", "in", uuids)]
            domain = ["|"] + domain + uuid_domain if domain else uuid_domain
        if domain:
            self.search(domain)._ohana_sync_kitchen_tickets()
        return result

    def _ohana_sync_kitchen_tickets(self):
        Ticket = self.env["ohana.kitchen.ticket"].sudo()
        TicketLine = self.env["ohana.kitchen.ticket.line"].sudo()
        Display = self.env["ohana.kitchen.display"].sudo()
        for order in self.sudo():
            if not order.config_id:
                continue
            if not any(line.qty > 0 for line in order.lines):
                continue
            displays = Display.search(
                [
                    ("active", "=", True),
                    ("company_id", "=", order.company_id.id),
                    ("pos_config_ids", "in", order.config_id.id),
                ]
            )
            for display in displays:
                ticket = Ticket.search(
                    [("pos_order_id", "=", order.id), ("display_id", "=", display.id)],
                    limit=1,
                )
                table = _first_existing(order, ["table_id"])
                employee = _first_existing(order, ["employee_id"])
                preset = _first_existing(order, ["preset_id"])
                customer_count = _first_existing(order, ["customer_count"], 0)
                note = _first_existing(order, ["general_note", "note"], "")
                order_uuid = str(_first_existing(order, ["uuid"], ""))
                values = {
                    "name": order.pos_reference or order.name,
                    "pos_reference": order.pos_reference or order.name,
                    "order_uuid": order_uuid,
                    "pos_config_id": order.config_id.id,
                    "session_id": order.session_id.id,
                    "table_name": table.display_name if table else "Counter",
                    "order_type": preset.display_name if preset else ("Dine In" if table else "Takeaway"),
                    "customer_name": order.partner_id.name if order.partner_id else "",
                    "waiter_name": employee.name if employee else order.user_id.name,
                    "guest_count": int(customer_count or 0),
                    "notes": str(note or ""),
                    "updated_at": fields.Datetime.now(),
                }
                if not ticket:
                    stage = display.stage_ids.filtered(lambda item: item.code == "to_cook")[:1]
                    if not stage:
                        stage = display.stage_ids.sorted("sequence")[:1]
                    if not stage:
                        continue
                    values.update(
                        {
                            "display_id": display.id,
                            "pos_order_id": order.id,
                            "stage_id": stage.id,
                            "opened_at": order.date_order or fields.Datetime.now(),
                        }
                    )
                    ticket = Ticket.create(values)
                else:
                    ticket.with_context(skip_ohana_kitchen_sync=True).write(values)

                current_line_ids = []
                allowed_categories = display.category_ids
                for index, order_line in enumerate(order.lines):
                    if order_line.qty <= 0:
                        continue
                    product = order_line.product_id
                    product_category = _first_existing(product, ["pos_categ_ids", "pos_categ_id"])
                    if allowed_categories:
                        if not product_category:
                            continue
                        product_category_ids = product_category.ids
                        if not set(product_category_ids) & set(allowed_categories.ids):
                            continue
                    line = TicketLine.search(
                        [
                            ("ticket_id", "=", ticket.id),
                            ("pos_order_line_id", "=", order_line.id),
                        ],
                        limit=1,
                    )
                    line_note = _first_existing(order_line, ["customer_note", "note"], "")
                    course = _first_existing(order_line, ["course_id"])
                    line_values = {
                        "ticket_id": ticket.id,
                        "pos_order_line_id": order_line.id,
                        "product_id": product.id,
                        "product_name": product.display_name,
                        "quantity": order_line.qty,
                        "notes": str(line_note or ""),
                        "course_name": course.display_name if course else "",
                        "sequence": (index + 1) * 10,
                        "active": True,
                    }
                    if line:
                        line.write(line_values)
                    else:
                        line = TicketLine.create(line_values)
                    current_line_ids.append(line.id)
                ticket.line_ids.filtered(lambda line: line.id not in current_line_ids).write(
                    {"active": False}
                )

        return True
