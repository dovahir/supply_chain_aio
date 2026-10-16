# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError
from markupsafe import Markup, escape


class SupplyChainAllocation(models.Model):
    _name = 'supply.chain.allocation'
    _description = 'Asignación Transversal de Cadena de Suministro'
    _order = 'id desc'

    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        index=True
    )

    # Documentos Nativos Finales (Destino / Cumplimiento Nivel 3)
    stock_move_id = fields.Many2one(
        'stock.move',
        string='Movimiento de Salida/Entrega',
        ondelete='cascade',
        index=True,
        check_company=True
    )
    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Línea de Orden de Compra',
        ondelete='cascade',
        index=True,
        check_company=True
    )
    purchase_stock_move_id = fields.Many2one(
        'stock.move',
        string='Movimiento de Recepción de Compra',
        ondelete='set null',
        index=True,
        check_company=True
    )

    product_id = fields.Many2one(
        'product.product',
        string='Producto',
        required=True,
        index=True,
        check_company=True
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unidad de Medida',
        required=True
    )

    requested_qty = fields.Float(
        string='Cantidad Asignada',
        required=True,
        digits='Product Unit of Measure'
    )
    delivered_qty = fields.Float(
        string='Cantidad Entregada / Recibida',
        default=0.0,
        digits='Product Unit of Measure'
    )

    open_qty = fields.Float(
        string='Cantidad en Tránsito / Abierta',
        compute='_compute_open_qty',
        store=True,
        digits='Product Unit of Measure',
        help='Cantidad activa en proceso pendiente de surtir o recibir en esta asignación.'
    )

    supply_type = fields.Selection(
        [
            ('consumption', 'Consumo Directo'),
            ('resg', 'Resguardo'),
            ('custody', 'Préstamo / Resguardo'),
        ],
        string='Tipo de Suministro',
        default='consumption',
        required=True
    )

    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('in_progress', 'En Proceso'),
            ('done', 'Completado'),
            ('cancel', 'Cancelado'),
        ],
        string='Estado de Asignación',
        compute='_compute_state',
        store=True,
        readonly=False,
        default='draft',
        index=True
    )

    # --- Gestión de Cancelación y Cierre de Saldos ---
    cancel_action = fields.Selection(
        [
            ('reintegrate', 'Reintegrar a Pendiente (Re-suministrar)'),
            ('close', 'Cerrar Saldo (Ya no se requerirá más)'),
        ],
        string='Tratamiento del Saldo al Cancelar',
        default='reintegrate'
    )
    cancel_reason = fields.Text(
        string='Motivo de Cancelación'
    )
    cancelled_qty = fields.Float(
        string='Cantidad Cancelada Definitiva',
        default=0.0,
        digits='Product Unit of Measure',
        help='Cantidad que no se surtirá y cuyo saldo queda cerrado definitivamente en la requisición.'
    )

    @api.depends('requested_qty', 'delivered_qty', 'cancelled_qty', 'state')
    def _compute_open_qty(self):
        for rec in self:
            if rec.state in ('done', 'cancel'):
                rec.open_qty = 0.0
            else:
                rec.open_qty = max(0.0, rec.requested_qty - rec.delivered_qty - rec.cancelled_qty)

    @api.depends(
        'stock_move_id.state',
        'purchase_line_id.order_id.state',
        'delivered_qty',
        'requested_qty',
        'cancelled_qty'
    )
    def _compute_state(self):
        for rec in self:
            # 1. Si la entrega física ya se completó o cubrió la solicitud
            if (rec.stock_move_id and rec.stock_move_id.state == 'done') or \
               (rec.requested_qty > 0 and rec.delivered_qty >= (rec.requested_qty - rec.cancelled_qty) and rec.delivered_qty > 0):
                rec.state = 'done'
            # 2. Si fue cancelada explícitamente o sus documentos vinculados están cancelados (y no hubo entregas)
            elif (rec.stock_move_id and rec.stock_move_id.state == 'cancel' and rec.delivered_qty == 0) or \
                 (rec.purchase_line_id and rec.purchase_line_id.order_id.state == 'cancel' and rec.delivered_qty == 0) or \
                 (rec.state == 'cancel' and rec.delivered_qty == 0):
                rec.state = 'cancel'
            # 3. Si el documento destino está confirmado / en proceso
            elif (rec.stock_move_id and rec.stock_move_id.state in ('waiting', 'confirmed', 'assigned')) or \
                 (rec.purchase_line_id and rec.purchase_line_id.order_id.state in ('draft', 'sent', 'to approve', 'purchase')):
                rec.state = 'in_progress'
            elif rec.state:
                pass
            else:
                rec.state = 'draft'

    def action_cancel_allocation(self, cancel_action='reintegrate', reason=''):
        """
        Cancela o ajusta las asignaciones seleccionadas aplicando la política elegida:
        - Si ya está 'done' y delivered_qty >= requested_qty, se omite (no se puede cancelar una entrega concluida).
        - Si delivered_qty > 0 (entrega parcial):
          * 'close': el saldo no entregado pasa a cancelled_qty y la asignación concluye en 'done'.
          * 'reintegrate': el saldo no entregado se devuelve a la requisición y la asignación se ajusta a lo entregado ('done').
        - Si delivered_qty == 0:
          * 'close': cancelled_qty = requested_qty, state = 'cancel'.
          * 'reintegrate': cancelled_qty = 0, state = 'cancel'.
        """
        notified_records = self.env['supply.chain.allocation']
        for rec in self:
            # No intervenir asignaciones que ya fueron 100% completadas
            if rec.state == 'done' and rec.delivered_qty >= rec.requested_qty:
                continue

            unfulfilled = max(0.0, rec.requested_qty - rec.delivered_qty)
            vals = {
                'cancel_action': cancel_action,
                'cancel_reason': reason,
            }

            if rec.delivered_qty > 0:
                # Caso entrega parcial: el hecho físico de la entrega permanece inmutable
                if cancel_action == 'close':
                    vals['cancelled_qty'] = unfulfilled
                else:
                    vals['cancelled_qty'] = 0.0
                    vals['requested_qty'] = rec.delivered_qty
                vals['state'] = 'done'
            else:
                # Caso sin entregas: se cancela por completo la asignación
                vals['state'] = 'cancel'
                vals['cancelled_qty'] = unfulfilled if cancel_action == 'close' else 0.0

            rec.write(vals)
            notified_records |= rec

        if notified_records:
            notified_records._notify_allocation_cancellation(cancel_action, reason)

    def _notify_allocation_cancellation(self, cancel_action, reason):
        """Gancho extensible para notificar la cancelación a modelos de origen (ej. requisiciones)."""
        pass

    def _sync_origin_document_status(self):
        """Gancho extensible para sincronizar el estado del documento de origen tras cambios en la asignación."""
        pass

    def _on_move_delivered(self, move, qty):
        """Gancho invocado al registrarse entregas en movimientos de salida."""
        for rec in self:
            rec.delivered_qty = min(qty, rec.requested_qty)
        self._sync_origin_document_status()

    def _on_move_returned(self, move, qty):
        """Gancho invocado al registrarse devoluciones en movimientos de retorno."""
        for rec in self:
            if rec.supply_type == 'consumption':
                rec.delivered_qty = max(0.0, rec.delivered_qty - qty)
        self._sync_origin_document_status()

    def _on_purchase_received(self, move, qty):
        """Gancho invocado al recibirse mercancía de una orden de compra en bodega."""
        for rec in self:
            if not rec.purchase_stock_move_id:
                rec.purchase_stock_move_id = move.id
            rec.delivered_qty = min(qty, rec.requested_qty)
        self._sync_origin_document_status()

    def _get_split_extra_vals(self, new_move, split_qty):
        """Gancho extensible para inyectar campos adicionales al dividir asignaciones (ej. backorders)."""
        return {}

    @api.ondelete(at_uninstall=False)
    def _unlink_except_in_progress_or_done(self):
        for rec in self:
            if rec.state in ('in_progress', 'done'):
                raise UserError(_(
                    "No se pueden eliminar asignaciones de suministro en proceso o completadas. "
                    "Cancele la asignación primero si desea reintegrar o cerrar el saldo."
                ))

    def unlink(self):
        """Al eliminarse asignaciones, sincroniza el estado de los documentos de origen."""
        self._sync_origin_document_status()
        return super().unlink()
