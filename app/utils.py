"""Small shared helpers."""
import re
import unicodedata


def slugify(value, fallback='item'):
    """Turn a product/brand/category name into a URL-safe slug.

    'The Ordinary — Niacinamide 10% + Zinc 1%' -> 'the-ordinary-niacinamide-10-zinc-1'
    """
    if not value:
        return fallback
    value = unicodedata.normalize('NFKD', str(value))
    value = value.encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '-', value)
    return value or fallback


def unique_slug(model, value, slug_field='slug', pk_field=None, pk_value=None):
    """slugify() plus a numeric suffix so the result is unique for `model`."""
    base = slugify(value)
    slug = base
    n = 2
    while True:
        query = model.query.filter(getattr(model, slug_field) == slug)
        if pk_field and pk_value:
            query = query.filter(getattr(model, pk_field) != pk_value)
        if not query.first():
            return slug
        slug = f'{base}-{n}'
        n += 1
