# -*- coding: utf-8 -*-
from odoo import fields, models


# =========================================================================
# IMPLEMENTACIÓN: Control de Stock Negativo y Números de Serie en Ubicaciones
# =========================================================================

class StockLocation(models.Model):
    """
    Extensión del modelo 'stock.location' para permitir excepciones de stock negativo
    y controlar la verificación estricta de números de serie por ubicación.
    """
    _inherit = 'stock.location'

    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    allow_negative_stock = fields.Boolean(
        string='Permitir stock negativo',
        help='Si está marcado, se permite que esta ubicación específica quede en cantidades negativas.'
    )
    check_serial_no = fields.Boolean(
        default=True,
        string='Comprobar número de serie',
        help='Si está marcado, se verificarán los números de serie en los movimientos y se generará '
             'un error si el número de serie está reservado en otro movimiento o no está disponible.'
    )
