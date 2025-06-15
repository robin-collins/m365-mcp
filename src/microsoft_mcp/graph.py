import httpx
from typing import Any
from .auth import get_token

BASE_URL = "https://graph.microsoft.com/v1.0"


def request(
    method: str,
    path: str,
    account_id: str | None = None,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
    data: bytes | None = None,
) -> dict[str, Any] | None:
    headers = {
        "Authorization": f"Bearer {get_token(account_id)}",
        "Content-Type": "application/json" if json else "application/octet-stream",
    }
    
    with httpx.Client() as client:
        response = client.request(
            method=method,
            url=f"{BASE_URL}{path}",
            headers=headers,
            params=params,
            json=json,
            content=data,
        )
        response.raise_for_status()
        
        if response.content:
            return response.json()
        return None


def download_raw(path: str, account_id: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {get_token(account_id)}"}
    
    with httpx.Client(follow_redirects=True) as client:
        response = client.get(f"{BASE_URL}{path}", headers=headers)
        response.raise_for_status()
        return response.content