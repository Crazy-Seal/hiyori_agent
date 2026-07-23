/** 中断恢复请求中用于后端身份校验的公共字段。 */
export type InterruptResponseIdentity = {
  sessionId: string;
  requestId: string;
  streamRequestId?: string;
};


/** 把 Electron 字段转换为后端恢复接口使用的身份字段。 */
export const buildBackendInterruptIdentity = (
  payload: InterruptResponseIdentity
): { session_id: string; request_id: string } => ({
  session_id: payload.sessionId,
  request_id: payload.requestId,
});
