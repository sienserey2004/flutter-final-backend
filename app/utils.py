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


# ── Local image storage ────────────────────────────────────────────────────────
# Images live inside the project under app/static/images/uploads/<folder>/ and
# the database stores only the /static-relative path (e.g.
# 'images/uploads/products/3f2a….jpg'). External http(s) URLs are not accepted.
ALLOWED_IMAGE_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif'}
UPLOAD_SUBDIR = 'images/uploads'


class ImageUploadError(ValueError):
    pass


def is_external_url(value):
    return bool(value) and value.strip().lower().startswith(('http://', 'https://', '//'))


def _store_image_bytes(data, folder):
    """Validate raw bytes as a real image and write them under static/. Returns
    the /static-relative path."""
    import io
    import os
    import uuid
    from flask import current_app
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise ImageUploadError('The file is not a valid image.')
    ext = ALLOWED_IMAGE_FORMATS.get(fmt)
    if not ext:
        raise ImageUploadError('Only JPG, PNG, WEBP or GIF images are allowed.')

    rel_dir = f'{UPLOAD_SUBDIR}/{slugify(folder, "misc")}'
    abs_dir = os.path.join(current_app.static_folder, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{ext}'
    with open(os.path.join(abs_dir, filename), 'wb') as fh:
        fh.write(data)
    return f'{rel_dir}/{filename}'


def save_image_upload(file_storage, folder):
    """Save an uploaded werkzeug FileStorage into the project. Returns the
    /static-relative path, or None when no file was chosen."""
    if not file_storage or not file_storage.filename:
        return None
    return _store_image_bytes(file_storage.read(), folder)


def download_image_to_static(url, folder, timeout=20):
    """Fetch an external image once and keep a local copy (used to migrate
    old URL-based records)."""
    import requests
    resp = requests.get(url, timeout=timeout,
                        headers={'User-Agent': 'Mozilla/5.0 (image localizer)'})
    resp.raise_for_status()
    return _store_image_bytes(resp.content, folder)


def delete_uploaded_image(rel_path):
    """Remove a file previously written by save_image_upload(). Paths outside
    the uploads folder (seed images) are left alone."""
    import os
    from flask import current_app
    if not rel_path or not rel_path.startswith(UPLOAD_SUBDIR + '/'):
        return
    abs_path = os.path.normpath(os.path.join(current_app.static_folder, rel_path))
    if abs_path.startswith(os.path.normpath(current_app.static_folder)) and os.path.isfile(abs_path):
        os.remove(abs_path)
