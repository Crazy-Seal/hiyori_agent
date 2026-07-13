/**
 * 绑定“按住显示，松开隐藏”的密钥查看交互。
 */
export const bindPressToRevealSecret = (
  input: HTMLInputElement,
  trigger: HTMLButtonElement,
  globalTarget: EventTarget = window
): (() => void) => {
  const conceal = (): void => {
    input.type = "password";
  };

  const reveal = (event: Event): void => {
    if ((event as PointerEvent).button !== 0) {
      return;
    }
    input.type = "text";
  };

  trigger.addEventListener("pointerdown", reveal);
  trigger.addEventListener("pointerup", conceal);
  trigger.addEventListener("pointerleave", conceal);
  trigger.addEventListener("pointercancel", conceal);
  trigger.addEventListener("blur", conceal);
  globalTarget.addEventListener("pointerup", conceal);
  globalTarget.addEventListener("blur", conceal);

  return () => {
    conceal();
    trigger.removeEventListener("pointerdown", reveal);
    trigger.removeEventListener("pointerup", conceal);
    trigger.removeEventListener("pointerleave", conceal);
    trigger.removeEventListener("pointercancel", conceal);
    trigger.removeEventListener("blur", conceal);
    globalTarget.removeEventListener("pointerup", conceal);
    globalTarget.removeEventListener("blur", conceal);
  };
};
