from odoo import _, fields, http
from odoo.exceptions import AccessError
from odoo.http import request


class OhanaKitchenController(http.Controller):
    @staticmethod
    def _check_kitchen_access():
        user = request.env.user
        if not (
            user.has_group("ohana_kitchen_display.group_ohana_kitchen_user")
            or user.has_group("ohana_kitchen_display.group_ohana_kitchen_manager")
        ):
            raise AccessError(_("Ohana Kitchen access is required."))

    @staticmethod
    def _get_display(display_id=None):
        Display = request.env["ohana.kitchen.display"]
        if display_id:
            display = Display.browse(int(display_id)).exists()
        else:
            display = Display.search(
                [("active", "=", True), ("company_id", "in", request.env.companies.ids)],
                order="sequence, name",
                limit=1,
            )
        return display

    @http.route("/ohana/kitchen", type="http", auth="user", methods=["GET"])
    def kitchen_screen(self, display_id=None, **kwargs):
        self._check_kitchen_access()
        display = self._get_display(display_id)
        displays = request.env["ohana.kitchen.display"].search(
            [("active", "=", True), ("company_id", "in", request.env.companies.ids)],
            order="sequence, name",
        )
        return request.render(
            "ohana_kitchen_display.kitchen_screen",
            {
                "display": display,
                "displays": displays,
                "user": request.env.user,
            },
        )

    @http.route(
        "/ohana/kitchen/data",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def kitchen_data(self, display_id=None, **kwargs):
        self._check_kitchen_access()
        display = self._get_display(display_id)
        if not display:
            return {"ok": False, "error": _("No kitchen display is configured.")}
        return display.ohana_screen_payload()

    @http.route(
        "/ohana/kitchen/action",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def kitchen_action(
        self,
        display_id=None,
        ticket_id=None,
        action=None,
        stage_id=None,
        alert_id=None,
        **kwargs,
    ):
        self._check_kitchen_access()
        display = self._get_display(display_id)
        ticket = request.env["ohana.kitchen.ticket"].browse(int(ticket_id or 0)).exists()
        if not display or not ticket or ticket.display_id != display:
            return {"ok": False, "error": _("Kitchen ticket was not found.")}

        if action == "set_stage":
            stage = request.env["ohana.kitchen.stage"].browse(int(stage_id or 0)).exists()
            if not stage or stage not in display.stage_ids:
                return {"ok": False, "error": _("Kitchen stage was not found.")}
            ticket.action_set_stage(stage)
        elif action == "next":
            ticket.action_next_stage()
        elif action == "recall":
            ticket.action_recall()
        elif action == "ack_alert":
            alert = request.env["ohana.kitchen.alert"].browse(int(alert_id or 0)).exists()
            if alert and alert.ticket_id == ticket:
                alert.sudo().write(
                    {
                        "acknowledged": True,
                        "acknowledged_by_id": request.env.user.id,
                        "acknowledged_at": fields.Datetime.now(),
                    }
                )
        else:
            return {"ok": False, "error": _("Unsupported kitchen action.")}
        return {"ok": True}

