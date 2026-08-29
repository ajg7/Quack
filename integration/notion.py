import requests
import config  # type: ignore

def query_data_source(data_source_id: str, filter_: dict | None = None) -> list[dict]:
  response = requests.post(
    f"{config.NOTION_API}/data_sources/{data_source_id}/query",
    headers=config.notion_headers(),
    json={"filter": filter_} if filter_ else {},
    timeout=config.NOTION_TIMEOUT,
  )  
  if response.status_code != 200:
    print(f"Error calling Notion! {response.status_code}: {response.text}")
    return []
  
  return response.json().get("results", [])

def get_page_blocks(page_id: str) -> list[dict]:
  NotImplemented()

def blocks_to_text(blocks: list[dict]) -> str:
  NotImplemented()