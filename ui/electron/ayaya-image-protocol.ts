import { protocol } from "electron";

import { backendFetch } from "./backend-client.js";

const SAFE_FILENAME = /^[A-Za-z0-9._-]+$/;

/** 初始化带认证代理的本地历史图片协议。 */
export const initAyayaImageProtocolHandler = (): void => {
  protocol.handle("ayaya-image", async (request) => {
    try {
      const url = new URL(request.url);
      const filename = decodeURIComponent(url.pathname).replace(/^\/+/, "");
      if (url.hostname !== "local" || !SAFE_FILENAME.test(filename) || filename.includes("..")) {
        return new Response("Forbidden", { status: 403 });
      }
      return backendFetch(`/images/${encodeURIComponent(filename)}`);
    } catch {
      return new Response("Bad request", { status: 400 });
    }
  });
};
