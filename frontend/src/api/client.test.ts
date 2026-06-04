import {
  ApiError,
  apiFetch,
  getToken,
  setToken,
  setUnauthorizedHandler,
} from "./client";

function mockFetch(status: number, body: unknown) {
  return vi.fn().mockResolvedValue({
    status,
    ok: status < 400,
    statusText: "status",
    json: async () => body,
  });
}

beforeEach(() => {
  localStorage.clear();
  setUnauthorizedHandler(null);
});
afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("attaches Bearer when a token is stored", async () => {
    setToken("tok");
    const f = mockFetch(200, { ok: 1 });
    vi.stubGlobal("fetch", f);
    await apiFetch("/x");
    expect(f.mock.calls[0][1].headers["Authorization"]).toBe("Bearer tok");
  });

  it("omits Authorization when auth:false", async () => {
    setToken("tok");
    const f = mockFetch(200, {});
    vi.stubGlobal("fetch", f);
    await apiFetch("/x", { auth: false });
    expect(f.mock.calls[0][1].headers["Authorization"]).toBeUndefined();
  });

  it("clears token + calls handler + throws on 401", async () => {
    setToken("tok");
    let called = false;
    setUnauthorizedHandler(() => {
      called = true;
    });
    vi.stubGlobal("fetch", mockFetch(401, { detail: "nope" }));
    await expect(apiFetch("/x")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(called).toBe(true);
  });

  it("throws ApiError with status + detail on failure", async () => {
    vi.stubGlobal("fetch", mockFetch(409, { detail: "dup" }));
    await expect(apiFetch("/x")).rejects.toMatchObject({
      status: 409,
      message: "dup",
    });
  });

  it("returns parsed json on success", async () => {
    vi.stubGlobal("fetch", mockFetch(200, { value: 42 }));
    expect(await apiFetch("/x")).toEqual({ value: 42 });
  });
});
