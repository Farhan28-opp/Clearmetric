import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("sends the CSRF header and JSON body to the same-origin /api path", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/workspaces", { method: "POST", json: { name: "A" } });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/workspaces");
    expect(new Headers(init.headers).get("X-CM-Client")).toBe("web");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ name: "A" }));
  });
  it("turns the backend error envelope into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "invalid_plan", message: "Unknown column 'x'" } }), { status: 422 })));
    await expect(api("/x")).rejects.toMatchObject({ status: 422, code: "invalid_plan" });
    expect(errorMessage(new ApiError(422, "c", "Readable message"))).toBe("Readable message");
  });
});
