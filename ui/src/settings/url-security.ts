export type HttpEndpointClassification =
  | { kind: "safe"; normalizedUrl: string }
  | { kind: "insecure_http"; normalizedUrl: string }
  | { kind: "invalid"; normalizedUrl: null };

const isIpv4Loopback = (hostname: string): boolean => {
  const parts = hostname.split(".");
  if (parts.length !== 4 || parts.some((part) => !/^\d+$/.test(part))) {
    return false;
  }
  const octets = parts.map(Number);
  return octets.every((octet) => octet >= 0 && octet <= 255) && octets[0] === 127;
};

const isLoopbackHostname = (hostname: string): boolean => {
  const normalized = hostname.toLowerCase();
  return normalized === "localhost" || normalized === "[::1]" || normalized === "::1" || isIpv4Loopback(normalized);
};

export const classifyHttpEndpoint = (rawUrl: string): HttpEndpointClassification => {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl.trim());
  } catch {
    return { kind: "invalid", normalizedUrl: null };
  }

  if (parsed.username || parsed.password || (parsed.protocol !== "http:" && parsed.protocol !== "https:")) {
    return { kind: "invalid", normalizedUrl: null };
  }

  const normalizedUrl = parsed.pathname === "/" && !parsed.search && !parsed.hash
    ? parsed.href.slice(0, -1)
    : parsed.href;
  if (parsed.protocol === "https:" || isLoopbackHostname(parsed.hostname)) {
    return { kind: "safe", normalizedUrl };
  }
  return { kind: "insecure_http", normalizedUrl };
};

type AuthorizeBaseUrlChangeOptions = {
  previousUrl: string;
  nextUrl: string;
  confirmInsecure: (normalizedUrl: string) => Promise<boolean>;
};

export const authorizeBaseUrlChange = async ({
  previousUrl,
  nextUrl,
  confirmInsecure,
}: AuthorizeBaseUrlChangeOptions): Promise<boolean> => {
  if (nextUrl.trim() === "") {
    return true;
  }

  const next = classifyHttpEndpoint(nextUrl);
  if (next.kind === "invalid") {
    throw new Error("Base URL 必须是有效的 HTTP 或 HTTPS 地址");
  }

  if (next.kind !== "insecure_http") {
    return true;
  }

  const previous = classifyHttpEndpoint(previousUrl);
  if (previous.kind !== "invalid" && previous.normalizedUrl === next.normalizedUrl) {
    return true;
  }

  return confirmInsecure(next.normalizedUrl);
};
