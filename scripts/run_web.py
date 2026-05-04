from __future__ import annotations

import uvicorn

from ragrig.main import create_app, create_runtime_settings


def main() -> None:
    settings = create_runtime_settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)


if __name__ == "__main__":
    main()
