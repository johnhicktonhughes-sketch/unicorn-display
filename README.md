# DHL Parcel FastAPI Endpoint

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Endpoint

`POST /dhl/track-order`

This endpoint does all 3 steps:
1. POST `https://api-gw.dhlparcel.nl/authenticate/api-key`
2. GET `https://api-gw.dhlparcel.nl/labels?orderReferenceFilter={{orderId}}`
3. GET `https://api-gw.dhlparcel.nl/track-trace?key={{trackerCode}}` (or `trackerCode+postalCode`)

### Example request

```bash
curl -X POST http://127.0.0.1:8000/dhl/track-order \
  -H "Content-Type: application/json" \
  -d '{
    "auth": {
      "userId": "2d7c835f-12bf-461a-bb9d-fbff44019469",
      "key": "fc2a0122-4286-431b-90d2-d93df6248341",
      "accountNumbers": ["05868468"],
      "orderId": 510048027
    },
    "postalCode": "1234AB"
  }'
```

`postalCode` is optional. If provided, the service sends `key=trackerCode+postalCode` to DHL track-trace.

## Stored tokens

Tokens are kept in memory (for demo/testing) and can be read via:

`GET /dhl/tokens/{order_id}`
