import sys
from quack.agent import ask

def main() -> None:
  if len(sys.argv) < 2:
    sys.exit('usage: python -m quack "your question"')
  print(ask(sys.argv[1]))
    
if __name__ == "__main__":
  main()