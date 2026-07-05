import type { DesktopPetApi } from "../shared-types.js";

declare global {
  interface Window {
    desktopPetApi: DesktopPetApi;
    hideElementsForScreenshot: () => void;
    restoreElementsAfterScreenshot: () => void;
    playMotionByLabel?: (label: string) => void;
    getExpressionLabels?: () => string[];
  }
}

export {};
