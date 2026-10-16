# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from markupsafe import Markup, escape


class SupplyChainCancelAuditMixin(models.AbstractModel):
    """
    Mixin transversal para estandarizar la auditoría de cancelaciones y motivos
    en documentos transaccionales de la cadena de suministro en Odoo 19 Enterprise.
    """
    _name = 'supply.chain.cancel.audit.mixin'
    _description = 'Mixin de Auditoría de Cancelación de Cadena de Suministro'

    cancelled_by_id = fields.Many2one(
        'res.users',
        string='Cancelado por',
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
        help='Usuario que autorizó o ejecutó la cancelación del documento.'
    )
    date_cancelled = fields.Datetime(
        string='Fecha de Cancelación',
        readonly=True,
        copy=False,
        tracking=True,
        help='Marca de tiempo en que se formalizó la cancelación del documento.'
    )
    cancel_reason = fields.Text(
        string='Motivo de Cancelación',
        readonly=True,
        copy=False,
        help='Justificación operativa o causa de la cancelación.'
    )

    def _set_cancellation_audit(self, reason=None, user=None):
        """Asigna los valores de auditoría de cancelación de forma consistente."""
        cancel_user = user or self.env.user
        now = fields.Datetime.now()
        for rec in self:
            rec.write({
                'cancelled_by_id': cancel_user.id,
                'date_cancelled': now,
                'cancel_reason': reason or False,
            })

    def _reset_cancellation_audit(self):
        """Limpia los campos de auditoría de cancelación (ej. al restablecer a borrador)."""
        self.write({
            'cancelled_by_id': False,
            'date_cancelled': False,
            'cancel_reason': False,
        })


class SupplyChainCategoryCascadingMixin(models.AbstractModel):
    """
    Mixin abstracto para soportar propagación jerárquica en cascada de banderas y
    configuraciones en modelos jerárquicos (ej. product.category) hacia descendientes y plantillas.
    """
    _name = 'supply.chain.category.cascading.mixin'
    _description = 'Mixin de Propagación en Cascada de Categorías'

    def _cascade_field_to_descendants(self, field_name, new_val, skip_context_key, update_product_template=False):
        """
        Propaga el valor del campo a todas las subcategorías descendientes sin afectar ancestros.
        Opcionalmente actualiza plantillas de producto vinculadas si el campo existe en product.template.
        """
        if not self:
            return

        descendants = self.search([
            ('id', 'child_of', self.ids),
            ('id', 'not in', self.ids),
            (field_name, '!=', new_val),
        ])
        if descendants:
            descendants.with_context(**{skip_context_key: True}).write({
                field_name: new_val
            })

        if update_product_template and hasattr(self.env['product.template'], field_name):
            all_affected_categ_ids = self.ids + descendants.ids
            products = self.env['product.template'].search([
                ('categ_id', 'in', all_affected_categ_ids),
                (field_name, '!=', new_val),
            ])
            if products:
                products.write({field_name: new_val})
