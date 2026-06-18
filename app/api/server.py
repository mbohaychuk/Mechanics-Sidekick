import uvicorn

from app.api.main import create_app
from app.config import settings


def main() -> None:
    uvicorn.run(create_app(), host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
