import {
  ipcMain,
  type IpcMainEvent,
  type IpcMainInvokeEvent,
} from "electron";

import {
  describeRendererUrl,
  isTrustedIpcSender,
  type TrustedRendererPolicy,
} from "./renderer-security.js";

const senderDescriptor = (event: IpcMainEvent | IpcMainInvokeEvent) => {
  const frame = event.senderFrame;
  if (!frame) {
    return null;
  }
  return {
    url: frame.url,
    isMainFrame: frame === event.sender.mainFrame,
  };
};

const logBlockedIpc = (channel: string, event: IpcMainEvent | IpcMainInvokeEvent): void => {
  const source = event.senderFrame ? describeRendererUrl(event.senderFrame.url) : "missing-frame";
  console.warn(`[Security] 拒绝不可信 IPC: channel=${channel} source=${source}`);
};

export const createTrustedIpcRegistrar = (policy: TrustedRendererPolicy) => ({
  handle<TArgs extends unknown[], TResult>(
    channel: string,
    handler: (event: IpcMainInvokeEvent, ...args: TArgs) => TResult
  ): void {
    ipcMain.handle(channel, (event, ...args) => {
      if (!isTrustedIpcSender(senderDescriptor(event), policy)) {
        logBlockedIpc(channel, event);
        throw new Error("拒绝来自不可信页面的 IPC 请求");
      }
      return handler(event, ...(args as TArgs));
    });
  },

  on<TArgs extends unknown[]>(
    channel: string,
    handler: (event: IpcMainEvent, ...args: TArgs) => void
  ): void {
    ipcMain.on(channel, (event, ...args) => {
      if (!isTrustedIpcSender(senderDescriptor(event), policy)) {
        logBlockedIpc(channel, event);
        return;
      }
      handler(event, ...(args as TArgs));
    });
  },
});
