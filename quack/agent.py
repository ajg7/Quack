from quack import config, tools

def ask(question: str) -> str:
  cliet = config.anthropic_client()
  
  with open("quack/prompts/system.md") as f:
    system_prompt = f.read()
  
  messages = [
    {"role": "user", "content": question},
  ]
  
  while True:
    response = client.messages.create(
      model=config.MODEL,
      max_tokens=config.MAX_TOKENS,
      system=system_prompt,
      tools=tools.SCHEMAS,
      messages=messages,
    )