"""支持 python -m mechagent.cli 调用。"""

from mechagent.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
