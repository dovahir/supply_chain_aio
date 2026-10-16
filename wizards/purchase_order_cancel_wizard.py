# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseOrderCancelWizard(models.TransientModel):
    """
    Asistente interactivo que permite al comprador definir si el saldo
    de las líneas vinculadas a requisiciones se reintegra a pendiente
    o se cancela definitivamente, registrando el motivo en el chatter.
    """
    _name = 'purchase.order.cancel.wizard'
    _description = 'Asistente de Cancelación de Pedido con Asignaciones'

    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Pedido de Compra',
        required=True
    )
    cancel_action = fields.Selection([
        ('reintegrate', 'Reintegrar a Pendiente (Re-suministrar / Comprar con otro proveedor)'),
        ('close', 'Cerrar Saldo Definitivo (Ya no se requerirá más este material o servicio)'),
    ], string='Tratamiento del Saldo en Requisición', default='reintegrate', required=True)

    cancel_reason = fields.Text(
        string='Motivo de Cancelación',
        required=True,
        placeholder="Indique la justificación de la cancelación..."
    )

    def action_confirm_cancel(self):
        self.ensure_one()
        order = self.purchase_order_id
        return order.with_context(
            skip_allocation_wizard=True,
            allocation_cancel_action=self.cancel_action,
            allocation_cancel_reason=self.cancel_reason
        ).button_cancel()
