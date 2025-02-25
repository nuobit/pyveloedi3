# The MIT License (MIT)
#
# Copyright (c) 2014 Max Holtzberg <mh@uvc.de>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
import urllib

from lxml import etree
from lxml.builder import ElementMaker
import requests
import re

from .base import ProductBase, ContextBase, EDIException, OrderBase, Model
from . import base

CAC_NAMESPACE = 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-1.0'
CBC_NAMESPACE = 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-1.0'
VCC_NAMESPACE = 'urn:veloconnect:catalog-1.1'
VCO_NAMESPACE = 'urn:veloconnect:order-1.1'
VCP_NAMESPACE = 'urn:veloconnect:profile-1.1'
VCT_NAMESPACE = 'urn:veloconnect:transaction-1.0'

NAMESPACES = {
    'cac': CAC_NAMESPACE,
    'cbc': CBC_NAMESPACE,
    'vcc': VCC_NAMESPACE,
    'vco': VCO_NAMESPACE,
    'vcp': VCP_NAMESPACE,
    'vct': VCT_NAMESPACE,
}

#
# Veloconnect Order
#
VCO = ElementMaker(namespace=VCO_NAMESPACE, nsmap=NAMESPACES)
GetItemDetailsRequest = VCO.GetItemDetailsRequest
GetItemDetailsListRequest = VCO.GetItemDetailsListRequest
RequestEntry = VCO.RequestEntry
CreateOrderRequest = VCO.CreateOrderRequest
OrderRequestLine = VCO.OrderRequestLine
ViewOrderRequest = VCO.ViewOrderRequest
UpdateOrderRequest = VCO.UpdateOrderRequest
FinishOrderRequest = VCO.FinishOrderRequest

#
# Common Aggregate Components
#
CAC = ElementMaker(namespace=CAC_NAMESPACE)
SellersItemIdentification = CAC.SellersItemIdentification
ID = CAC.ID

#
# Common Basic Components
#
CBC = ElementMaker(namespace=CBC_NAMESPACE)
Quantity = CBC.Quantity

#
# Veloconnect Transaction
#
VCT = ElementMaker(namespace=VCT_NAMESPACE)
BuyersID = VCT.BuyersID
Credential = VCT.Credential
Password = VCT.Password
TransactionID = VCT.TransactionID
RollbackRequest = VCT.RollbackRequest
IsTest = VCT.IsTest

#
# Veloconnect Catalog
#
ALT_NAMESPACE = {
    **NAMESPACES,
    None: VCC_NAMESPACE
}
ALT_NAMESPACE.pop('vcc')

VCC = ElementMaker(namespace=VCC_NAMESPACE, nsmap=ALT_NAMESPACE)
CreateTextSearchRequest = VCC.CreateTextSearchRequest
SearchString = VCC.SearchString
SearchResultRequest = VCC.SearchResultRequest
StartIndex = VCC.StartIndex
Count = VCC.Count
ResultFormat = VCC.ResultFormat
GetClassificationSchemeRequest = VCC.GetClassificationSchemeRequest

XML_POST_HEADER = {
    'Content-Type': 'application/xml',
}

ERR_NONE = 200
ERR_ANY = 400
ERR_NOT_SUPPORTED = 404
ERR_WRONG_REQUEST = 405
ERR_OLD_REQUEST = 406
ERR_UNKNOWN_USER = 410
ERR_AUTH_FAILED = 411
ERR_UNKNOWN_SELLERS_ID = 415
ERR_UNKNOWN_TRANSACTION_ID = 420
ERR_CANT_CREATE_TRANSACTION = 421
ERR_ILLEGAL_OP = 430
ERR_ILLEGAL_ISTEST = 435
ERR_INTERNAL = 500
ERR_INVALID_MAX_TRIES = 513
ERR_MAX_TRIES_REACHED = 514
ERR_MULTIPLE_ELEMENT_FOUND = 460
ERR_ELEMENT_NOT_FOUND = 461

ERR_CODES = {
    ERR_ANY: 'General error.',
    ERR_NOT_SUPPORTED: 'Request not supported.',
    ERR_WRONG_REQUEST: 'Wrong request.',
    ERR_OLD_REQUEST: 'Wrong request. (Old version)',
    ERR_UNKNOWN_USER: 'Unknown user.',
    ERR_AUTH_FAILED: 'Authentication failed.',
    ERR_UNKNOWN_SELLERS_ID: 'Unknown sellers ID',
    ERR_UNKNOWN_TRANSACTION_ID: 'Unknown transaction ID',
    ERR_CANT_CREATE_TRANSACTION: 'Can\'t create further transactions.',
    ERR_ILLEGAL_OP: 'Operation not possible in current transaction state.',
    ERR_ILLEGAL_ISTEST: 'IsTest not allowed in current transaction state.',
    ERR_INTERNAL: 'Internal error.',
    ERR_INVALID_MAX_TRIES: 'Max tries values should be greater than 0.',
    ERR_MAX_TRIES_REACHED: 'Max tries reached.',
    ERR_MULTIPLE_ELEMENT_FOUND: 'More than one elements found.',
    ERR_ELEMENT_NOT_FOUND: 'Element not found'
}


class VeloConnectException(EDIException):
    def __init__(self, code):
        self._code = code
        self._msg = ERR_CODES[code] + ' (Code: %d)' % code


class Context(ContextBase):
    MAX_FETCH_TRIES = 3

    def __init__(self, url, userid, passwd, istest=False, log=False, use_objects=True):
        self._istest = istest
        self._use_objects = use_objects
        super(Context, self).__init__(url, userid, passwd, log)
        self._params = None

    def _load_params(self):
        if self._params is not None:
            return
        gp = GetProfile(context=self)
        self._params = gp.get_params()

    def check(self):
        # Simply pulling the bindings does often work even if the
        # credentials are worng.
        try:
            Product = self.get('Product')
            Product.search(['NOTHING'])
        except:
            return False
        return True

    def get(self, clsname):
        self._load_params()
        if clsname == 'Product':
            return Product.copy(self)
        elif clsname == 'Order':
            return Order.copy(self)
        return None

    def dispatch_request(self, request):
        if request._name not in self._params:
            raise VeloConnectException(ERR_NOT_SUPPORTED)
        if self.MAX_FETCH_TRIES <= 0:
            raise VeloConnectException(ERR_INVALID_MAX_TRIES)
        ntry = 0
        while ntry < self.MAX_FETCH_TRIES:
            binding, uri = self._params[request._name]
            if binding == 'XML-POST':
                xml = etree.tostring(request.get_xml(), pretty_print=True)
                res = self.query_post(uri, xml)
            else:
                res = self.query_get(uri, request.get_url_args())

            self.log('XML response', res.decode())

            # Sometimes some supplier return invalid XML.
            # Normally when requesting the data again it will be fine.
            try:
                root = etree.fromstring(res)
                break
            except etree.XMLSyntaxError:
                self.log('XMLSyntaxError', 'Will fetch xml again.')
                ntry += 1
        if ntry == self.MAX_FETCH_TRIES:
            raise VeloConnectException(ERR_MAX_TRIES_REACHED)
        rcode, = root.xpath('//vct:ResponseCode', namespaces=NAMESPACES)
        err = int(rcode.text)
        if err != ERR_NONE:
            raise VeloConnectException(err)

        return root

    def query_get(self, uri, params):
        params += [
            ('BuyersID', self._userid),
            ('Password', self._passwd),
            ('IsTest', self._istest),
        ]
        self.log('URL for GET request', '%s?%s' % (uri, urllib.parse.urlencode(params)))
        resp = requests.get(uri, params=params)
        encoding = resp.encoding or resp.apparent_encoding or 'utf-8'
        return resp.text.encode(encoding)

    def query_post(self, uri, data):
        data = b'<?xml version="1.0" encoding="utf-8"?>\n' + data
        self.log('XML for POST request', '%s\n%s' % (uri, data.decode()))
        resp = requests.post(uri, data=data, headers=XML_POST_HEADER)
        encoding = resp.encoding or resp.apparent_encoding or 'utf-8'
        return resp.text.encode(encoding)


class Operation(object):
    def __init__(self, context):
        self._ctx = context

        self._xml_auth = [
            BuyersID(self._ctx._userid),
            Credential(Password(self._ctx._passwd)),
        ]
        self._xml_istest = IsTest(str(int(self._ctx._istest)))

    def get_url_args(self):
        raise NotImplementedError(
            'URL binding not implemented for %s.' % self._name)

    def get_xml(self):
        raise NotImplementedError(
            'XML binding not implemented for %s.' % self._name)

    def execute(self):
        self._ctx.dispatch_request(self)

    def _format_item(self, item):
        product = Product(item)
        # return only products without replacement
        return not product.replacement and product or None

    def _format_items(self, items):
        res = []
        for item in items:
            product = self._format_item(item)
            if product:
                res.append(product)
        return res


class Rollback(Operation):
    _name = 'Rollback'

    def get_url_args(self):
        return [
            ('RequestName', 'RollbackRequest'),
            ('TransactionID', self._tan),
        ]

    def get_xml(self):
        res = RollbackRequest()
        res.extend(self._xml_auth)
        res.append(TransactionID(self._tan))
        return res

    def execute(self, tan):
        self._tan = tan
        self._ctx.dispatch_request(self)


class GetProfile(Operation):
    _name = 'GetProfile'

    def get_params(self):
        profile = self._ctx.query_get(self._ctx._url, [('RequestName', 'GetProfileRequest')])
        root = etree.fromstring(profile)
        implements = root.xpath(
            '/vcp:GetProfileResponse/vcp:VeloconnectProfile/vcp:Implements',
            namespaces=NAMESPACES)

        find = lambda path: impl.find(path, namespaces=NAMESPACES)
        bindings = {}
        for impl in implements:
            binding = find('vcp:Binding')
            uri = find('vcp:URI')
            uri_text = uri is not None and uri.text or self._ctx._url
            op = find('vcp:Transaction')
            if op is None:
                op = find('vcp:Operation')

            # Overwrite URL bindings in favor of XML-POST
            if binding.text in ('XML-POST', 'XML-POST-S'):
                bindings[op.text] = ('XML-POST', uri_text)
            elif op.text not in bindings:
                bindings[op.text] = (binding.text, uri_text)

        return bindings


class GetClassificationScheme(Operation):
    _name = 'GetClassificationScheme'

    def get_xml(self):
        return GetClassificationSchemeRequest(self._xml_auth)

    def execute(self):
        res = self._ctx.dispatch_request(self)


class GetItemDetails(Operation):
    _name = 'GetItemDetails'

    def get_url_args(self):
        return [
            ('RequestName', 'GetItemDetailsRequest'),
            ('SellersItemIdentification', self._code)]

    def get_xml(self):
        req = GetItemDetailsRequest()
        req.extend(self._xml_auth)
        req.append(SellersItemIdentification(
            ID(self._code)))
        return req

    def execute(self, code):
        self._code = code
        root = self._ctx.dispatch_request(self)
        item = root.xpath(
            '/vco:GetItemDetailsResponse',
            namespaces=NAMESPACES)
        if len(item) > 1:
            raise VeloConnectException(ERR_MULTIPLE_ELEMENT_FOUND)
        elif not item:
            raise VeloConnectException(ERR_ELEMENT_NOT_FOUND)
        if not self._ctx._use_objects:
            return item[0]
        return self._format_item(item[0])


class GetItemDetailsList(Operation):
    _name = 'GetItemDetailsList'

    def get_url_args(self):
        args = [('RequestName', 'GetItemDetailsListRequest')]
        for code in self._codes:
            args.append(('SellersItemIdentification', code))
        return args

    def get_xml(self):
        req = GetItemDetailsListRequest()
        req.extend(self._xml_auth)
        for code in self._codes:
            req.append(RequestEntry(SellersItemIdentification(
                ID(code))))
        return req

    def execute(self, codes):
        self._codes = codes
        root = self._ctx.dispatch_request(self)
        items = root.xpath(
            '/vco:GetItemDetailsListResponse/vco:ItemDetail',
            namespaces=NAMESPACES)
        if not self._ctx._use_objects:
            return items
        return self._format_items(items)


class CreateTextSearch(Operation):
    _name = 'TextSearch'

    def get_url_args(self):
        res = [('RequestName', 'CreateTextSearchRequest')]
        if self._keywords:
            res.append(('SearchString', self._keywords))
        return res

    def get_xml(self):
        res = CreateTextSearchRequest()
        res.extend(self._xml_auth)
        if self._keywords:
            res.append(SearchString(self._keywords))
        return res

    def execute(self, keywords):
        self._keywords = keywords
        return TextSearchResponse(self._ctx.dispatch_request(self))


class SearchResult(Operation):
    _name = 'TextSearch'

    def get_url_args(self):
        return [
            ('RequestName', 'SearchResultRequest'),
            ('TransactionID', self._tan),
            ('StartIndex', self._offset),
            ('Count', self._limit),
            ('ResultFormat', 'ID_ONLY'),
        ]

    def get_xml(self):
        res = SearchResultRequest()
        res.extend(self._xml_auth + [
            TransactionID(self._tan),
            StartIndex(str(self._offset)),
            Count(str(self._limit)),
            ResultFormat('ID_ONLY'),
        ])
        return res

    def execute(self, tan, offset, limit):
        self._offset = offset
        self._limit = limit
        self._tan = tan
        root = self._ctx.dispatch_request(self)
        # Some implementations differ, so:
        items = root.xpath('//cac:SellersItemIdentification/cac:ID',
                           namespaces=NAMESPACES)
        return [i.text for i in items]


class SearchReadResult(Operation):
    _name = 'TextSearch'

    def get_url_args(self):
        return [
            ('RequestName', 'SearchResultRequest'),
            ('TransactionID', self._tan),
            ('StartIndex', self._offset),
            ('Count', self._limit),
            ('ResultFormat', 'ITEM_DETAIL'),
        ]

    def get_xml(self):
        res = SearchResultRequest()
        res.extend(self._xml_auth + [
            TransactionID(self._tan),
            StartIndex(str(self._offset)),
            Count(str(self._limit)),
            ResultFormat('ITEM_DETAIL'),
        ])
        return res

    def execute(self, tan, offset, limit):
        self._offset = offset
        self._limit = limit
        self._tan = tan
        root = self._ctx.dispatch_request(self)
        items = root.xpath(
            '/vcc:SearchResultResponse/vco:ItemDetail',
            namespaces=NAMESPACES)
        if not self._ctx._use_objects:
            return items
        return self._format_items(items)


class CreateOrder(Operation):
    _name = 'Order'

    def get_url_args(self):
        args = [('RequestName', 'CreateOrderRequest')]
        for line in self._lines:
            product_id = line.find('cac:SellersItemIdentification/cac:ID',
                                   namespaces=NAMESPACES).text
            quantity = line.find('cbc:Quantity', namespaces=NAMESPACES)
            args += [
                ('Quantity.' + product_id, quantity.text),
                ('quantityUnitCode.' + product_id, quantity.get('quantityUnitCode'))
            ]
        return args

    def get_xml(self):
        res = CreateOrderRequest()
        res.extend(self._xml_auth)
        res.append(self._xml_istest)
        res.extend(self._lines)
        return res

    def execute(self, lines):
        self._lines = lines
        return Order(self._ctx.dispatch_request(self), self._ctx)


class UpdateOrder(Operation):
    _name = 'Order'

    def get_xml(self):
        res = UpdateOrderRequest()
        res.extend(self._xml_auth)
        res.append(TransactionID(self._tan))
        res.append(self._xml_istest)
        res.extend(self._lines)
        return res

    def execute(self, tan, lines):
        self._lines = lines
        self._tan = tan
        return self._ctx.dispatch_request(self)


class ViewOrder(Operation):
    _name = 'Order'

    def get_xml(self):
        res = ViewOrderRequest()
        res.extend(self._xml_auth)
        res.append(TransactionID(self._tan))
        res.append(self._xml_istest)
        return res

    def execute(self, tan):
        self._tan = tan
        return self._ctx.dispatch_request(self)


class FinishOrder(Operation):
    _name = 'Order'

    def get_url_args(self):
        return [
            ('RequestName', 'FinishOrderRequest'),
            ('TransactionID', self._tan),
        ]

    def get_xml(self):
        res = FinishOrderRequest()
        res.extend(self._xml_auth)
        res.append(TransactionID(self._tan))
        res.append(self._xml_istest)
        return res

    def execute(self, tan):
        self._tan = tan
        return self._ctx.dispatch_request(self)


#
# Veloconnect XML Models
#
class VeloModelMixin(object):
    _namespaces = NAMESPACES


class TransactionMixin(object):
    tan = base.String('vct:TransactionID')

    def rollback(self):
        try:
            rbk = Rollback(self._ctx)
            rbk.execute(self.tan)
        except VeloConnectException as e:
            if e.code != ERR_NOT_SUPPORTED:
                raise


class TextSearchResponse(VeloModelMixin, TransactionMixin, Model):
    count = base.Integer('vcc:TotalCount')


class Product(VeloModelMixin, ProductBase):
    _name_exp = re.compile(r'[\n\r]|&nbsp;')
    _prefixes = ['cac:Item/']  # 'Works with ItemDetail and Item nodes.'

    valid = ~base.Bool(
        'vco:ItemUnknown/cac:SellersItemIdentification/cac:ID', default=True)
    code = base.String(
        'cac:SellersItemIdentification/cac:ID',
        'vco:RequestReplacement/cac:SellersItemIdentification/cac:ID',
        'vco:ItemUnknown/cac:SellersItemIdentification/cac:ID')
    replacement = base.String(
        'vco:RequestReplacement/cac:ItemReplacement/cac:ID')
    description = base.String('cbc:Description',
                              subst=(r'&nbsp;', ' '))
    list_price = base.Decimal(
        'cac:RecommendedRetailPrice/cbc:PriceAmount')
    cost_price = base.Decimal('cac:BasePrice/cbc:PriceAmount')
    unit_code = base.Attribute('cac:BasePrice/cbc:BaseQuantity',
                               attr='quantityUnitCode')
    manufacturer = base.String('cac:ManufacturersItemIdentification'
                               '/cac:IssuerParty/cac:PartyName/cbc:Name')
    manufacturer_id = base.String('cac:Item/cac:ManufacturersItemIdentification/cac:ID')
    availability = base.String('vco:Availability/vco:Code')
    available_quantity = base.Decimal('vco:Availability/vco:AvailableQuantity')

    @property
    def name(self):
        if self.description is None:
            return None
        return self._name_exp.sub(' ', self.description[:100] + '...')

    @property
    def ean13(self):
        ean13 = self._data.xpath(
            'cac:Item/cac:StandardItemIdentification'
            '/cac:ID[@identificationSchemeID="EAN/UCC-13"]',
            namespaces=NAMESPACES)
        return len(ean13) and ean13[0].text or None

    @property
    def sellers_item_identification(self):
        return SellersItemIdentification(ID(self.code))

    @property
    def picture(self):
        urls = self._data.xpath(
            'cac:Item/vcc:ItemInformation/vcc:InformationURL'
            '/vcc:Disposition[text()="picture"]/../vcc:URI',
            namespaces=NAMESPACES)
        url = len(urls) and urls[0].text or None
        if url is None:
            return None
        return memoryview(requests.get(url).content)

    @classmethod
    def search(cls, keywords, offset=0, limit=20, count=False):
        cts = CreateTextSearch(cls._ctx)
        ctsresp = cts.execute(keywords)

        if count:
            return ctsresp.count

        if ctsresp.count == 0:
            return []

        sr = SearchResult(cls._ctx)
        if limit <= 0:
            limit = ctsresp.count
        return sr.execute(ctsresp.tan, offset, limit)

    @classmethod
    def search_read(cls, keywords, offset=0, limit=20, count=False):
        cts = CreateTextSearch(cls._ctx)
        ctsresp = cts.execute(keywords)

        if count:
            return ctsresp.count

        if ctsresp.count == 0:
            return []

        sr = SearchReadResult(cls._ctx)
        if limit <= 0:
            limit = ctsresp.count
        return sr.execute(ctsresp.tan, offset, limit)

    @classmethod
    def read(cls, codes):
        gidl = GetItemDetailsList(cls._ctx)
        return gidl.execute(codes)


class Line(VeloModelMixin, Model):
    quantity = base.Decimal('cbc:Quantity')
    unit_price = base.Decimal('cac:UnitPrice')
    product = base.Many2One('cac:Item', model=Product)
    availability = base.String('vco:Availability/vco:Code')
    available_quantity = base.Decimal('vco:Availability/vco:AvailableQuantity')


class Order(VeloModelMixin, TransactionMixin, OrderBase):
    lines = base.One2Many('/vco:OrderResponse/vco:OrderResponseLine',
                          model=Line)
    orderid = base.String('vco:OrderHeader/vco:OrderID')

    def _load(self, tan):
        vo = ViewOrder(self._ctx)
        self._data = vo.execute(tan)

    @staticmethod
    def _build_lines(lines):
        rlines = []
        for product, qty in lines:
            line = OrderRequestLine(product.sellers_item_identification,
                                    Quantity(str(qty), quantityUnitCode=product.unit_code))
            rlines.append(line)
        return rlines

    def add_lines(self, lines):
        uo = UpdateOrder(self._ctx)
        self._data = uo.execute(self.tan, self._build_lines(lines))

    def finish(self):
        fo = FinishOrder(self._ctx)
        self._data = fo.execute(self.tan)
        return self

    @classmethod
    def create(cls, lines):
        co = CreateOrder(cls._ctx)
        return co.execute(cls._build_lines(lines))
