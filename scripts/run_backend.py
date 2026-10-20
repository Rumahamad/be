"""Start BNC using an explicit environment file; no configuration copying required."""
import argparse
from pathlib import Path

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not args.env.is_file():
        raise SystemExit("Configuration file does not exist")
    load_dotenv(args.env, override=True)
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
