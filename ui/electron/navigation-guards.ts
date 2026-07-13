export type BlockedNavigationKind = "导航" | "新窗口";

type NavigationEvent = {
  preventDefault(): void;
};

type GuardedWebContents = {
  on(
    event: "will-navigate" | "will-redirect",
    listener: (event: NavigationEvent, targetUrl: string) => void
  ): unknown;
  setWindowOpenHandler(
    handler: (details: { url: string }) => { action: "deny" }
  ): unknown;
};

export const installNavigationGuards = (
  webContents: GuardedWebContents,
  isAllowed: (targetUrl: string) => boolean,
  onBlocked: (kind: BlockedNavigationKind, targetUrl: string) => void
): void => {
  const guardNavigation = (event: NavigationEvent, targetUrl: string): void => {
    if (!isAllowed(targetUrl)) {
      event.preventDefault();
      onBlocked("导航", targetUrl);
    }
  };
  webContents.on("will-navigate", guardNavigation);
  webContents.on("will-redirect", guardNavigation);
  webContents.setWindowOpenHandler(({ url }) => {
    onBlocked("新窗口", url);
    return { action: "deny" };
  });
};
