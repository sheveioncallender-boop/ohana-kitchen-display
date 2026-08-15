from odoo import _, fields, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    ohana_kitchen_ticket_ids = fields.One2many(
        "ohana.kitchen.ticket",
        "pos_order_id",
        string="Ohana Kitchen Tickets",
        readonly=True,
    )

    def _ohana_routed_lines(self, display):
        """Return positive native POS lines routed to one kitchen display."""
        self.ensure_one()
        lines = self.lines.filtered(lambda line: line.qty > 0 and line.product_id)
        if not display.category_ids:
            return lines
        allowed_category_ids = set(display.category_ids.ids)
        return lines.filtered(
            lambda line: bool(
                set(line.product_id.pos_categ_ids.ids) & allowed_category_ids
            )
        )

    def _ohana_ticket_values(self):
        self.ensure_one()
        employee = (
            self.employee_id
            if "employee_id" in self._fields and self.employee_id
            else False
        )
        table = self.table_id
        preset = self.preset_id
        return {
            "name": self.pos_reference or self.name,
            "pos_reference": self.pos_reference or self.name,
            "order_uuid": self.uuid or "",
            "pos_config_id": self.config_id.id,
            "session_id": self.session_id.id,
            "table_name": table.display_name if table else _("Counter"),
            "order_type": (
                preset.display_name
                if preset
                else (_("Dine In") if table else _("Takeaway"))
            ),
            "customer_name": self.partner_id.name if self.partner_id else "",
            "waiter_name": employee.name if employee else self.user_id.name,
            "guest_count": int(self.customer_count or 0),
            "customer_note": self.general_customer_note or "",
            "internal_note": self.internal_note or "",
            "pos_order_write_date": self.write_date,
        }

    @staticmethod
    def _ohana_course_name(order_line):
        if not order_line.course_id:
            return ""
        return _("Course %s") % (order_line.course_id.index + 1)

    def _ohana_line_values(self, order_line, sequence):
        self.ensure_one()
        return {
            "pos_order_line_id": order_line.id,
            "product_id": order_line.product_id.id,
            "product_name": order_line.full_product_name
            or order_line.product_id.display_name,
            "quantity": order_line.qty,
            "notes": order_line.customer_note or "",
            "course_name": self._ohana_course_name(order_line),
            "sequence": sequence,
            "is_active": True,
        }

    @staticmethod
    def _ohana_values_changed(record, values, ignored_fields=()):
        for field_name, new_value in values.items():
            if field_name in ignored_fields:
                continue
            current_value = record[field_name]
            if hasattr(current_value, "id"):
                current_value = current_value.id
            if (current_value or False) != (new_value or False):
                return True
        return False

    def _ohana_sync_kitchen_tickets(self, target_displays=None):
        """Mirror native POS orders without changing any POS lifecycle method."""
        Ticket = self.env["ohana.kitchen.ticket"].sudo()
        TicketLine = self.env["ohana.kitchen.ticket.line"].sudo()
        Display = self.env["ohana.kitchen.display"].sudo()

        for order in self.sudo():
            if not order.config_id:
                continue
            if target_displays is None:
                displays = Display.search(
                    [
                        ("active", "=", True),
                        ("company_id", "=", order.company_id.id),
                        ("pos_config_ids", "in", order.config_id.id),
                    ]
                )
            else:
                displays = target_displays.sudo().filtered(
                    lambda display: display.active
                    and display.company_id == order.company_id
                    and order.config_id in display.pos_config_ids
                )

            for display in displays:
                ticket = Ticket.search(
                    [
                        ("pos_order_id", "=", order.id),
                        ("display_id", "=", display.id),
                    ],
                    limit=1,
                )
                routed_lines = order._ohana_routed_lines(display)
                if order.state == "cancel" or not routed_lines:
                    if ticket and ticket.is_open:
                        ticket._ohana_close_from_pos_cancel(
                            reason=(
                                "pos_cancelled"
                                if order.state == "cancel"
                                else "routing"
                            )
                        )
                    continue

                ticket_values = order._ohana_ticket_values()
                ticket_values["display_write_date"] = display.write_date
                now = fields.Datetime.now()
                is_new_ticket = not ticket
                content_changed = False

                if is_new_ticket:
                    first_stage = display.stage_ids.filtered(
                        lambda stage: not stage.is_done and not stage.is_cancelled
                    ).sorted("sequence")[:1]
                    if not first_stage:
                        continue
                    ticket_values.update(
                        {
                            "display_id": display.id,
                            "pos_order_id": order.id,
                            "stage_id": first_stage.id,
                            "opened_at": order.date_order or now,
                            "updated_at": now,
                        }
                    )
                    ticket = Ticket.create(ticket_values)
                else:
                    content_changed = self._ohana_values_changed(
                        ticket,
                        ticket_values,
                        ignored_fields={
                            "name",
                            "pos_reference",
                            "pos_order_write_date",
                            "display_write_date",
                        },
                    )

                existing_by_order_line = {
                    line.pos_order_line_id.id: line
                    for line in ticket.line_ids
                    if line.pos_order_line_id
                }
                current_line_ids = []
                changed_line_ids = []
                for index, order_line in enumerate(routed_lines):
                    line = existing_by_order_line.get(order_line.id)
                    line_values = order._ohana_line_values(
                        order_line, (index + 1) * 10
                    )
                    line_values["ticket_id"] = ticket.id
                    line_changed = not line or self._ohana_values_changed(
                        line,
                        line_values,
                        ignored_fields={"ticket_id"},
                    )
                    if line:
                        changed_now = bool(line_changed and not is_new_ticket)
                        line_values["is_changed"] = bool(
                            line.is_changed or changed_now
                        )
                        line.write(line_values)
                    else:
                        changed_now = not is_new_ticket
                        line_values["is_changed"] = changed_now
                        line = TicketLine.create(line_values)
                    current_line_ids.append(line.id)
                    if changed_now:
                        changed_line_ids.append(line.id)

                removed_lines = ticket.line_ids.filtered(
                    lambda line: line.is_active and line.id not in current_line_ids
                )
                if removed_lines:
                    removed_lines.write({"is_active": False, "is_changed": True})
                    changed_line_ids.extend(removed_lines.ids)

                content_changed = bool(
                    content_changed or changed_line_ids or removed_lines
                )
                update_values = dict(ticket_values)
                if (
                    not is_new_ticket
                    and ticket.is_open
                    and ticket.stage_id not in display.stage_ids
                ):
                    first_stage = display.stage_ids.filtered(
                        lambda stage: not stage.is_done and not stage.is_cancelled
                    ).sorted("sequence")[:1]
                    if first_stage:
                        update_values.update(
                            {"stage_id": first_stage.id, "updated_at": now}
                        )
                if content_changed and not is_new_ticket:
                    update_values.update(
                        {
                            "has_changes": True,
                            "last_change_at": now,
                            "updated_at": now,
                        }
                    )
                    if not ticket.is_open:
                        first_stage = display.stage_ids.filtered(
                            lambda stage: not stage.is_done
                            and not stage.is_cancelled
                        ).sorted("sequence")[:1]
                        if first_stage:
                            update_values.update(
                                {
                                    "stage_id": first_stage.id,
                                    "is_open": True,
                                    "completed_at": False,
                                    "close_reason": False,
                                    "revision_count": ticket.revision_count + 1,
                                }
                            )
                elif (
                    not is_new_ticket
                    and not ticket.is_open
                    and ticket.close_reason == "routing"
                ):
                    first_stage = display.stage_ids.filtered(
                        lambda stage: not stage.is_done and not stage.is_cancelled
                    ).sorted("sequence")[:1]
                    if first_stage:
                        update_values.update(
                            {
                                "stage_id": first_stage.id,
                                "is_open": True,
                                "completed_at": False,
                                "close_reason": False,
                                "revision_count": ticket.revision_count + 1,
                                "opened_at": now,
                                "updated_at": now,
                            }
                        )
                ticket.write(update_values)

        return True
