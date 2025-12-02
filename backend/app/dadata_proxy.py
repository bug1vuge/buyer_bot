import requests
from .config import settings

DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"

def suggest_address(query):
    headers = {"Authorization": f"Token {settings.DADATA_API_KEY}", "Content-Type": "application/json"}
    data = {"query": query, "count": 5}
    resp = requests.post(DADATA_URL, headers=headers, json=data, timeout=5)
    resp.raise_for_status()
    return resp.json()
