"""OpenAPI 3.0 specification and Swagger UI for the mobile API.

Served at:
  GET /api/docs          — interactive Swagger UI (try requests straight from it)
  GET /api/openapi.json  — the raw specification

The spec is written by hand rather than generated from decorators: every route
in this app answers as both HTML and JSON (see app/api.py), so an introspecting
generator would document the web pages too. This file describes the JSON
contract only — what a mobile client actually calls.
"""
from flask import Blueprint, jsonify, render_template_string, url_for

docs_bp = Blueprint('docs', __name__)

API_VERSION = '1.0.0'


# ─────────────────────────────────────────────────────────────────────────────
# Small builders — keep the path table below readable
# ─────────────────────────────────────────────────────────────────────────────
def _ref(name):
    return {'$ref': f'#/components/schemas/{name}'}


def _envelope(data_schema=None, extra=None):
    """Every successful response is {"success": true, "data": ...}."""
    props = {'success': {'type': 'boolean', 'example': True}}
    if data_schema is not None:
        props['data'] = data_schema
    if extra:
        props.update(extra)
    return {'type': 'object', 'properties': props}


def _ok(description, data_schema=None, extra=None, status='200'):
    return {status: {'description': description,
                     'content': {'application/json':
                                 {'schema': _envelope(data_schema, extra)}}}}


def _errors(*codes):
    """Attach the standard error envelope to the given status codes."""
    known = {
        '400': 'Malformed request.',
        '401': 'Not authenticated — send a bearer token.',
        '403': 'Authenticated, but not allowed (admin-only, or a suspended account).',
        '404': 'No such resource.',
        '405': 'Wrong HTTP method for this path.',
        '409': 'Conflict — usually stock ran out between adding and checkout.',
        '422': 'Validation failed. See `errors` for the field messages.',
        '500': 'Unexpected server error.',
    }
    out = {}
    for code in codes:
        out[code] = {'description': known.get(code, 'Error.'),
                     'content': {'application/json': {'schema': _ref('Error')}}}
    return out


def _body(properties, required=(), description=None):
    """A JSON request body. Every endpoint also accepts the same fields as
    form-encoded data, which is how the HTML pages post them."""
    schema = {'type': 'object', 'properties': properties}
    if required:
        schema['required'] = list(required)
    content = {'application/json': {'schema': schema},
               'application/x-www-form-urlencoded': {'schema': schema}}
    body = {'required': True, 'content': content}
    if description:
        body['description'] = description
    return body


def _path_param(name, description, schema=None):
    return {'name': name, 'in': 'path', 'required': True,
            'description': description,
            'schema': schema or {'type': 'integer'}}


def _query(name, description, schema=None, example=None):
    param = {'name': name, 'in': 'query', 'required': False,
             'description': description, 'schema': schema or {'type': 'string'}}
    if example is not None:
        param['example'] = example
    return param


PAGE_PARAM = _query('page', 'Page number, 1-based.', {'type': 'integer', 'default': 1})

AUTH = [{'bearerAuth': []}]

_PAGINATION = {
    'page':  {'type': 'integer', 'example': 1},
    'pages': {'type': 'integer', 'example': 4},
    'total': {'type': 'integer', 'example': 47},
}


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
def _schemas():
    return {
        'Error': {
            'type': 'object',
            'properties': {
                'success': {'type': 'boolean', 'example': False},
                'error': {'type': 'string', 'example': 'Not found'},
                'errors': {'type': 'array', 'items': {'type': 'string'},
                           'description': 'Present on 422 — one message per failed field.'},
            },
        },
        'User': {
            'type': 'object',
            'properties': {
                'user_id': {'type': 'integer', 'example': 4},
                'name': {'type': 'string', 'example': 'Alice Chan'},
                'email': {'type': 'string', 'format': 'email'},
                'phone': {'type': 'string', 'nullable': True},
                'is_active': {'type': 'boolean',
                              'description': 'False means the account is suspended and cannot sign in.'},
                'roles': {'type': 'array', 'items': {'type': 'string'},
                          'example': ['Customer']},
                'skin_profile': {'nullable': True, 'allOf': [_ref('SkinProfile')]},
                'created_at': {'type': 'string', 'format': 'date-time'},
                'stats': {'allOf': [_ref('CustomerStats')],
                          'description': 'Admin views only.'},
            },
        },
        'CustomerStats': {
            'type': 'object',
            'properties': {
                'order_count': {'type': 'integer', 'example': 6},
                'total_spent': {'type': 'number', 'format': 'float', 'example': 412.5},
                'average_order': {'type': 'number', 'format': 'float', 'example': 68.75},
                'last_order_date': {'type': 'string', 'format': 'date-time', 'nullable': True},
            },
        },
        'SkinProfile': {
            'type': 'object',
            'properties': {
                'skin_type_id': {'type': 'integer', 'nullable': True},
                'age_range': {'type': 'string', 'nullable': True, 'example': '25-34'},
                'concerns': {'type': 'array', 'items': _ref('Concern')},
            },
        },
        'Category': {
            'type': 'object',
            'properties': {
                'category_id': {'type': 'integer', 'example': 3},
                'parent_id': {'type': 'integer', 'nullable': True},
                'name': {'type': 'string', 'example': 'Cleansers'},
                'slug': {'type': 'string', 'example': 'cleansers'},
                'description': {'type': 'string', 'nullable': True},
                'image': {'type': 'string', 'nullable': True},
                'sort_order': {'type': 'integer'},
                'product_count': {'type': 'integer',
                                  'description': 'Active products filed directly on this category.'},
                'total_product_count': {'type': 'integer',
                                        'description': 'Including everything under its children.'},
                'children': {'type': 'array', 'items': _ref('Category')},
            },
        },
        'Brand': {
            'type': 'object',
            'properties': {
                'brand_id': {'type': 'integer'},
                'name': {'type': 'string', 'example': 'Hanbit'},
                'slug': {'type': 'string'},
                'logo': {'type': 'string', 'nullable': True},
            },
        },
        'Concern': {
            'type': 'object',
            'properties': {
                'concern_id': {'type': 'integer'},
                'name': {'type': 'string', 'example': 'Dark spots'},
                'slug': {'type': 'string'},
            },
        },
        'ProductImage': {
            'type': 'object',
            'properties': {
                'image_id': {'type': 'integer'},
                'product_id': {'type': 'integer'},
                'image_url': {'type': 'string'},
                'alt_text': {'type': 'string', 'nullable': True},
                'is_primary': {'type': 'boolean'},
                'sort_order': {'type': 'integer'},
            },
        },
        'Variant': {
            'type': 'object',
            'properties': {
                'variant_id': {'type': 'integer', 'example': 12},
                'product_id': {'type': 'integer'},
                'sku': {'type': 'string'},
                'size': {'type': 'string', 'nullable': True, 'example': '50ml'},
                'shade': {'type': 'string', 'nullable': True},
                'price': {'type': 'number', 'format': 'float', 'example': 24.0},
                'compare_at_price': {'type': 'number', 'format': 'float', 'nullable': True,
                                     'description': 'Was-price. Higher than `price` means it is on sale.'},
                'stock': {'type': 'integer', 'example': 18},
                'expiry_date': {'type': 'string', 'format': 'date', 'nullable': True},
            },
        },
        'Product': {
            'type': 'object',
            'properties': {
                'product_id': {'type': 'integer', 'example': 7},
                'name': {'type': 'string', 'example': 'Barrier Repair Moisturiser'},
                'slug': {'type': 'string'},
                'description': {'type': 'string', 'nullable': True},
                'base_price': {'type': 'number', 'format': 'float', 'example': 24.0},
                'category_id': {'type': 'integer', 'nullable': True},
                'brand_id': {'type': 'integer', 'nullable': True},
                'brand_name': {'type': 'string', 'nullable': True},
                'product_type': {'type': 'string', 'nullable': True, 'example': 'Moisturiser'},
                'routine_step': {'type': 'integer', 'nullable': True},
                'spf': {'type': 'integer', 'nullable': True},
                'is_active': {'type': 'boolean'},
                'is_vegan': {'type': 'boolean'},
                'is_cruelty_free': {'type': 'boolean'},
                'is_fragrance_free': {'type': 'boolean'},
                'is_non_comedogenic': {'type': 'boolean'},
                'is_dermatologist_tested': {'type': 'boolean'},
                'avg_rating': {'type': 'number', 'format': 'float', 'example': 4.5},
                'review_count': {'type': 'integer', 'example': 12},
                'primary_image': {'type': 'string', 'nullable': True},
                'images': {'type': 'array', 'items': _ref('ProductImage')},
                'variants': {'type': 'array', 'items': _ref('Variant'),
                             'description': 'Omitted from list endpoints — fetch the product to get them.'},
            },
        },
        'CartItem': {
            'type': 'object',
            'properties': {
                'cart_item_id': {'type': 'integer', 'example': 31},
                'variant_id': {'type': 'integer'},
                'product_id': {'type': 'integer'},
                'product_name': {'type': 'string'},
                'brand_name': {'type': 'string', 'nullable': True},
                'size': {'type': 'string', 'nullable': True},
                'price': {'type': 'number', 'format': 'float'},
                'quantity': {'type': 'integer', 'example': 2},
                'subtotal': {'type': 'number', 'format': 'float'},
                'stock': {'type': 'integer'},
                'image': {'type': 'string', 'nullable': True},
            },
        },
        'Cart': {
            'type': 'object',
            'properties': {
                'cart_id': {'type': 'integer'},
                'user_id': {'type': 'integer'},
                'items': {'type': 'array', 'items': _ref('CartItem')},
                'item_count': {'type': 'integer', 'example': 3},
                'total': {'type': 'number', 'format': 'float', 'example': 72.0},
            },
        },
        'OrderItem': {
            'type': 'object',
            'properties': {
                'order_item_id': {'type': 'integer'},
                'variant_id': {'type': 'integer'},
                'product_name': {'type': 'string',
                                 'description': 'Snapshot taken at purchase time — survives a rename.'},
                'variant_label': {'type': 'string', 'nullable': True},
                'price': {'type': 'number', 'format': 'float',
                          'description': 'Price captured at purchase time, not the current price.'},
                'quantity': {'type': 'integer'},
                'subtotal': {'type': 'number', 'format': 'float'},
            },
        },
        'Order': {
            'type': 'object',
            'properties': {
                'order_id': {'type': 'integer', 'example': 1042},
                'user_id': {'type': 'integer'},
                'created_at': {'type': 'string', 'format': 'date-time'},
                'status': {'type': 'string',
                           'enum': ['Pending', 'Processing', 'Shipped', 'Delivered', 'Cancelled']},
                'subtotal': {'type': 'number', 'format': 'float'},
                'discount_amount': {'type': 'number', 'format': 'float'},
                'shipping_fee': {'type': 'number', 'format': 'float'},
                'tax': {'type': 'number', 'format': 'float'},
                'total_amount': {'type': 'number', 'format': 'float', 'example': 78.5},
                'coupon_id': {'type': 'integer', 'nullable': True},
                'shipping_method_id': {'type': 'integer', 'nullable': True},
                'shipping_method': {'type': 'string', 'nullable': True},
                'item_count': {'type': 'integer'},
                'items': {'type': 'array', 'items': _ref('OrderItem'),
                          'description': 'Omitted where the endpoint lists many orders.'},
                'payment': {'nullable': True, 'allOf': [_ref('Payment')]},
                'shipping': {'nullable': True, 'allOf': [_ref('Shipping')]},
                'status_history': {'type': 'array', 'items': {'type': 'object'}},
            },
        },
        'Payment': {
            'type': 'object',
            'properties': {
                'payment_id': {'type': 'integer'},
                'method': {'type': 'string',
                           'enum': ['Cash', 'Card', 'PayPal', 'Bank Transfer', 'KHQR']},
                'status': {'type': 'string', 'enum': ['Pending', 'Paid', 'Failed', 'Refunded']},
                'amount': {'type': 'number', 'format': 'float'},
                'paid_at': {'type': 'string', 'format': 'date-time', 'nullable': True},
            },
        },
        'Shipping': {
            'type': 'object',
            'properties': {
                'shipping_id': {'type': 'integer'},
                'recipient_name': {'type': 'string'},
                'address': {'type': 'string'},
                'city': {'type': 'string'},
                'postal_code': {'type': 'string', 'nullable': True},
                'country': {'type': 'string'},
                'phone': {'type': 'string'},
                'status': {'type': 'string'},
                'tracking_number': {'type': 'string', 'nullable': True},
            },
        },
        'Address': {
            'type': 'object',
            'properties': {
                'address_id': {'type': 'integer'},
                'label': {'type': 'string', 'example': 'Home'},
                'recipient_name': {'type': 'string'},
                'phone': {'type': 'string'},
                'line1': {'type': 'string'},
                'line2': {'type': 'string', 'nullable': True},
                'city': {'type': 'string'},
                'state': {'type': 'string', 'nullable': True},
                'postal_code': {'type': 'string', 'nullable': True},
                'country': {'type': 'string', 'example': 'Cambodia'},
                'is_default': {'type': 'boolean'},
            },
        },
        'Wishlist': {
            'type': 'object',
            'properties': {
                'wishlist_id': {'type': 'integer'},
                'user_id': {'type': 'integer'},
                'item_count': {'type': 'integer'},
                'items': {'type': 'array', 'items': {
                    'type': 'object',
                    'properties': {
                        'wishlist_item_id': {'type': 'integer'},
                        'product_id': {'type': 'integer'},
                        'product': _ref('Product'),
                    },
                }},
            },
        },
        'Review': {
            'type': 'object',
            'properties': {
                'review_id': {'type': 'integer'},
                'user_id': {'type': 'integer'},
                'product_id': {'type': 'integer'},
                'user_name': {'type': 'string'},
                'rating': {'type': 'integer', 'minimum': 1, 'maximum': 5, 'example': 5},
                'title': {'type': 'string', 'nullable': True},
                'comment': {'type': 'string', 'nullable': True},
                'skin_type_id': {'type': 'integer', 'nullable': True},
                'age_range': {'type': 'string', 'nullable': True},
                'is_verified_purchase': {'type': 'boolean'},
                'created_at': {'type': 'string', 'format': 'date-time'},
            },
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
def _auth_paths():
    return {
        '/api/auth/register': {'post': {
            'tags': ['Auth'], 'summary': 'Create an account',
            'description': 'Creates the user, assigns the Customer role and an empty cart. '
                           'Does **not** sign them in — call `/api/auth/login` next.',
            'requestBody': _body({
                'name': {'type': 'string', 'example': 'Alice Chan'},
                'email': {'type': 'string', 'format': 'email', 'example': 'alice@example.com'},
                'password': {'type': 'string', 'minLength': 6, 'example': 'secret123'},
                'confirm': {'type': 'string', 'example': 'secret123'},
                'phone': {'type': 'string', 'example': '+855 12 345 678'},
            }, required=['name', 'email', 'password', 'confirm']),
            'responses': {**_ok('Account created.', _ref('User'), status='201'),
                          **_errors('422')},
        }},
        '/api/auth/login': {'post': {
            'tags': ['Auth'], 'summary': 'Sign in and get a bearer token',
            'description': 'The `token` in the response is what mobile clients send as '
                           '`Authorization: Bearer <token>` on every later request. '
                           'It is valid for 30 days and stops working immediately if the '
                           'account is deactivated.',
            'requestBody': _body({
                'email': {'type': 'string', 'format': 'email', 'example': 'alice@example.com'},
                'password': {'type': 'string', 'example': 'password'},
                'remember': {'type': 'boolean', 'default': False},
            }, required=['email', 'password']),
            'responses': {
                **_ok('Signed in.', _ref('User'),
                      extra={'token': {'type': 'string',
                                       'example': 'eyJ1c2VyX2lkIjo0fQ.aBcDeF.xxxxxxxx'}}),
                **_errors('401', '403'),
            },
        }},
        '/api/auth/logout': {'get': {
            'tags': ['Auth'], 'summary': 'Sign out', 'security': AUTH,
            'description': 'Clears the session cookie. Bearer tokens are stateless — a '
                           'mobile client should also discard its stored token.',
            'responses': {**_ok('Signed out.',
                                extra={'message': {'type': 'string'}}), **_errors('401')},
        }},
        '/api/auth/profile': {
            'get': {'tags': ['Auth'], 'summary': 'Get the signed-in user', 'security': AUTH,
                    'responses': {**_ok('The current user.', _ref('User')), **_errors('401')}},
            'post': {'tags': ['Auth'], 'summary': 'Update name, phone or password',
                     'security': AUTH,
                     'requestBody': _body({
                         'name': {'type': 'string'},
                         'phone': {'type': 'string'},
                         'new_password': {'type': 'string', 'minLength': 6,
                                          'description': 'Omit to keep the current password.'},
                     }),
                     'responses': {**_ok('Updated.', _ref('User')), **_errors('401', '422')}},
        },
    }


def _catalog_paths():
    product_array = {'type': 'array', 'items': _ref('Product')}
    return {
        '/api/': {'get': {
            'tags': ['Catalog'], 'summary': 'Home feed',
            'description': 'Everything a home screen needs in one call: new arrivals, '
                           'best sellers, sale items, the category tree, concerns, skin '
                           'types, brands, bundles and active promotions.',
            'responses': _ok('The home feed.', {'type': 'object', 'properties': {
                'new_in': product_array, 'bestsellers': product_array,
                'on_sale': product_array,
                'categories': {'type': 'array', 'items': _ref('Category')},
                'concerns': {'type': 'array', 'items': _ref('Concern')},
                'brands': {'type': 'array', 'items': _ref('Brand')},
                'stats': {'type': 'object'},
            }}),
        }},
        '/api/products/': {'get': {
            'tags': ['Catalog'], 'summary': 'Search and filter products',
            'description': 'Paginated, 12 per page. Repeat `brand`, `concern`, '
                           '`ingredient` and `claim` to filter on several values — '
                           'concerns narrow (AND), so `?concern=1&concern=2` returns '
                           'products that address both.',
            'parameters': [
                PAGE_PARAM,
                _query('q', 'Free-text search across name, description, type, INCI list and brand.', example='niacinamide'),
                _query('category', 'Category id. A parent category includes its children.', {'type': 'integer'}),
                _query('brand', 'Brand id. Repeatable.', {'type': 'integer'}),
                _query('type', 'Product type, e.g. "Serum".'),
                _query('step', 'Routine step number.', {'type': 'integer'}),
                _query('skin_type', 'Skin type id.', {'type': 'integer'}),
                _query('concern', 'Skin concern id. Repeatable (AND).', {'type': 'integer'}),
                _query('ingredient', 'Ingredient id. Repeatable.', {'type': 'integer'}),
                _query('claim', 'One of vegan, cruelty_free, fragrance_free, non_comedogenic, dermatologist_tested. Repeatable.'),
                _query('min_price', 'Minimum base price.', {'type': 'number'}),
                _query('max_price', 'Maximum base price.', {'type': 'number'}),
                _query('spf', 'Set to 1 for SPF products only.', {'type': 'string', 'enum': ['1']}),
                _query('in_stock', 'Set to 1 to hide sold-out products.', {'type': 'string', 'enum': ['1']}),
                _query('on_sale', 'Set to 1 for discounted products only.', {'type': 'string', 'enum': ['1']}),
                _query('sort', 'Ordering.', {'type': 'string', 'default': 'newest',
                                             'enum': ['newest', 'price_asc', 'price_desc', 'rating', 'name']}),
            ],
            'responses': _ok('A page of products, plus every available filter value.',
                             {'type': 'object', 'properties': {
                                 'products': product_array, **_PAGINATION,
                                 'filters': {'type': 'object',
                                             'description': 'The filters as the server parsed them.'},
                                 'options': {'type': 'object',
                                             'description': 'Categories, brands, concerns, … for building a filter UI.'},
                             }}),
        }},
        '/api/products/{product_id}': {'get': {
            'tags': ['Catalog'], 'summary': 'Product detail',
            'description': 'Full product with variants, images, ingredients, reviews and '
                           'related products. `in_wishlist` is always false when the '
                           'caller is not signed in.',
            'parameters': [_path_param('product_id', 'Product id.'),
                           _query('review_skin_type', 'Only show reviews from this skin type.', {'type': 'integer'})],
            'responses': {**_ok('The product.', {'type': 'object', 'properties': {
                'product': _ref('Product'),
                'reviews': {'type': 'array', 'items': _ref('Review')},
                'related': product_array,
                'in_wishlist': {'type': 'boolean'},
            }}), **_errors('404')},
        }},
        '/api/products/for-you': {'get': {
            'tags': ['Catalog'], 'summary': 'Personalised recommendations',
            'description': 'Matched against the signed-in user\'s saved skin profile. '
                           'Falls back to general bestsellers for anonymous callers.',
            'responses': _ok('Recommended products.', product_array),
        }},
        '/api/products/brand/{slug}': {'get': {
            'tags': ['Catalog'], 'summary': 'Products by brand',
            'parameters': [_path_param('slug', 'Brand slug.', {'type': 'string'})],
            'responses': {**_ok('Products for the brand.', {'type': 'object'}), **_errors('404')},
        }},
        '/api/products/concern/{slug}': {'get': {
            'tags': ['Catalog'], 'summary': 'Products by skin concern',
            'parameters': [_path_param('slug', 'Concern slug, e.g. "dark-spots".', {'type': 'string'})],
            'responses': {**_ok('Products for the concern.', {'type': 'object'}), **_errors('404')},
        }},
        '/api/products/ingredient/{slug}': {'get': {
            'tags': ['Catalog'], 'summary': 'Products containing an ingredient',
            'parameters': [_path_param('slug', 'Ingredient slug, e.g. "niacinamide".', {'type': 'string'})],
            'responses': {**_ok('Products with the ingredient.', {'type': 'object'}), **_errors('404')},
        }},
        '/api/products/bundles': {'get': {
            'tags': ['Catalog'], 'summary': 'List routine kits (bundles)',
            'responses': _ok('Active bundles.', {'type': 'array', 'items': {'type': 'object'}}),
        }},
        '/api/products/bundles/{slug}': {'get': {
            'tags': ['Catalog'], 'summary': 'Bundle detail',
            'parameters': [_path_param('slug', 'Bundle slug.', {'type': 'string'})],
            'responses': {**_ok('The bundle and its members.', {'type': 'object'}), **_errors('404')},
        }},
        '/api/ingredients': {'get': {
            'tags': ['Catalog'], 'summary': 'Ingredient glossary',
            'description': 'Plain-language reference, split into active and supporting ingredients.',
            'responses': _ok('The glossary.', {'type': 'object'}),
        }},
    }


def _category_paths():
    return {
        '/api/categories/': {'get': {
            'tags': ['Categories'], 'summary': 'The category tree',
            'description': 'Root categories with their children nested underneath, each '
                           'carrying a live product count. Use `?flat=1` for one '
                           'ungrouped list instead.',
            'parameters': [_query('flat', 'Set to 1 for a flat list rather than a tree.',
                                  {'type': 'string', 'enum': ['1']})],
            'responses': _ok('The categories.', {'type': 'array', 'items': _ref('Category')},
                             extra={'count': {'type': 'integer'}}),
        }},
        '/api/categories/{identifier}': {'get': {
            'tags': ['Categories'], 'summary': 'One category with a page of its products',
            'description': 'Accepts either a numeric id or a slug. Products include '
                           'everything filed under child categories.',
            'parameters': [_path_param('identifier', 'Category id or slug.', {'type': 'string'}),
                           PAGE_PARAM],
            'responses': {**_ok('The category, its ancestry and its products.',
                                {'type': 'object', 'properties': {
                                    'category': _ref('Category'),
                                    'breadcrumb': {'type': 'array', 'items': _ref('Category')},
                                    'products': {'type': 'array', 'items': _ref('Product')},
                                    **_PAGINATION,
                                }}),
                          **_errors('404')},
        }},
        '/api/categories/{identifier}/products': {'get': {
            'tags': ['Categories'], 'summary': 'Just the products in a category',
            'description': 'The lighter call when the client already holds the category.',
            'parameters': [_path_param('identifier', 'Category id or slug.', {'type': 'string'}),
                           PAGE_PARAM],
            'responses': {**_ok('A page of products.', {'type': 'object', 'properties': {
                'category_id': {'type': 'integer'},
                'products': {'type': 'array', 'items': _ref('Product')},
                **_PAGINATION,
            }}), **_errors('404')},
        }},
    }


def _cart_paths():
    cart_ok = _ok('The whole cart after the change.', _ref('Cart'),
                  extra={'warning': {'type': 'string', 'nullable': True,
                                     'description': 'Set when the quantity was clamped to available stock.'}})
    return {
        '/api/cart/': {'get': {
            'tags': ['Cart'], 'summary': 'Get the cart', 'security': AUTH,
            'description': 'Creates an empty cart on first call if the user has none.',
            'responses': {**_ok('The cart.', _ref('Cart')), **_errors('401')},
        }},
        '/api/cart/add': {'post': {
            'tags': ['Cart'], 'summary': 'Add a variant to the cart', 'security': AUTH,
            'description': 'Adding a variant already in the cart increases its quantity. '
                           'The quantity is capped at available stock and `warning` says so.',
            'requestBody': _body({
                'variant_id': {'type': 'integer', 'example': 12},
                'quantity': {'type': 'integer', 'default': 1, 'minimum': 1},
            }, required=['variant_id']),
            'responses': {**cart_ok, **_errors('401', '404')},
        }},
        '/api/cart/add-bundle': {'post': {
            'tags': ['Cart'], 'summary': 'Add every product in a routine kit', 'security': AUTH,
            'description': 'The bundle is exploded into individual variants so the '
                           'customer can still drop one before checkout. Out-of-stock '
                           'members are skipped and named in `warning`.',
            'requestBody': _body({'bundle_id': {'type': 'integer'}}, required=['bundle_id']),
            'responses': {**cart_ok, **_errors('401', '404')},
        }},
        '/api/cart/update/{item_id}': {'post': {
            'tags': ['Cart'], 'summary': 'Change a line quantity', 'security': AUTH,
            'description': 'Setting the quantity to 0 removes the line.',
            'parameters': [_path_param('item_id', 'Cart item id.')],
            'requestBody': _body({'quantity': {'type': 'integer', 'minimum': 0}},
                                 required=['quantity']),
            'responses': {**cart_ok, **_errors('401', '403', '404')},
        }},
        '/api/cart/remove/{item_id}': {'post': {
            'tags': ['Cart'], 'summary': 'Remove a line', 'security': AUTH,
            'parameters': [_path_param('item_id', 'Cart item id.')],
            'responses': {**_ok('The cart without that line.', _ref('Cart')),
                          **_errors('401', '403', '404')},
        }},
        '/api/cart/clear': {'post': {
            'tags': ['Cart'], 'summary': 'Empty the cart', 'security': AUTH,
            'responses': {**_ok('The now-empty cart.', _ref('Cart')), **_errors('401')},
        }},
    }


def _order_paths():
    return {
        '/api/orders/': {'get': {
            'tags': ['Orders'], 'summary': 'Order history', 'security': AUTH,
            'responses': {**_ok('The user\'s orders, newest first.',
                                {'type': 'array', 'items': _ref('Order')}), **_errors('401')},
        }},
        '/api/orders/{order_id}': {'get': {
            'tags': ['Orders'], 'summary': 'Order detail', 'security': AUTH,
            'parameters': [_path_param('order_id', 'Order id.')],
            'responses': {**_ok('The order.', _ref('Order')), **_errors('401', '403', '404')},
        }},
        '/api/orders/checkout': {
            'get': {'tags': ['Orders'], 'summary': 'Checkout quote', 'security': AUTH,
                    'description': 'The current cart priced up: subtotal, shipping options '
                                   'and saved addresses. Nothing is created.',
                    'responses': {**_ok('The quote.', {'type': 'object'}),
                                  **_errors('401', '422')}},
            'post': {
                'tags': ['Orders'], 'summary': 'Apply a coupon, re-quote, or place the order',
                'security': AUTH,
                'description': 'One endpoint, three actions selected by `action`:\n\n'
                               '- `update_shipping` — re-price for a different delivery method\n'
                               '- `apply_coupon` — validate a code and return the new totals\n'
                               '- `place_order` — create the order, decrement stock, empty the cart\n\n'
                               'For `place_order`, send either `address_id` (a saved address) '
                               'or the loose `recipient_name` / `address` / `city` / `phone` fields.\n\n'
                               'Paying by `KHQR` returns a `payment_transaction` — show its QR, '
                               'then poll `/api/orders/api/check-payment`.',
                'requestBody': _body({
                    'action': {'type': 'string',
                               'enum': ['update_shipping', 'apply_coupon', 'place_order']},
                    'shipping_method_id': {'type': 'integer'},
                    'coupon_code': {'type': 'string', 'example': 'WELCOME10'},
                    'coupon_id': {'type': 'integer', 'description': 'For place_order, the validated coupon.'},
                    'payment_method': {'type': 'string',
                                       'enum': ['Cash', 'Card', 'PayPal', 'Bank Transfer', 'KHQR'],
                                       'default': 'Cash'},
                    'address_id': {'type': 'integer', 'description': 'A saved address id.'},
                    'recipient_name': {'type': 'string'},
                    'address': {'type': 'string', 'description': 'Street line.'},
                    'city': {'type': 'string'},
                    'postal_code': {'type': 'string'},
                    'country': {'type': 'string', 'default': 'Cambodia'},
                    'phone': {'type': 'string'},
                }, required=['action']),
                'responses': {
                    **_ok('The new totals, or the created order.', {'type': 'object'}),
                    **_errors('401', '409', '422'),
                },
            },
        },
        '/api/orders/khqr-payment/{tx_id}': {'get': {
            'tags': ['Orders'], 'summary': 'KHQR payment details', 'security': AUTH,
            'description': 'The QR payload and deep link for a pending Bakong payment.',
            'parameters': [_path_param('tx_id', 'Payment transaction id.')],
            'responses': {**_ok('The transaction.', {'type': 'object'}),
                          **_errors('401', '403', '404')},
        }},
        '/api/orders/api/check-payment': {'post': {
            'tags': ['Orders'], 'summary': 'Poll a KHQR payment', 'security': AUTH,
            'description': 'Asks Bakong whether the transaction has settled. Poll every '
                           'few seconds while the QR is on screen.',
            'requestBody': _body({'tx_id': {'type': 'integer'}}, required=['tx_id']),
            'responses': {**_ok('Current payment state.', {'type': 'object', 'properties': {
                'status': {'type': 'string', 'enum': ['Pending', 'Paid', 'Failed', 'Expired']},
                'order_id': {'type': 'integer', 'nullable': True},
            }}), **_errors('401', '404')},
        }},
    }


def _account_paths():
    return {
        '/api/account/': {'get': {
            'tags': ['Account'], 'summary': 'Account overview', 'security': AUTH,
            'description': 'Addresses, recent orders, skin profile and subscriptions in one call.',
            'responses': {**_ok('The overview.', {'type': 'object'}), **_errors('401')},
        }},
        '/api/account/skin-profile': {
            'get': {'tags': ['Account'], 'summary': 'Get the skin profile', 'security': AUTH,
                    'responses': {**_ok('The profile.', _ref('SkinProfile')), **_errors('401')}},
            'post': {'tags': ['Account'], 'summary': 'Save the skin profile', 'security': AUTH,
                     'description': 'Drives the `/api/products/for-you` recommendations.',
                     'requestBody': _body({
                         'skin_type_id': {'type': 'integer'},
                         'age_range': {'type': 'string', 'example': '25-34'},
                         'concern_ids': {'type': 'array', 'items': {'type': 'integer'}},
                     }),
                     'responses': {**_ok('Saved.', _ref('SkinProfile')), **_errors('401')}},
        },
        '/api/account/addresses': {'get': {
            'tags': ['Account'], 'summary': 'List saved addresses', 'security': AUTH,
            'responses': {**_ok('The addresses, default first.',
                                {'type': 'array', 'items': _ref('Address')}), **_errors('401')},
        }},
        '/api/account/addresses/new': {'post': {
            'tags': ['Account'], 'summary': 'Add an address', 'security': AUTH,
            'requestBody': _body({
                'label': {'type': 'string', 'default': 'Home'},
                'recipient_name': {'type': 'string'},
                'phone': {'type': 'string'},
                'line1': {'type': 'string'},
                'line2': {'type': 'string'},
                'city': {'type': 'string'},
                'state': {'type': 'string'},
                'postal_code': {'type': 'string'},
                'country': {'type': 'string', 'default': 'Cambodia'},
                'is_default': {'type': 'boolean'},
            }, required=['recipient_name', 'phone', 'line1', 'city']),
            'responses': {**_ok('Created.', _ref('Address'), status='201'),
                          **_errors('401', '422')},
        }},
        '/api/account/addresses/{address_id}/edit': {'post': {
            'tags': ['Account'], 'summary': 'Update an address', 'security': AUTH,
            'parameters': [_path_param('address_id', 'Address id.')],
            'requestBody': _body({'recipient_name': {'type': 'string'},
                                  'phone': {'type': 'string'},
                                  'line1': {'type': 'string'},
                                  'city': {'type': 'string'}}),
            'responses': {**_ok('Updated.', _ref('Address')), **_errors('401', '403', '404', '422')},
        }},
        '/api/account/addresses/{address_id}/default': {'post': {
            'tags': ['Account'], 'summary': 'Make an address the default', 'security': AUTH,
            'parameters': [_path_param('address_id', 'Address id.')],
            'responses': {**_ok('Updated.', _ref('Address')), **_errors('401', '403', '404')},
        }},
        '/api/account/addresses/{address_id}/delete': {'post': {
            'tags': ['Account'], 'summary': 'Delete an address', 'security': AUTH,
            'parameters': [_path_param('address_id', 'Address id.')],
            'responses': {**_ok('Deleted.', extra={'message': {'type': 'string'}}),
                          **_errors('401', '403', '404')},
        }},
        '/api/account/wishlist': {'get': {
            'tags': ['Account'], 'summary': 'Get the wishlist', 'security': AUTH,
            'responses': {**_ok('The wishlist.', _ref('Wishlist')), **_errors('401')},
        }},
        '/api/account/wishlist/toggle': {'post': {
            'tags': ['Account'], 'summary': 'Add or remove a favourite', 'security': AUTH,
            'description': 'One call for both directions — `in_wishlist` says which way it went.',
            'requestBody': _body({'product_id': {'type': 'integer'}}, required=['product_id']),
            'responses': {**_ok('The new state.', {'type': 'object', 'properties': {
                'in_wishlist': {'type': 'boolean'},
                'wishlist_count': {'type': 'integer'},
            }}), **_errors('401', '404')},
        }},
        '/api/account/alerts': {'get': {
            'tags': ['Account'], 'summary': 'List back-in-stock alerts', 'security': AUTH,
            'responses': {**_ok('The alerts.', {'type': 'array', 'items': {'type': 'object'}}),
                          **_errors('401')},
        }},
        '/api/account/alerts/subscribe': {'post': {
            'tags': ['Account'], 'summary': 'Notify me when a variant is back', 'security': AUTH,
            'requestBody': _body({'variant_id': {'type': 'integer'},
                                  'email': {'type': 'string', 'format': 'email',
                                            'description': 'Defaults to the account email.'}},
                                 required=['variant_id']),
            'responses': {**_ok('Subscribed.', {'type': 'object'}, status='201'),
                          **_errors('401', '404')},
        }},
        '/api/account/subscriptions': {'get': {
            'tags': ['Account'], 'summary': 'List refill subscriptions', 'security': AUTH,
            'responses': {**_ok('The subscriptions.', {'type': 'array', 'items': {'type': 'object'}}),
                          **_errors('401')},
        }},
        '/api/account/subscriptions/new': {'post': {
            'tags': ['Account'], 'summary': 'Start a refill subscription', 'security': AUTH,
            'description': 'Repeat delivery of one variant, 10% off each refill.',
            'requestBody': _body({'variant_id': {'type': 'integer'},
                                  'quantity': {'type': 'integer', 'default': 1},
                                  'interval_days': {'type': 'integer', 'default': 30}},
                                 required=['variant_id']),
            'responses': {**_ok('Created.', {'type': 'object'}, status='201'),
                          **_errors('401', '404')},
        }},
        '/api/account/subscriptions/{sub_id}/{action}': {'post': {
            'tags': ['Account'], 'summary': 'Pause, resume or cancel a subscription',
            'security': AUTH,
            'parameters': [_path_param('sub_id', 'Subscription id.'),
                           _path_param('action', 'One of pause, resume, cancel.',
                                       {'type': 'string', 'enum': ['pause', 'resume', 'cancel']})],
            'responses': {**_ok('Updated.', {'type': 'object'}), **_errors('401', '403', '404')},
        }},
        '/api/account/returns': {'get': {
            'tags': ['Account'], 'summary': 'List return requests', 'security': AUTH,
            'responses': {**_ok('The requests.', {'type': 'array', 'items': {'type': 'object'}}),
                          **_errors('401')},
        }},
        '/api/account/returns/new/{order_id}': {'post': {
            'tags': ['Account'], 'summary': 'Request a return', 'security': AUTH,
            'parameters': [_path_param('order_id', 'The order being returned.')],
            'requestBody': _body({
                'reason': {'type': 'string', 'example': 'Reaction to fragrance'},
                'order_item_ids': {'type': 'array', 'items': {'type': 'integer'}},
            }, required=['reason']),
            'responses': {**_ok('Requested.', {'type': 'object'}, status='201'),
                          **_errors('401', '403', '404', '422')},
        }},
    }


def _review_paths():
    return {
        '/api/reviews/submit': {'post': {
            'tags': ['Reviews'], 'summary': 'Write or update a review', 'security': AUTH,
            'description': 'One review per user per product — posting again edits the '
                           'existing one. `is_verified_purchase` is set by the server '
                           'from the order history and cannot be sent by the client.',
            'requestBody': _body({
                'product_id': {'type': 'integer'},
                'rating': {'type': 'integer', 'minimum': 1, 'maximum': 5},
                'title': {'type': 'string'},
                'comment': {'type': 'string'},
                'skin_type_id': {'type': 'integer',
                                 'description': 'Defaults to the reviewer\'s saved skin type.'},
                'age_range': {'type': 'string'},
            }, required=['product_id', 'rating']),
            'responses': {**_ok('The review.', _ref('Review')), **_errors('401', '422')},
        }},
        '/api/reviews/{review_id}/delete': {'post': {
            'tags': ['Reviews'], 'summary': 'Delete your review', 'security': AUTH,
            'parameters': [_path_param('review_id', 'Review id.')],
            'responses': {**_ok('Deleted.', extra={'message': {'type': 'string'}}),
                          **_errors('401', '403', '404')},
        }},
    }


def _admin_paths():
    """Admin endpoints require a token belonging to a user with the Admin role;
    everything else there returns 403."""
    admin_errors = _errors('401', '403')
    return {
        '/api/admin/': {'get': {
            'tags': ['Admin'], 'summary': 'Dashboard figures', 'security': AUTH,
            'description': 'Revenue, order counts, low stock and the monthly series.',
            'responses': {**_ok('The dashboard.', {'type': 'object'}), **admin_errors},
        }},

        # ── Customers ──
        '/api/admin/users': {'get': {
            'tags': ['Admin · Customers'], 'summary': 'List customers', 'security': AUTH,
            'parameters': [
                _query('q', 'Search name, email or phone.'),
                _query('role', 'Filter by role.', {'type': 'string', 'enum': ['Admin', 'Customer']}),
                _query('status', 'Filter by account status.',
                       {'type': 'string', 'enum': ['active', 'inactive']}),
            ],
            'responses': {**_ok('The customers.', {'type': 'array', 'items': _ref('User')},
                                extra={'count': {'type': 'integer'},
                                       'stats': {'type': 'object'}}),
                          **admin_errors},
        }},
        '/api/admin/users/{user_id}': {'get': {
            'tags': ['Admin · Customers'], 'summary': 'Customer detail', 'security': AUTH,
            'description': 'Profile plus lifetime spend, every order, reviews, addresses '
                           'and wishlist.',
            'parameters': [_path_param('user_id', 'User id.')],
            'responses': {**_ok('The customer.', {'type': 'object', 'properties': {
                'user': _ref('User'),
                'orders': {'type': 'array', 'items': _ref('Order')},
                'reviews': {'type': 'array', 'items': _ref('Review')},
                'addresses': {'type': 'array', 'items': _ref('Address')},
                'wishlist': _ref('Wishlist'),
                'status_counts': {'type': 'object', 'additionalProperties': {'type': 'integer'}},
            }}), **admin_errors, **_errors('404')},
        }},
        '/api/admin/users/new': {'post': {
            'tags': ['Admin · Customers'], 'summary': 'Create a customer', 'security': AUTH,
            'requestBody': _body({
                'name': {'type': 'string'}, 'email': {'type': 'string', 'format': 'email'},
                'phone': {'type': 'string'}, 'password': {'type': 'string', 'minLength': 6},
                'is_admin': {'type': 'boolean', 'default': False},
            }, required=['name', 'email', 'password']),
            'responses': {**_ok('Created.', _ref('User'), status='201'),
                          **admin_errors, **_errors('422')},
        }},
        '/api/admin/users/{user_id}/edit': {'post': {
            'tags': ['Admin · Customers'], 'summary': 'Edit a customer', 'security': AUTH,
            'description': 'Send `password` only to reset it; omit it to leave it alone.',
            'parameters': [_path_param('user_id', 'User id.')],
            'requestBody': _body({'name': {'type': 'string'},
                                  'email': {'type': 'string', 'format': 'email'},
                                  'phone': {'type': 'string'},
                                  'password': {'type': 'string', 'minLength': 6}}),
            'responses': {**_ok('Updated.', _ref('User')),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/users/{user_id}/toggle-admin': {'post': {
            'tags': ['Admin · Customers'], 'summary': 'Grant or revoke admin', 'security': AUTH,
            'description': 'Refused (422) on your own account, or when it would remove '
                           'the last active admin.',
            'parameters': [_path_param('user_id', 'User id.')],
            'responses': {**_ok('Updated.', _ref('User'), extra={'message': {'type': 'string'}}),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/users/{user_id}/toggle-active': {'post': {
            'tags': ['Admin · Customers'], 'summary': 'Suspend or restore an account',
            'security': AUTH,
            'description': 'A suspended user cannot sign in, and any bearer token they '
                           'still hold stops working on their next request. Refused on '
                           'your own account or the last active admin.',
            'parameters': [_path_param('user_id', 'User id.')],
            'responses': {**_ok('Updated.', _ref('User'), extra={'message': {'type': 'string'}}),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/users/{user_id}/delete': {'post': {
            'tags': ['Admin · Customers'], 'summary': 'Delete an account', 'security': AUTH,
            'description': 'Refused (422) once the customer has placed an order — order '
                           'history is a financial record. Suspend the account instead.',
            'parameters': [_path_param('user_id', 'User id.')],
            'responses': {**_ok('Deleted.', extra={'message': {'type': 'string'}}),
                          **admin_errors, **_errors('404', '422')},
        }},

        # ── Categories ──
        '/api/admin/categories': {'get': {
            'tags': ['Admin · Catalog'], 'summary': 'List categories', 'security': AUTH,
            'responses': {**_ok('The categories.', {'type': 'array', 'items': _ref('Category')}),
                          **admin_errors},
        }},
        '/api/admin/categories/new': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Create a category', 'security': AUTH,
            'requestBody': _body({'name': {'type': 'string'},
                                  'parent_id': {'type': 'integer', 'nullable': True},
                                  'description': {'type': 'string'},
                                  'image': {'type': 'string'},
                                  'sort_order': {'type': 'integer'}}, required=['name']),
            'responses': {**_ok('Created.', _ref('Category'), status='201'),
                          **admin_errors, **_errors('422')},
        }},
        '/api/admin/categories/{cat_id}/edit': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Update a category', 'security': AUTH,
            'parameters': [_path_param('cat_id', 'Category id.')],
            'requestBody': _body({'name': {'type': 'string'},
                                  'parent_id': {'type': 'integer', 'nullable': True},
                                  'description': {'type': 'string'},
                                  'sort_order': {'type': 'integer'}}),
            'responses': {**_ok('Updated.', _ref('Category')),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/categories/{cat_id}/delete': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Delete a category', 'security': AUTH,
            'description': 'Refused while products or child categories still point at it.',
            'parameters': [_path_param('cat_id', 'Category id.')],
            'responses': {**_ok('Deleted.', extra={'message': {'type': 'string'}}),
                          **admin_errors, **_errors('404', '422')},
        }},

        # ── Products ──
        '/api/admin/products': {'get': {
            'tags': ['Admin · Catalog'], 'summary': 'List products (admin view)', 'security': AUTH,
            'description': 'Includes inactive products, which the storefront hides.',
            'responses': {**_ok('The products.', {'type': 'array', 'items': _ref('Product')}),
                          **admin_errors},
        }},
        '/api/admin/products/new': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Create a product', 'security': AUTH,
            'requestBody': _body({
                'name': {'type': 'string'}, 'description': {'type': 'string'},
                'base_price': {'type': 'number'}, 'category_id': {'type': 'integer'},
                'brand_id': {'type': 'integer'}, 'product_type': {'type': 'string'},
                'routine_step': {'type': 'integer'}, 'spf': {'type': 'integer'},
                'ingredients_full': {'type': 'string', 'description': 'Full INCI list.'},
                'is_active': {'type': 'boolean', 'default': True},
                'is_vegan': {'type': 'boolean'}, 'is_cruelty_free': {'type': 'boolean'},
                'is_fragrance_free': {'type': 'boolean'},
                'concern_ids': {'type': 'array', 'items': {'type': 'integer'}},
                'skin_type_ids': {'type': 'array', 'items': {'type': 'integer'}},
            }, required=['name', 'base_price']),
            'responses': {**_ok('Created.', _ref('Product'), status='201'),
                          **admin_errors, **_errors('422')},
        }},
        '/api/admin/products/{product_id}/edit': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Update a product', 'security': AUTH,
            'parameters': [_path_param('product_id', 'Product id.')],
            'requestBody': _body({'name': {'type': 'string'}, 'base_price': {'type': 'number'},
                                  'is_active': {'type': 'boolean'}}),
            'responses': {**_ok('Updated.', _ref('Product')),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/products/{product_id}/delete': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Delete a product', 'security': AUTH,
            'parameters': [_path_param('product_id', 'Product id.')],
            'responses': {**_ok('Deleted.', extra={'message': {'type': 'string'}}),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/products/{product_id}/variants/new': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Add a variant', 'security': AUTH,
            'parameters': [_path_param('product_id', 'Product id.')],
            'requestBody': _body({'sku': {'type': 'string'}, 'size': {'type': 'string'},
                                  'price': {'type': 'number'},
                                  'compare_at_price': {'type': 'number'},
                                  'stock': {'type': 'integer'}},
                                 required=['sku', 'price']),
            'responses': {**_ok('Created.', _ref('Variant'), status='201'),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/products/{product_id}/images': {'post': {
            'tags': ['Admin · Catalog'], 'summary': 'Attach a product image', 'security': AUTH,
            'parameters': [_path_param('product_id', 'Product id.')],
            'requestBody': _body({'image_url': {'type': 'string'},
                                  'alt_text': {'type': 'string'},
                                  'is_primary': {'type': 'boolean'}},
                                 required=['image_url']),
            'responses': {**_ok('Attached.', _ref('ProductImage'), status='201'),
                          **admin_errors, **_errors('404', '422')},
        }},

        # ── Orders ──
        '/api/admin/orders': {'get': {
            'tags': ['Admin · Orders'], 'summary': 'List every order', 'security': AUTH,
            'parameters': [_query('status', 'Filter by status.')],
            'responses': {**_ok('The orders.', {'type': 'array', 'items': _ref('Order')}),
                          **admin_errors},
        }},
        '/api/admin/orders/{order_id}': {'get': {
            'tags': ['Admin · Orders'], 'summary': 'Order detail (admin view)', 'security': AUTH,
            'parameters': [_path_param('order_id', 'Order id.')],
            'responses': {**_ok('The order.', _ref('Order')), **admin_errors, **_errors('404')},
        }},
        '/api/admin/orders/{order_id}/update-status': {'post': {
            'tags': ['Admin · Orders'], 'summary': 'Move an order along the pipeline',
            'security': AUTH,
            'description': 'Pending → Processing → Shipped → Delivered, or Cancelled. '
                           'Cancelling returns the reserved stock.',
            'parameters': [_path_param('order_id', 'Order id.')],
            'requestBody': _body({'status': {'type': 'string',
                                             'enum': ['Pending', 'Processing', 'Shipped',
                                                      'Delivered', 'Cancelled']},
                                  'note': {'type': 'string'}}, required=['status']),
            'responses': {**_ok('Updated.', _ref('Order')),
                          **admin_errors, **_errors('404', '422')},
        }},
        '/api/admin/orders/{order_id}/tracking': {'post': {
            'tags': ['Admin · Orders'], 'summary': 'Set a tracking number', 'security': AUTH,
            'parameters': [_path_param('order_id', 'Order id.')],
            'requestBody': _body({'tracking_number': {'type': 'string'},
                                  'carrier': {'type': 'string'}}, required=['tracking_number']),
            'responses': {**_ok('Updated.', _ref('Shipping')), **admin_errors, **_errors('404')},
        }},

        # ── Inventory & marketing ──
        '/api/admin/inventory': {'get': {
            'tags': ['Admin · Operations'], 'summary': 'Stock levels and expiry warnings',
            'security': AUTH,
            'responses': {**_ok('Inventory state.', {'type': 'object'}), **admin_errors},
        }},
        '/api/admin/coupons': {'get': {
            'tags': ['Admin · Operations'], 'summary': 'List coupons', 'security': AUTH,
            'responses': {**_ok('The coupons.', {'type': 'array', 'items': {'type': 'object'}}),
                          **admin_errors},
        }},
        '/api/admin/coupons/new': {'post': {
            'tags': ['Admin · Operations'], 'summary': 'Create a coupon', 'security': AUTH,
            'requestBody': _body({'code': {'type': 'string', 'example': 'WELCOME10'},
                                  'discount_type': {'type': 'string',
                                                    'enum': ['percentage', 'fixed']},
                                  'discount_value': {'type': 'number'},
                                  'min_amount': {'type': 'number'},
                                  'expiry_date': {'type': 'string', 'format': 'date'}},
                                 required=['code', 'discount_type', 'discount_value']),
            'responses': {**_ok('Created.', {'type': 'object'}, status='201'),
                          **admin_errors, **_errors('422')},
        }},
        '/api/admin/promotions': {'get': {
            'tags': ['Admin · Operations'], 'summary': 'List promotions', 'security': AUTH,
            'responses': {**_ok('The promotions.', {'type': 'array', 'items': {'type': 'object'}}),
                          **admin_errors},
        }},
        '/api/admin/returns': {'get': {
            'tags': ['Admin · Operations'], 'summary': 'List return requests', 'security': AUTH,
            'responses': {**_ok('The requests.', {'type': 'array', 'items': {'type': 'object'}}),
                          **admin_errors},
        }},
    }


DESCRIPTION = """
REST API for the Aurea Skin storefront — the backend the Flutter app talks to.

### Response shape
Every endpoint answers with the same envelope, so a client can branch on one field:

```json
{ "success": true,  "data": { ... } }
{ "success": false, "error": "Not found" }
```

A `422` also carries an `errors` array with one message per failed field.

### Authentication
`POST /api/auth/login` returns a **token**. Send it on every later request:

```
Authorization: Bearer <token>
```

Tokens are signed, stateless and valid for 30 days. They stop working
immediately if the account is deactivated. Browsers may use the session cookie
instead — both are accepted.

Press **Authorize** above to paste a token and try the protected endpoints
straight from this page.

### Requests
Endpoints accept a JSON body (`Content-Type: application/json`) or ordinary
form-encoded fields — the same route serves the web pages and the mobile app.

### Status codes
| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 401 | No or invalid token |
| 403 | Signed in but not allowed (admin-only, or suspended) |
| 404 | No such resource |
| 405 | Wrong method for that path |
| 409 | Conflict — typically stock ran out mid-checkout |
| 422 | Validation failed — see `errors` |
| 500 | Unexpected server error |

Errors are always JSON for API clients. Never HTML.
"""


def build_spec():
    """Assemble the whole OpenAPI document."""
    paths = {}
    for group in (_auth_paths, _catalog_paths, _category_paths, _cart_paths,
                  _order_paths, _account_paths, _review_paths, _admin_paths):
        paths.update(group())

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'Aurea Skin API',
            'version': API_VERSION,
            'description': DESCRIPTION,
        },
        'servers': [
            {'url': '/', 'description': 'This server'},
        ],
        'tags': [
            {'name': 'Auth', 'description': 'Registration, sign-in and the bearer token.'},
            {'name': 'Catalog', 'description': 'Products, search, filters and the home feed.'},
            {'name': 'Categories', 'description': 'The category tree and category browsing.'},
            {'name': 'Cart', 'description': 'The signed-in user\'s shopping cart.'},
            {'name': 'Orders', 'description': 'Checkout, order history and KHQR payment.'},
            {'name': 'Account', 'description': 'Addresses, wishlist, skin profile, returns.'},
            {'name': 'Reviews', 'description': 'Product ratings and written reviews.'},
            {'name': 'Admin', 'description': 'Back-office. Requires the Admin role.'},
            {'name': 'Admin · Customers', 'description': 'Customer management.'},
            {'name': 'Admin · Catalog', 'description': 'Category, product, variant and image CRUD.'},
            {'name': 'Admin · Orders', 'description': 'Order pipeline and fulfilment.'},
            {'name': 'Admin · Operations', 'description': 'Inventory, coupons, promotions, returns.'},
        ],
        'components': {
            'securitySchemes': {
                'bearerAuth': {
                    'type': 'http', 'scheme': 'bearer',
                    'description': 'The `token` from POST /api/auth/login.',
                },
            },
            'schemas': _schemas(),
        },
        'paths': paths,
    }


@docs_bp.route('/api/openapi.json')
def openapi_spec():
    """The raw OpenAPI 3.0 document — import this into Postman or Insomnia."""
    return jsonify(build_spec())


SWAGGER_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>API Docs — {{ store }}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui.css">
  <style>
    body { margin: 0; background: #fafafa; }
    .topbar { display: none; }
    .swagger-ui .info { margin: 2rem 0; }
    header.aurea {
      background: #1a2412; color: #fff; padding: 1rem 1.5rem;
      font: 600 1rem/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
      display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    }
    header.aurea a { color: #9fd8b4; text-decoration: none; font-weight: 500; font-size: .875rem; }
    header.aurea a:hover { text-decoration: underline; }
    header.aurea .spacer { margin-left: auto; }
  </style>
</head>
<body>
  <header class="aurea">
    <span>{{ store }} — API</span>
    <span class="spacer"></span>
    <a href="{{ spec_url }}">openapi.json</a>
    <a href="/">← Storefront</a>
  </header>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.17.14/swagger-ui-standalone-preset.js"></script>
  <script>
    window.ui = SwaggerUIBundle({
      url: "{{ spec_url }}",
      dom_id: "#swagger-ui",
      deepLinking: true,
      docExpansion: "none",
      defaultModelsExpandDepth: 1,
      filter: true,
      tryItOutEnabled: true,
      persistAuthorization: true,
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "StandaloneLayout"
    });
  </script>
</body>
</html>
"""


@docs_bp.route('/api/docs')
def swagger_ui():
    """Interactive API documentation."""
    from flask import current_app
    return render_template_string(
        SWAGGER_PAGE,
        store=current_app.config.get('STORE_NAME', 'Aurea Skin'),
        spec_url=url_for('docs.openapi_spec'),
    )
