# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import api, fields, models, _
from odoo.osv import expression


# =========================================================================
# IMPLEMENTACIÓN: Secuencias y Restricción de Lotes en Movimientos de Stock
# =========================================================================

class StockMove(models.Model):
    """
    Extensión del modelo 'stock.move' para:
    1. Añadir numeración secuencial a las líneas de movimientos en operaciones de inventario.
    2. Restringir los números de serie/lote disponibles en la ubicación origen (y sus hijas).
    """
    _inherit = 'stock.move'

    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    sequence_number = fields.Integer(
        string='#',
        compute='_compute_sequence_number',
        default=False
    )
    available_lot_ids = fields.Many2many(
        comodel_name='stock.lot',
        compute='_compute_available_lot_ids',
        string='Lotes Disponibles en Origen'
    )
    is_internal_origin = fields.Boolean(
        string='Origen Interno',
        compute='_compute_available_lot_ids'
    )
    note = fields.Char(
        string='Notas',
        help='Notas u observaciones adicionales para este movimiento de almacén'
    )

    # -------------------------------------------------------------------------
    # MÉTODOS COMPUTADOS
    # -------------------------------------------------------------------------
    @api.depends('picking_id', 'picking_id.move_ids')
    def _compute_sequence_number(self):
        """Calcula el número de línea secuencial para cada movimiento del albarán."""
        for move in self:
            move.sequence_number = 0

        for picking in self.mapped('picking_id'):
            sequence_number = 1
            for move in picking.move_ids:
                if move in self:
                    move.sequence_number = sequence_number
                    sequence_number += 1

    @api.depends('product_id', 'location_id', 'company_id')
    def _compute_available_lot_ids(self):
        """
        Determina los números de serie y lotes físicamente disponibles en la ubicación
        de origen (y todas sus sub-ubicaciones hijas) para movimientos de salida o traslados.
        Se ejecuta en lote (batch) agrupando por ubicaciones raíz únicas.
        """
        internal_moves = self.filtered(
            lambda m: m.product_id and m.location_id and m.location_id.usage == 'internal'
        )
        non_internal_moves = self - internal_moves
        non_internal_moves.is_internal_origin = False
        if non_internal_moves:
            non_int_with_prod = non_internal_moves.filtered(lambda m: m.product_id)
            if non_int_with_prod:
                all_lots = self.env['stock.lot'].search([
                    ('product_id', 'in', non_int_with_prod.mapped('product_id').ids)
                ])
                lots_by_prod = defaultdict(lambda: self.env['stock.lot'])
                for lot in all_lots:
                    lots_by_prod[lot.product_id.id] |= lot
                for move in non_int_with_prod:
                    move.available_lot_ids = lots_by_prod.get(move.product_id.id, self.env['stock.lot'])
            (non_internal_moves - non_int_with_prod).available_lot_ids = False

        internal_moves.is_internal_origin = True

        # 1. Obtener todas las ubicaciones hijas en una sola consulta por lote
        unique_locations = internal_moves.location_id
        all_child_locations = self.env['stock.location'].search([('id', 'child_of', unique_locations.ids)])

        loc_to_child_ids = {}
        for loc in unique_locations:
            prefix = loc.parent_path or f"{loc.id}/"
            loc_to_child_ids[loc.id] = {
                child.id for child in all_child_locations
                if child.parent_path and child.parent_path.startswith(prefix)
            } | {loc.id}

        all_child_location_ids = set(all_child_locations.ids)

        # 2. Consultar quants en lote con existencia física mayor a cero
        product_ids = internal_moves.mapped('product_id').ids
        companies = internal_moves.mapped('company_id').ids

        domain = [
            ('product_id', 'in', product_ids),
            ('location_id', 'in', list(all_child_location_ids)),
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
        ]
        if companies:
            domain.append(('company_id', 'in', companies))

        quants = self.env['stock.quant'].search(domain)

        # 3. Mapear en memoria los lotes por (product_id, location_id)
        lots_by_prod_loc = defaultdict(lambda: self.env['stock.lot'])
        for quant in quants:
            lots_by_prod_loc[(quant.product_id.id, quant.location_id.id)] |= quant.lot_id

        # 4. Asignar a cada movimiento los lotes de su ubicación y todas sus hijas
        for move in internal_moves:
            child_loc_ids = loc_to_child_ids.get(move.location_id.id, {move.location_id.id})
            lots = self.env['stock.lot']
            prod_id = move.product_id.id
            for loc_id in child_loc_ids:
                lots |= lots_by_prod_loc.get((prod_id, loc_id), self.env['stock.lot'])

            # Si el movimiento ya tiene lotes asignados previamente, conservarlos
            if move.lot_ids:
                lots |= move.lot_ids

            move.available_lot_ids = lots


# =========================================================================
# IMPLEMENTACIÓN: Restricción de Lotes en Líneas de Movimiento (Operaciones)
# =========================================================================

class StockMoveLine(models.Model):
    """
    Extensión del modelo 'stock.move.line' para restringir los números de serie
    disponibles en operaciones de salida y traslados internos.
    """
    _inherit = 'stock.move.line'

    # -------------------------------------------------------------------------
    # CAMPOS
    # -------------------------------------------------------------------------
    available_lot_ids = fields.Many2many(
        comodel_name='stock.lot',
        compute='_compute_available_lot_ids',
        string='Lotes Disponibles en Origen'
    )
    is_internal_origin = fields.Boolean(
        string='Origen Interno',
        compute='_compute_available_lot_ids'
    )

    # -------------------------------------------------------------------------
    # MÉTODOS COMPUTADOS
    # -------------------------------------------------------------------------
    @api.depends('product_id', 'location_id', 'company_id')
    def _compute_available_lot_ids(self):
        """
        Determina los números de serie y lotes físicamente disponibles en la ubicación
        de origen (y todas sus sub-ubicaciones hijas) para líneas de operaciones detalladas.
        Se ejecuta en lote (batch) agrupando por ubicaciones raíz únicas.
        """
        internal_lines = self.filtered(
            lambda l: l.product_id and l.location_id and l.location_id.usage == 'internal'
        )
        non_internal_lines = self - internal_lines
        non_internal_lines.is_internal_origin = False
        if non_internal_lines:
            non_int_with_prod = non_internal_lines.filtered(lambda l: l.product_id)
            if non_int_with_prod:
                all_lots = self.env['stock.lot'].search([
                    ('product_id', 'in', non_int_with_prod.mapped('product_id').ids)
                ])
                lots_by_prod = defaultdict(lambda: self.env['stock.lot'])
                for lot in all_lots:
                    lots_by_prod[lot.product_id.id] |= lot
                for line in non_int_with_prod:
                    line.available_lot_ids = lots_by_prod.get(line.product_id.id, self.env['stock.lot'])
            (non_internal_lines - non_int_with_prod).available_lot_ids = False

        internal_lines.is_internal_origin = True

        # 1. Obtener todas las ubicaciones hijas en una sola consulta por lote
        unique_locations = internal_lines.location_id
        all_child_locations = self.env['stock.location'].search([('id', 'child_of', unique_locations.ids)])

        loc_to_child_ids = {}
        for loc in unique_locations:
            prefix = loc.parent_path or f"{loc.id}/"
            loc_to_child_ids[loc.id] = {
                child.id for child in all_child_locations
                if child.parent_path and child.parent_path.startswith(prefix)
            } | {loc.id}

        all_child_location_ids = set(all_child_locations.ids)

        # 2. Consultar quants en lote con existencia física mayor a cero
        product_ids = internal_lines.mapped('product_id').ids
        companies = internal_lines.mapped('company_id').ids

        domain = [
            ('product_id', 'in', product_ids),
            ('location_id', 'in', list(all_child_location_ids)),
            ('lot_id', '!=', False),
            ('quantity', '>', 0),
        ]
        if companies:
            domain.append(('company_id', 'in', companies))

        quants = self.env['stock.quant'].search(domain)

        # 3. Mapear en memoria los lotes por (product_id, location_id)
        lots_by_prod_loc = defaultdict(lambda: self.env['stock.lot'])
        for quant in quants:
            lots_by_prod_loc[(quant.product_id.id, quant.location_id.id)] |= quant.lot_id

        # 4. Asignar a cada línea los lotes disponibles en su jerarquía de origen
        for line in internal_lines:
            child_loc_ids = loc_to_child_ids.get(line.location_id.id, {line.location_id.id})
            lots = self.env['stock.lot']
            prod_id = line.product_id.id
            for loc_id in child_loc_ids:
                lots |= lots_by_prod_loc.get((prod_id, loc_id), self.env['stock.lot'])

            # Si la línea ya tiene un lote asignado previamente, conservarlo
            if line.lot_id:
                lots |= line.lot_id

            line.available_lot_ids = lots


# =========================================================================
# IMPLEMENTACIÓN: Secuencias y Cancelación/Eliminación en Albaranes
# =========================================================================

class StockPicking(models.Model):
    """
    Extensión del modelo 'stock.picking' para:
    1. Numeración secuencial de líneas en eventos onchange.
    2. Cancelar, eliminar y devolver a borrador transferencias en estado Hecho/Asignado.
    """
    _inherit = 'stock.picking'

    # -------------------------------------------------------------------------
    # MÉTODOS ONCHANGE (SECUENCIAS)
    # -------------------------------------------------------------------------
    @api.onchange('move_ids')
    def _onchange_move_ids_without_package(self):
        """Recalcula el número de línea secuencial al modificar movimientos en la vista."""
        sequence_number = 1
        for rec in self.move_ids:
            rec.sequence_number = sequence_number
            sequence_number += 1

    # -------------------------------------------------------------------------
    # CONFIRMACIÓN Y ASIGNACIÓN: EVITAR AUTO-LLENADO DE SERIES
    # -------------------------------------------------------------------------
    def _clean_auto_assigned_serials(self, manual_lots_by_move=None):
        """
        Limpia las series auto-asignadas por el motor de reservas de Odoo en productos
        con seguimiento (serial/lote), conservando únicamente las que el usuario haya
        seleccionado manualmente antes de la confirmación o reserva.
        """
        if manual_lots_by_move is None:
            manual_lots_by_move = {}

        for picking in self:
            for move in picking.move_ids.filtered(lambda m: m.product_id.tracking in ('serial', 'lot')):
                user_lot_ids = manual_lots_by_move.get(move.id, set())

                # Eliminar líneas de movimiento creadas por la reserva automática con series no elegidas
                auto_lines = move.move_line_ids.filtered(
                    lambda ml: ml.lot_id and ml.lot_id.id not in user_lot_ids
                )
                if auto_lines:
                    auto_lines.unlink()

                # Líneas restantes sin lote: asegurar cantidad en 0 para no marcar hecho sin serie
                lines_without_lot = move.move_line_ids.filtered(lambda ml: not ml.lot_id)
                if lines_without_lot:
                    lines_without_lot.write({'quantity': 0})

                if not user_lot_ids:
                    move.write({'quantity': 0})

    def action_confirm(self):
        """Sobrescritura para evitar que Odoo llene automáticamente el campo de series al confirmar."""
        manual_lots_by_move = {
            move.id: set(move.lot_ids.ids) for move in self.move_ids if move.lot_ids
        }
        res = super().action_confirm()
        self._clean_auto_assigned_serials(manual_lots_by_move)
        return res

    def action_assign(self):
        """Sobrescritura para evitar que se pueblen automáticamente las series al comprobar disponibilidad."""
        manual_lots_by_move = {
            move.id: set(move.lot_ids.ids) for move in self.move_ids if move.lot_ids
        }
        res = super().action_assign()
        self._clean_auto_assigned_serials(manual_lots_by_move)
        return res

    # -------------------------------------------------------------------------
    # ACCIONES: CANCELACIÓN, ELIMINACIÓN Y RETORNO A BORRADOR
    # -------------------------------------------------------------------------
    def action_cancel_delete_picking(self):
        """Abre el asistente interactivo para cancelar o eliminar la transferencia."""
        return {
            'name': 'Cancelar/Eliminar Transferencia',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_ids': self.ids},
        }

    def action_draft(self):
        """Restablece la transferencia, sus movimientos y líneas a estado borrador."""
        self.move_ids.write({'state': 'draft'})
        self.move_line_ids.write({'state': 'draft'})
        return self.write({'state': 'draft'})

    def _action_cancel_custom(self, delete_lots=False):
        """
        Lógica personalizada de cancelación de transferencias validadas:
        - Revierte/limpia quants y lotes en destino.
        - Elimina capas de valoración y asientos contables asociados.
        - Cancela movimientos y el albarán.
        """
        pickings_to_cancel = self.filtered(lambda p: p.state == 'done')
        other_pickings = self - pickings_to_cancel

        if pickings_to_cancel:
            batch_size = self.env.context.get('batch_size', 1000)

            # 1. Cancelar movimientos y líneas de movimiento PRIMERO
            # Esto desactiva el trigger nativo de Odoo (StockMoveLine.write) que intenta
            # sincronizar quants en destino/origen al detectar ediciones en movimientos en estado 'done'.
            pickings_to_cancel.move_ids.write({'state': 'cancel'})
            pickings_to_cancel.move_line_ids.write({'state': 'cancel'})

            # 2. Revertir y limpiar quants y lotes en destino mediante el ORM
            pickings_to_cancel.with_context(batch_size=batch_size)._delete_quants_and_lots(pickings_to_cancel, delete_lots)

            # 3. Eliminar capas de valoración y asientos contables asociados
            self._delete_valuation_layers_and_accounting_entries(pickings_to_cancel)

        if other_pickings:
            other_pickings.action_cancel()

        self.write({'state': 'cancel'})
        return True

    def _delete_valuation_layers_and_accounting_entries(self, pickings):
        """Elimina capas de valoración y asientos contables asociados a los movimientos de los albaranes."""
        if 'stock.valuation.layer' not in self.env:
            return

        move_ids = pickings.move_ids.ids
        if not move_ids:
            return

        StockValuationLayer = self.env['stock.valuation.layer'].sudo()
        valuation_layers = StockValuationLayer.search([('stock_move_id', 'in', move_ids)])

        if 'account.move' in self.env:
            AccountMove = self.env['account.move'].sudo()
            account_moves = AccountMove.search([('stock_move_id', 'in', move_ids)])
            if hasattr(valuation_layers, 'account_move_id'):
                account_moves |= valuation_layers.mapped('account_move_id')

            if account_moves:
                account_moves.button_cancel()
                account_moves.with_context(force_delete=True).unlink()

        if valuation_layers:
            valuation_layers.with_context(force_delete=True).unlink()

    def _delete_quants_and_lots(self, pickings, delete_lots=False):
        """
        Limpia los quants creados o actualizados en la ubicación destino mediante el ORM nativo.
        Soporta productos con seguimiento (lote/serie) y productos estándar sin seguimiento (lot_id=False).
        Toda la operación se ejecuta dentro de una única transacción atómica de PostgreSQL.
        """
        move_lines = pickings.mapped('move_line_ids')
        if not move_lines:
            return

        Quant = self.env['stock.quant'].sudo()

        # 1. Agrupar cantidades transferidas por clave: (product_id, location_dest_id, lot_id)
        quant_qty_map = defaultdict(float)
        for ml in move_lines:
            qty = ml.product_uom_id._compute_quantity(
                ml.quantity, ml.product_id.uom_id
            ) if ml.product_uom_id and ml.product_id.uom_id else ml.quantity
            key = (ml.product_id.id, ml.location_dest_id.id, ml.lot_id.id if ml.lot_id else False)
            quant_qty_map[key] += qty

        # 2. Buscar y actualizar quants en destino mediante el ORM
        keys = list(quant_qty_map.keys())
        if keys:
            batch_size = self.env.context.get('batch_size', 1000)
            quants_to_unlink = self.env['stock.quant']

            for i in range(0, len(keys), batch_size):
                batch_keys = keys[i:i + batch_size]
                domains = [
                    [('product_id', '=', p_id), ('location_id', '=', l_id), ('lot_id', '=', lot_id)]
                    for (p_id, l_id, lot_id) in batch_keys
                ]
                quants = Quant.search(expression.OR(domains))

                for quant in quants:
                    key = (quant.product_id.id, quant.location_id.id, quant.lot_id.id if quant.lot_id else False)
                    qty_to_deduct = quant_qty_map.get(key, 0.0)

                    if quant.product_id.tracking == 'serial':
                        # Número de serie único: resetear a 0
                        new_qty = 0.0
                    else:
                        # Sin seguimiento o con lote: descontar únicamente la cantidad del albarán
                        new_qty = quant.quantity - qty_to_deduct

                    if quant.product_id.uom_id.compare(new_qty, 0) <= 0:
                        quants_to_unlink |= quant
                    else:
                        quant.write({'quantity': new_qty})

            # 3. Eliminar quants cuya cantidad restante sea menor o igual a cero
            if quants_to_unlink:
                quants_to_unlink.sudo().unlink()

        # 4. Depuración opcional de lotes/series sin existencias
        if delete_lots:
            lots = move_lines.mapped('lot_id')
            if lots:
                # Consultar en una sola búsqueda ORM qué lotes aún tienen existencias positivas
                quants_with_stock = Quant.search([
                    ('lot_id', 'in', lots.ids),
                    ('quantity', '>', 0),
                ])
                lots_with_stock = quants_with_stock.mapped('lot_id')
                lots_to_delete = lots - lots_with_stock

                if lots_to_delete:
                    # Desvincular de quants remanentes (ej. quants en cero que no hayan sido eliminados)
                    orphan_quants = Quant.search([('lot_id', 'in', lots_to_delete.ids)])
                    if orphan_quants:
                        orphan_quants.sudo().write({'lot_id': False})

                    # Eliminar registros de lote mediante ORM (PostgreSQL ejecuta ON DELETE SET NULL en stock_move_line)
                    lots_to_delete.sudo().unlink()

        # 5. Limpieza final de quants con cantidad cero en las ubicaciones de destino involucradas
        prod_ids = move_lines.mapped('product_id').ids
        loc_ids = move_lines.mapped('location_dest_id').ids
        if prod_ids and loc_ids:
            zero_quants = Quant.search([
                ('quantity', '<=', 0),
                ('product_id', 'in', prod_ids),
                ('location_id', 'in', loc_ids),
            ])
            if zero_quants:
                zero_quants.sudo().unlink()


class StockPickingType(models.Model):
    """
    Extensión transversal de tipos de operaciones de almacén para encadenar
    la recepción por defecto en transferencias internas.
    """
    _inherit = 'stock.picking.type'

    default_dest_picking_type = fields.Many2one(
        'stock.picking.type',
        string="Recepción Predeterminada",
        check_company=True,
        help="Tipo de operación predeterminado en destino para recepcionar traslados generados desde este origen."
    )


