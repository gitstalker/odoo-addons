# -*- coding: utf-8 -*-
import logging

from openerp import http
from openerp.http import request

_logger = logging.getLogger(__name__)

class BarcodeController(http.Controller):

    @http.route(['/barcode_stock/web/'], type='http', auth='user')
    def a(self, debug=False, **k):
        if not request.session.uid:
            return http.local_redirect('/web/login?redirect=/barcode_stock/web')

        return request.render('barcode_stock.index')