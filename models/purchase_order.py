# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


# =========================================================================
# IMPLEMENTACIÓN: Secuencia / Número de línea y Duplicación en Líneas de Compra
# =========================================================================

class PurchaseOrderLine(models.Model):
    """
    Extensión del modelo 'purchase.order.line' para añadir numeración secuencial,
    funcionalidad para duplicar líneas y vinculación con la matriz de asignación.
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
    allocation_ids = fields.One2many(
        'supply.chain.allocation',
        'purchase_line_id',
        string='Asignaciones de Cadena de Suministro'
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
    # INTEGRACIÓN CON INVENTARIO Y ASIGNACIONES
    # -------------------------------------------------------------------------
    def _prepare_stock_move_vals(self, picking, price_unit, product_uom_qty, product_uom):
        """Transfiere las notas de la línea de compra al movimiento de inventario generado."""
        vals = super()._prepare_stock_move_vals(picking, price_unit, product_uom_qty, product_uom)
        if self.note:
            vals['note'] = self.note
        return vals

    def write(self, vals):
        res = super().write(vals)
        # Sincronización cuando se modifica la cantidad en la línea de compra (product_qty)
        if 'product_qty' in vals:
            for line in self:
                allocations = line.allocation_ids.filtered(lambda a: a.state != 'cancel')
                if not allocations:
                    continue
                new_qty = vals['product_qty']
                if len(allocations) == 1:
                    alloc = allocations[0]
                    target_qty = new_qty
                    if line.product_uom and alloc.product_uom_id and line.product_uom != alloc.product_uom_id:
                        target_qty = line.product_uom._compute_quantity(new_qty, alloc.product_uom_id)
                    final_qty = max(target_qty, alloc.delivered_qty)
                    if alloc.requested_qty != final_qty:
                        alloc.write({'requested_qty': final_qty})
                else:
                    current_total = sum(allocations.mapped('requested_qty'))
                    if current_total > 0 and current_total != new_qty:
                        ratio = new_qty / current_total
                        for alloc in allocations:
                            final_qty = max(alloc.requested_qty * ratio, alloc.delivered_qty)
                            if alloc.requested_qty != final_qty:
                                alloc.write({'requested_qty': final_qty})
                for alloc in allocations:
                    alloc._sync_origin_document_status()

        # Sincronización para servicios: cuando cambia qty_received se actualiza la asignación
        if 'qty_received' in vals:
            for line in self:
                if line.product_id.type == 'service':
                    for alloc in line.allocation_ids.filtered(lambda a: a.state != 'cancel'):
                        alloc.delivered_qty = min(line.qty_received, alloc.requested_qty)
                        alloc._sync_origin_document_status()
        return res

    def unlink(self):
        """Al eliminar una línea de compra, cancela las asignaciones activas reintegrando el saldo."""
        allocs_to_notify = self.env['supply.chain.allocation']
        for line in self:
            active_allocs = line.allocation_ids.filtered(lambda a: a.state != 'cancel')
            if active_allocs:
                active_allocs.action_cancel_allocation(
                    cancel_action='reintegrate',
                    reason=_("Línea de compra eliminada")
                )
                allocs_to_notify |= active_allocs
        res = super().unlink()
        for alloc in allocs_to_notify:
            alloc._sync_origin_document_status()
        return res


class PurchaseOrder(models.Model):
    """
    Extensión de purchase.order para coordinar la trazabilidad, enlace de recepciones
    y control de cancelación interactiva con asignaciones a requisiciones.
    """
    _inherit = 'purchase.order'

    req_note = fields.Text(
        string="Notas de Requisición",
        readonly=True,
        help="Notas generales transferidas desde la requisición de origen."
    )

    def button_confirm(self):
        res = super().button_confirm()
        # Enlazar los movimientos de recepción entrantes a las asignaciones de compra
        for order in self:
            for line in order.order_line:
                if line.allocation_ids:
                    incoming_moves = line.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
                    if incoming_moves:
                        allocs_to_link = line.allocation_ids.filtered(
                            lambda a: not a.purchase_stock_move_id and a.state != 'cancel'
                        )
                        for alloc in allocs_to_link:
                            alloc.purchase_stock_move_id = incoming_moves[0].id
        return res

    def button_cancel(self):
        """
        Intercepta la cancelación: si el pedido tiene asignaciones activas a requisición,
        despliega el asistente para consultar si se reintegra el saldo o se cancela definitivamente.
        """
        if not self.env.context.get('skip_allocation_wizard'):
            orders_with_allocations = self.filtered(
                lambda o: o.order_line.allocation_ids.filtered(lambda a: a.state != 'cancel')
            )
            if orders_with_allocations:
                return {
                    'name': _('Cancelar Pedido y Gestión de Asignaciones'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'purchase.order.cancel.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_purchase_order_id': orders_with_allocations[0].id,
                        'active_ids': self.ids,
                    }
                }

        res = super().button_cancel()
        for order in self:
            active_allocs = order.order_line.allocation_ids.filtered(lambda a: a.state != 'cancel')
            if active_allocs:
                cancel_action = self.env.context.get('allocation_cancel_action', 'reintegrate')
                cancel_reason = self.env.context.get('allocation_cancel_reason', _('Orden de compra cancelada'))
                for alloc in active_allocs:
                    alloc.action_cancel_allocation(cancel_action=cancel_action, reason=cancel_reason)

        return res
