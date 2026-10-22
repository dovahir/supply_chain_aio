# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


# =========================================================================
# IMPLEMENTACIÓN: Secuencia / Número de línea y Duplicación en Líneas de Compra
# =========================================================================

class PurchaseOrderLine(models.Model):
    """
    Extensión del modelo 'purchase.order.line' para añadir numeración secuencial,
    funcionalidad para duplicar líneas y transferir notas a movimientos de stock.
    """
    _inherit = 'purchase.order.line'

    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    sequence_number = fields.Integer(
        string='#',
        compute='_compute_sequence_number'
    )
    note = fields.Char(
        string='Notas',
        help='Notas u observaciones adicionales para esta línea de compra'
    )

    # -------------------------------------------------------------------------
    # MÉTODOS COMPUTADOS
    # -------------------------------------------------------------------------
    @api.depends('sequence', 'order_id', 'order_id.order_line.sequence', 'display_type')
    def _compute_sequence_number(self):
        """Calcula el número de línea secuencial para cada registro del pedido, ignorando secciones y notas."""
        for line in self:
            line.sequence_number = False

        for order in self.mapped('order_id'):
            sequence_number = 1
            for line in order.order_line.sorted(key=lambda l: (l.sequence or 0, l.id or 0)):
                if line.display_type:
                    line.sequence_number = False
                else:
                    line.sequence_number = sequence_number
                    sequence_number += 1

    # -------------------------------------------------------------------------
    # ACCIONES DE LÍNEA
    # -------------------------------------------------------------------------
    def action_copy_line(self):
        """Duplica la línea de pedido de compra seleccionada e inserta la copia inmediatamente después."""
        for record in self:
            if record.order_id.state in ('done', 'cancel'):
                raise UserError(_("No se pueden duplicar líneas en pedidos bloqueados o cancelados."))
            if record.display_type:
                raise UserError(_("No se permite duplicar líneas de sección o nota."))
            if not record.id or not isinstance(record.id, int):
                raise UserError(_("Por favor, guarde el pedido antes de duplicar la línea."))

            order = record.order_id
            all_lines = order.order_line.sorted(key=lambda l: (l.sequence or 0, l.id or 0))

            # Re-secuenciar todas las líneas y colocar la nueva línea justo después de la seleccionada
            current_seq = 10
            for line in all_lines:
                line.sequence = current_seq
                current_seq += 10
                if line.id == record.id:
                    record.copy(default={
                        'order_id': order.id,
                        'sequence': current_seq,
                    })
                    current_seq += 10

    # -------------------------------------------------------------------------
    # INTEGRACIÓN CON INVENTARIO
    # -------------------------------------------------------------------------
    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        """Transfiere las notas de la línea de compra al movimiento de inventario generado."""
        vals = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        if self.note:
            vals['note'] = self.note
        return vals
