/**
 * Live2D 自定义协议处理
 */

import { protocol, net } from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { loadModelConfig } from "./model-manager.js";

/**
 * 注册 live2d:// 自定义协议
 */
export const registerLive2DProtocol = (): void => {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: "live2d",
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: true,
      },
    },
    {
      scheme: "ayaya-image",
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
      },
    },
  ]);
};

/**
 * 处理 live2d:// 协议请求
 */
export const handleLive2DProtocol = async (request: Request): Promise<Response> => {
  try {
    const requestUrl = new URL(request.url);
    const modelId = requestUrl.hostname;
    const relPath = decodeURIComponent(requestUrl.pathname).replace(/^\/+/, "");
    const config = loadModelConfig();
    const model = config.models.find(
      (item) => item.id === modelId && item.source === "custom"
    );
    if (!model?.rootDir) {
      return new Response("Model not found", { status: 404 });
    }

    const { resolveRootDirAbsolute } = await import("./model-manager.js");
    const rootDir = resolveRootDirAbsolute(model.rootDir);
    const absoluteFilePath = path.normalize(path.join(rootDir, relPath));
    const normalizedRoot = path.normalize(`${rootDir}${path.sep}`);
    if (!absoluteFilePath.startsWith(normalizedRoot)) {
      return new Response("Forbidden", { status: 403 });
    }

    return net.fetch(pathToFileURL(absoluteFilePath).toString());
  } catch {
    return new Response("Bad request", { status: 400 });
  }
};

/**
 * 初始化 Live2D 协议处理器
 */
export const initLive2DProtocolHandler = (): void => {
  protocol.handle("live2d", handleLive2DProtocol);
};
