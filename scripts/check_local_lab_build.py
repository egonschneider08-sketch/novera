"""Smoke-test the actual Vite output through the single-origin FastAPI app.

Run *after* npm run build in frontend CI, not in the Python-only quality job.
"""

import re

from fastapi.testclient import TestClient

from novera.local_lab import create_local_app


def main() -> None:
    with TestClient(create_local_app()) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "text/html" in home.headers["content-type"]
        assert "Novera" in home.text
        javascript = re.findall(r'src="(/assets/[^"]+\.js)"', home.text)
        assert javascript, "Missing compiled Vite JS bundle"
        for path in javascript:
            asset = client.get(path)
            assert asset.status_code == 200, path
            assert "javascript" in asset.headers["content-type"], path
        comparison = client.get("/api/v1/demo/comparison")
        assert comparison.status_code == 200
        document = comparison.json()
        assert document["synthetic"] is True
        assert document["total_scenarios"] == 3
        assert [report["asset"]["identifier"] for report in document["reports"]] == [
            "LAB-A",
            "LAB-B",
            "LAB-C",
        ]
        assert comparison.headers["content-security-policy"]
        assert comparison.headers["cache-control"] == "no-store"
    print("Novera Lab static build, React asset and same-origin FastAPI smoke test passed.")


if __name__ == "__main__":
    main()
