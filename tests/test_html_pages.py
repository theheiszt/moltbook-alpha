from fastapi.testclient import TestClient
import api_server


def test_html_pages_and_static_assets_serve_correctly():
    client = TestClient(api_server.app)

    # 1. Main Landing Pages
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "text/html" in r_root.headers.get("content-type", "")

    r_index = client.get("/index.html")
    assert r_index.status_code == 200
    assert "text/html" in r_index.headers.get("content-type", "")

    # 2. Live Metrics / Dashboard
    r_dash = client.get("/dashboard")
    assert r_dash.status_code == 200
    assert "text/html" in r_dash.headers.get("content-type", "")

    r_dash_html = client.get("/dashboard.html")
    assert r_dash_html.status_code == 200
    assert "text/html" in r_dash_html.headers.get("content-type", "")

    # 3. Jobs & Bounties
    r_jobs = client.get("/jobs")
    assert r_jobs.status_code == 200
    assert "text/html" in r_jobs.headers.get("content-type", "")

    r_jobs_html = client.get("/jobs.html")
    assert r_jobs_html.status_code == 200
    assert "text/html" in r_jobs_html.headers.get("content-type", "")

    # 4. NFTs Portal
    r_nfts = client.get("/nfts")
    assert r_nfts.status_code == 200
    assert "text/html" in r_nfts.headers.get("content-type", "")

    r_nfts_html = client.get("/nfts.html")
    assert r_nfts_html.status_code == 200
    assert "text/html" in r_nfts_html.headers.get("content-type", "")

    # 5. Sample JSON
    r_sample = client.get("/sample.json")
    assert r_sample.status_code == 200
    assert "application/json" in r_sample.headers.get("content-type", "")

    # 6. Static NFT Image Assets
    r_asset = client.get("/assets/nfts/molt-alpha-dems/01_the_synth.png")
    assert r_asset.status_code == 200
    assert "image/png" in r_asset.headers.get("content-type", "")
