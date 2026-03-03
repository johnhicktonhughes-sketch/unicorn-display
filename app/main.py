from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


app = FastAPI(title="DHL Parcel Integration API")


# Simple in-memory token store keyed by orderId.
# Replace with Redis/DB in production.
TOKEN_STORE: dict[str, dict[str, Any]] = {}


class DHLAuthPayload(BaseModel):
    userId: str = Field(..., examples=["string"])
    key: str = Field(..., examples=["string"])
    accountNumbers: list[str] = ["05868468"]
    orderId: int = Field(..., description="DHL orderId to query labels for.")


class TrackOrderRequest(BaseModel):
    auth: DHLAuthPayload
    postalCode: str | None = Field(
        default=None,
        description="Optional receiver postal code for richer track-trace response.",
    )


def _build_label_pending_response(order_id: str, upstream_message: str | None = None) -> JSONResponse:
    detail = {
        "status": "label_pending",
        "message": "Label has not been produced yet. Retry this order later.",
        "orderId": order_id,
        "labelsFound": 0,
    }
    if upstream_message:
        detail["upstream"] = upstream_message
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=detail)


@app.post("/dhl/track-order")
async def dhl_track_order(request: TrackOrderRequest) -> dict[str, Any] | JSONResponse:
    auth_url = "https://api-gw.dhlparcel.nl/authenticate/api-key"
    labels_url = "https://api-gw.dhlparcel.nl/labels"
    track_url = "https://api-gw.dhlparcel.nl/track-trace"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1) Authenticate and store accessToken + refreshToken
        auth_resp = await client.post(auth_url, json=request.auth.model_dump())
        if auth_resp.status_code != 200:
            raise HTTPException(
                status_code=auth_resp.status_code,
                detail={"step": "authenticate", "upstream": auth_resp.text},
            )

        auth_data = auth_resp.json()
        access_token = auth_data.get("accessToken")
        refresh_token = auth_data.get("refreshToken")
        if not access_token or not refresh_token:
            raise HTTPException(
                status_code=502,
                detail="Authenticate response missing accessToken/refreshToken.",
            )

        order_id = str(request.auth.orderId)
        TOKEN_STORE[order_id] = {
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "accessTokenExpiration": auth_data.get("accessTokenExpiration"),
            "refreshTokenExpiration": auth_data.get("refreshTokenExpiration"),
        }

        # 2) Get label(s) by orderReferenceFilter and extract trackerCode
        labels_resp = await client.get(
            labels_url,
            params={"orderReferenceFilter": order_id},
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        if labels_resp.status_code == 404:
            return _build_label_pending_response(order_id, labels_resp.text)
        if labels_resp.status_code != 200:
            raise HTTPException(
                status_code=labels_resp.status_code,
                detail={"step": "labels", "upstream": labels_resp.text},
            )

        labels_data = labels_resp.json()
        if not isinstance(labels_data, list) or not labels_data:
            return _build_label_pending_response(order_id)

        tracker_code = labels_data[0].get("trackerCode")
        if not tracker_code:
            raise HTTPException(
                status_code=502,
                detail="Label response missing trackerCode.",
            )

        # 3) Call Track & Trace
        # DHL expects key=<trackerCode> or key=<trackerCode+postalCode>
        key_value = tracker_code
        if request.postalCode:
            key_value = f"{tracker_code}+{request.postalCode}"

        track_resp = await client.get(
            track_url,
            params={"key": key_value},
            headers={"Accept": "application/json"},
        )
        if track_resp.status_code != 200:
            raise HTTPException(
                status_code=track_resp.status_code,
                detail={"step": "track-trace", "upstream": track_resp.text},
            )

        track_data = track_resp.json()

    return {
        "orderId": order_id,
        "labelsFound": 1,
        "trackerCode": tracker_code,
        "tokensStored": True,
        "tokenStoreKey": order_id,
        "trackTrace": track_data,
    }


@app.get("/dhl/tokens/{order_id}")
async def get_stored_tokens(order_id: str) -> dict[str, Any]:
    token_record = TOKEN_STORE.get(order_id)
    if not token_record:
        raise HTTPException(status_code=404, detail=f"No token record for order_id={order_id}")
    return token_record
