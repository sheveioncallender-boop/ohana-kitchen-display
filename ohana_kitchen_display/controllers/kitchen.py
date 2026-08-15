from odoo import _, http
from odoo.exceptions import AccessError
from odoo.http import request


class OhanaKitchenController(http.Controller):
    @staticmethod
    def _safe_id(value):
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

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
        domain = [
            ("active", "=", True),
            ("company_id", "in", request.env.companies.ids),
        ]
        requested_id = OhanaKitchenController._safe_id(display_id)
        if requested_id:
            display = Display.search(domain + [("id", "=", requested_id)], limit=1)
            if display:
                return display
        return Display.search(domain, order="sequence, name", limit=1)

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
        **kwargs,
    ):
        self._check_kitchen_access()
        display = self._get_display(display_id)
        requested_ticket_id = self._safe_id(ticket_id)
        ticket = request.env["ohana.kitchen.ticket"].search(
            [
                ("id", "=", requested_ticket_id),
                ("display_id", "=", display.id if display else 0),
                ("company_id", "in", request.env.companies.ids),
            ],
            limit=1,
        )
        if not display or not ticket:
            return {"ok": False, "error": _("Kitchen ticket was not found.")}

        if action == "set_stage":
            stage = request.env["ohana.kitchen.stage"].browse(
                self._safe_id(stage_id)
            ).exists()
            if not stage or stage not in display.stage_ids:
                return {"ok": False, "error": _("Kitchen stage was not found.")}
            ticket.action_set_stage(stage)
        elif action == "next":
            ticket.action_next_stage()
        elif action == "recall":
            ticket.action_recall()
        else:
            return {"ok": False, "error": _("Unsupported kitchen action.")}
        return {"ok": True}
