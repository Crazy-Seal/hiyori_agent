import type { ChatInterruptData } from "../../shared-types.js";


/** 构造中断响应使用的持久化 ID 与流关联 ID。 */
export const buildInterruptResponseMeta = (
  interrupt: ChatInterruptData,
  streamRequestId: string
): { requestId: string; streamRequestId: string } => ({
  requestId: interrupt.request_id,
  streamRequestId,
});
