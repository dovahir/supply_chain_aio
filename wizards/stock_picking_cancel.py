# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


# =========================================================================
# ASISTENTE: Cancelar / Eliminar Transferencias de Inventario
# =========================================================================

class StockPickingCancelWizard(models.TransientModel):
    """
    Asistente interactivo para permitir a los usuarios autorizados cancelar
    o eliminar transferencias de inventario en estado Hecho o Asignado,
    con soporte para decidir el destino del saldo en requisiciones vinculadas.
    """
    _name = 'stock.picking.cancel.wizard'
    _description = 'Asistente para Cancelar o Eliminar Transferencias'

    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    action = fields.Selection([
        ('cancel', 'Cancelar transferencia'),
        ('delete', 'Eliminar transferencia')
    ], string='Acción', required=True, default='cancel')

    delete_lots = fields.Boolean(
        string='Borrar números de serie/lote',
        default=False,
        help='Si se marca, elimina los números de serie vinculados que ya no tengan existencias.'
    )
    process_by_quantities = fields.Boolean(
        string='Procesar por bloques',
        default=True,
        help='Habilita el procesamiento en bloques para optimizar transferencias de gran volumen.'
    )
    batch_size = fields.Integer(
        string='Tamaño del bloque',
        default=1000,
        help='Número de registros a procesar en cada iteración SQL.'
    )

    # Campos de gestión de asignaciones a requisiciones
    has_allocations = fields.Boolean(
        string='Tiene Asignaciones a Requisición',
        compute='_compute_has_allocations'
    )
    cancel_action = fields.Selection([
        ('reintegrate', 'Reintegrar a Pendiente (Re-suministrar por otra vía)'),
        ('close', 'Cerrar Saldo Definitivo (Ya no se requerirá más)'),
    ], string='Tratamiento del Saldo en Requisición', default='reintegrate')
    cancel_reason = fields.Text(
        string='Motivo de Cancelación'
    )

    @api.depends_context('active_ids')
    def _compute_has_allocations(self):
        pickings = self.env['stock.picking'].browse(self._context.get('active_ids', []))
        has_any = any(
            p.move_ids.allocation_ids.filtered(lambda a: a.state != 'cancel')
            for p in pickings
        )
        for rec in self:
            rec.has_allocations = has_any

    # -------------------------------------------------------------------------
    # ACCIONES
    # -------------------------------------------------------------------------
    def action_confirm(self):
        """Ejecuta la cancelación o eliminación sobre los albaranes seleccionados."""
        pickings = self.env['stock.picking'].browse(self._context.get('active_ids', []))
        batch = self.batch_size if self.process_by_quantities else 1000

        # Si hay asignaciones vinculadas, procesar antes de cancelar el movimiento
        if self.has_allocations:
            for picking in pickings:
                allocs = picking.move_ids.allocation_ids.filtered(lambda a: a.state != 'cancel')
                if allocs:
                    allocs.action_cancel_allocation(
                        cancel_action=self.cancel_action,
                        reason=self.cancel_reason or _("Cancelado mediante asistente de albaranes")
                    )

        for picking in pickings:
            picking.with_context(batch_size=batch)._action_cancel_custom(self.delete_lots)

        if self.action == 'delete':
            pickings.sudo().unlink()

        return {'type': 'ir.actions.act_window_close'}
