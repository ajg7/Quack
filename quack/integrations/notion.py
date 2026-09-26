from quack import config
import requests

def query_data_source(data_source_id: str, filters: dict | None = None) -> list[dict]:
  url = f"{config.NOTION_API}/data_sources/{data_source_id}/query"
  results = []
  has_more = True
  next_cursor = None
  
  while has_more:
    payload = {}
    if filters:
      payload["filter"] = filters
    if next_cursor:
      payload["start_cursor"] = next_cursor
      
    response = requests.post(url, json=payload, headers=config.notion_headers(), timeout=config.NOTION_TIMEOUT)
    
    if response.status_code != 200:
      raise requests.exceptions.HTTPError(
        f"API request failed with status {response.status_code}. Response: {response.text}",
        response=response)
    data = response.json()
    
    results.extend(data.get("results", []))
    
    has_more = data.get("has_more", False)
    next_cursor = data.get("next_cursor")
  
  return results
