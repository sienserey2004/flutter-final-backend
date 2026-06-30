# Bakong Payment Integration Guide

## Overview

This document explains the end-to-end process of integrating and processing payments using Bakong's KHQR (Khmer QR) payment system in our e-commerce application. Bakong is Cambodia's national payment gateway that enables QR code-based payments through various banking apps.

## Prerequisites

### 1. Bakong Account Setup

- Register as a merchant with Bakong (NBC - National Bank of Cambodia)
- Obtain API credentials (token)
- Set up merchant information (name, bank account, city, terminal label)

### 2. Environment Configuration

Set the following environment variable:

```bash
BAKONG_TOKEN=your_bakong_api_token_here
```

### 3. Dependencies

The application uses the `bakong-khqr` Python library:

```txt
bakong-khqr[image]==1.0.0
```

## Database Models

### BakongMerchant

Stores merchant information required for QR generation:

- `merchant_name`: Display name for the merchant
- `bank_account`: Bank account number for receiving payments
- `merchant_city`: City where the merchant is located
- `terminal_label`: Unique identifier for the payment terminal
- `is_active`: Flag to enable/disable the merchant

### PaymentTransaction

Tracks individual payment transactions:

- `qr_string`: The generated QR code data
- `md5_hash`: MD5 hash of the QR string (used for verification)
- `amount`: Payment amount
- `currency`: Payment currency (default: USD)
- `user_id`: User who initiated the payment
- `order_id`: Associated order
- `status`: Payment status (Pending, Paid, Failed, Expired)
- `paid_at`: Timestamp when payment was confirmed

## End-to-End Payment Flow

### 1. Merchant Configuration

Before processing payments, an active Bakong merchant must be configured:

```python
# Create merchant via admin interface or CLI
merchant = BakongMerchant(
    merchant_name="My E-commerce Store",
    bank_account="123456789",
    merchant_city="Phnom Penh",
    terminal_label="ECOM001",
    is_active=True
)
```

### 2. Order Creation and Payment Initiation

When a user selects KHQR as payment method during checkout:

1. **Order Creation**: Standard order is created with status 'Pending'
2. **Payment Record**: Payment record is created with status 'Pending'
3. **QR Generation**: KHQR library generates a QR code string

```python
# Initialize KHQR client
khqr = KHQR(current_app.config.get('BAKONG_TOKEN'))

# Generate QR string
qr_string = khqr.create_qr(
    merchant_name=merchant.merchant_name,
    merchant_city=merchant.merchant_city,
    amount=order_total,
    currency='USD',
    store_label='Ecommerce',
    terminal_label=merchant.terminal_label,
    phone_number='061275099',
    bill_number=str(order.order_id),
    bank_account=merchant.bank_account
)

# Generate MD5 hash for verification
md5_hash = khqr.generate_md5(qr_string)

# Store transaction
transaction = PaymentTransaction(
    qr_string=qr_string,
    md5_hash=md5_hash,
    amount=order_total,
    currency='USD',
    user_id=current_user.user_id,
    order_id=order.order_id
)
```

### 3. QR Code Display

The QR string is converted to a visual QR code and displayed to the user along with a deeplink for mobile apps:

```python
# Generate QR image
qr = qrcode.QRCode(version=1, box_size=10, border=5)
qr.add_data(qr_string)
qr.make(fit=True)
img = qr.make_image(fill='black', back_color='white')

# Convert to base64 for web display
buffer = io.BytesIO()
img.save(buffer, format='PNG')
qr_b64 = base64.b64encode(buffer.getvalue()).decode()

# Generate mobile deeplink
deeplink = khqr.generate_deeplink(qr_string)
```

The payment page displays:

- QR code image
- Payment amount
- Countdown timer (60 seconds)
- Deeplink button to open Bakong app directly
- Manual check payment button

### 4. User Payment Process

1. User opens their banking app (that supports Bakong/KHQR)
2. Scans the displayed QR code
3. Confirms payment amount and details
4. Authorizes the payment through their bank
5. Bank processes the transaction and notifies Bakong

### 5. Payment Verification

The application uses a dual verification approach:

#### Automatic Polling

Frontend JavaScript automatically polls the payment status every 5 seconds for 60 seconds:

```javascript
// Automatic check every 5 seconds
checkInterval = setInterval(checkPayment, 5000);

// Stop after 60 seconds
timeoutTimer = setTimeout(stopChecking, 60000);
```

#### Manual Verification

Users can manually trigger payment checks or use the deeplink to open their banking app.

#### API Verification

The backend calls Bakong's API to check payment status:

```python
# API Endpoint: POST https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5
headers = {
    'Authorization': f'Bearer {bakong_token}',
    'Content-Type': 'application/json'
}
payload = {'md5': md5_hash}

response = requests.post(url, json=payload, headers=headers)
result = response.json()

if result.get('responseCode') == 0:
    # Payment successful
    transaction.status = 'Paid'
    transaction.paid_at = datetime.utcnow()
    order.payment.status = 'Paid'
    order.payment.paid_at = datetime.utcnow()
```

### 6. Order Fulfillment

Once payment is confirmed:

- Order status changes to 'Processing'
- Payment status changes to 'Paid'
- Inventory is updated
- User receives confirmation
- Order fulfillment process begins
     
## API Endpoints

### Frontend Routes

- `GET /orders/checkout`: Display checkout form with payment method selection
- `POST /orders/checkout`: Process order and initiate KHQR payment if selected
- `GET /orders/khqr-payment/<tx_id>`: Display QR code and handle payment verification

### Backend API Routes

- `POST /orders/api/check-payment`: AJAX endpoint to check payment status
  - Request: `{"md5": "md5_hash_of_qr"}`
  - Response: `{"status": "paid|pending", "message": "..."}` or `{"error": "..."}`

## Error Handling

### Common Issues

1. **No Active Merchant**: Ensure at least one BakongMerchant is active
2. **Invalid Token**: Verify BAKONG_TOKEN environment variable
3. **Network Issues**: Handle API timeouts and connection errors
4. **Expired QR**: QR codes have expiration time, implement refresh mechanism

### Status Codes

- `responseCode: 0`: Payment successful
- Other codes: Payment pending or failed

## Security Considerations

1. **Token Storage**: Store BAKONG_TOKEN securely as environment variable
2. **MD5 Verification**: Use MD5 hash to prevent tampering
3. **User Authorization**: Verify user owns the transaction before status checks
4. **HTTPS**: Ensure all API calls use HTTPS

## Testing

Use the management command to create sample merchants for testing:

```bash
flask create-sample-merchant
```

## Production Deployment

1. Obtain production Bakong credentials
2. Configure production environment variables
3. Test with small amounts first
4. Monitor API response times and error rates
5. Implement proper logging for payment transactions

## Troubleshooting

### Payment Not Detected

- Check Bakong API connectivity
- Verify MD5 hash matches QR string
- Ensure transaction hasn't expired
- Check user has sufficient balance

### QR Code Not Scanning

- Verify QR string format
- Check merchant information accuracy
- Ensure proper QR code generation

### API Errors

- Validate BAKONG_TOKEN
- Check API endpoint URLs
- Monitor rate limits
- Handle network timeouts gracefully</content>
  <parameter name="filePath">d:\Work\Personal Works\pyEcom\ecommerce\BAKONG_PAYMENT_GUIDE.md
