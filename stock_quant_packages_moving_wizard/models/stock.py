# -*- coding: utf8 -*-

#
# Copyright (C) 2015 NDP Systèmes (<http://www.ndp-systemes.fr>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from openerp import models, fields, api, exceptions, _
from openerp.tools.sql import drop_view_if_exists
from openerp.tools import float_compare, float_round


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.multi
    def partial_move(self, move_items, product, qty):
        if not move_items.get(product):
            move_items[product] = []
        move_items[product] += [{'quants': self, 'qty': qty}]
        return move_items

    @api.multi
    def move_to(self, dest_location, picking_type_id, move_items=False, is_manual_op=False):
        """
        :param move_items: {product: [{'quants': quants recordset, 'qty': float}, ...], ...}
        """
        move_recordset = self.env['stock.move']
        list_reservation = {}
        if self:
            new_picking = self.env['stock.picking'].create({
                'picking_type_id': picking_type_id.id,
            })
            if move_items:
                for product in move_items.keys():
                    list_move = []
                    tuples_reservation = []
                    move_tuples = move_items[product]
                    location_from = move_tuples[0]['quants'][0].location_id
                    prec = product.uom_id.rounding

                    list_old_moves = {}
                    for move_tuple in move_tuples:
                        for quant in move_tuple['quants']:
                            if quant.reservation_id:
                                list_old_moves[quant.reservation_id.id] = quant.reservation_id

                    split_val = sum(move_tuple['qty'] for move_tuple in move_tuples)
                    #print split_val

                    for move_reserved in list_old_moves.values():

                        if float_compare(split_val, move_reserved.product_uom_qty, precision_rounding=prec) >= 0:
                            move_reserved.write({
                                'picking_id': new_picking.id
                            })

                            split_val = split_val - move_reserved.product_uom_qty
                            move_recordset = move_recordset | move_reserved
                            list_move.append(move_reserved)
                        else:
                            diff = move_reserved.product_uom_qty - split_val
                            move_reserved.split(move_reserved, diff)
                            move_reserved.write({
                                'picking_id': new_picking.id
                            })
                            split_val = 0
                            move_recordset = move_recordset | move_reserved
                            list_move.append(move_reserved)
                            break

                    for move_unreserved in list_old_moves.values():
                        self.quants_unreserve(move_unreserved)

                    if split_val > 0:
                        new_move = self.env['stock.move'].with_context(mail_notrack=True).create({
                            'name': 'Move %s to %s' % (product.name, dest_location.name),
                            'product_id': product.id,
                            'location_id': location_from.id,
                            'location_dest_id': dest_location.id,
                            'product_uom_qty': split_val,
                            'product_uom': product.uom_id.id,
                            'date_expected': fields.Datetime.now(),
                            'date': fields.Datetime.now(),
                            'picking_type_id': picking_type_id.id,
                            'picking_id': new_picking.id,
                        })
                        move_recordset = move_recordset | new_move
                        list_move.append(new_move)
                    for move_tuple in move_tuples:
                        qty_reserved = 0
                        qty_to_reserve = move_tuple['qty']
                        for quant in move_tuple['quants']:
                            # If the new quant does not exceed the requested qty, we move it (end of loop) and continue
                            # If requested qty is reached, we break the loop
                            if float_compare(qty_reserved, qty_to_reserve, precision_rounding=prec) >= 0:
                                break
                            # If the new quant exceeds the requested qty, we reserve the good qty and then break
                            elif float_compare(qty_reserved + quant.qty, qty_to_reserve, precision_rounding=prec) > 0:
                                tuples_reservation += [(quant, qty_to_reserve - qty_reserved)]
                                break
                            tuples_reservation += [(quant, quant.qty)]
                            qty_reserved += quant.qty
                    list_reservation[tuple(list_move)] = tuples_reservation


                if move_recordset:
                    move_recordset.action_confirm()
                for new_moves in list_reservation.keys():
                    for new_move in new_moves:
                        if new_move.picking_id != new_picking:
                            raise exceptions.except_orm(_("error"), _("The moves of all the quants could not be "
                                                                      "assigned to the same picking."))

                        list_tuple_quant = []
                        move_qty = new_move.product_uom_qty
                        for quant, qty in list_reservation[new_moves]:
                            if not quant.reservation_id:

                                if float_compare(move_qty, qty,
                                                 precision_rounding=new_move.product_id.uom_id.rounding) >= 0:

                                    if float_compare(quant.qty, qty,
                                                     precision_rounding=new_move.product_id.uom_id.rounding) > 0:
                                        q = quant._quant_split(quant, float_round(qty,
                                                                                  precision_rounding=new_move.product_id.uom_id.rounding))
                                        list_reservation[new_moves].append((q, q.qty))
                                    list_tuple_quant.append((quant, qty))
                                    move_qty = move_qty - qty
                                else:
                                    if float_compare(quant.qty, move_qty,
                                                     precision_rounding=new_move.product_id.uom_id.rounding) > 0:
                                        q = quant._quant_split(quant, float_round(move_qty,
                                                                                  precision_rounding=new_move.product_id.uom_id.rounding))
                                        list_reservation[new_moves].append((q, q.qty))
                                    list_tuple_quant.append((quant, move_qty))
                                    break

                                if float_round(move_qty, precision_rounding=new_move.product_id.uom_id.rounding) <= 0:
                                    break

                        self.quants_reserve(list_tuple_quant, new_move)

            else:
                values = self.env['stock.quant'].read_group([('id', 'in', self.ids)],
                                                            ['product_id', 'location_id', 'qty'],
                                                            ['product_id', 'location_id'], lazy=False)
                for val in values:
                    new_move = self.env['stock.move'].with_context(mail_notrack=True).create({
                        'name': 'Move %s to %s' % (val['product_id'][1], dest_location.name),
                        'product_id': val['product_id'][0],
                        'location_id': val['location_id'][0],
                        'location_dest_id': dest_location.id,
                        'product_uom_qty': val['qty'],
                        'product_uom':
                            self.env['product.product'].search([('id', '=', val['product_id'][0])]).uom_id.id,
                        'date_expected': fields.Datetime.now(),
                        'date': fields.Datetime.now(),
                        'picking_type_id': picking_type_id.id,
                        'picking_id': new_picking.id,
                    })
                    quants = self.env['stock.quant'].search(
                        [('id', 'in', self.ids), ('product_id', '=', val['product_id'][0])])
                    qtys = quants.read(['id', 'qty'])
                    list_reservation[new_move] = []
                    for qt in qtys:
                        list_reservation[new_move].append((self.env['stock.quant'].search(
                            [('id', '=', qt['id'])]), qt['qty']))

                    move_recordset = move_recordset | new_move

                if move_recordset:
                    move_recordset.action_confirm()
                for new_move in list_reservation.keys():
                    if new_move.picking_id != new_picking:
                        raise exceptions.except_orm(_("error"), _("The moves of all the quants could not be "
                                                                  "assigned to the same picking."))
                    self.quants_reserve(list_reservation[new_move], new_move)

            new_picking.do_prepare_partial()
            packops = new_picking.pack_operation_ids
            packops.write({'location_dest_id': dest_location.id})
            if not is_manual_op:
                new_picking.do_transfer()
        return move_recordset


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    picking_type_id = fields.Many2one('stock.picking.type', string="Default picking type")


class Stock(models.Model):
    _name = 'stock.product.line'
    _auto = False
    _order = 'package_id asc, product_id asc'

    product_id = fields.Many2one('product.product', readonly=True, index=True, string="Product")
    package_id = fields.Many2one("stock.quant.package", string="Package", index=True)
    lot_id = fields.Many2one("stock.production.lot", string="Lot")
    qty = fields.Float(string="Quantity")
    uom_id = fields.Many2one("product.uom", string="UOM")
    location_id = fields.Many2one("stock.location", string="Location")
    parent_id = fields.Many2one("stock.quant.package", "Parent Package", index=True)

    def init(self, cr):
        drop_view_if_exists(cr, 'stock_product_line')
        cr.execute("""CREATE OR REPLACE VIEW stock_product_line AS (
  SELECT
    COALESCE(rqx.product_id, 0)
    || '-' || COALESCE(rqx.package_id, 0) || '-' || COALESCE(rqx.lot_id, 0) || '-' ||
    COALESCE(rqx.uom_id, 0) || '-' || COALESCE(rqx.location_id, 0) AS id,
    rqx.*
  FROM
    (SELECT
       sq.product_id,
       sq.package_id,
       sq.lot_id,
       sum(sq.qty) qty,
       pt.uom_id,
       sq.location_id,
       sqp.parent_id
     FROM
       stock_quant sq
       LEFT JOIN product_product pp ON pp.id = sq.product_id
       LEFT JOIN product_template pt ON pp.product_tmpl_id = pt.id
       LEFT JOIN stock_quant_package sqp ON sqp.id = sq.package_id
     GROUP BY
       sq.product_id,
       sq.package_id,
       sq.lot_id,
       pt.uom_id,
       sq.location_id,
       sqp.parent_id
     UNION ALL
     SELECT
       NULL   product_id,
       sqp.id package_id,
       NULL   lot_id,
       0      qty,
       NULL   uom_id,
       sqp.location_id,
       sqp.parent_id
     FROM
       stock_quant_package sqp
     WHERE exists(SELECT 1
                  FROM
                    stock_quant sq
                    LEFT JOIN stock_quant_package sqp_bis ON sqp_bis.id = sq.package_id
                  WHERE sqp_bis.id = sqp.id
                  GROUP BY sqp_bis.id
                  HAVING count(DISTINCT sq.product_id) <> 1) or exists(SELECT 1
                  FROM
                    stock_quant_package sqp_bis
                  WHERE sqp_bis.parent_id = sqp.id)
    ) rqx)
            """)

    @api.multi
    def move_products(self):
        if self:
            location = self[0].location_id
            if any([line.location_id != location for line in self]):
                raise exceptions.except_orm(_("error"),
                                            _("Impossible to move simultaneously products of different locations"))
        ctx = self.env.context.copy()
        ctx['active_ids'] = self.ids
        return {
            'name': _("Move products"),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'product.move.wizard',
            'target': 'new',
            'context': ctx,
        }
