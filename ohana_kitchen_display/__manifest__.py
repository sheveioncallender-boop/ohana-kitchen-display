{
    "name": "Ohana Kitchen Display",
    "summary": "Community kitchen display integrated with the native Odoo restaurant POS",
    "version": "19.0.1.1.2",
    "category": "Point of Sale",
    "author": "Spxcorp Limited",
    "website": "https://spxcorp.net",
    "license": "LGPL-3",
    "depends": ["point_of_sale", "pos_restaurant"],
    "data": [
        "security/kitchen_security.xml",
        "security/ir.model.access.csv",
        "data/kitchen_stage_data.xml",
        "views/kitchen_templates.xml",
        "views/kitchen_stage_views.xml",
        "views/kitchen_display_views.xml",
        "views/kitchen_ticket_views.xml",
        "views/kitchen_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ohana_kitchen_display/static/src/css/backend.css",
        ],
    },
    "installable": True,
    "application": True,
}
