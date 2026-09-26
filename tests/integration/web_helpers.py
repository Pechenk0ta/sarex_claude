import re

import httpx


async def csrf(client: httpx.AsyncClient, path: str) -> str:
    page = await client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert match, f"no CSRF token on {path}"
    return match.group(1)


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    token = await csrf(client, "/login")
    return await client.post(
        "/login", data={"email": email, "password": password, "csrf_token": token, "next": "/"}
    )


async def post(client: httpx.AsyncClient, path: str, data: dict[str, str]) -> httpx.Response:
    token = await csrf(client, "/refs/users")
    return await client.post(path, data={**data, "csrf_token": token})
