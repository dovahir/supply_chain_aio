# -*- coding: utf-8 -*-
{
    "name": "Cadena de Suministro AIO",
    "version": "19.0.1.0.0",
    "category": "Supply Chain",
    "summary": "Gestión integral de la cadena de suministro, compras e inventarios.",
    "description": """
Cadena de Suministro AIO
========================
Módulo principal para la gestión, control y optimización de la cadena de suministro.

Características principales:
- Duplicación rápida y organización de líneas en pedidos de compra.
- Cancelación ágil y segura de recepciones y entregas de inventario.
- Prevención de inventarios negativos y validaciones de existencias en almacén.
- Control y asignación de números de serie y lotes en movimientos de inventario.
- Seguimiento centralizado de entregas de compras y surtido de materiales.
    """,
    "author": "Aldahir",
    "maintainer": "Aldahir",
    "website": "https://github.com/dovahir/supply_chain_aio.git",
    "depends": [
        "base",
        "purchase",
        "stock",
        "stock_account",
    ],
    "data": [
        "security/stock_picking_cancel_security.xml",
        "security/ir.model.access.csv",
        "views/purchase_order_views.xml",
        "views/stock_picking_views.xml",
        "views/res_config_views.xml",
        "views/stock_location_views.xml",
        "views/stock_product_views.xml",
        "wizards/stock_picking_cancel_views.xml",
        "wizards/purchase_order_cancel_wizard_views.xml",
    ],
    "assets": {},
    "license": "LGPL-3",
    "installable": True,
    "auto_install": False,
    "application": True,
}