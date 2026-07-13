export type TrustedRendererPolicy =
  | {
      mode: "development";
      origin: string;
      allowedPaths: ReadonlySet<string>;
    }
  | {
      mode: "production";
      allowedUrls: ReadonlySet<string>;
    };

type TrustedRendererPolicyOptions = {
  devServerUrl?: string;
  productionEntryUrls: string[];
};

type IpcSenderDescriptor = {
  url: string;
  isMainFrame: boolean;
};

const DEV_ALLOWED_PATHS = new Set(["/", "/index.html", "/settings.html"]);

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

const normalizedProductionUrl = (rawUrl: string): string | null => {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== "file:" || parsed.username || parsed.password || parsed.host) {
      return null;
    }
    parsed.search = "";
    parsed.hash = "";
    return parsed.href;
  } catch {
    return null;
  }
};

export const createTrustedRendererPolicy = ({
  devServerUrl,
  productionEntryUrls,
}: TrustedRendererPolicyOptions): TrustedRendererPolicy => {
  if (devServerUrl) {
    let parsed: URL;
    try {
      parsed = new URL(devServerUrl);
    } catch {
      throw new Error("VITE_DEV_SERVER_URL 必须是有效 URL");
    }
    if (
      (parsed.protocol !== "http:" && parsed.protocol !== "https:") ||
      parsed.username ||
      parsed.password ||
      !isLoopbackHostname(parsed.hostname)
    ) {
      throw new Error("VITE_DEV_SERVER_URL 必须使用环回地址");
    }
    if (parsed.pathname !== "/" || parsed.search || parsed.hash) {
      throw new Error("VITE_DEV_SERVER_URL 必须是纯 origin，不能包含路径、查询或片段");
    }
    return {
      mode: "development",
      origin: parsed.origin,
      allowedPaths: DEV_ALLOWED_PATHS,
    };
  }

  const allowedUrls = new Set<string>();
  for (const entryUrl of productionEntryUrls) {
    const normalized = normalizedProductionUrl(entryUrl);
    if (!normalized) {
      throw new Error("生产 renderer 入口必须是本地 file URL");
    }
    allowedUrls.add(normalized);
  }
  return { mode: "production", allowedUrls };
};

export const isTrustedRendererUrl = (rawUrl: string, policy: TrustedRendererPolicy): boolean => {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.username || parsed.password) {
      return false;
    }
    if (policy.mode === "development") {
      return parsed.origin === policy.origin && policy.allowedPaths.has(parsed.pathname);
    }
    const normalized = normalizedProductionUrl(rawUrl);
    return normalized !== null && policy.allowedUrls.has(normalized);
  } catch {
    return false;
  }
};

export const isTrustedIpcSender = (
  sender: IpcSenderDescriptor | null,
  policy: TrustedRendererPolicy
): boolean => Boolean(sender?.isMainFrame && isTrustedRendererUrl(sender.url, policy));

export const describeRendererUrl = (rawUrl: string): string => {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:" && parsed.protocol !== "file:") {
      return parsed.protocol;
    }
    return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
  } catch {
    return "invalid-url";
  }
};
