import os
from flask import Flask

def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return "Dashboard running"

    return app

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=True)
