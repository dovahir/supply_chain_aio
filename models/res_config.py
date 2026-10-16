# -*- coding: utf-8 -*-
from odoo import fields, models


# =========================================================================
# CENTRALIZACIÓN: Campos de Configuración a nivel de Compañía
# =========================================================================

class ResCompany(models.Model):
    """
    Extensión del modelo 'res.company' para almacenar los parámetros
    y activaciones de las funcionalidades del Supply Chain Kit.
    """
    _inherit = 'res.company'

    # -------------------------------------------------------------------------
    # 1. Control de Stock Negativo
    # -------------------------------------------------------------------------
    no_negative_stock = fields.Boolean(
        string='No permitir stock negativo',
        default=True,
        help='Permite prohibir las cantidades y movimientos que dejen el stock en negativo.'
    )

    # -------------------------------------------------------------------------
    # (Futuras configuraciones a nivel de compañía)
    # -------------------------------------------------------------------------


# =========================================================================
# CENTRALIZACIÓN: Ajustes Generales de Inventario (ResConfigSettings)
# =========================================================================

class ResConfigSettings(models.TransientModel):
    """
    Extensión de los ajustes generales de inventario para centralizar
    las opciones del módulo Supply Chain Kit en una sola sección.
    """
    _inherit = 'res.config.settings'

    # -------------------------------------------------------------------------
    # 1. Control de Stock Negativo
    # -------------------------------------------------------------------------
    no_negative_stock = fields.Boolean(
        related='company_id.no_negative_stock',
        string='No permitir stock negativo',
        readonly=False,
        help='Permite prohibir las cantidades y movimientos que dejen el stock en negativo.'
    )

    # -------------------------------------------------------------------------
    # (Futuras configuraciones en los ajustes de inventario)
    # -------------------------------------------------------------------------
