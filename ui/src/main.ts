import * as PIXI from "pixi.js";
import "./style.css";

(globalThis as unknown as { PIXI: typeof PIXI }).PIXI = PIXI;

const stageHost = document.querySelector<HTMLDivElement>("#live2d-stage");
const bubble = document.querySelector<HTMLDivElement>("#bubble");
const form = document.querySelector<HTMLFormElement>("#chat-form");
const input = document.querySelector<HTMLInputElement>("#chat-input");
const sendBtn = document.querySelector<HTMLButtonElement>("#send-btn");
const settingsBtn = document.querySelector<HTMLButtonElement>("#settings-btn");

if (!stageHost || !bubble || !form || !input || !sendBtn || !settingsBtn) {
  throw new Error("UI 初始化失败");
}

settingsBtn.addEventListener("click", () => {
  window.desktopPetApi.openSettingsWindow();
});

const app = new PIXI.Application({
  resizeTo: stageHost,
  transparent: true,
  antialias: true,
  autoDensity: true,
  resolution: Math.min(globalThis.devicePixelRatio || 1, 2),
  autoStart: true
});

stageHost.appendChild(app.view as HTMLCanvasElement);

const unsubscribeModelChanged = window.desktopPetApi?.onModelChanged?.(() => {
  globalThis.location.reload();
});

const modelPath = "/live2d/hiyori_pro_zh/runtime/hiyori_pro_t11.model3.json";

const setBubbleText = (text: string) => {
  bubble.textContent = text;
};

let hasUserSubmittedMessage = false;

const startLatestAiMessageBootstrap = (sessionId: string) => {
  let stopped = false;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  const stop = () => {
    stopped = true;
    if (retryTimer) {
      clearTimeout(retryTimer);
      retryTimer = null;
    }
  };

  const scheduleRetry = () => {
    if (stopped) {
      return;
    }

    retryTimer = setTimeout(() => {
      void run();
    }, 1000);
  };

  const run = async () => {
    if (stopped) {
      return;
    }

    try {
      const { latestAiMessage } = await window.desktopPetApi.getLatestAiMessage(sessionId);
      if (!hasUserSubmittedMessage && typeof latestAiMessage === "string" && latestAiMessage.trim().length > 0) {
        setBubbleText(latestAiMessage.trim());
      }
      stop();
    } catch {
      scheduleRetry();
    }
  };

  void run();
  return stop;
};

const forceWindowInteractive = () => {
  if (!window.desktopPetApi || typeof window.desktopPetApi.setPointerInteractive !== "function") {
    return;
  }

  window.desktopPetApi.setPointerInteractive(true);
};

const handleModelLoadFailure = (error: unknown) => {
  forceWindowInteractive();
  const message = error instanceof Error ? error.message : String(error);
  setBubbleText(`模型加载失败，请在设置-模型管理中重选模型（${message}）`);
  sendBtn.disabled = true;

  if (window.desktopPetApi && typeof window.desktopPetApi.openSettingsWindow === "function") {
    window.desktopPetApi.openSettingsWindow();
  }
};

const clamp = (value: number, min: number, max: number) => {
  return Math.max(min, Math.min(max, value));
};

const initModel = async () => {
  forceWindowInteractive();
  const activeModel = await window.desktopPetApi.getActiveModel();
  const { Live2DModel } = await import("pixi-live2d-display/cubism4");
  const model = await Live2DModel.from(activeModel.modelUrl);
  model.interactive = true;
  app.stage.addChild(model);

  const activeModelId = activeModel.id;
  let baseScale = 1;
  let userScale = activeModel.userScale;
  let offsetX = activeModel.offsetX;
  let offsetY = activeModel.offsetY;
  let followCursor = activeModel.followCursor;
  let lastPointerInteractive: boolean | null = null;
  let targetGazeX = 0;
  let targetGazeY = 0;
  let smoothGazeX = 0;
  let smoothGazeY = 0;
  let targetHeadX = 0;
  let targetHeadY = 0;
  let smoothHeadX = 0;
  let smoothHeadY = 0;
  let persistTimer: ReturnType<typeof setTimeout> | null = null;

  const applyTransform = () => {
    const localBounds = model.getLocalBounds();
    model.scale.set(baseScale * userScale);
    model.pivot.set(localBounds.x + localBounds.width / 2, localBounds.y + localBounds.height);
    model.x = stageHost.clientWidth * 0.5 + offsetX;
    model.y = stageHost.clientHeight * 0.96 + offsetY;
  };

  const persistTransform = () => {
    if (persistTimer) {
      clearTimeout(persistTimer);
    }

    persistTimer = setTimeout(() => {
      void window.desktopPetApi.updateModelTransform({
        modelId: activeModelId,
        offsetX,
        offsetY,
        userScale
      });
      persistTimer = null;
    }, 120);
  };

  const fitModel = () => {
    const localBounds = model.getLocalBounds();
    const sourceWidth = localBounds.width > 0 ? localBounds.width : 1000;
    const sourceHeight = localBounds.height > 0 ? localBounds.height : 1400;
    const widthScale = (stageHost.clientWidth * 0.8) / sourceWidth;
    const heightScale = (stageHost.clientHeight * 0.78) / sourceHeight;
    baseScale = Math.min(widthScale, heightScale);
    applyTransform();
  };

  const applyFocusByParams = (eyeX: number, eyeY: number, headX: number, headY: number) => {
    const modelLike = model as unknown as {
      internalModel?: {
        coreModel?: {
          setParameterValueById?: (id: string, value: number, weight?: number) => void;
          setParamFloat?: (id: string, value: number, weight?: number) => void;
        };
      };
    };

    const coreModel = modelLike.internalModel?.coreModel;
    if (!coreModel) {
      return;
    }

    const setParam = (id: string, value: number, weight = 1) => {
      if (typeof coreModel.setParameterValueById === "function") {
        coreModel.setParameterValueById(id, value, weight);
        return;
      }

      if (typeof coreModel.setParamFloat === "function") {
        coreModel.setParamFloat(id, value, weight);
      }
    };

    setParam("ParamEyeBallX", eyeX);
    setParam("ParamEyeBallY", eyeY);
    setParam("ParamAngleX", headX * 32, 1);
    setParam("ParamAngleY", headY * 24, 1);
    setParam("ParamBodyAngleX", headX * 14, 0.85);
    setParam("ParamAngleZ", -headX * headY * 10, 0.5);
  };

  const updateGazeTargetByScreenPoint = (
    screenX: number,
    screenY: number,
    windowX: number,
    windowY: number,
    displayX: number,
    displayY: number,
    displayWidth: number,
    displayHeight: number,
    insideWindow: boolean
  ) => {
    const rect = stageHost.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return;
    }

    const centerX = windowX + rect.left + rect.width * 0.5;
    const centerY = windowY + rect.top + rect.height * 0.42;

    const halfRangeX = Math.max(displayWidth * 0.45, 1);
    const halfRangeY = Math.max(displayHeight * 0.45, 1);
    const dx = (screenX - centerX) / halfRangeX;
    const dy = (centerY - screenY) / halfRangeY;

    const displayCenterX = displayX + displayWidth * 0.5;
    const displayCenterY = displayY + displayHeight * 0.5;
    const globalBiasX = clamp((screenX - displayCenterX) / Math.max(displayWidth * 0.8, 1), -0.35, 0.35);
    const globalBiasY = clamp((displayCenterY - screenY) / Math.max(displayHeight * 0.8, 1), -0.25, 0.25);

    targetGazeX = clamp(dx + globalBiasX, -1.2, 1.2);
    targetGazeY = clamp(dy + globalBiasY, -1.2, 1.2);

    const outsideBoost = insideWindow ? 1 : 1.9;
    targetHeadX = clamp(targetGazeX * outsideBoost, -1.5, 1.5);
    targetHeadY = clamp(targetGazeY * (insideWindow ? 1 : 1.5), -1.4, 1.4);
  };

  const applyGazeEachFrame = () => {
    smoothGazeX += (targetGazeX - smoothGazeX) * 0.2;
    smoothGazeY += (targetGazeY - smoothGazeY) * 0.2;
    smoothHeadX += (targetHeadX - smoothHeadX) * 0.22;
    smoothHeadY += (targetHeadY - smoothHeadY) * 0.22;
    applyFocusByParams(smoothGazeX, smoothGazeY, smoothHeadX, smoothHeadY);
  };

  const sampleCanvasAlpha = (windowX: number, windowY: number): number => {
    const canvas = app.view as HTMLCanvasElement;
    const rect = canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      return 0;
    }

    if (windowX < rect.left || windowX > rect.right || windowY < rect.top || windowY > rect.bottom) {
      return 0;
    }

    const pixelX = Math.floor(((windowX - rect.left) / rect.width) * canvas.width);
    const pixelY = Math.floor(((windowY - rect.top) / rect.height) * canvas.height);
    if (pixelX < 0 || pixelX >= canvas.width || pixelY < 0 || pixelY >= canvas.height) {
      return 0;
    }

    const renderer = app.renderer as PIXI.Renderer;
    const gl = renderer.gl;
    const sampleRadius = 1;
    let maxAlpha = 0;

    for (let offsetY = -sampleRadius; offsetY <= sampleRadius; offsetY += 1) {
      for (let offsetX = -sampleRadius; offsetX <= sampleRadius; offsetX += 1) {
        const sx = pixelX + offsetX;
        const sy = pixelY + offsetY;
        if (sx < 0 || sx >= canvas.width || sy < 0 || sy >= canvas.height) {
          continue;
        }

        const pixel = new Uint8Array(4);
        gl.readPixels(sx, canvas.height - sy - 1, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
        if (pixel[3] > maxAlpha) {
          maxAlpha = pixel[3];
        }
      }
    }

    return maxAlpha;
  };

  const updatePointerInteractive = (windowX: number, windowY: number) => {
    if (!window.desktopPetApi || typeof window.desktopPetApi.setPointerInteractive !== "function") {
      return;
    }

    const hoveredElement = document.elementFromPoint(windowX, windowY) as HTMLElement | null;
    const onControls = Boolean(hoveredElement?.closest("#chat-form, #bubble, #settings-panel, #settings-btn"));
    const localBounds = model.getLocalBounds();
    const scale = model.scale.x;
    const modelBounds = {
      x: model.x + (localBounds.x - model.pivot.x) * scale,
      y: model.y + (localBounds.y - model.pivot.y) * scale,
      width: localBounds.width * scale,
      height: localBounds.height * scale
    };
    const onModelBounds =
      windowX >= modelBounds.x &&
      windowX <= modelBounds.x + modelBounds.width &&
      windowY >= modelBounds.y &&
      windowY <= modelBounds.y + modelBounds.height;
    const modelAlpha = onModelBounds ? sampleCanvasAlpha(windowX, windowY) : 0;
    const onModelPixel = modelAlpha >= 12;
    const shouldCapture = onControls || (onModelBounds && onModelPixel);

    if (lastPointerInteractive !== shouldCapture) {
      window.desktopPetApi.setPointerInteractive(shouldCapture);
      lastPointerInteractive = shouldCapture;
    }
  };

  const isCursorOnChatControls = (windowX: number, windowY: number) => {
    const hoveredElement = document.elementFromPoint(windowX, windowY) as HTMLElement | null;
    return Boolean(hoveredElement?.closest("#chat-form, #bubble"));
  };

  fitModel();
  setTimeout(fitModel, 120);
  window.addEventListener("resize", () => {
    fitModel();
  });

  window.addEventListener(
    "wheel",
    (event) => {
      if (!isCursorOnChatControls(event.clientX, event.clientY)) {
        return;
      }

      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.08 : 0.92;
      userScale = clamp(userScale * factor, 0.5, 1.5);
      applyTransform();
      persistTransform();
    },
    { passive: false }
  );

  const unsubscribeCursor = window.desktopPetApi?.onCursor?.(
    ({ localX, localY, screenX, screenY, windowX, windowY, displayX, displayY, displayWidth, displayHeight, insideWindow }) => {
      if (followCursor) {
        updateGazeTargetByScreenPoint(
          screenX,
          screenY,
          windowX,
          windowY,
          displayX,
          displayY,
          displayWidth,
          displayHeight,
          insideWindow
        );
      } else {
        targetGazeX = 0;
        targetGazeY = 0;
        targetHeadX = 0;
        targetHeadY = 0;
      }
      updatePointerInteractive(localX, localY);
    }
  );

  const unsubscribeModelTransformChanged = window.desktopPetApi?.onModelTransformChanged?.((payload) => {
    if (payload.id !== activeModelId) {
      return;
    }

    offsetX = payload.offsetX;
    offsetY = payload.offsetY;
    userScale = payload.userScale;
    followCursor = payload.followCursor;
    applyTransform();
  });

  app.ticker.add(applyGazeEachFrame, undefined, PIXI.UPDATE_PRIORITY.LOW);

  window.addEventListener("beforeunload", () => {
    if (typeof unsubscribeCursor === "function") {
      unsubscribeCursor();
    }
    if (typeof unsubscribeModelTransformChanged === "function") {
      unsubscribeModelTransformChanged();
    }
    if (persistTimer) {
      clearTimeout(persistTimer);
    }

    app.ticker.remove(applyGazeEachFrame);
  });

  return {
    sessionId: activeModel.sessionId
  };
};

let currentSessionId = "";
let stopLatestAiMessageBootstrap: (() => void) | null = null;

void initModel()
  .then((state) => {
    currentSessionId = state.sessionId;
    stopLatestAiMessageBootstrap = startLatestAiMessageBootstrap(state.sessionId);
  })
  .catch((error) => {
    handleModelLoadFailure(error);
  });

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  hasUserSubmittedMessage = true;
  if (stopLatestAiMessageBootstrap) {
    stopLatestAiMessageBootstrap();
    stopLatestAiMessageBootstrap = null;
  }

  const message = input.value.trim();
  if (!message) {
    return;
  }

  sendBtn.disabled = true;
  setBubbleText("思考中...");

  const requestId = `chat-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  let streamedText = "";
  let cursorVisible = true;
  let cursorTimer: ReturnType<typeof setInterval> | null = null;

  const renderStreamingBubble = () => {
    const baseText = streamedText || "思考中...";
    setBubbleText(`${baseText}${cursorVisible ? "▋" : ""}`);
  };

  const stopCursor = () => {
    if (cursorTimer) {
      clearInterval(cursorTimer);
      cursorTimer = null;
    }
  };

  cursorTimer = setInterval(() => {
    cursorVisible = !cursorVisible;
    renderStreamingBubble();
  }, 380);

  renderStreamingBubble();

  const unsubscribeChatChunk = window.desktopPetApi.onChatChunk(({ requestId: chunkRequestId, chunk }) => {
    if (chunkRequestId !== requestId) {
      return;
    }

    streamedText += chunk;
    renderStreamingBubble();
  });

  try {
    if (!window.desktopPetApi || typeof window.desktopPetApi.chat !== "function") {
      throw new Error("桌宠桥接未就绪，请重启桌宠程序");
    }

    const result = await window.desktopPetApi.chat(message, currentSessionId || undefined, requestId);
    stopCursor();
    setBubbleText(streamedText || result.response);
    input.value = "";
  } catch (error) {
    stopCursor();
    setBubbleText(`请求失败: ${String(error)}`);
  } finally {
    stopCursor();

    unsubscribeChatChunk();
    sendBtn.disabled = false;
    input.focus();
  }
});

window.addEventListener("beforeunload", () => {
  if (stopLatestAiMessageBootstrap) {
    stopLatestAiMessageBootstrap();
    stopLatestAiMessageBootstrap = null;
  }

  if (typeof unsubscribeModelChanged === "function") {
    unsubscribeModelChanged();
  }
});
