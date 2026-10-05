import sys

def main() -> None:
  args = [a for a in sys.argv[1:] if a != "--lc"]
  use_langchain = "--lc" in sys.argv[1:]

  if not args:
    sys.exit('usage: python -m quack [--lc] "your question"')

  if use_langchain:
    from quack.agent_lc import ask
  else:
    from quack.agent import ask

  print(ask(args[0]))

if __name__ == "__main__":
  main()
