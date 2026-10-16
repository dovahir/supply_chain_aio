# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import _, api, models
from odoo.exceptions import UserError


# =========================================================================
# IMPLEMENTACIÓN: Cálculo de Cantidad Disponible en Quants
# =========================================================================

class StockQuant(models.Model):
    """
    Extensión del modelo 'stock.quant' para omitir el filtro de número de serie
    si la ubicación desactiva el chequeo de serie y no permite negativos,
    y configurar filtros predeterminados al consultar ubicaciones.
    """
    _inherit = 'stock.quant'

    # -------------------------------------------------------------------------
    # MÉTODOS SOBREESCRITOS / EXTENDIDOS
    # -------------------------------------------------------------------------
    @api.model
    def action_view_quants(self):
        """
        Sobrescritura de la acción para ver existencias en ubicaciones (quants),
        activando por defecto el filtro de cantidades mayores a 0.
        """
        self = self.with_context(search_default_positive_qty=1)
        return super().action_view_quants()

    def _get_available_quantity(
        self, product_id, location_id, lot_id=None, package_id=None, owner_id=None, strict=False, allow_negative=False
    ):
        """
        Método de lectura/cálculo de disponibilidad. La regla estricta de no negativos
        se valida en la confirmación del movimiento en StockMoveLine._action_done().
        """
        if (
            location_id
            and not location_id.allow_negative_stock
            and not location_id.check_serial_no
            and product_id.tracking == 'serial'
        ):
            lot_id = None
        return super()._get_available_quantity(
            product_id=product_id,
            location_id=location_id,
            lot_id=lot_id,
            package_id=package_id,
            owner_id=owner_id,
            strict=strict,
            allow_negative=allow_negative,
        )


# =========================================================================
# IMPLEMENTACIÓN: Restricción de Stock Negativo en Líneas de Movimiento
# =========================================================================

class StockMoveLine(models.Model):
    """
    Extensión del modelo 'stock.move.line' para evitar que las operaciones de inventario
    dejen cantidades negativas en ubicaciones internas cuando la regla está activa.
    """
    _inherit = 'stock.move.line'

    # -------------------------------------------------------------------------
    # MÉTODOS SOBREESCRITOS / EXTENDIDOS
    # -------------------------------------------------------------------------
    def _action_done(self):
        """Valida que no se genere stock negativo antes de marcar el movimiento como realizado."""
        self._check_no_negative_stock()
        return super()._action_done()

    # -------------------------------------------------------------------------
    # MÉTODOS DE VALIDACIÓN
    # -------------------------------------------------------------------------
    def _check_no_negative_stock(self):
        """
        Bloquea la validación real del movimiento si no hay stock físico suficiente.
        Agrupa los movimientos por producto y ubicación, indicando los productos y cantidades faltantes.
        """
        Quant = self.env['stock.quant']
        # Agrupar cantidades requeridas por clave para validar totales acumulados en la operación
        grouped_moves = defaultdict(float)

        for ml in self:
            location = ml.location_id
            # Omitir si no es ubicación interna o si la ubicación permite negativos explícitamente
            if not location or location.usage != 'internal' or location.allow_negative_stock:
                continue

            company = ml.company_id or self.env.company
            # Omitir si la compañía no tiene activada la regla
            if not company.no_negative_stock:
                continue

            # Convertir cantidad a la unidad de medida principal del producto
            quantity = ml.product_uom_id._compute_quantity(
                ml.quantity, ml.product_id.uom_id, rounding_method='HALF-UP'
            )
            if ml.product_id.uom_id.compare(quantity, 0) <= 0:
                continue

            lot_id = ml.lot_id
            if ml.product_id.tracking == 'serial' and not location.check_serial_no:
                lot_id = False

            key = (
                ml.product_id,
                location,
                lot_id,
                ml.package_id if ml.package_id else False,
                ml.owner_id if ml.owner_id else False,
            )
            grouped_moves[key] += quantity

        if not grouped_moves:
            return

        # Consulta en lote (batch) mediante agregación _read_group para evitar consultas N+1
        product_ids = [product.id for product, location, lot, package, owner in grouped_moves]
        location_ids = [location.id for product, location, lot, package, owner in grouped_moves]

        quant_domain = [
            ('product_id', 'in', product_ids),
            ('location_id', 'in', location_ids),
        ]
        quants_grouped = Quant.sudo()._read_group(
            quant_domain,
            ['product_id', 'location_id', 'lot_id', 'package_id', 'owner_id'],
            ['quantity:sum']
        )
        quant_qty_map = {
            (
                p.id if p else False,
                l.id if l else False,
                lot.id if lot else False,
                pkg.id if pkg else False,
                own.id if own else False,
            ): qty_sum
            for p, l, lot, pkg, own, qty_sum in quants_grouped
        }

        error_items = []
        for (product, location, lot, package, owner), total_qty in grouped_moves.items():
            key = (
                product.id,
                location.id,
                lot.id if lot else False,
                package.id if package else False,
                owner.id if owner else False,
            )
            physical_qty = quant_qty_map.get(key, 0.0)

            # Si el stock físico restante sería negativo
            if product.uom_id.compare(physical_qty - total_qty, 0) < 0:
                missing_qty = total_qty - physical_qty
                uom_name = product.uom_id.name or ''

                item_desc = f"• {product.display_name}"
                if lot:
                    item_desc += f" (Lote/Serie: {lot.name})"
                item_desc += (
                    f"\n    - Ubicación: {location.display_name}"
                    f"\n    - Cantidad requerida: {total_qty:g} {uom_name}"
                    f"\n    - Stock disponible: {physical_qty:g} {uom_name}"
                    f"\n    - Cantidad faltante: {missing_qty:g} {uom_name}"
                )
                error_items.append(item_desc)

        if error_items:
            error_details = "\n".join(error_items)
            raise UserError(
                _(
                    "No se puede validar la operación porque generaría stock negativo "
                    "para los siguientes productos:\n\n"
                    "%(error_details)s\n\n"
                    "Por favor, ajuste las cantidades a transferir."
                )
                % {'error_details': error_details}
            )
