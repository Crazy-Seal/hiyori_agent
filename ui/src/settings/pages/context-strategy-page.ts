import type {
  ChatSettingsState,
  ISettingsPage,
  PageEditingData,
  PageEventCallback,
  PageRenderData,
} from "../types.js";

type ContextStrategyKey = keyof ChatSettingsState["context_strategy"];

export const CONTEXT_STRATEGY_FIELDS: ContextStrategyKey[] = [
  "recent_context_human_messages",
  "max_images_in_context",
  "image_ttl_human_messages",
  "max_screenshots_in_context",
  "screenshot_ttl_human_messages",
];

export const getContextStrategyMinimum = (key: ContextStrategyKey): number => (
  key === "recent_context_human_messages" ? 1 : 0
);

export class ContextStrategyPage implements ISettingsPage {
  private inputs: Record<ContextStrategyKey, HTMLInputElement>;
  private eventCallback?: PageEventCallback;

  constructor(inputs: Record<ContextStrategyKey, HTMLInputElement>, confirmBtn: HTMLButtonElement) {
    this.inputs = inputs;
    confirmBtn.addEventListener("click", () => {
      this.eventCallback?.({ type: "submit", page: "contextStrategy" });
    });
  }

  onEvent(callback: PageEventCallback): void {
    this.eventCallback = callback;
  }

  render(data: PageRenderData): void {
    for (const key of CONTEXT_STRATEGY_FIELDS) {
      this.inputs[key].value = String(data.saved.context_strategy[key]);
    }
  }

  getEditingData(): PageEditingData {
    return {
      contextStrategy: {
        context_strategy: {
          recent_context_human_messages: Number(this.inputs.recent_context_human_messages.value),
          max_images_in_context: Number(this.inputs.max_images_in_context.value),
          image_ttl_human_messages: Number(this.inputs.image_ttl_human_messages.value),
          max_screenshots_in_context: Number(this.inputs.max_screenshots_in_context.value),
          screenshot_ttl_human_messages: Number(this.inputs.screenshot_ttl_human_messages.value),
        },
      },
    };
  }
}
